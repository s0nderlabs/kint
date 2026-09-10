"use client";
import { useCallback, useState } from "react";
import { unlock, loadMemory, requestVaultSignature, type Memory, type UnlockMethod, type VaultRef } from "@/lib/kint";
import ConnectCard from "./ConnectCard";
import MemoryView from "./MemoryView";

type Phase =
  | { kind: "idle" }
  | { kind: "busy"; msg: string }
  | { kind: "error"; msg: string }
  | { kind: "ready"; ref: VaultRef; memory: Memory; method: UnlockMethod };

export default function AppClient() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  const open = useCallback(async (ref: VaultRef, method: UnlockMethod, secret: string) => {
    try {
      setPhase({ kind: "busy", msg: method === "signature" ? "waiting for the wallet to sign the vault message" : "deriving the key from the passphrase" });
      const key = method === "signature" ? await requestVaultSignature(ref.owner) : secret;
      setPhase({ kind: "busy", msg: "reading the head and the newest epoch" });
      const u = await unlock(ref, method, key);
      const memory = await loadMemory(ref, u, (msg) => setPhase({ kind: "busy", msg }));
      setPhase({ kind: "ready", ref, memory, method });
    } catch (e) {
      setPhase({ kind: "error", msg: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const reset = useCallback(() => setPhase({ kind: "idle" }), []);

  return (
    <main className="app">
      <div className="wrap">
        {phase.kind === "ready" ? (
          <MemoryView owner={phase.ref.owner} tenant={phase.ref.tenant} memory={phase.memory} method={phase.method} onClose={reset} />
        ) : (
          <>
            <header className="app-head">
              <h1>Your memory, read off Base.</h1>
              <p>Nothing decrypted leaves this page. Type the vault passphrase, sign the one frozen message with the owner wallet, or paste the recovery code; the page reads the epochs from the chain and opens them here.</p>
            </header>
            <ConnectCard busy={phase.kind === "busy" ? phase.msg : null} error={phase.kind === "error" ? phase.msg : null} onOpen={open} />
          </>
        )}
      </div>
    </main>
  );
}
