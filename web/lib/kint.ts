/* The app's data layer over @s0nderlabs/kint-core. Everything here runs in the browser: the three
   RPC reads fetch public ciphertext, the key never leaves the page, and nothing is ever written. */
"use client";

import { createPublicClient, http, type Hex, type PublicClient } from "viem";
import { base } from "viem/chains";
import {
  fromViem, readHead, walkEpochs, epochCiphertext, assertCiphertextMatchesDigest,
  readEpoch, applyEpoch, spaceId, kekFromSignature, kekFromPassphrase, findWrap, unwrapDek,
  peekHeader, decodeRecoveryCode, dekId, isSnapshotHeader, typedData, rowId, deletedId, toHex, fromHex,
  DEFAULT_CONTRACT, PUBLIC_RPC, KintCryptoError,
  type EpochEvent, type Row, type Head, type EpochReadClient,
} from "@/lib/core";

export type UnlockMethod = "passphrase" | "signature" | "recovery";

export interface VaultRef { owner: string; tenant: string; contract?: string; rpc?: string }

export interface Unlocked { dek: Uint8Array; dekId: string; head: Head; space: Uint8Array; kind: UnlockMethod }

export interface EpochSummary {
  seq: number; block: number; tx: Hex; digest: string; writer: string;
  snapshot: boolean; nRows: number; changed: number; deleted: number; bucket: number;
  createdAt: string; matchesRoot: boolean; opened: boolean; note?: string;
}

export interface RowVersion { seq: number; block: number; row: Row | null }

export interface Memory {
  head: Head; space: string; epochs: EpochSummary[]; rows: Row[];
  versions: Map<string, RowVersion[]>; stoppedAt: number | null;
}

export function makeClient(rpc?: string): EpochReadClient {
  return fromViem(createPublicClient({ chain: base, transport: http(rpc || PUBLIC_RPC) }) as PublicClient);
}

export function short(hex: string, head = 6, tail = 4): string {
  return hex.length > head + tail + 2 ? `${hex.slice(0, head + 2)}…${hex.slice(-tail)}` : hex;
}

export function fmtBlock(n: number): string { return n.toLocaleString("en-US"); }

export function idOf(row: Row): string { return rowId(row); }

/** head(owner, space): the newest digest, seq and block. Public, needs no key. */
export async function fetchHead(ref: VaultRef): Promise<{ head: Head; space: Uint8Array }> {
  const client = makeClient(ref.rpc);
  const space = spaceId(ref.tenant);
  const head = await readHead(client, ref.contract || DEFAULT_CONTRACT, ref.owner, space);
  return { head, space };
}

/** Ask a browser wallet for the one frozen vault message. The signature IS the key: it stays in this tab. */
export async function requestVaultSignature(owner: string): Promise<Uint8Array> {
  const eth = (globalThis as { ethereum?: { request: (a: { method: string; params?: unknown[] }) => Promise<unknown> } }).ethereum;
  if (!eth) throw new Error("no browser wallet found on this page");
  const accounts = (await eth.request({ method: "eth_requestAccounts" })) as string[];
  const from = accounts.find((a) => a.toLowerCase() === owner.toLowerCase());
  if (!from) throw new Error(`the wallet is not on ${short(owner)}; switch accounts and try again`);
  const sig = (await eth.request({ method: "eth_signTypedData_v4", params: [from, JSON.stringify(typedData(owner))] })) as string;
  return fromHex(sig);
}

/** Find this key's wrap in the newest header and unwrap the data key. */
export async function unlock(ref: VaultRef, method: UnlockMethod, secret: string | Uint8Array): Promise<Unlocked> {
  const client = makeClient(ref.rpc);
  const contract = ref.contract || DEFAULT_CONTRACT;
  const space = spaceId(ref.tenant);
  const head = await readHead(client, contract, ref.owner, space);
  if (head.seq === 0) throw new Error("this owner has no epochs in this space yet");
  const [newest] = await walkEpochs(client, contract, ref.owner, space, { head, maxEpochs: 1 });
  const { ct } = await epochCiphertext(client, newest.txHash, contract);
  assertCiphertextMatchesDigest(ct, newest.digest);
  const header = peekHeader(ct);
  let dek: Uint8Array;
  if (method === "recovery") {
    dek = decodeRecoveryCode(String(secret));
    if (toHex(dekId(dek)) !== toHex(header.dekId)) throw new KintCryptoError("this recovery code does not open the current data key (rotated since it was written?)");
  } else {
    const kek = method === "passphrase"
      ? kekFromPassphrase(String(secret), ref.owner, space)
      : await kekFromSignature(secret as Uint8Array, ref.owner, space);
    const wrap = findWrap(header.wraps, kek.tag);
    if (!wrap) throw new KintCryptoError(method === "passphrase" ? "no wrap in the newest epoch opens with this passphrase" : "no wrap in the newest epoch opens with this wallet's signature");
    dek = await unwrapDek(wrap, kek.kek, kek.tag);
  }
  return { dek, dekId: toHex(dekId(dek)), head, space, kind: method };
}

/** Walk the whole history, open what this key opens, fold the state, keep every row's versions. */
export async function loadMemory(ref: VaultRef, u: Unlocked, onProgress?: (msg: string) => void): Promise<Memory> {
  const client = makeClient(ref.rpc);
  const contract = ref.contract || DEFAULT_CONTRACT;
  onProgress?.("walking the chain from the head to genesis");
  const newestFirst = await walkEpochs(client, contract, ref.owner, u.space, { head: u.head });
  const events: EpochEvent[] = [...newestFirst].reverse();
  let state = new Map<string, Row>();
  const versions = new Map<string, RowVersion[]>();
  const epochs: EpochSummary[] = [];
  let stoppedAt: number | null = null;
  for (const ev of events) {
    onProgress?.(`opening epoch ${ev.seq} at block ${fmtBlock(ev.blockNumber)}`);
    const { ct } = await epochCiphertext(client, ev.txHash, contract);
    assertCiphertextMatchesDigest(ct, ev.digest);
    const header = peekHeader(ct);
    const summary: EpochSummary = {
      seq: ev.seq, block: ev.blockNumber, tx: ev.txHash, digest: toHex(ev.digest), writer: ev.writer,
      snapshot: isSnapshotHeader(header), nRows: 0, changed: 0, deleted: 0, bucket: header.bucket,
      createdAt: "", matchesRoot: false, opened: false,
    };
    if (stoppedAt !== null) { epochs.push({ ...summary, note: "not applied: an earlier epoch did not open" }); continue; }
    try {
      const { header: h, doc } = await readEpoch(ct, { dek: u.dek, owner: ref.owner, space: u.space, seq: ev.seq, prev: ev.prev });
      const applied = applyEpoch(state, h, doc);
      if (doc.snapshot) {
        for (const id of state.keys()) if (!applied.state.has(id)) push(versions, id, { seq: ev.seq, block: ev.blockNumber, row: null });
      }
      for (const row of doc.rows) push(versions, rowId(row), { seq: ev.seq, block: ev.blockNumber, row });
      for (const d of doc.deleted) push(versions, deletedId(d), { seq: ev.seq, block: ev.blockNumber, row: null });
      state = applied.state;
      epochs.push({ ...summary, snapshot: applied.snapshot, nRows: doc.n_rows, changed: doc.rows.length, deleted: doc.deleted.length, createdAt: doc.created_at, matchesRoot: applied.matchesRowsRoot, opened: true });
    } catch (e) {
      stoppedAt = ev.seq;
      epochs.push({ ...summary, note: e instanceof Error ? e.message : String(e) });
    }
  }
  return { head: u.head, space: toHex(u.space), epochs, rows: [...state.values()], versions, stoppedAt };
}

function push(m: Map<string, RowVersion[]>, id: string, v: RowVersion) {
  const arr = m.get(id); if (arr) arr.push(v); else m.set(id, [v]);
}
