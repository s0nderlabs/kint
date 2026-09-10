/** Small byte helpers. No dependency on Buffer, so this runs unchanged in a browser. */

import { getAddress } from 'viem';
import type { Address } from 'viem';

import { KintCryptoError } from './constants';

export const encoder: TextEncoder = new TextEncoder();
export const decoder: TextDecoder = new TextDecoder('utf-8', { fatal: true });

export function utf8Bytes(s: string): Uint8Array {
  return encoder.encode(s);
}

export function utf8String(b: Uint8Array): string {
  return decoder.decode(b);
}

export function concatBytes(...parts: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

export function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

const HEX_CHARS = '0123456789abcdef';

export function toHex(b: Uint8Array): string {
  let out = '';
  for (let i = 0; i < b.length; i++) {
    const v = b[i]!;
    out += HEX_CHARS[v >> 4]! + HEX_CHARS[v & 0x0f]!;
  }
  return out;
}

const HEX_ONLY = /^[0-9a-fA-F]*$/;

/**
 * Accepts a bare or 0x-prefixed hex string. Rejects anything else loudly.
 *
 * The whole string is validated before a single byte is parsed: parseInt is
 * happy to read "1z" as 1 and "-1" as a negative, and a digest silently short
 * of what the sender wrote is exactly the bug this package exists to catch.
 */
export function fromHex(s: string): Uint8Array {
  let t = s.trim();
  if (t.startsWith('0x') || t.startsWith('0X')) t = t.slice(2);
  if (!HEX_ONLY.test(t)) throw new KintCryptoError(`"${s}" is not hex`);
  if (t.length % 2 !== 0) throw new KintCryptoError(`hex string has odd length ${t.length}`);
  const out = new Uint8Array(t.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = Number.parseInt(t.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

/** 0x-prefixed hex, the shape viem wants. */
export function to0x(b: Uint8Array): `0x${string}` {
  return `0x${toHex(b)}`;
}

/**
 * The checksummed form of an address, from any shape a user can hand over.
 *
 * viem's getAddress rejects a "0X" prefix outright, where Python's
 * to_checksum_address takes it, and a page that pastes an address from a block
 * explorer or a wallet gets both. Nothing here validates a checksum the caller
 * supplied: getAddress lowercases the body before it checksums it, so every
 * address is RE-checksummed and a mixed-case one with a wrong capital comes back
 * corrected rather than refused. That is exactly what Python's
 * to_checksum_address does, which is the point. A caller that wants to reject a
 * bad checksum has to compare its own input against what this returns.
 */
export function normaliseAddress(input: string): Address {
  const t = input.trim().replace(/\s+/g, '');
  const body = t.startsWith('0x') || t.startsWith('0X') ? t.slice(2) : t;
  try {
    return getAddress(`0x${body}`);
  } catch (e) {
    throw new KintCryptoError(`"${input}" is not an address: ${(e as Error).message || e}`);
  }
}

export function u32be(n: number): Uint8Array {
  if (!Number.isInteger(n) || n < 0 || n > 0xffffffff) {
    throw new KintCryptoError(`uint32 out of range: ${n}`);
  }
  const out = new Uint8Array(4);
  new DataView(out.buffer).setUint32(0, n, false);
  return out;
}

export function readU32be(b: Uint8Array, offset: number): number {
  if (offset + 4 > b.length) throw new KintCryptoError('uint32 read past the end of the buffer');
  return new DataView(b.buffer, b.byteOffset, b.byteLength).getUint32(offset, false);
}

export function bytesToBigInt(b: Uint8Array): bigint {
  let n = 0n;
  for (let i = 0; i < b.length; i++) n = (n << 8n) | BigInt(b[i]!);
  return n;
}

export function bigIntTo32(n: bigint): Uint8Array {
  if (n < 0n || n >= 1n << 256n) throw new KintCryptoError('bigint does not fit in 32 bytes');
  const out = new Uint8Array(32);
  let v = n;
  for (let i = 31; i >= 0; i--) {
    out[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  return out;
}

/**
 * Compare two strings by Unicode CODE POINT, which is how Python sorts str.
 * JavaScript's default comparison walks UTF-16 code units, so an astral
 * character (a surrogate pair starting at 0xD800) sorts before U+E000..U+FFFF
 * there and after it in Python. Row ids carry user text, so the difference is
 * real and it changes the merkle root.
 */
export function compareCodePoints(a: string, b: string): number {
  const ai = a[Symbol.iterator]();
  const bi = b[Symbol.iterator]();
  for (;;) {
    const x = ai.next();
    const y = bi.next();
    if (x.done && y.done) return 0;
    if (x.done) return -1;
    if (y.done) return 1;
    const cx = x.value.codePointAt(0)!;
    const cy = y.value.codePointAt(0)!;
    if (cx !== cy) return cx < cy ? -1 : 1;
  }
}

/** sorted(strings) with Python's ordering. */
export function sortCodePoints(items: Iterable<string>): string[] {
  return [...items].sort(compareCodePoints);
}
