/** Hex parsing and address normalisation: the two places a typo turns into a key. */

import { describe, expect, test } from 'bun:test';

import { fromHex, normaliseAddress, toHex } from '../src/bytes.js';
import { KintCryptoError } from '../src/constants.js';
import { canonicalPayloadJson, typedData, vaultDigestHex } from '../src/typedData.js';
import { epochAad } from '../src/envelope.js';
import { kekInfo } from '../src/kek.js';
import { V } from './vectors.js';

const SPACE = fromHex(V.space);
const OWNER = V.owner as `0x${string}`;
const UPPER_0X = `0X${V.owner.slice(2).toUpperCase()}`;

describe('fromHex', () => {
  test('it accepts bare, 0x and 0X hex', () => {
    expect(toHex(fromHex('00ff'))).toBe('00ff');
    expect(toHex(fromHex('0x00FF'))).toBe('00ff');
    expect(toHex(fromHex('0X00ff'))).toBe('00ff');
    expect(fromHex('').length).toBe(0);
    expect(toHex(fromHex(`  ${V.space}  `))).toBe(V.space);
  });

  test('it refuses a string that is not hex, instead of reading half of it', () => {
    // Number.parseInt is happy to call "1z" 1 and "-1" negative; every one of
    // these used to come back as a plausible-looking byte
    for (const bad of ['1z', '0 12', '-1', '+1', '0x1z']) {
      expect(() => fromHex(bad)).toThrow(KintCryptoError);
      expect(() => fromHex(bad)).toThrow(/is not hex/);
    }
  });

  test('it still refuses an odd length', () => {
    expect(() => fromHex('abc')).toThrow(/odd length 3/);
    expect(() => fromHex('0xabc')).toThrow(/odd length 3/);
  });
});

describe('normaliseAddress', () => {
  test('lower case, upper case, 0X and whitespace all reach the same address', () => {
    // viem's getAddress throws on the 0X form; Python's to_checksum_address takes
    // it, and a page gets both from wallets and explorers
    expect(normaliseAddress(OWNER)).toBe(OWNER);
    expect(normaliseAddress(V.owner.toLowerCase())).toBe(OWNER);
    expect(normaliseAddress(UPPER_0X)).toBe(OWNER);
    expect(normaliseAddress(V.owner.slice(2).toUpperCase())).toBe(OWNER);
    expect(normaliseAddress(`  ${V.owner}  `)).toBe(OWNER);
  });

  test('a wrong checksum is CORRECTED, not refused: nothing here validates one', () => {
    // lower ONE checksum letter. eth_utils.to_checksum_address re-checksums that
    // rather than rejecting it, and so does this: the body is lowercased before
    // it is checksummed, so the supplied capitals never get to mean anything.
    // This test pins the re-checksumming, NOT a checksum check, because there is
    // no checksum check to pin.
    const body = V.owner.slice(2);
    const i = [...body].findIndex((c) => /[A-F]/.test(c));
    const broken = `0x${body.slice(0, i)}${body[i]!.toLowerCase()}${body.slice(i + 1)}`;
    expect(broken).not.toBe(V.owner);
    expect(broken).not.toBe(broken.toLowerCase());
    expect(normaliseAddress(broken)).toBe(OWNER);
    // and the mixed-case input reaches the same address as its own lowercase form
    expect(normaliseAddress(broken)).toBe(normaliseAddress(broken.toLowerCase()));
  });

  test('garbage names itself in the error', () => {
    expect(() => normaliseAddress('0xnothex')).toThrow(/"0xnothex" is not an address/);
    expect(() => normaliseAddress('0x1234')).toThrow(KintCryptoError);
  });
});

describe('the owner reaches every derivation the same way', () => {
  test('the typed data payload and the vault digest', () => {
    for (const owner of [V.owner, V.owner.toLowerCase(), UPPER_0X]) {
      expect(typedData(owner).message.owner).toBe(OWNER);
      expect(canonicalPayloadJson(owner)).toBe(V.canonical_payload_json);
      expect(vaultDigestHex(owner)).toBe(`0x${V.vault_digest}`);
    }
  });

  test('the kek info and the epoch AAD', () => {
    for (const owner of [V.owner, V.owner.toLowerCase(), UPPER_0X]) {
      expect(toHex(kekInfo(owner, SPACE))).toBe(V.kek_info);
      const aad = epochAad({
        owner,
        space: SPACE,
        seq: V.epoch1.seq,
        prev: fromHex(V.epoch1.prev),
        bucket: V.epoch1.bucket,
        rowsRoot: fromHex(V.epoch1.header.rows_root),
        dekId: fromHex(V.epoch1.header.dek_id),
      });
      expect(toHex(aad)).toBe(V.epoch1.aad);
    }
  });
});
