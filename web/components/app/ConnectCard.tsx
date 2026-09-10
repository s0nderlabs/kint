"use client";
import { useState, type FormEvent } from "react";
import type { UnlockMethod, VaultRef } from "@/lib/kint";

const DEMO = { owner: "0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3", tenant: "kint-demo" };
const METHODS: { id: UnlockMethod; label: string; sub: string; hint: string }[] = [
  { id: "passphrase", label: "Passphrase", sub: "Base Account owners", hint: "The vault passphrase a Base Account owner typed at kint connect. A smart wallet's passkey signatures are not deterministic, so the passphrase is the key. Stretched here with scrypt; it takes a second." },
  { id: "signature", label: "Wallet signature", sub: "EOA owners: Ledger, MetaMask, Rabby", hint: "An EOA owner signs the one frozen message in the browser wallet. The signature is the key and stays in this tab; nothing is sent anywhere." },
  { id: "recovery", label: "Recovery code", sub: "either owner", hint: "The grouped code kint wrote at first connect. It decodes straight to the data key." },
];

export default function ConnectCard({ busy, error, onOpen }: { busy: string | null; error: string | null; onOpen: (ref: VaultRef, method: UnlockMethod, secret: string) => void }) {
  const [owner, setOwner] = useState("");
  const [tenant, setTenant] = useState("");
  const [method, setMethod] = useState<UnlockMethod>("passphrase");
  const [secret, setSecret] = useState("");
  const m = METHODS.find((x) => x.id === method)!;
  const ok = /^0x[0-9a-fA-F]{40}$/.test(owner.trim()) && tenant.trim().length > 0 && (method === "signature" || secret.length > 0);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!ok || busy) return;
    onOpen({ owner: owner.trim(), tenant: tenant.trim() }, method, secret);
  }

  return (
    <form className="bx t1 connect" onSubmit={submit} aria-busy={!!busy}>
      <div className="field">
        <label htmlFor="owner">Owner</label>
        <input id="owner" className="mono" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="0x…" autoComplete="off" spellCheck={false} inputMode="text" />
      </div>
      <div className="field">
        <label htmlFor="tenant">Sibyl tenant</label>
        <input id="tenant" className="mono" value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="the tenant id from credentials.json" autoComplete="off" spellCheck={false} />
      </div>
      <div className="field">
        <span className="lbl">Open with</span>
        <div className="seg" role="radiogroup" aria-label="Unlock method">
          {METHODS.map((x) => (
            <button key={x.id} type="button" role="radio" aria-checked={method === x.id} className={method === x.id ? "on" : ""} onClick={() => { setMethod(x.id); setSecret(""); }}><span>{x.label}</span><small>{x.sub}</small></button>
          ))}
        </div>
        <p className="hint">{m.hint}</p>
      </div>
      {method !== "signature" && (
        <div className="field">
          <label htmlFor="secret">{method === "passphrase" ? "Vault passphrase" : "Recovery code"}</label>
          <input id="secret" className="mono" type={method === "passphrase" ? "password" : "text"} value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" spellCheck={false} placeholder={method === "recovery" ? "xxxx-xxxx-xxxx-…" : ""} />
        </div>
      )}
      <div className="actions">
        <button type="submit" className="cta" disabled={!ok || !!busy}>{busy ? "Opening" : "Open"}</button>
        <button type="button" className="ghost" onClick={() => { setOwner(DEMO.owner); setTenant(DEMO.tenant); setMethod("passphrase"); }}>Fill the demo lane</button>
        <span className="status mono" aria-live="polite">{busy ? busy : error ? error : ""}</span>
      </div>
    </form>
  );
}
