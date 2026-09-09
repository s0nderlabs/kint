/**
 * Key derivation. Port of the KEK half of src/kint/crypto.py.
 *
 *     owner signs ONE frozen EIP-712 message  ->  65-byte signature (a SECRET)
 *     ikm = r || s (low-S normalised)         ->  HKDF-SHA256  ->  KEK (32 bytes)
 *
 * The recover check is a hard check, never behind a try/catch: it is the only
 * thing between the reader and a silently different key.
 */

import { hkdf } from '@noble/hashes/hkdf.js';
import { hmac } from '@noble/hashes/hmac.js';
import { scrypt } from '@noble/hashes/scrypt.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { keccak_256 } from '@noble/hashes/sha3.js';
import { recoverAddress } from 'viem';

import {
  KEK_CHECK,
  KEK_INFO_PREFIX,
  KintCryptoError,
  SCRYPT_DKLEN,
  SCRYPT_MAXMEM,
  SCRYPT_N,
  SCRYPT_P,
  SCRYPT_R,
  SECP256K1_HALF_N,
  SECP256K1_N,
  SPACE_PREFIX,
} from './constants.js';
import {
  bigIntTo32,
  bytesToBigInt,
  concatBytes,
  fromHex,
  normaliseAddress,
  to0x,
  utf8Bytes,
} from './bytes.js';
import { vaultDigest } from './typedData.js';

export interface Kek {
  kek: Uint8Array;
  tag: Uint8Array;
}

export interface ParsedSignature {
  r: bigint;
  s: bigint;
  /** Normalised to 0 or 1. */
  v: number;
}

/** 32-byte space id: keccak256("kint-space-v1" || tenant_id). */
export function spaceId(tenantId: string): Uint8Array {
  return keccak_256(concatBytes(SPACE_PREFIX, utf8Bytes(tenantId)));
}

/** The 20 raw bytes of a checksummed address. */
export function owner20(owner: string): Uint8Array {
  return fromHex(normaliseAddress(owner).slice(2));
}

/** "kint-kek-v1" || owner20 || space, always 63 bytes. */
export function kekInfo(owner: string, space: Uint8Array): Uint8Array {
  if (space.length !== 32) throw new KintCryptoError(`space must be 32 bytes, got ${space.length}`);
  const info = concatBytes(KEK_INFO_PREFIX, owner20(owner), space);
  if (info.length !== 63) throw new KintCryptoError(`kek info must be 63 bytes, got ${info.length}`);
  return info;
}

/** Return (r, s, v01) from a 65-byte signature. v is normalised to 0/1. */
export function parseSignature(sig: Uint8Array): ParsedSignature {
  if (sig.length !== 65) {
    throw new KintCryptoError(`signature must be 65 bytes, got ${sig.length}`);
  }
  const r = bytesToBigInt(sig.subarray(0, 32));
  const s = bytesToBigInt(sig.subarray(32, 64));
  let v = sig[64]!;
  if (v === 27 || v === 28) v -= 27;
  if (v !== 0 && v !== 1) {
    throw new KintCryptoError(`signature v must be 27/28 or 0/1, got ${sig[64]}`);
  }
  if (!(r > 0n && r < SECP256K1_N && s > 0n && s < SECP256K1_N)) {
    throw new KintCryptoError('signature r or s out of range');
  }
  return { r, s, v };
}

/** Return the low-S twin of a signature. A malleated twin derives the same KEK. */
export function normaliseLowS(sig: Uint8Array): { sig: Uint8Array; r: bigint; s: bigint } {
  const parsed = parseSignature(sig);
  let { s, v } = parsed;
  const { r } = parsed;
  if (s > SECP256K1_HALF_N) {
    s = SECP256K1_N - s;
    v ^= 1;
  }
  return {
    sig: concatBytes(bigIntTo32(r), bigIntTo32(s), Uint8Array.from([v + 27])),
    r,
    s,
  };
}

/** Checksummed address that produced `sig` over `digest`. Rejects garbage. */
export async function recoverSigner(digest: Uint8Array, sig: Uint8Array): Promise<string> {
  parseSignature(sig);
  return recoverAddress({ hash: to0x(digest), signature: to0x(sig) });
}

/** scrypt(passphrase, salt = owner20, N = 2^17, r = 8, p = 1) -> 32 bytes. */
export function passphraseStretch(passphrase: string, owner: string): Uint8Array {
  if (!passphrase) throw new KintCryptoError('empty passphrase');
  // UTF-8 as typed. No unicode normalisation, exactly like Python's str.encode.
  return scrypt(utf8Bytes(passphrase), owner20(owner), {
    N: SCRYPT_N,
    r: SCRYPT_R,
    p: SCRYPT_P,
    dkLen: SCRYPT_DKLEN,
    maxmem: SCRYPT_MAXMEM,
  });
}

/** HMAC-SHA256(kek, "kint-kek-check-v1")[:16]. How a client finds its wrap. */
export function kekTag(kek: Uint8Array): Uint8Array {
  return hmac(sha256, kek, KEK_CHECK).slice(0, 16);
}

function hkdf32(ikm: Uint8Array, salt: Uint8Array, info: Uint8Array): Uint8Array {
  return hkdf(sha256, ikm, salt, info, 32);
}

/**
 * Kind 0x01: KEK from the owner's derive signature.
 *
 * `signer` defaults to `owner` (plain EOA). For an EOA-owned smart account,
 * `owner` is the account and `signer` is the EOA whose 65 bytes are the ikm.
 */
export async function kekFromSignature(
  sig: Uint8Array,
  owner: string,
  space: Uint8Array,
  passphrase?: string | null,
  opts: { digest?: Uint8Array; signer?: string } = {},
): Promise<Kek> {
  if (sig.length !== 65) {
    throw new KintCryptoError(`derive signature must be 65 bytes, got ${sig.length}`);
  }
  const digest = opts.digest ?? vaultDigest(owner);
  const expected = normaliseAddress(opts.signer ?? owner);
  const recovered = await recoverSigner(digest, sig);
  if (recovered !== expected) {
    throw new KintCryptoError(
      `derive signature recovers to ${recovered}, expected ${expected}; ` +
        'refusing to derive a key from it',
    );
  }
  const { r, s } = normaliseLowS(sig);
  const ikm = concatBytes(bigIntTo32(r), bigIntTo32(s));
  const salt = passphrase ? passphraseStretch(passphrase, owner) : new Uint8Array(0);
  const kek = hkdf32(ikm, salt, kekInfo(owner, space));
  return { kek, tag: kekTag(kek) };
}

/**
 * Kind 0x02: KEK = HKDF(scrypt(passphrase, owner20), salt = "", info).
 * No wallet needed; this is the path a Base Account owner uses.
 */
export function kekFromPassphrase(passphrase: string, owner: string, space: Uint8Array): Kek {
  const ikm = passphraseStretch(passphrase, owner);
  const kek = hkdf32(ikm, new Uint8Array(0), kekInfo(owner, space));
  return { kek, tag: kekTag(kek) };
}
