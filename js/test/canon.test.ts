/** Row ids, leaves, the code-point sort, the root, proofs and the epoch plaintext. */

import { describe, expect, test } from 'bun:test';

import { compareCodePoints, fromHex, toHex } from '../src/bytes.js';
import { EMPTY_ROOT, FLAG_SNAPSHOT } from '../src/constants.js';
import {
  deletedId,
  journalContentKey,
  leaf,
  leavesOf,
  merkleProof,
  merkleRoot,
  rowId,
  sortedIds,
  verifyProof,
} from '../src/canon.js';
import type { ProofStep, Row } from '../src/canon.js';
import { applyEpoch, parsePlaintext } from '../src/epoch.js';
import type { EpochPlaintext } from '../src/epoch.js';
import { peekHeader } from '../src/envelope.js';
import type { Header } from '../src/envelope.js';
import { V } from './vectors.js';

const ROWS: Row[] = V.rows.map((r) => r.row as unknown as Row);

function steps(proof: [string, boolean][]): ProofStep[] {
  return proof.map(([sibling, siblingIsLeft]) => ({ sibling, siblingIsLeft }));
}

/** The row set epoch 1 anchored, as a fresh map every time. */
function state1(): Map<string, Row> {
  const state = new Map<string, Row>();
  for (const r of parsePlaintext(fromHex(V.epoch1.plaintext)).rows) state.set(rowId(r), r);
  return state;
}

function doc2(): EpochPlaintext {
  return parsePlaintext(fromHex(V.epoch2.plaintext));
}

function header2(): Header {
  return peekHeader(fromHex(V.epoch2.blob));
}

describe('rows', () => {
  test('every row id and leaf matches the Python', () => {
    for (const rec of V.rows) {
      const row = rec.row as unknown as Row;
      expect(rowId(row)).toBe(rec.row_id);
      expect(toHex(leaf(row))).toBe(rec.leaf);
    }
    expect(V.rows.length).toBe(8);
  });

  test('all four tiers, a null category, a null status and a null meta are covered', () => {
    const tiers = new Set(V.rows.map((r) => r.row.tier));
    expect(tiers).toEqual(new Set(['entity', 'state', 'reference', 'journal']));
    expect(V.rows.some((r) => r.row.category === null)).toBe(true);
    expect(V.rows.some((r) => r.row.status === null)).toBe(true);
    expect(V.rows.some((r) => r.row.tier === 'reference' && r.row.meta === null)).toBe(true);
  });

  test('the journal key is the content key, not a uuid', () => {
    const j = V.journal_key_inputs;
    expect(journalContentKey(j.ts, j.evaluated, j.acted, j.forward, j.extra)).toBe(j.key);
    const journalRow = V.rows.find((r) => r.row.tier === 'journal')!;
    expect(journalRow.row.key).toBe(j.key);
  });

  test('a deletion triple resolves to the same id as the row it removes', () => {
    const triple = V.epoch2.deleted![0]!;
    expect(deletedId(triple)).toBe(V.epoch2.deleted_ids![0]!);
    expect(V.sorted_ids).toContain(V.epoch2.deleted_ids![0]!);
  });
});

describe('code point ordering', () => {
  test('sortedIds matches Python sorted() exactly', () => {
    const leaves = leavesOf(ROWS);
    expect(sortedIds(leaves)).toEqual(V.sorted_ids);
  });

  test("it is NOT JavaScript's default UTF-16 order", () => {
    const naive = [...V.sorted_ids].sort();
    expect(naive).not.toEqual(V.sorted_ids);
  });

  test('an astral character sorts after U+FB01, the way Python sorts it', () => {
    expect(compareCodePoints('\u{1F525}hot', 'ﬁrst')).toBeGreaterThan(0);
    expect('\u{1F525}hot' < 'ﬁrst').toBe(true); // the trap: raw JS says the opposite
  });
});

describe('merkle', () => {
  test('the root over the full row set matches', () => {
    expect(toHex(merkleRoot(leavesOf(ROWS)))).toBe(V.rows_root);
    expect(V.epoch1.rows_root).toBe(V.rows_root);
  });

  test('the empty root is keccak256("kint-empty-v1")', () => {
    expect(toHex(EMPTY_ROOT)).toBe(V.empty_root);
    expect(toHex(merkleRoot(new Map()))).toBe(V.empty_root);
  });

  test('the recorded proofs verify against the root', () => {
    const root = fromHex(V.rows_root);
    for (const p of V.proofs) {
      expect(verifyProof(fromHex(p.leaf), steps(p.proof), root)).toBe(true);
    }
    expect(V.proofs.length).toBe(2);
  });

  test('proofs computed here equal the Python proofs', () => {
    const leaves = leavesOf(ROWS);
    for (const p of V.proofs) {
      expect(merkleProof(leaves, p.row_id)).toEqual(steps(p.proof));
    }
  });

  test('a proof does not verify against a different root', () => {
    const p = V.proofs[0]!;
    expect(verifyProof(fromHex(p.leaf), steps(p.proof), new Uint8Array(32))).toBe(false);
  });

  test('a proof does not verify for a different leaf', () => {
    const p = V.proofs[0]!;
    const other = fromHex(V.proofs[1]!.leaf);
    expect(verifyProof(other, steps(p.proof), fromHex(V.rows_root))).toBe(false);
  });

  test('an unknown id has no proof', () => {
    expect(() => merkleProof(leavesOf(ROWS), 'nope')).toThrow(/no leaf for/);
  });
});

describe('epoch plaintext', () => {
  test('epoch 1 parses and its rows rebuild the leaves and the root', () => {
    const doc = parsePlaintext(fromHex(V.epoch1.plaintext));
    expect(doc.v).toBe(1);
    expect(doc.tenant).toBe(V.tenant);
    expect(doc.space).toBe(V.space);
    expect(doc.seq).toBe(1);
    expect(doc.prev).toBe(V.epoch1.prev);
    expect(doc.rows_root).toBe(V.rows_root);
    expect(doc.n_rows).toBe(V.rows.length);
    expect(doc.deleted).toEqual([]);
    expect(doc.snapshot).toBe(false);

    const leaves = leavesOf(doc.rows);
    expect(sortedIds(leaves)).toEqual(V.sorted_ids);
    expect(toHex(merkleRoot(leaves))).toBe(V.rows_root);
    for (const rec of V.rows) {
      const row = doc.rows.find((r) => rowId(r) === rec.row_id)!;
      expect(toHex(leaf(row))).toBe(rec.leaf);
    }
  });

  test('epoch 2 carries the WHOLE state and declares itself a snapshot', () => {
    const doc = parsePlaintext(fromHex(V.epoch2.plaintext));
    expect(doc.seq).toBe(2);
    expect(doc.prev).toBe(V.epoch1.digest);
    expect(doc.snapshot).toBe(true);
    expect(V.epoch2.snapshot_in_plaintext).toBe(true);
    expect(V.epoch2.snapshot_flag_set).toBe(true);
    // the full state: epoch 1's rows less the deleted one, with one row updated
    expect(doc.rows.length).toBe(V.rows.length - 1);
    expect(doc.n_rows).toBe(doc.rows.length);
    expect(doc.deleted).toEqual(V.epoch2.deleted!);
    expect(doc.rows_root).toBe(V.epoch2.rows_root);
    // the anchored root is the root of exactly those rows, nothing folded in
    expect(toHex(merkleRoot(leavesOf(doc.rows)))).toBe(V.epoch2.rows_root);
  });

  test('a snapshot REPLACES the state and reaches the anchored root', () => {
    const { state, root, snapshot, matchesRowsRoot, dropped } = applyEpoch(
      state1(),
      header2(),
      doc2(),
    );
    expect(snapshot).toBe(true);
    expect(matchesRowsRoot).toBe(true);
    expect(toHex(root)).toBe(V.epoch2.rows_root);
    expect(toHex(root)).toBe(V.epoch2.state_after!.root);
    expect(state.size).toBe(V.epoch2.state_after!.n_rows);
    expect(sortedIds(leavesOf([...state.values()]))).toEqual(V.epoch2.state_after!.sorted_ids);
    // the row epoch 1 held and the snapshot does not is gone, not merely unchanged
    expect(dropped).toEqual(V.epoch2.deleted_ids!);
  });

  test('a snapshot does not need doc.deleted to reach the anchored root', () => {
    const stripped: EpochPlaintext = { ...doc2(), deleted: [] };
    const { rootHex, state } = applyEpoch(state1(), header2(), stripped);
    expect(rootHex).toBe(V.epoch2.rows_root);
    expect(state.size).toBe(V.epoch2.state_after!.n_rows);
  });

  test('merging a snapshot as a diff does NOT reach the anchored root', () => {
    // the bug this test exists for: keep the prior rows and merge the snapshot's
    // rows on top. doc.deleted is informational on a snapshot, so a merging
    // reader carries the deleted row forward and the root refuses.
    const state = state1();
    for (const r of doc2().rows) state.set(rowId(r), r);
    const merged = toHex(merkleRoot(leavesOf([...state.values()])));

    expect(state.size).toBe(V.rows.length);
    expect(merged).not.toBe(V.epoch2.rows_root);
    expect(merged).not.toBe(V.epoch2.state_after!.root);
  });

  test('an ordinary epoch IS a diff: rows set, then deleted removed', () => {
    // the same document as a non-snapshot epoch: now the prior rows survive and
    // only doc.deleted takes one away
    const doc: EpochPlaintext = { ...doc2(), snapshot: false };
    const header: Header = { ...header2(), flags: header2().flags & ~FLAG_SNAPSHOT };
    const { state, dropped } = applyEpoch(state1(), header, doc);

    expect(state.size).toBe(V.rows.length - 1);
    expect(dropped).toEqual(V.epoch2.deleted_ids!);
    // and with nothing deleted, a diff only ever grows or updates
    const kept = applyEpoch(state1(), header, { ...doc, deleted: [] });
    expect(kept.state.size).toBe(V.rows.length);
    expect(kept.dropped).toEqual([]);
  });

  test('applyEpoch leaves the state it was given alone', () => {
    const state = state1();
    applyEpoch(state, header2(), doc2());
    expect(state.size).toBe(V.rows.length);
  });

  test('a header and a plaintext that disagree about the snapshot bit are refused', () => {
    expect(() => applyEpoch(state1(), header2(), { ...doc2(), snapshot: false })).toThrow(
      /snapshot flag disagrees/,
    );
  });

  test('a version other than 1 is refused', () => {
    expect(() => parsePlaintext('{"v":2}')).toThrow(/unsupported epoch version 2/);
  });
});
