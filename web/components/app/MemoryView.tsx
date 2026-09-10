"use client";
import { useMemo, useState } from "react";
import type { Row } from "@/lib/core";
import { fmtBlock, idOf, short, type Memory, type UnlockMethod } from "@/lib/kint";

const TIER_ORDER = ["entity", "state", "reference", "journal"];
const BASESCAN = "https://basescan.org";

function scalar(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (Array.isArray(v) && v.every((x) => typeof x !== "object" || x == null)) return v.map(scalar).join(", ");
  return JSON.stringify(v);
}

/* One level of nesting is flattened to "key.subkey" rows; arrays of scalars read as a list. */
function pretty(text: string | null | undefined): { lines: [string, string][] } | { text: string } | null {
  if (text == null || text === "") return null;
  try {
    const v = JSON.parse(text);
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const lines: [string, string][] = [];
      for (const [k, val] of Object.entries(v)) {
        if (val && typeof val === "object" && !Array.isArray(val)) {
          for (const [k2, v2] of Object.entries(val as Record<string, unknown>)) lines.push([`${k}.${k2}`, scalar(v2)]);
        } else lines.push([k, scalar(val)]);
      }
      return { lines };
    }
    return { text: scalar(v) };
  } catch {
    return { text };
  }
}

function Body({ text }: { text: string | null | undefined }) {
  const p = pretty(text);
  if (!p) return <span className="dim">no body</span>;
  if ("lines" in p) return <dl className="kv">{p.lines.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
  return <p className="txt">{p.text}</p>;
}

function blockOf(memory: Memory, row: Row): number | null {
  const vs = memory.versions.get(idOf(row));
  return vs && vs.length ? vs[vs.length - 1].block : null;
}

export default function MemoryView({ owner, tenant, memory, method, onClose }: { owner: string; tenant: string; memory: Memory; method: UnlockMethod; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string | null>(null);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = memory.rows.filter((r) => !needle || [r.tier, r.category, r.key, r.body, r.acted, r.evaluated, r.forward, r.extra].some((s) => s && String(s).toLowerCase().includes(needle)));
    const byTier = new Map<string, Row[]>();
    for (const r of rows) { const t = String(r.tier); const arr = byTier.get(t); if (arr) arr.push(r); else byTier.set(t, [r]); }
    return [...byTier.entries()].sort((a, b) => TIER_ORDER.indexOf(a[0]) - TIER_ORDER.indexOf(b[0]));
  }, [memory, q]);

  const selected = sel ? memory.rows.find((r) => idOf(r) === sel) ?? null : null;
  const versions = sel ? memory.versions.get(sel) ?? [] : [];
  const head = memory.head;
  const bad = memory.epochs.filter((e) => e.opened && !e.matchesRoot);

  return (
    <section className="mem">
      <header className="mem-head">
        <div>
          <h1>{fmtBlock(head.blockNumber)}</h1>
          <p>The block that holds epoch {head.seq}, the newest anchored state of this memory. {memory.rows.length} rows, every one of them opened in this tab and folded in order; each root matched the chain{bad.length ? ` except ${bad.map((e) => e.seq).join(", ")}` : ""}.</p>
        </div>
        <dl className="facts">
          <div><dt>owner</dt><dd className="mono">{owner}</dd></div>
          <div><dt>tenant</dt><dd className="mono">{tenant}</dd></div>
          <div><dt>space</dt><dd className="mono">{short(memory.space, 8, 8)}</dd></div>
          <div><dt>opened with</dt><dd className="mono">{method === "signature" ? "wallet signature" : method === "passphrase" ? "passphrase" : "recovery code"}</dd></div>
        </dl>
        <button type="button" className="ghost close" onClick={onClose}>Close</button>
      </header>

      {memory.stoppedAt !== null && (
        <p className="warn">Epoch {memory.stoppedAt} did not open with this key, so nothing after it was applied. A rotated key or a different owner wrap would do that.</p>
      )}

      <div className="mem-grid">
        <div className="bx t1 rows">
          <div className="rows-top">
            <input className="mono" value={q} onChange={(e) => setQ(e.target.value)} placeholder="filter rows" aria-label="Filter rows" spellCheck={false} />
            <span className="mono dim">{memory.rows.length} rows</span>
          </div>
          {groups.length === 0 && <p className="dim">Nothing matches.</p>}
          {groups.map(([tier, rows]) => (
            <div className="tier" key={tier}>
              <h2 className="mono">{tier}</h2>
              <ul>
                {rows.map((r) => {
                  const id = idOf(r); const b = blockOf(memory, r);
                  return (
                    <li key={id} className={sel === id ? "on" : ""}>
                      <button type="button" onClick={() => setSel(sel === id ? null : id)} aria-pressed={sel === id}>
                        <span className="rk mono">{r.category ? <em>{r.category} / </em> : null}{tier === "journal" ? short(r.key, 6, 4) : r.key}</span>
                        {b !== null && <span className="rb mono">no later than block {fmtBlock(b)}</span>}
                      </button>
                      <div className="rbody">
                        {tier === "journal" ? <Body text={r.acted || r.evaluated || r.forward || r.extra} /> : <Body text={r.body} />}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>

        <aside className="bx t2 time">
          <h2>Timeline</h2>
          <ol className="epochs">
            {[...memory.epochs].reverse().map((e) => (
              <li key={e.seq} className={e.opened ? "" : "sealed"}>
                <span className="mono seq">epoch {e.seq}</span>
                <a className="mono blk" href={`${BASESCAN}/tx/${e.tx}`} target="_blank" rel="noopener">block {fmtBlock(e.block)}</a>
                <span className="mono what">{e.opened ? `${e.snapshot ? "snapshot, " : ""}${e.changed} changed${e.deleted ? `, ${e.deleted} deleted` : ""}, ${e.bucket / 1024} KB` : e.note}</span>
                {e.opened && <span className={`mono ok ${e.matchesRoot ? "" : "no"}`}>{e.matchesRoot ? "root matches" : "root differs"}</span>}
              </li>
            ))}
          </ol>

          {selected && (
            <div className="hist">
              <h3 className="mono">{selected.category ? `${selected.category} / ` : ""}{String(selected.tier) === "journal" ? short(selected.key, 6, 4) : selected.key}</h3>
              <ol>
                {[...versions].reverse().map((v, i) => (
                  <li key={`${v.seq}-${i}`}>
                    <span className="mono">epoch {v.seq}, no later than block {fmtBlock(v.block)}</span>
                    {v.row ? <Body text={String(v.row.tier) === "journal" ? (v.row.acted || v.row.evaluated || v.row.forward || v.row.extra) : v.row.body} /> : <span className="dim">deleted in this epoch</span>}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {!selected && <p className="dim">Select a row to see what it held at every anchored epoch.</p>}
        </aside>
      </div>
    </section>
  );
}
