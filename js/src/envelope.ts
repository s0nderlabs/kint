/**
 * The epoch envelope, read side only. Port of the envelope half of
 * src/kint/crypto.py: wraps, the header, the AAD and open_epoch.
 *
 * There is deliberately no seal here. The browser opens epochs; the machine
 * that holds the Sibyl store is the only thing that writes them.
 */

import { hmac } from '@noble/hashes/hmac.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { keccak_256 } from '@noble/hashes/sha3.js';
import { gunzipSync } from 'fflate';
import { encodeAbiParameters, keccak256 } from 'viem';
import type { Hex } from 'viem';

import {
  BUCKETS,
  CHAIN_ID,
  DEK_ID_INFO,
  ENVELOPE_VERSION,
  FLAG_SNAPSHOT,
  GCM_TAG_LEN,
  HEADER_FIXED_LEN,
  KintCryptoError,
  WRAP_AAD_PREFIX,
  WRAP_LEN,
} from './constants.js';
import { bytesEqual, concatBytes, fromHex, normaliseAddress, readU32be, to0x, toHex } from './bytes.js';
import { kekTag } from './kek.js';

// ---------------------------------------------------------------------------
// DEK identity
// ---------------------------------------------------------------------------

/** HMAC-SHA256(dek, "kint-dek-id-v1")[:8]. Cheap "is this the right data key". */
export function dekId(dek: Uint8Array): Uint8Array {
  if (dek.length !== 32) throw new KintCryptoError(`dek must be 32 bytes, got ${dek.length}`);
  return hmac(sha256, dek, DEK_ID_INFO).slice(0, 8);
}

// ---------------------------------------------------------------------------
// Wraps
// ---------------------------------------------------------------------------

export interface Wrap {
  kind: number;
  /** 16 bytes. */
  tag: Uint8Array;
  /** 12 bytes. */
  nonce: Uint8Array;
  /** 48 bytes: the 32-byte DEK plus the 16-byte GCM tag. */
  wrapped: Uint8Array;
}

export function parseWrap(b: Uint8Array): Wrap {
  if (b.length !== WRAP_LEN) throw new KintCryptoError('bad wrap length');
  return {
    kind: b[0]!,
    tag: b.slice(1, 17),
    nonce: b.slice(17, 29),
    wrapped: b.slice(29, 77),
  };
}

export function wrapToBytes(w: Wrap): Uint8Array {
  if (w.tag.length !== 16 || w.nonce.length !== 12 || w.wrapped.length !== 48) {
    throw new KintCryptoError('wrap fields have the wrong lengths');
  }
  return concatBytes(Uint8Array.from([w.kind]), w.tag, w.nonce, w.wrapped);
}

/** The wrap whose kek_tag matches. Compare tags, never trial-decrypt. */
export function findWrap(wraps: readonly Wrap[], kekTagBytes: Uint8Array): Wrap | null {
  for (const w of wraps) {
    if (bytesEqual(w.tag, kekTagBytes)) return w;
  }
  return null;
}

async function aesGcmDecrypt(
  key: Uint8Array,
  nonce: Uint8Array,
  ciphertext: Uint8Array,
  aad: Uint8Array,
): Promise<Uint8Array> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new KintCryptoError('WebCrypto subtle is unavailable; kint needs a secure context');
  const cryptoKey = await subtle.importKey('raw', key.slice(), 'AES-GCM', false, ['decrypt']);
  const out = await subtle.decrypt(
    { name: 'AES-GCM', iv: nonce.slice(), additionalData: aad.slice(), tagLength: GCM_TAG_LEN * 8 },
    cryptoKey,
    ciphertext.slice(),
  );
  return new Uint8Array(out);
}

/**
 * Open a wrap with a KEK. The kek_tag must match FIRST: AES-GCM is not
 * key-committing, so a trial decrypt is not a safe way to pick a wrap.
 *
 * `kekTagBytes` defaults to the tag OF THIS KEK, which is the only value that
 * makes the check mean anything: a caller that passes `wrap.tag` instead is
 * comparing the wrap to itself and has disabled the check. Pass it only when
 * the tag was computed elsewhere from the same key.
 */
export async function unwrapDek(
  wrap: Wrap,
  kek: Uint8Array,
  kekTagBytes: Uint8Array = kekTag(kek),
): Promise<Uint8Array> {
  if (!bytesEqual(kekTagBytes, wrap.tag)) {
    throw new KintCryptoError('kek_tag mismatch: this key does not open this wrap');
  }
  const aad = concatBytes(WRAP_AAD_PREFIX, Uint8Array.from([wrap.kind]), wrap.tag);
  let dek: Uint8Array;
  try {
    dek = await aesGcmDecrypt(kek, wrap.nonce, wrap.wrapped, aad);
  } catch (e) {
    throw new KintCryptoError(`wrap did not authenticate: ${(e as Error).message || e}`);
  }
  if (dek.length !== 32) throw new KintCryptoError(`unwrapped dek is ${dek.length} bytes, expected 32`);
  return dek;
}

// ---------------------------------------------------------------------------
// Recovery code
// ---------------------------------------------------------------------------

const B32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

/**
 * base32 of DEK || sha256(DEK)[:2]. Accepts the grouped, lowercase or
 * space-separated forms the user actually types.
 */
export function decodeRecoveryCode(code: string): Uint8Array {
  const raw = code.trim().replace(/[-\s]/g, '').toUpperCase().replace(/=+$/, '');
  const out: number[] = [];
  let acc = 0;
  let bits = 0;
  for (const ch of raw) {
    const idx = B32_ALPHABET.indexOf(ch);
    if (idx < 0) throw new KintCryptoError('recovery code is not valid base32');
    acc = (acc << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      out.push((acc >> bits) & 0xff);
    }
  }
  if (bits >= 5 || (acc & ((1 << bits) - 1)) !== 0) {
    throw new KintCryptoError('recovery code is not valid base32');
  }
  const data = Uint8Array.from(out);
  if (data.length !== 34) throw new KintCryptoError('recovery code has the wrong length');
  const dek = data.slice(0, 32);
  const check = data.slice(32);
  if (!bytesEqual(sha256(dek).slice(0, 2), check)) {
    throw new KintCryptoError('recovery code checksum failed (typo?)');
  }
  return dek;
}

// ---------------------------------------------------------------------------
// Buckets and padding
// ---------------------------------------------------------------------------

export function bucketFor(length: number): number {
  for (const b of BUCKETS) {
    if (length <= b) return b;
  }
  throw new KintCryptoError(
    `payload of ${length} bytes exceeds the largest bucket ${BUCKETS[BUCKETS.length - 1]}; split the epoch`,
  );
}

/** Monotone ratchet per space: never publish a smaller bucket than before. */
export function nextBucket(length: number, previousBucket: number): number {
  return Math.max(bucketFor(length), previousBucket);
}

/** uint32(len) || gz || zeros -> gz. */
export function unpad(padded: Uint8Array): Uint8Array {
  if (padded.length < 4) throw new KintCryptoError('padded payload is shorter than its length prefix');
  const n = readU32be(padded, 0);
  if (4 + n > padded.length) {
    throw new KintCryptoError('padded payload declares a length beyond its size');
  }
  return padded.slice(4, 4 + n);
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

export interface Header {
  version: number;
  flags: number;
  /** 12 bytes. */
  nonce: Uint8Array;
  /** 32 bytes: the merkle root of the FULL state after this epoch. */
  rowsRoot: Uint8Array;
  /** 8 bytes. */
  dekId: Uint8Array;
  bucket: number;
  wraps: Wrap[];
}

/** True when this epoch carries the full row set (flag 0x02). */
export function isSnapshotHeader(header: Header): boolean {
  return (header.flags & FLAG_SNAPSHOT) !== 0;
}

/** Parse the header off the front of a blob. Returns it and the ciphertext offset. */
export function parseHeader(blob: Uint8Array): { header: Header; offset: number } {
  if (blob.length < HEADER_FIXED_LEN) throw new KintCryptoError('blob shorter than a header');
  const version = blob[0]!;
  const flags = blob[1]!;
  if (version !== ENVELOPE_VERSION) {
    throw new KintCryptoError(`unsupported envelope version ${version}`);
  }
  const nonce = blob.slice(2, 14);
  const rowsRoot = blob.slice(14, 46);
  const did = blob.slice(46, 54);
  const bucket = readU32be(blob, 54);
  const n = blob[58]!;
  let off = HEADER_FIXED_LEN;
  const wraps: Wrap[] = [];
  for (let i = 0; i < n; i++) {
    if (off + WRAP_LEN > blob.length) throw new KintCryptoError('blob truncated inside its wraps');
    wraps.push(parseWrap(blob.slice(off, off + WRAP_LEN)));
    off += WRAP_LEN;
  }
  return { header: { version, flags, nonce, rowsRoot, dekId: did, bucket, wraps }, offset: off };
}

export function peekHeader(blob: Uint8Array): Header {
  return parseHeader(blob).header;
}

// ---------------------------------------------------------------------------
// AAD and open
// ---------------------------------------------------------------------------

const AAD_TYPES = [
  { type: 'uint256' },
  { type: 'address' },
  { type: 'bytes32' },
  { type: 'uint64' },
  { type: 'bytes32' },
  { type: 'uint32' },
  { type: 'bytes32' },
  { type: 'bytes8' },
] as const;

export interface EpochAadInput {
  owner: string;
  space: Uint8Array;
  seq: number | bigint;
  prev: Uint8Array;
  bucket: number;
  rowsRoot: Uint8Array;
  dekId: Uint8Array;
}

/**
 * keccak256(abi.encode(chainId, owner, space, seq, prev, lenBucket, rows_root, dek_id)).
 * Every field the reader must already know binds the ciphertext to its place in
 * the chain, so a replayed epoch under a different seq or prev simply refuses.
 */
export function epochAad(input: EpochAadInput): Uint8Array {
  if (input.space.length !== 32) throw new KintCryptoError('space must be 32 bytes');
  if (input.prev.length !== 32) throw new KintCryptoError('prev must be 32 bytes');
  if (input.rowsRoot.length !== 32) throw new KintCryptoError('rows_root must be 32 bytes');
  if (input.dekId.length !== 8) throw new KintCryptoError('dek_id must be 8 bytes');
  const encoded = encodeAbiParameters(AAD_TYPES, [
    BigInt(CHAIN_ID),
    normaliseAddress(input.owner),
    to0x(input.space),
    BigInt(input.seq),
    to0x(input.prev),
    input.bucket,
    to0x(input.rowsRoot),
    to0x(input.dekId),
  ]);
  return fromHex(keccak256(encoded));
}

export interface OpenEpochInput {
  dek: Uint8Array;
  owner: string;
  space: Uint8Array;
  seq: number | bigint;
  prev: Uint8Array;
}

export interface OpenedEpoch {
  header: Header;
  plaintext: Uint8Array;
}

/**
 * The inverse of Python's seal_epoch. Every epoch decrypts with the DEK from its
 * OWN header; the caller finds its wrap with findWrap / unwrapDek first.
 */
export async function openEpoch(blob: Uint8Array, input: OpenEpochInput): Promise<OpenedEpoch> {
  const { header, offset } = parseHeader(blob);
  const ct = blob.slice(offset);
  if (ct.length !== header.bucket + GCM_TAG_LEN) {
    throw new KintCryptoError(
      `ciphertext length ${ct.length} does not match bucket ${header.bucket} + tag`,
    );
  }
  if (!bytesEqual(dekId(input.dek), header.dekId)) {
    throw new KintCryptoError('dek_id mismatch: wrong data key for this epoch');
  }
  const aad = epochAad({
    owner: input.owner,
    space: input.space,
    seq: input.seq,
    prev: input.prev,
    bucket: header.bucket,
    rowsRoot: header.rowsRoot,
    dekId: header.dekId,
  });
  let padded: Uint8Array;
  try {
    padded = await aesGcmDecrypt(input.dek, header.nonce, ct, aad);
  } catch (e) {
    throw new KintCryptoError(
      'epoch did not authenticate: wrong key, wrong seq/prev/owner/space, or tampered ciphertext' +
        ` (${(e as Error).message || e})`,
    );
  }
  return { header, plaintext: gunzipSync(unpad(padded)) };
}

/** keccak256 of a ciphertext, the digest the Epoch event carries. */
export function ciphertextDigest(ct: Uint8Array): Uint8Array {
  return keccak_256(ct);
}

/** Convenience: the 0x digest as viem hands it back from a log. */
export function ciphertextDigestHex(ct: Uint8Array): Hex {
  return `0x${toHex(ciphertextDigest(ct))}`;
}
