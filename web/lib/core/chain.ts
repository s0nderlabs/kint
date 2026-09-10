/**
 * The EpochAnchor reads the viewer needs. Port of the read half of src/kint/chain.py.
 *
 * The walk goes head to genesis through the prevBlock field of each Epoch event,
 * one exact-block eth_getLogs per hop, so no RPC log-range cap is ever hit.
 * Nothing here writes; the browser only reads.
 */

import { decodeFunctionData, getAddress, keccak256 } from 'viem';
import type { Address, Hex, PublicClient } from 'viem';

import { KintCryptoError } from './constants';
import { fromHex, normaliseAddress, to0x } from './bytes';
import { isSnapshotHeader, peekHeader } from './envelope';

/** EpochAnchor on Base mainnet, deployed Sep 9 2026 at block 51,081,696. */
export const DEFAULT_CONTRACT = '0xa22E03f7a4145Bf4909a83595C90a38E14d79600' as const;
export const BASE_CHAIN_ID = 8453;
export const PUBLIC_RPC = 'https://mainnet.base.org';

export const EPOCH_EVENT = {
  type: 'event',
  name: 'Epoch',
  anonymous: false,
  inputs: [
    { name: 'owner', type: 'address', indexed: true },
    { name: 'space', type: 'bytes32', indexed: true },
    { name: 'writer', type: 'address', indexed: true },
    { name: 'seq', type: 'uint64', indexed: false },
    { name: 'prev', type: 'bytes32', indexed: false },
    { name: 'digest', type: 'bytes32', indexed: false },
    { name: 'prevBlock', type: 'uint64', indexed: false },
  ],
} as const;

/** The minimal slice of EpochAnchor a reader needs. Full ABI: contracts/abi/EpochAnchor.json. */
export const EPOCH_ANCHOR_ABI = [
  {
    type: 'function',
    name: 'head',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'space', type: 'bytes32' },
    ],
    outputs: [
      { name: 'digest', type: 'bytes32' },
      { name: 'seq', type: 'uint64' },
      { name: 'blockNumber', type: 'uint64' },
    ],
  },
  {
    type: 'function',
    name: 'sessionKeyExpiry',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'key', type: 'address' },
    ],
    outputs: [{ name: 'expiry', type: 'uint64' }],
  },
  {
    type: 'function',
    name: 'startSeq',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'space', type: 'bytes32' },
    ],
    outputs: [{ name: 'seq', type: 'uint64' }],
  },
  {
    type: 'function',
    name: 'push',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'space', type: 'bytes32' },
      { name: 'prev', type: 'bytes32' },
      { name: 'ct', type: 'bytes' },
    ],
    outputs: [
      { name: 'digest', type: 'bytes32' },
      { name: 'seq', type: 'uint64' },
    ],
  },
  EPOCH_EVENT,
] as const;

// ---------------------------------------------------------------------------
// The client seam
// ---------------------------------------------------------------------------

/** One decoded Epoch log, in the shape both viem and the tests produce. */
export interface EpochLog {
  args: {
    owner: Address;
    space: Hex;
    writer: Address;
    seq: bigint;
    prev: Hex;
    digest: Hex;
    prevBlock: bigint;
  };
  blockNumber: bigint | null;
  transactionHash: Hex | null;
}

/**
 * The three RPC calls this module makes. A viem PublicClient satisfies it
 * through fromViem(); a fake object satisfies it directly, which is how the
 * walk is tested without a network.
 */
export interface EpochReadClient {
  readContract(args: {
    address: Address;
    abi: readonly unknown[];
    functionName: string;
    args?: readonly unknown[];
  }): Promise<unknown>;
  getLogs(args: {
    address: Address;
    event: unknown;
    args?: Record<string, unknown>;
    fromBlock: bigint;
    toBlock: bigint;
    strict?: boolean;
  }): Promise<readonly EpochLog[]>;
  getTransaction(args: { hash: Hex }): Promise<{ to: Address | null; input: Hex }>;
}

/** Wrap a viem PublicClient so the readers below can use it. */
export function fromViem(client: PublicClient): EpochReadClient {
  return {
    readContract: (args) => client.readContract(args as never) as Promise<unknown>,
    getLogs: (args) => client.getLogs(args as never) as unknown as Promise<readonly EpochLog[]>,
    getTransaction: (args) =>
      client.getTransaction(args) as unknown as Promise<{ to: Address | null; input: Hex }>,
  };
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

export interface Head {
  digest: Uint8Array;
  seq: number;
  blockNumber: number;
}

export interface EpochEvent {
  owner: Address;
  space: Uint8Array;
  writer: Address;
  seq: number;
  prev: Uint8Array;
  digest: Uint8Array;
  prevBlock: number;
  blockNumber: number;
  txHash: Hex;
}

function toBytes32(h: Hex): Uint8Array {
  const b = fromHex(h);
  if (b.length !== 32) throw new KintCryptoError(`expected 32 bytes, got ${b.length}`);
  return b;
}

/** head(owner, space) -> the newest digest, its seq and the block it landed in. */
export async function readHead(
  client: EpochReadClient,
  contract: Address | string,
  owner: string,
  space: Uint8Array,
): Promise<Head> {
  const raw = (await client.readContract({
    address: normaliseAddress(contract),
    abi: EPOCH_ANCHOR_ABI,
    functionName: 'head',
    args: [normaliseAddress(owner), to0x(space)],
  })) as readonly [Hex, bigint | number, bigint | number];
  return {
    digest: toBytes32(raw[0]),
    seq: Number(raw[1]),
    blockNumber: Number(raw[2]),
  };
}

/** sessionKeyExpiry(owner, key) as a unix second, 0 when the key was never authorized. */
export async function readSessionKeyExpiry(
  client: EpochReadClient,
  contract: Address | string,
  owner: string,
  key: string,
): Promise<number> {
  const raw = (await client.readContract({
    address: normaliseAddress(contract),
    abi: EPOCH_ANCHOR_ABI,
    functionName: 'sessionKeyExpiry',
    args: [normaliseAddress(owner), normaliseAddress(key)],
  })) as bigint | number;
  return Number(raw);
}

/**
 * startSeq(owner, space): the lowest seq the owner still vouches for. A reader
 * that walks below it is looking at epochs the owner has disowned.
 */
export async function readStartSeq(
  client: EpochReadClient,
  contract: Address | string,
  owner: string,
  space: Uint8Array,
): Promise<number> {
  const raw = (await client.readContract({
    address: normaliseAddress(contract),
    abi: EPOCH_ANCHOR_ABI,
    functionName: 'startSeq',
    args: [normaliseAddress(owner), to0x(space)],
  })) as bigint | number;
  return Number(raw);
}

function toEvent(log: EpochLog): EpochEvent {
  if (log.blockNumber === null) throw new KintCryptoError('Epoch log has no block number (pending?)');
  if (log.transactionHash === null) throw new KintCryptoError('Epoch log has no transaction hash');
  const a = log.args;
  return {
    owner: getAddress(a.owner),
    space: toBytes32(a.space),
    writer: getAddress(a.writer),
    seq: Number(a.seq),
    prev: toBytes32(a.prev),
    digest: toBytes32(a.digest),
    prevBlock: Number(a.prevBlock),
    blockNumber: Number(log.blockNumber),
    txHash: log.transactionHash,
  };
}

/** Exact-block query: every Epoch event for (owner, space) in that one block. */
export async function epochsAtBlock(
  client: EpochReadClient,
  contract: Address | string,
  owner: string,
  space: Uint8Array,
  blockNumber: number,
): Promise<EpochEvent[]> {
  const logs = await client.getLogs({
    address: normaliseAddress(contract),
    event: EPOCH_EVENT,
    args: { owner: normaliseAddress(owner), space: to0x(space) },
    fromBlock: BigInt(blockNumber),
    toBlock: BigInt(blockNumber),
    strict: true,
  });
  return logs.map(toEvent);
}

export interface WalkOptions {
  /** Exclusive floor: the walk stops once it has taken seq = stopSeq + 1. */
  stopSeq?: number;
  /** Skip the head() call when the caller already has it. */
  head?: Head;
  maxEpochs?: number;
  /**
   * Evaluated AFTER an event is appended. True ends the walk with that event
   * included, which is how a cold start stops at the newest snapshot epoch.
   * It may be async, because deciding that usually needs the ciphertext:
   * see isSnapshotEvent.
   */
  stopWhen?: (ev: EpochEvent) => boolean | Promise<boolean>;
}

/** Head to genesis (or to stopSeq exclusive), newest first, via prevBlock. */
export async function walkEpochs(
  client: EpochReadClient,
  contract: Address | string,
  owner: string,
  space: Uint8Array,
  options: WalkOptions = {},
): Promise<EpochEvent[]> {
  const { stopSeq = 0, maxEpochs = 100000, stopWhen } = options;
  const head = options.head ?? (await readHead(client, contract, owner, space));
  const out: EpochEvent[] = [];
  if (head.seq === 0) return out;
  let block = head.blockNumber;
  let wantSeq = head.seq;
  while (block > 0 && wantSeq > stopSeq && out.length < maxEpochs) {
    const evs = (await epochsAtBlock(client, contract, owner, space, block)).filter(
      (e) => e.seq === wantSeq,
    );
    const ev = evs[0];
    if (!ev) {
      throw new KintCryptoError(
        `no Epoch event for seq ${wantSeq} at block ${block}; the RPC may be pruned or lying`,
      );
    }
    out.push(ev);
    if (await stopWhen?.(ev)) break;
    block = ev.prevBlock;
    wantSeq -= 1;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Calldata
// ---------------------------------------------------------------------------

export interface PushCall {
  owner: Address;
  space: Uint8Array;
  prev: Uint8Array;
  ct: Uint8Array;
}

/** Decode push(owner, space, prev, ct) out of a transaction's input. */
export function decodePushCalldata(data: Hex): PushCall {
  const decoded = decodeFunctionData({ abi: EPOCH_ANCHOR_ABI, data });
  if (decoded.functionName !== 'push') {
    throw new KintCryptoError(`calldata calls ${decoded.functionName}, not push`);
  }
  const [owner, space, prev, ct] = decoded.args as readonly [Address, Hex, Hex, Hex];
  return {
    owner: getAddress(owner),
    space: toBytes32(space),
    prev: toBytes32(prev),
    ct: fromHex(ct),
  };
}

/**
 * The epoch ciphertext, straight out of the push transaction's calldata.
 * The caller must still check keccak256(ct) against the event digest; see
 * assertCiphertextMatchesDigest.
 */
export async function epochCiphertext(
  client: EpochReadClient,
  txHash: Hex,
  contract: Address | string,
): Promise<PushCall> {
  const tx = await client.getTransaction({ hash: txHash });
  // `contract` is required: without it a reader would decode push() calldata out of
  // ANY transaction, and an attacker's own contract can emit whatever it likes.
  if (tx.to === null || normaliseAddress(tx.to) !== normaliseAddress(contract)) {
    throw new KintCryptoError(`tx ${txHash} is not addressed to EpochAnchor`);
  }
  return decodePushCalldata(tx.input);
}

/** keccak256(ct) must equal the digest the Epoch event published. */
export function assertCiphertextMatchesDigest(ct: Uint8Array, digest: Uint8Array): void {
  const got = keccak256(to0x(ct));
  const want = to0x(digest);
  if (got !== want) {
    throw new KintCryptoError(
      `ciphertext digest ${got} does not match the anchored digest ${want}; refusing this epoch`,
    );
  }
}

/**
 * Does this epoch carry the full row set? The Epoch event does not say, so this
 * fetches the push calldata and peeks the header flag. Use it as the stopWhen of
 * a cold-start walk: the newest snapshot is far enough back to restore from.
 */
export async function isSnapshotEvent(
  client: EpochReadClient,
  ev: EpochEvent,
  contract: Address | string,
): Promise<boolean> {
  try {
    const call = await epochCiphertext(client, ev.txHash, contract);
    assertCiphertextMatchesDigest(call.ct, ev.digest);
    return isSnapshotHeader(peekHeader(call.ct));
  } catch {
    // an epoch we cannot even read the header of is not a place to stop
    return false;
  }
}

// ---------------------------------------------------------------------------
// Cold start
// ---------------------------------------------------------------------------

export interface ColdStartOptions {
  /** Exclusive floor, as in WalkOptions: the walk stops once it has taken stopSeq + 1. */
  stopSeq?: number;
  /** Skip the head() call when the caller already has it. */
  head?: Head;
  /**
   * Open the epoch and check it, which is the whole point of this call: the
   * FLAG_SNAPSHOT bit sits outside the AAD, so only opening the epoch and
   * comparing its plaintext can tell a real snapshot from a flipped byte. The
   * app supplies this because only the app has the DEK; it should fetch the
   * ciphertext and run readEpoch, then return true. False or a throw both mean
   * "this is not a place to stop".
   */
  tryOpen: (ev: EpochEvent) => boolean | Promise<boolean>;
}

export interface ColdStart {
  /** OLDEST FIRST, ready to feed to applyEpoch in order. */
  events: EpochEvent[];
  /**
   * The seq of an epoch whose header claimed FLAG_SNAPSHOT and which then did
   * not open, or null. The events list walks past it, so the app must skip that
   * one epoch when it applies them and should say on screen that it did.
   */
  refusedSnapshotSeq: number | null;
  /** True when the list starts at a snapshot epoch that opened: a short restore. */
  stoppedAtSnapshot: boolean;
}

/**
 * The walk a cold start should use. Port of the retry in src/kint/pull.py.
 *
 * Stopping at the newest snapshot bounds the restore by the size of the memory
 * rather than by its history, but the flag that says "snapshot" is an
 * UNAUTHENTICATED header byte. If the walk stops on a flipped one, a reader that
 * trusts it ends with a single epoch it cannot open and no rows at all. So the
 * stop is provisional: the epoch has to open before it is allowed to end the
 * walk, and when it does not this re-walks the whole history without the
 * predicate and names the epoch it refused.
 */
export async function coldStartEvents(
  client: EpochReadClient,
  contract: Address | string,
  owner: string,
  space: Uint8Array,
  options: ColdStartOptions,
): Promise<ColdStart> {
  const { stopSeq, head, tryOpen } = options;
  // an array, not a `let`: the assignment happens inside the callback, and this
  // keeps the value readable afterwards without fighting the narrowing
  const stops: EpochEvent[] = [];
  const walked = await walkEpochs(client, contract, owner, space, {
    stopSeq,
    head,
    stopWhen: async (ev) => {
      const flagged = await isSnapshotEvent(client, ev, contract);
      if (flagged) stops.push(ev);
      return flagged;
    },
  });
  const stoppedAt = stops[stops.length - 1];
  if (stoppedAt !== undefined) {
    let opened = false;
    try {
      opened = (await tryOpen(stoppedAt)) === true;
    } catch {
      opened = false;
    }
    if (!opened) {
      const all = await walkEpochs(client, contract, owner, space, { stopSeq, head });
      all.reverse();
      return { events: all, refusedSnapshotSeq: stoppedAt.seq, stoppedAtSnapshot: false };
    }
  }
  walked.reverse();
  return { events: walked, refusedSnapshotSeq: null, stoppedAtSnapshot: stoppedAt !== undefined };
}
