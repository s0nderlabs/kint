/** The typed data, the digest and the three KEK paths, against the Python vectors. */

import { describe, expect, test } from 'bun:test';

import { fromHex, toHex } from '../src/bytes.js';
import { KEK_KIND_PASSPHRASE, KEK_KIND_SIGNATURE, KintCryptoError } from '../src/constants.js';
import {
  kekFromPassphrase,
  kekFromSignature,
  kekInfo,
  kekTag,
  normaliseLowS,
  parseSignature,
  recoverSigner,
  spaceId,
} from '../src/kek.js';
import { canonicalPayloadJson, typedData, vaultDigest, vaultDigestHex } from '../src/typedData.js';
import { dekId, decodeRecoveryCode } from '../src/envelope.js';
import { V } from './vectors.js';

const SPACE = fromHex(V.space);
const SIG = fromHex(V.derive_signature);
// scrypt at N = 2^17 is the point of the passphrase paths; give them room.
const SLOW = { timeout: 30_000 };

describe('typed data', () => {
  test('the payload is byte-identical to the Python dict', () => {
    expect(JSON.stringify(typedData(V.owner))).toBe(JSON.stringify(V.typed_data));
  });

  test('canonical payload json matches byte for byte, trailing newline included', () => {
    expect(canonicalPayloadJson(V.owner)).toBe(V.canonical_payload_json);
    expect(canonicalPayloadJson(V.owner.toLowerCase())).toBe(V.canonical_payload_json);
    expect(canonicalPayloadJson(V.owner).endsWith('\n')).toBe(true);
    expect(canonicalPayloadJson(V.owner)).toContain('"chainId":8453');
    expect(canonicalPayloadJson(V.owner)).not.toContain('verifyingContract');
  });

  test('the vault digest matches', () => {
    expect(vaultDigestHex(V.owner)).toBe(`0x${V.vault_digest}`);
    expect(toHex(vaultDigest(V.owner))).toBe(V.vault_digest);
  });

  test('space id and kek info match', () => {
    expect(toHex(spaceId(V.tenant))).toBe(V.space);
    expect(toHex(kekInfo(V.owner, SPACE))).toBe(V.kek_info);
    expect(kekInfo(V.owner, SPACE).length).toBe(63);
  });
});

describe('signatures', () => {
  test('parse and low-S normalise', () => {
    const { r, s, v } = parseSignature(SIG);
    expect(r > 0n).toBe(true);
    expect(s > 0n).toBe(true);
    expect(v === 0 || v === 1).toBe(true);
    const low = normaliseLowS(SIG);
    expect(low.sig.length).toBe(65);
    expect(toHex(low.sig)).toBe(toHex(normaliseLowS(low.sig).sig));
  });

  test('it recovers to the owner', async () => {
    expect(await recoverSigner(vaultDigest(V.owner), SIG)).toBe(V.owner);
  });

  test('a 64-byte signature is refused', () => {
    expect(() => parseSignature(SIG.subarray(0, 64))).toThrow(KintCryptoError);
  });
});

describe('kek derivation', () => {
  test('the signature path matches the Python KEK and tag', async () => {
    const { kek, tag } = await kekFromSignature(SIG, V.owner, SPACE);
    expect(toHex(kek)).toBe(V.keks.signature.kek);
    expect(toHex(tag)).toBe(V.keks.signature.tag);
    expect(toHex(kekTag(kek))).toBe(V.keks.signature.tag);
    expect(V.keks.signature.kind).toBe(KEK_KIND_SIGNATURE);
  });

  test(
    'the signature path with a passphrase salt matches',
    async () => {
      const { kek, tag } = await kekFromSignature(
        SIG,
        V.owner,
        SPACE,
        V.keks.signature_salted.passphrase!,
      );
      expect(toHex(kek)).toBe(V.keks.signature_salted.kek);
      expect(toHex(tag)).toBe(V.keks.signature_salted.tag);
    },
    SLOW,
  );

  test(
    'the passphrase-only path matches',
    () => {
      const { kek, tag } = kekFromPassphrase(V.keks.passphrase.passphrase!, V.owner, SPACE);
      expect(toHex(kek)).toBe(V.keks.passphrase.kek);
      expect(toHex(tag)).toBe(V.keks.passphrase.tag);
      expect(V.keks.passphrase.kind).toBe(KEK_KIND_PASSPHRASE);
    },
    SLOW,
  );

  test('the three KEKs are all different', () => {
    const set = new Set([
      V.keks.signature.kek,
      V.keks.signature_salted.kek,
      V.keks.passphrase.kek,
    ]);
    expect(set.size).toBe(3);
  });

  test('a malleated twin derives the same KEK', async () => {
    const { r, s, v } = parseSignature(SIG);
    const N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
    const twin = new Uint8Array(65);
    twin.set(fromHex(r.toString(16).padStart(64, '0')), 0);
    twin.set(fromHex((N - s).toString(16).padStart(64, '0')), 32);
    twin[64] = (v ^ 1) + 27;
    const a = await kekFromSignature(SIG, V.owner, SPACE);
    const b = await kekFromSignature(twin, V.owner, SPACE);
    expect(toHex(b.kek)).toBe(toHex(a.kek));
  });

  test('a signature that recovers to another address is refused, never derived', async () => {
    // Flipping the recovery bit keeps the signature well formed and moves it to
    // a different public key, which is exactly the case the check exists for.
    const bad = Uint8Array.from(SIG);
    bad[64] = bad[64] === 27 ? 28 : 27;
    await expect(kekFromSignature(bad, V.owner, SPACE)).rejects.toThrow(/recovers to/);
  });

  test('a corrupt signature is refused too, and never silently derived', async () => {
    const bad = Uint8Array.from(SIG);
    bad[5] = bad[5]! ^ 0x01;
    await expect(kekFromSignature(bad, V.owner, SPACE)).rejects.toThrow();
  });

  test('a signature of the wrong length is refused before anything else', async () => {
    await expect(kekFromSignature(SIG.subarray(0, 64), V.owner, SPACE)).rejects.toThrow(
      /must be 65 bytes/,
    );
  });

  test('a different space gives a different KEK', async () => {
    const other = await kekFromSignature(SIG, V.owner, spaceId('other'));
    expect(toHex(other.kek)).not.toBe(V.keks.signature.kek);
  });
});

describe('dek identity and recovery code', () => {
  test('dek_id matches', () => {
    expect(toHex(dekId(fromHex(V.dek)))).toBe(V.dek_id);
  });

  test('the recovery code decodes to the DEK', () => {
    expect(toHex(decodeRecoveryCode(V.recovery_code))).toBe(V.dek);
  });

  test('it accepts the lowercase, space-separated form the user types', () => {
    const typed = V.recovery_code.toLowerCase().replace(/-/g, ' ');
    expect(toHex(decodeRecoveryCode(typed))).toBe(V.dek);
  });

  test('a single-character typo fails the checksum', () => {
    const chars = [...V.recovery_code];
    chars[0] = chars[0] === 'B' ? 'C' : 'B';
    expect(() => decodeRecoveryCode(chars.join(''))).toThrow(KintCryptoError);
  });

  test('a truncated code is refused on length', () => {
    expect(() => decodeRecoveryCode(V.recovery_code.slice(0, 20))).toThrow(KintCryptoError);
  });
});
