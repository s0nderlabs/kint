"use client";
// Copy buttons, the headings column that follows the reader, the chapters menu on narrow screens, and search
// over every section. Event delegation on the docs root, so it survives client navigation between pages.
import { useEffect } from "react";
import { usePathname } from "next/navigation";

type Entry = { s: string; t: string; h: string; a: string; x: string; lt: string; lh: string; lx: string };

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}
function hl(s: string, terms: string[]): string {
  let o = esc(s);
  for (const t of terms) {
    if (!t) continue;
    o = o.replace(new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
  }
  return o;
}
function snip(e: Entry, terms: string[]): string {
  let i = -1;
  for (let k = 0; k < terms.length && i < 0; k++) i = e.lx.indexOf(terms[k]);
  if (i < 0) return e.x.slice(0, 120);
  const s = Math.max(0, i - 40);
  return (s ? "…" : "") + e.x.slice(s, s + 140);
}
function fallbackCopy(t: string) {
  try {
    const ta = document.createElement("textarea");
    ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta);
  } catch {}
}

export default function DocsClient() {
  const pathname = usePathname();

  // per page: close the menu, follow the headings
  useEffect(() => {
    const root = document.getElementById("kdocs");
    root?.classList.remove("menu");
    document.getElementById("mnav")?.setAttribute("aria-expanded", "false");
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>(".kdocs .toc nav a"));
    if (!links.length) return;
    const byId: Record<string, HTMLAnchorElement> = {};
    links.forEach((a) => { byId[decodeURIComponent(a.hash.slice(1))] = a; });
    const heads = Array.from(document.querySelectorAll<HTMLElement>(".kdocs .doc h2[id], .kdocs .doc h3[id]")).filter((h) => byId[h.id]);
    let raf = 0;
    const mark = () => {
      raf = 0;
      let act: HTMLElement | null = null;
      for (const h of heads) { if (h.getBoundingClientRect().top <= 104) act = h; else break; }
      if (!act && heads.length) act = heads[0];
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4 && heads.length) act = heads[heads.length - 1];
      links.forEach((a) => a.classList.toggle("on", !!act && byId[act.id] === a));
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(mark); };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    mark();
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); if (raf) cancelAnimationFrame(raf); };
  }, [pathname]);

  // once: copy, menu, search
  useEffect(() => {
    const root = document.getElementById("kdocs");
    const sd = document.getElementById("sd");
    const sin = document.getElementById("sin") as HTMLInputElement | null;
    const sul = document.getElementById("sul");
    if (!root || !sd || !sin || !sul) return;
    let idx: Entry[] | null = null;
    let loading = false;
    let sel = 0;
    let last: HTMLElement | null = null;

    const run = () => {
      const q = sin.value.trim().toLowerCase();
      if (!idx) { sul.innerHTML = ""; return; }
      const terms = q ? q.split(/\s+/) : [];
      let hits: Entry[];
      if (!q) hits = idx.filter((e) => !e.a).slice(0, 16);
      else {
        const scored: { e: Entry; s: number }[] = [];
        for (const e of idx) {
          let sc = 0, ok = true;
          for (const t of terms) {
            let s = 0;
            if (e.lt.includes(t)) s += 6;
            if (e.lh.includes(t)) s += 4;
            if (e.lx.includes(t)) s += 1;
            if (!s) { ok = false; break; }
            sc += s;
          }
          if (ok) scored.push({ e, s: sc + (e.a ? 0 : 0.5) });
        }
        hits = scored.sort((a, b) => b.s - a.s).slice(0, 24).map((x) => x.e);
      }
      sel = 0;
      if (!hits.length) { sul.innerHTML = '<li class="none">No section mentions that. Try a command, a tool name or a flag.</li>'; return; }
      sul.innerHTML = hits.map((e, i) => {
        const head = e.a ? esc(e.t) + " › " + hl(e.h, terms) : hl(e.t, terms);
        return `<li><a role="option" href="/docs/${e.s}${e.a ? "#" + e.a : ""}" aria-selected="${i === 0}"><span class="h">${head}</span><span class="w">${hl(snip(e, terms), terms)}</span></a></li>`;
      }).join("");
    };
    const load = () => {
      if (idx || loading) return;
      loading = true;
      fetch("/docs/search.json").then((r) => r.json()).then((j: Entry[]) => {
        idx = j.map((e) => ({ ...e, lt: e.t.toLowerCase(), lh: e.h.toLowerCase(), lx: e.x.toLowerCase() }));
        run();
      }).catch(() => { loading = false; sul.innerHTML = '<li class="none">The search index did not load.</li>'; });
    };
    const open = () => {
      last = document.activeElement as HTMLElement | null;
      sd.classList.add("open"); sd.setAttribute("aria-hidden", "false");
      load(); run();
      setTimeout(() => { sin.focus(); sin.select(); }, 10);
    };
    const close = () => { sd.classList.remove("open"); sd.setAttribute("aria-hidden", "true"); last?.focus?.(); };
    const move = (d: number) => {
      const as = sul.querySelectorAll("a");
      if (!as.length) return;
      as[sel].setAttribute("aria-selected", "false");
      sel = (sel + d + as.length) % as.length;
      as[sel].setAttribute("aria-selected", "true");
      as[sel].scrollIntoView({ block: "nearest" });
    };

    const onClick = (ev: MouseEvent) => {
      const t = ev.target as HTMLElement;
      const copy = t.closest<HTMLButtonElement>(".copy");
      if (copy) {
        const pre = copy.parentElement?.querySelector("pre");
        if (!pre) return;
        const txt = pre.getAttribute("data-copy") ?? pre.innerText;
        const done = () => { copy.classList.add("done"); copy.setAttribute("aria-label", "Copied"); setTimeout(() => { copy.classList.remove("done"); copy.setAttribute("aria-label", "Copy"); }, 1400); };
        try { navigator.clipboard.writeText(txt).then(done, () => { fallbackCopy(txt); done(); }); } catch { fallbackCopy(txt); done(); }
        return;
      }
      if (t.closest("[data-search]")) { open(); return; }
      const mn = t.closest<HTMLButtonElement>("#mnav");
      if (mn) { const o = root.classList.toggle("menu"); mn.setAttribute("aria-expanded", o ? "true" : "false"); return; }
      if (t === sd || t.closest("#sesc")) { close(); return; }
      if (t.closest("#sul a")) close();
    };
    const onKey = (e: KeyboardEvent) => {
      const tg = e.target as HTMLElement | null;
      const typing = !!tg && (tg.tagName === "INPUT" || tg.tagName === "TEXTAREA" || tg.isContentEditable);
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) { e.preventDefault(); open(); }
      else if (e.key === "Escape" && sd.classList.contains("open")) close();
    };
    const onInputKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") { const a = sul.querySelectorAll("a")[sel]; if (a) { close(); window.location.href = a.href; } }
    };
    root.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    sin.addEventListener("input", run);
    sin.addEventListener("keydown", onInputKey);
    return () => {
      root.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
      sin.removeEventListener("input", run);
      sin.removeEventListener("keydown", onInputKey);
    };
  }, []);

  return null;
}
