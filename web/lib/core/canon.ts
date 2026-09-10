/**
 * Canonical row identity, leaf hashes and the merkle root. Port of src/kint/canon.py.
 *
 * The leaf hashes the EXACT stored TEXT of a row: Sibyl's storage keeps
 * insertion order on purpose, so a re-serialised body would refuse every row on
 * the second device. Nothing in this file ever re-encodes a body.
 *
 * Leaves are ordered by their canonical id, and that ordering is Python's:
 * by Unicode code point, not by UTF-16 code unit. See compareCodePoints.
 */

import { keccak_256 } from '@noble/hashes/sha3.js';

import {
  EMPTY_ROOT,
  JOURNAL_KEY_PREFIX,
  KintCryptoError,
  LEAF_PREFIX,
  LP_NULL,
  TIERS,
} from './constants';
import type { Tier } from './constants';
import { compareCodePoints, concatBytes, fromHex, toHex, u32be, utf8Bytes } from './bytes';

/**
 * One row of a Sibyl store as it travels in an epoch. Same fields as Python's
 * Row minus rowid and journal_id, which are local only and never hashed.
 */
export interface Row {
  tier: Tier | string;
  /** entity name | state key | reference doc_key | journal content key */
  key: string;
  /** entities only */
  category?: string | null;
  /** entities only */
  status?: string | null;
  /** the stored TEXT (entity/state/reference) */
  body?: string | null;
  /** reference metadata TEXT */
  meta?: string | null;
  /** updated_at (regenerated on replay) or the journal ts (content) */
  ts?: string | null;
  /** journal TEXT columns */
  evaluated?: string | null;
  acted?: string | null;
  forward?: string | null;
  extra?: string | null;
}

/** Length prefix: uint32(len(utf8)) || utf8, and 0xFFFFFFFF for a null column. */
export function lp(x: string | null | undefined): Uint8Array {
  if (x === null || x === undefined) return u32be(LP_NULL);
  const b = utf8Bytes(x);
  return concatBytes(u32be(b.length), b);
}

/**
 * Journal rows get a new uuid on replay, so their identity is their content.
 * The exporter appends an ordinal suffix (":1", ":2") for a repeated identical
 * event; the first keeps the bare content key.
 */
export function journalContentKey(
  ts: string | null | undefined,
  evaluated: string | null | undefined,
  acted: string | null | undefined,
  forward: string | null | undefined,
  extra: string | null | undefined,
): string {
  return toHex(
    keccak_256(
      concatBytes(JOURNAL_KEY_PREFIX, lp(ts), lp(evaluated), lp(acted), lp(forward), lp(extra)),
    ),
  );
}

/** The canonical identity string of a row: tier \0 category \0 key. */
export function rowId(row: Row): string {
  if (!(TIERS as readonly string[]).includes(row.tier)) {
    throw new KintCryptoError(`unknown tier ${row.tier}`);
  }
  return `${row.tier}\u0000${row.category ?? ''}\u0000${row.key}`;
}

/** The same id from a [tier, category, key] deletion triple, as epochs carry it. */
export function deletedId(triple: readonly (string | null | undefined)[]): string {
  const [tier, category, key] = triple;
  return `${tier}\u0000${category ?? ''}\u0000${key}`;
}

/** keccak256("kint-leaf-v1" || the length-prefixed columns of the row). */
export function leaf(row: Row): Uint8Array {
  const pre =
    row.tier === 'journal'
      ? concatBytes(
          LEAF_PREFIX,
          lp('journal'),
          lp(null),
          lp(row.key),
          lp(null),
          lp(row.ts),
          lp(row.evaluated),
          lp(row.acted),
          lp(row.forward),
          lp(row.extra),
        )
      : concatBytes(
          LEAF_PREFIX,
          lp(row.tier),
          lp(row.category),
          lp(row.key),
          lp(row.status),
          lp(row.body),
          lp(row.meta),
        );
  return keccak_256(pre);
}

function hashPair(a: Uint8Array, b: Uint8Array): Uint8Array {
  return keccak_256(concatBytes(a, b));
}

/** row_id -> leaf, for a whole row set. */
export function leavesOf(rows: readonly Row[]): Map<string, Uint8Array> {
  const out = new Map<string, Uint8Array>();
  for (const r of rows) out.set(rowId(r), leaf(r));
  return out;
}

/** Accepts either a Map or a plain object of row_id -> leaf. */
export type Leaves = Map<string, Uint8Array> | Record<string, Uint8Array>;

function sortedEntries(leaves: Leaves): { ids: string[]; level: Uint8Array[] } {
  const map = leaves instanceof Map ? leaves : new Map(Object.entries(leaves));
  const ids = [...map.keys()].sort(compareCodePoints);
  return { ids, level: ids.map((id) => map.get(id)!) };
}

/** The ids of a leaf set in the canonical order, exactly as Python's sorted(). */
export function sortedIds(leaves: Leaves): string[] {
  return sortedEntries(leaves).ids;
}

/**
 * Root over leaves sorted by canonical id. An odd last node is carried up unchanged.
 *
 * The return is always a fresh array: with one leaf, or with an empty state, the
 * root IS a caller's leaf or the shared EMPTY_ROOT, and handing those out by
 * reference lets one careless write corrupt the constant.
 */
export function merkleRoot(leaves: Leaves): Uint8Array {
  let { level } = sortedEntries(leaves);
  if (level.length === 0) return EMPTY_ROOT.slice();
  while (level.length > 1) {
    const next: Uint8Array[] = [];
    for (let i = 0; i + 1 < level.length; i += 2) next.push(hashPair(level[i]!, level[i + 1]!));
    if (level.length % 2 === 1) next.push(level[level.length - 1]!);
    level = next;
  }
  return level[0]!.slice();
}

/** One step of an inclusion proof: the sibling and which side it sits on. */
export interface ProofStep {
  sibling: string;
  siblingIsLeft: boolean;
}

/** Inclusion proof for targetId. Mirrors canon.merkle_proof step for step. */
export function merkleProof(leaves: Leaves, targetId: string): ProofStep[] {
  const { ids, level: first } = sortedEntries(leaves);
  let idx = ids.indexOf(targetId);
  if (idx < 0) throw new KintCryptoError(`no leaf for ${JSON.stringify(targetId)}`);
  let level = first;
  const proof: ProofStep[] = [];
  while (level.length > 1) {
    const next: Uint8Array[] = [];
    for (let i = 0; i + 1 < level.length; i += 2) next.push(hashPair(level[i]!, level[i + 1]!));
    if (level.length % 2 === 1) next.push(level[level.length - 1]!);
    if (idx % 2 === 0) {
      if (idx + 1 < level.length) proof.push({ sibling: toHex(level[idx + 1]!), siblingIsLeft: false });
      // else: this node is carried up, there is no sibling at this level
    } else {
      proof.push({ sibling: toHex(level[idx - 1]!), siblingIsLeft: true });
    }
    idx = Math.floor(idx / 2);
    level = next;
  }
  return proof;
}

/** Replay a proof up to the root. */
export function verifyProof(
  leafHash: Uint8Array,
  proof: readonly ProofStep[],
  root: Uint8Array,
): boolean {
  let h = leafHash;
  for (const step of proof) {
    const sib = fromHex(step.sibling);
    h = step.siblingIsLeft ? hashPair(sib, h) : hashPair(h, sib);
  }
  return toHex(h) === toHex(root);
}
