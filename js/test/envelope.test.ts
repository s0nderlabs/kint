/** Wraps, the header, the AAD and openEpoch, against the Python vectors. */

import { describe, expect, test } from 'bun:test';

import { fromHex, toHex } from '../src/bytes.js';
import { kekTag } from '../src/kek.js';
import {
  ENVELOPE_VERSION,
  FLAG_SNAPSHOT,
  GCM_TAG_LEN,
  HEADER_FIXED_LEN,
  KintCryptoError,
  WRAP_LEN,
} from '../src/constants.js';
import {
  bucketFor,
  ciphertextDigest,
  dekId,
  epochAad,
  findWrap,
  isSnapshotHeader,
  nextBucket,
  openEpoch,
  parseHeader,
  parseWrap,
  peekHeader,
  unpad,
  unwrapDek,
  wrapToBytes,
} from '../src/envelope.js';
import type { Wrap } from '../src/envelope.js';
import { assertEpochConsistent, parsePlaintext, readEpoch } from '../src/epoch.js';
import { V } from './vectors.js';

const SPACE = fromHex(V.space);
const DEK = fromHex(V.dek);
const BLOB1 = fromHex(V.epoch1.blob);
const BLOB2 = fromHex(V.epoch2.blob);

describe('wraps', () => {
  test('every wrap parses back to its bytes', () => {
    for (const w of V.wraps) {
      const parsed = parseWrap(fromHex(w.bytes));
      expect(parsed.kind).toBe(w.kind);
      expect(toHex(parsed.tag)).toBe(w.tag);
      expect(toHex(parsed.nonce)).toBe(w.nonce);
      expect(toHex(parsed.wrapped)).toBe(w.wrapped);
      expect(toHex(wrapToBytes(parsed))).toBe(w.bytes);
      expect(fromHex(w.bytes).length).toBe(WRAP_LEN);
    }
  });

  test('each wrap unwraps to the same DEK under its own KEK', async () => {
    for (const w of V.wraps) {
      const wrap = parseWrap(fromHex(w.bytes));
      const dek = await unwrapDek(wrap, fromHex(w.kek), fromHex(w.tag));
      expect(toHex(dek)).toBe(V.dek);
      expect(toHex(dekId(dek))).toBe(V.dek_id);
    }
  });

  test('findWrap picks by tag and skips a foreign one', () => {
    const wraps: Wrap[] = [
      parseWrap(fromHex(V.foreign_wrap.bytes)),
      ...V.wraps.map((w) => parseWrap(fromHex(w.bytes))),
    ];
    for (const w of V.wraps) {
      const found = findWrap(wraps, fromHex(w.tag));
      expect(found).not.toBeNull();
      expect(toHex(found!.tag)).toBe(w.tag);
    }
    expect(findWrap([parseWrap(fromHex(V.foreign_wrap.bytes))], fromHex(V.wraps[0]!.tag))).toBeNull();
    expect(findWrap(wraps, new Uint8Array(16))).toBeNull();
  });

  test('each wrap unwraps with no tag argument at all', async () => {
    // the tag defaults to the tag OF THE KEK, which is the only value that makes
    // the check mean anything
    for (const w of V.wraps) {
      const dek = await unwrapDek(parseWrap(fromHex(w.bytes)), fromHex(w.kek));
      expect(toHex(dek)).toBe(V.dek);
      expect(toHex(kekTag(fromHex(w.kek)))).toBe(w.tag);
    }
  });

  test('the tag is checked before any decrypt', async () => {
    const wrap = parseWrap(fromHex(V.wraps[0]!.bytes));
    const otherKek = fromHex(V.wraps[2]!.kek);
    const otherTag = fromHex(V.wraps[2]!.tag);
    await expect(unwrapDek(wrap, otherKek, otherTag)).rejects.toThrow(/kek_tag mismatch/);
  });

  test('a wrong kek with no tag argument is refused by the tag check, not by AES', async () => {
    const wrap = parseWrap(fromHex(V.wraps[0]!.bytes));
    const wrongKek = fromHex(V.wraps[2]!.kek);
    const err = await unwrapDek(wrap, wrongKek).then(
      () => new Error('unwrapDek resolved with the wrong kek'),
      (e: Error) => e,
    );
    expect(err.message).toMatch(/kek_tag mismatch/);
    expect(err.message).not.toMatch(/did not authenticate/);
  });

  test('a wrap whose ciphertext was tampered with fails to authenticate', async () => {
    // the tag still matches its own kek, so this reaches AES and GCM refuses it
    const w = V.wraps[0]!;
    const wrap = parseWrap(fromHex(w.bytes));
    const wrapped = Uint8Array.from(wrap.wrapped);
    wrapped[0] = wrapped[0]! ^ 0x01;
    await expect(unwrapDek({ ...wrap, wrapped }, fromHex(w.kek))).rejects.toThrow(
      /did not authenticate/,
    );
  });
});

describe('header', () => {
  test('epoch 1 parses to the recorded fields', () => {
    const { header, offset } = parseHeader(BLOB1);
    expect(header.version).toBe(ENVELOPE_VERSION);
    expect(header.flags).toBe(V.epoch1.header.flags);
    expect(toHex(header.nonce)).toBe(V.epoch1.header.nonce);
    expect(toHex(header.rowsRoot)).toBe(V.epoch1.header.rows_root);
    expect(toHex(header.dekId)).toBe(V.epoch1.header.dek_id);
    expect(header.bucket).toBe(V.epoch1.header.bucket);
    expect(header.wraps.length).toBe(V.epoch1.header.n_wraps);
    expect(offset).toBe(V.epoch1.header.length);
    expect(offset).toBe(HEADER_FIXED_LEN + WRAP_LEN * V.wraps.length);
    expect(BLOB1.length).toBe(offset + header.bucket + GCM_TAG_LEN);
    expect(isSnapshotHeader(header)).toBe(false);
  });

  test('epoch 2 carries the snapshot flag', () => {
    const header = peekHeader(BLOB2);
    expect(header.flags & FLAG_SNAPSHOT).toBe(FLAG_SNAPSHOT);
    expect(isSnapshotHeader(header)).toBe(true);
    expect(V.epoch2.snapshot_flag_set).toBe(true);
  });

  test('an unknown envelope version is refused', () => {
    const bad = Uint8Array.from(BLOB1);
    bad[0] = 2;
    expect(() => parseHeader(bad)).toThrow(/unsupported envelope version 2/);
  });

  test('a stub shorter than a header is refused', () => {
    expect(() => parseHeader(BLOB1.slice(0, 10))).toThrow(/shorter than a header/);
  });
});

describe('aad and open', () => {
  test('the AAD matches the Python keccak', () => {
    const aad = epochAad({
      owner: V.owner,
      space: SPACE,
      seq: V.epoch1.seq,
      prev: fromHex(V.epoch1.prev),
      bucket: V.epoch1.bucket,
      rowsRoot: fromHex(V.epoch1.header.rows_root),
      dekId: fromHex(V.epoch1.header.dek_id),
    });
    expect(toHex(aad)).toBe(V.epoch1.aad);
  });

  test('epoch 2 AAD matches too', () => {
    const aad = epochAad({
      owner: V.owner,
      space: SPACE,
      seq: V.epoch2.seq,
      prev: fromHex(V.epoch2.prev),
      bucket: V.epoch2.bucket,
      rowsRoot: fromHex(V.epoch2.header.rows_root),
      dekId: fromHex(V.epoch2.header.dek_id),
    });
    expect(toHex(aad)).toBe(V.epoch2.aad);
  });

  test('openEpoch returns the exact plaintext bytes', async () => {
    const { header, plaintext } = await openEpoch(BLOB1, {
      dek: DEK,
      owner: V.owner,
      space: SPACE,
      seq: V.epoch1.seq,
      prev: fromHex(V.epoch1.prev),
    });
    expect(toHex(plaintext)).toBe(V.epoch1.plaintext);
    expect(new TextDecoder().decode(plaintext)).toBe(V.epoch1.plaintext_utf8);
    expect(toHex(header.rowsRoot)).toBe(V.rows_root);
  });

  test('epoch 2 opens against its own prev (the digest of epoch 1)', async () => {
    expect(V.epoch2.prev).toBe(V.epoch1.digest);
    const { plaintext } = await openEpoch(BLOB2, {
      dek: DEK,
      owner: V.owner,
      space: SPACE,
      seq: V.epoch2.seq,
      prev: fromHex(V.epoch2.prev),
    });
    expect(toHex(plaintext)).toBe(V.epoch2.plaintext);
  });

  test('the whole path from a wrap: find, unwrap, open', async () => {
    const { header } = parseHeader(BLOB1);
    const w = V.wraps[1]!;
    const wrap = findWrap(header.wraps, fromHex(w.tag));
    expect(wrap).not.toBeNull();
    const dek = await unwrapDek(wrap!, fromHex(w.kek), fromHex(w.tag));
    const { plaintext } = await openEpoch(BLOB1, {
      dek,
      owner: V.owner,
      space: SPACE,
      seq: V.epoch1.seq,
      prev: fromHex(V.epoch1.prev),
    });
    expect(toHex(plaintext)).toBe(V.epoch1.plaintext);
  });

  test('the anchored digest is keccak256 of the whole blob', () => {
    expect(toHex(ciphertextDigest(BLOB1))).toBe(V.epoch1.digest);
    expect(toHex(ciphertextDigest(BLOB2))).toBe(V.epoch2.digest);
  });
});

describe('open refuses', () => {
  const base = () => ({
    dek: DEK,
    owner: V.owner,
    space: SPACE,
    seq: V.epoch1.seq,
    prev: fromHex(V.epoch1.prev),
  });

  test('one flipped ciphertext byte', async () => {
    const tampered = Uint8Array.from(BLOB1);
    tampered[tampered.length - 1] = tampered[tampered.length - 1]! ^ 0x01;
    await expect(openEpoch(tampered, base())).rejects.toThrow(/did not authenticate/);
  });

  test('one flipped rows_root byte in the header', async () => {
    const tampered = Uint8Array.from(BLOB1);
    tampered[14] = tampered[14]! ^ 0x01;
    await expect(openEpoch(tampered, base())).rejects.toThrow(/did not authenticate/);
  });

  test('the wrong prev', async () => {
    await expect(openEpoch(BLOB1, { ...base(), prev: new Uint8Array(32).fill(9) })).rejects.toThrow(
      /did not authenticate/,
    );
  });

  test('the wrong seq', async () => {
    await expect(openEpoch(BLOB1, { ...base(), seq: 2 })).rejects.toThrow(/did not authenticate/);
  });

  test('the wrong owner', async () => {
    await expect(
      openEpoch(BLOB1, { ...base(), owner: '0x0000000000000000000000000000000000000001' }),
    ).rejects.toThrow(/did not authenticate/);
  });

  test('the wrong space', async () => {
    await expect(openEpoch(BLOB1, { ...base(), space: new Uint8Array(32).fill(7) })).rejects.toThrow(
      /did not authenticate/,
    );
  });

  test('the wrong DEK, by dek_id, before any decrypt', async () => {
    await expect(openEpoch(BLOB1, { ...base(), dek: new Uint8Array(32).fill(3) })).rejects.toThrow(
      /dek_id mismatch/,
    );
  });

  test('a truncated ciphertext, by length, before any decrypt', async () => {
    await expect(openEpoch(BLOB1.slice(0, BLOB1.length - 1), base())).rejects.toThrow(
      /does not match bucket/,
    );
  });
});

describe('buckets and padding', () => {
  test('the ladder', () => {
    expect(bucketFor(1)).toBe(4096);
    expect(bucketFor(4096)).toBe(4096);
    expect(bucketFor(4097)).toBe(8192);
    expect(nextBucket(100, 32768)).toBe(32768);
    expect(() => bucketFor(98305)).toThrow(KintCryptoError);
  });

  test('unpad reads the big-endian length prefix', () => {
    const padded = new Uint8Array(4096);
    padded.set([0, 0, 0, 3, 0xaa, 0xbb, 0xcc], 0);
    expect(toHex(unpad(padded))).toBe('aabbcc');
  });

  test('unpad refuses a length beyond the buffer', () => {
    const padded = new Uint8Array(16);
    padded.set([0, 0, 0xff, 0xff], 0);
    expect(() => unpad(padded)).toThrow(/beyond its size/);
  });
});

describe('readEpoch', () => {
  const input = () => ({
    dek: DEK,
    owner: V.owner,
    space: SPACE,
    seq: V.epoch1.seq,
    prev: fromHex(V.epoch1.prev),
  });

  test('it opens, parses and cross-checks in one call', async () => {
    const { header, doc, plaintext } = await readEpoch(BLOB1, input());
    expect(toHex(plaintext)).toBe(V.epoch1.plaintext);
    expect(doc.seq).toBe(V.epoch1.seq);
    expect(doc.rows_root).toBe(toHex(header.rowsRoot));
    expect(doc.snapshot).toBe(false);
  });

  test('the snapshot epoch reads back as a snapshot', async () => {
    const { header, doc } = await readEpoch(BLOB2, {
      ...input(),
      seq: V.epoch2.seq,
      prev: fromHex(V.epoch2.prev),
    });
    expect(isSnapshotHeader(header)).toBe(true);
    expect(doc.snapshot).toBe(true);
    expect(doc.rows.length).toBe(V.rows.length - 1);
  });

  test('a flipped FLAG_SNAPSHOT bit is caught, though the epoch still opens', async () => {
    // flags live OUTSIDE the AAD, so openEpoch cannot see this: byte 1 of the
    // blob turns an ordinary epoch into a snapshot for the cost of one bit
    const forged = Uint8Array.from(BLOB1);
    expect(forged[1]).toBe(0x00);
    forged[1] = FLAG_SNAPSHOT;

    const opened = await openEpoch(forged, input());
    expect(isSnapshotHeader(opened.header)).toBe(true);
    expect(toHex(opened.plaintext)).toBe(V.epoch1.plaintext);

    await expect(readEpoch(forged, input())).rejects.toThrow(/snapshot/);
  });

  test('assertEpochConsistent names the field that disagrees', () => {
    const header = peekHeader(BLOB1);
    const doc = parsePlaintext(fromHex(V.epoch1.plaintext));
    const expected = { seq: V.epoch1.seq, prev: V.epoch1.prev, spaceHex: V.space };

    expect(() => assertEpochConsistent(header, doc, expected)).not.toThrow();
    // 0x-prefixed and upper case say the same thing
    expect(() =>
      assertEpochConsistent(header, doc, {
        seq: BigInt(V.epoch1.seq),
        prev: `0x${V.epoch1.prev.toUpperCase()}`,
        spaceHex: `0x${V.space.toUpperCase()}`,
      }),
    ).not.toThrow();

    expect(() => assertEpochConsistent(header, doc, { ...expected, seq: 9 })).toThrow(/seq/);
    expect(() =>
      assertEpochConsistent(header, doc, { ...expected, prev: '11'.repeat(32) }),
    ).toThrow(/prev/);
    expect(() =>
      assertEpochConsistent(header, doc, { ...expected, spaceHex: '22'.repeat(32) }),
    ).toThrow(/space/);
    expect(() =>
      assertEpochConsistent({ ...header, rowsRoot: new Uint8Array(32) }, doc, expected),
    ).toThrow(/rows_root/);
    expect(() =>
      assertEpochConsistent({ ...header, flags: header.flags | FLAG_SNAPSHOT }, doc, expected),
    ).toThrow(/snapshot/);
  });
});
