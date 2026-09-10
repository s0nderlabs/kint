/**
 * The epoch plaintext format. Port of the wire half of src/kint/epoch.py.
 *
 *   {"v":1,"tenant","space","seq","prev","rows":[...],
 *    "deleted":[[tier,category,key],...],"rows_root","n_rows","created_at",
 *    "snapshot":true (only on a snapshot epoch)}
 */

import { EPOCH_VERSION, KintCryptoError } from './constants';
import { deletedId, leavesOf, merkleRoot, rowId } from './canon';
import type { Row } from './canon';
import { isSnapshotHeader, openEpoch } from './envelope';
import type { Header, OpenEpochInput } from './envelope';
import { toHex, utf8String } from './bytes';

/** A deletion as the epoch carries it: [tier, category, key]. */
export type DeletedTriple = [string, string | null, string];

export interface EpochPlaintext {
  v: number;
  tenant: string;
  space: string;
  seq: number;
  prev: string;
  rows: Row[];
  deleted: DeletedTriple[];
  /** Hex merkle root of the FULL state after this epoch. */
  rows_root: string;
  /** Total rows after this epoch. */
  n_rows: number;
  created_at: string;
  /**
   * True when "rows" is the full state, not a diff. Absent on an ordinary
   * epoch, so an older writer stays byte-identical to v1.
   */
  snapshot: boolean;
}

const ROW_FIELDS = [
  'tier',
  'key',
  'category',
  'status',
  'body',
  'meta',
  'ts',
  'evaluated',
  'acted',
  'forward',
  'extra',
] as const;

function toRow(raw: unknown): Row {
  if (typeof raw !== 'object' || raw === null) throw new KintCryptoError('epoch row is not an object');
  const src = raw as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const f of ROW_FIELDS) {
    if (f in src) out[f] = src[f];
  }
  if (typeof out.tier !== 'string' || typeof out.key !== 'string') {
    throw new KintCryptoError('epoch row is missing tier or key');
  }
  return out as unknown as Row;
}

/** Parse a decrypted epoch payload. Refuses any version but 1. */
export function parsePlaintext(data: Uint8Array | string): EpochPlaintext {
  const text = typeof data === 'string' ? data : utf8String(data);
  const doc = JSON.parse(text) as Record<string, unknown>;
  if (doc.v !== EPOCH_VERSION) {
    throw new KintCryptoError(`unsupported epoch version ${String(doc.v)}`);
  }
  const rawRows = Array.isArray(doc.rows) ? doc.rows : [];
  const rawDeleted = Array.isArray(doc.deleted) ? doc.deleted : [];
  return {
    v: EPOCH_VERSION,
    tenant: String(doc.tenant ?? ''),
    space: String(doc.space ?? ''),
    seq: Number(doc.seq ?? 0),
    prev: String(doc.prev ?? ''),
    rows: rawRows.map(toRow),
    deleted: rawDeleted as DeletedTriple[],
    rows_root: String(doc.rows_root ?? ''),
    n_rows: Number(doc.n_rows ?? 0),
    created_at: String(doc.created_at ?? ''),
    snapshot: doc.snapshot === true,
  };
}

// ---------------------------------------------------------------------------
// Header / plaintext agreement
// ---------------------------------------------------------------------------

/** What the reader already knows about this epoch before it opens it. */
export interface EpochExpectation {
  seq: number | bigint;
  /** The previous epoch's digest: raw bytes, or hex with or without 0x. */
  prev: Uint8Array | string;
  /** The 32-byte space id: hex with or without 0x, or raw bytes. */
  spaceHex: string | Uint8Array;
}

function bareHex(x: Uint8Array | string): string {
  if (typeof x !== 'string') return toHex(x);
  const t = x.trim();
  return (t.startsWith('0x') || t.startsWith('0X') ? t.slice(2) : t).toLowerCase();
}

/**
 * Every check kint's own pull runs after an epoch opens. Port of the block in
 * src/kint/pull.py that follows crypto.open_epoch.
 *
 * The AEAD already binds owner, space, seq, prev, bucket, rows_root and dek_id,
 * so a mismatch here means the plaintext contradicts the header it travelled in.
 * The snapshot flag is the one that matters most: header flags are NOT covered
 * by the AAD, so a byte flipped in transit turns a diff into a snapshot for free
 * unless a reader insists the plaintext agrees.
 */
export function assertEpochConsistent(
  header: Header,
  doc: EpochPlaintext,
  expected: EpochExpectation,
): void {
  const wantSeq = Number(expected.seq);
  if (doc.seq !== wantSeq) {
    throw new KintCryptoError(`epoch seq disagrees: plaintext ${doc.seq}, chain ${wantSeq}`);
  }
  const wantSpace = bareHex(expected.spaceHex);
  if (bareHex(doc.space) !== wantSpace) {
    throw new KintCryptoError(`epoch space disagrees: plaintext ${doc.space}, expected ${wantSpace}`);
  }
  const wantPrev = bareHex(expected.prev);
  if (bareHex(doc.prev) !== wantPrev) {
    throw new KintCryptoError(`epoch prev disagrees: plaintext ${doc.prev}, chain ${wantPrev}`);
  }
  const wantRoot = toHex(header.rowsRoot);
  if (bareHex(doc.rows_root) !== wantRoot) {
    throw new KintCryptoError(
      `epoch rows_root disagrees: plaintext ${doc.rows_root}, header ${wantRoot}`,
    );
  }
  if (isSnapshotHeader(header) !== doc.snapshot) {
    throw new KintCryptoError(
      `epoch snapshot flag disagrees: header says ${isSnapshotHeader(header)}, ` +
        `plaintext says ${doc.snapshot}; refusing to act on either`,
    );
  }
}

/** An opened, parsed and cross-checked epoch. */
export interface ReadEpoch {
  header: Header;
  doc: EpochPlaintext;
  /** The exact decompressed bytes, for a caller that caches them. */
  plaintext: Uint8Array;
}

/**
 * openEpoch + parsePlaintext + assertEpochConsistent, which is the only
 * combination a viewer should use. openEpoch alone authenticates the
 * ciphertext, not the header flags that sit outside the AAD.
 */
export async function readEpoch(blob: Uint8Array, input: OpenEpochInput): Promise<ReadEpoch> {
  const { header, plaintext } = await openEpoch(blob, input);
  const doc = parsePlaintext(plaintext);
  assertEpochConsistent(header, doc, {
    seq: input.seq,
    prev: input.prev,
    spaceHex: toHex(input.space),
  });
  return { header, doc, plaintext };
}

// ---------------------------------------------------------------------------
// Applying an epoch to a row set
// ---------------------------------------------------------------------------

/** row_id -> Row, as a Map or as a plain object. */
export type RowState = Map<string, Row> | Record<string, Row>;

export interface AppliedEpoch {
  /** A NEW map. applyEpoch never mutates the state it was given. */
  state: Map<string, Row>;
  root: Uint8Array;
  rootHex: string;
  /** True when this epoch carried the full row set. */
  snapshot: boolean;
  /** True when the new root is the one the header (and so the chain) anchored. */
  matchesRowsRoot: boolean;
  /** Row ids the prior state held and this epoch does not: gone, not unchanged. */
  dropped: string[];
}

function asMap(state: RowState): Map<string, Row> {
  return state instanceof Map ? new Map(state) : new Map(Object.entries(state));
}

/**
 * Fold one epoch into a row set, oldest first, and hand back the new root.
 *
 * A SNAPSHOT epoch REPLACES the state: the row map is cleared and set to exactly
 * `doc.rows`, because a snapshot's rows ARE the whole state and its `rows_root`
 * is the root of exactly those rows. Its `deleted` list is informational (what
 * went away since the previous epoch, already absent from `rows`) and is not
 * needed to reach the anchored root, which is what makes a cold start able to
 * stop at the newest snapshot and never read the epochs before it. Merging a
 * snapshot in as though it were a diff silently keeps rows the owner deleted,
 * and the root then refuses.
 *
 * An ordinary epoch is a diff: set `doc.rows`, then delete `doc.deleted`.
 *
 * The state passed in is left alone; use the returned one.
 */
export function applyEpoch(state: RowState, header: Header, doc: EpochPlaintext): AppliedEpoch {
  const snapshot = isSnapshotHeader(header);
  if (snapshot !== doc.snapshot) {
    throw new KintCryptoError(
      `epoch snapshot flag disagrees: header says ${snapshot}, plaintext says ${doc.snapshot}; ` +
        'refusing to apply it (call assertEpochConsistent or readEpoch first)',
    );
  }
  const before = asMap(state);
  const priorIds = [...before.keys()];
  const next = snapshot ? new Map<string, Row>() : before;
  for (const r of doc.rows) next.set(rowId(r), r);
  if (!snapshot) {
    for (const triple of doc.deleted) next.delete(deletedId(triple));
  }
  const dropped = priorIds.filter((id) => !next.has(id));
  const root = merkleRoot(leavesOf([...next.values()]));
  const rootHex = toHex(root);
  return {
    state: next,
    root,
    rootHex,
    snapshot,
    matchesRowsRoot: rootHex === toHex(header.rowsRoot),
    dropped,
  };
}
