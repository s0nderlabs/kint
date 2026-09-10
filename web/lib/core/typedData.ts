/**
 * The one frozen EIP-712 payload the owner signs to reveal the vault key.
 * Port of crypto.typed_data / canonical_payload_json / vault_digest.
 *
 * This signature is a SECRET, not a credential. Never accept it as
 * authentication, never send it anywhere.
 */

import { hashTypedData } from 'viem';
import type { Address, Hex } from 'viem';

import { CHAIN_ID, DOMAIN, PRIMARY_TYPE, PURPOSE, TYPES } from './constants';
import { fromHex, normaliseAddress } from './bytes';

export interface KintVaultTypedData {
  types: typeof TYPES;
  primaryType: typeof PRIMARY_TYPE;
  domain: typeof DOMAIN;
  message: { owner: Address; purpose: string };
}

/** The frozen EIP-712 payload for `owner` (checksummed). */
export function typedData(owner: string): KintVaultTypedData {
  return {
    types: TYPES,
    primaryType: PRIMARY_TYPE,
    domain: DOMAIN,
    message: { owner: normaliseAddress(owner), purpose: PURPOSE },
  };
}

/**
 * What `cast wallet sign --data --from-file` reads. Byte-stable, and byte-equal
 * to Python's canonical_payload_json: the same key order, no spaces, and a
 * trailing newline. JSON.stringify walks own keys in insertion order for
 * non-numeric keys, which is the same order the Python dict literal declares.
 */
export function canonicalPayloadJson(owner: string): string {
  return `${JSON.stringify(typedData(owner))}\n`;
}

/** keccak256(0x19 0x01 || domainSeparator || hashStruct(KintVault)). */
export function vaultDigestHex(owner: string): Hex {
  const td = typedData(owner);
  return hashTypedData({
    domain: { name: td.domain.name, version: td.domain.version, chainId: CHAIN_ID },
    types: { KintVault: [...TYPES.KintVault] },
    primaryType: 'KintVault',
    message: td.message,
  });
}

/** The same digest as raw bytes. */
export function vaultDigest(owner: string): Uint8Array {
  return fromHex(vaultDigestHex(owner));
}
