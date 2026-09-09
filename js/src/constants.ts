/**
 * The frozen constants of kint, ported byte for byte from src/kint/crypto.py and
 * src/kint/canon.py. Change nothing here without a format bump on both sides.
 */

import { keccak_256 } from '@noble/hashes/sha3.js';

/** Base mainnet. The chain id is part of the epoch AAD, so it is frozen too. */
export const CHAIN_ID = 8453;

/**
 * The one string every wallet renders. It has to warn, because this signature IS
 * the key. Byte-identical to crypto.PURPOSE.
 */
export const PURPOSE =
  'kint-memory-v1: signing this reveals your memory encryption key. ' +
  'Only sign it in a kint terminal or page you opened yourself.';

export const DOMAIN = { name: 'kint', version: '1', chainId: CHAIN_ID } as const;

export const TYPES = {
  EIP712Domain: [
    { name: 'name', type: 'string' },
    { name: 'version', type: 'string' },
    { name: 'chainId', type: 'uint256' },
  ],
  KintVault: [
    { name: 'owner', type: 'address' },
    { name: 'purpose', type: 'string' },
  ],
} as const;

export const PRIMARY_TYPE = 'KintVault';

const utf8 = (s: string): Uint8Array => new TextEncoder().encode(s);

export const SPACE_PREFIX: Uint8Array = utf8('kint-space-v1');
export const KEK_INFO_PREFIX: Uint8Array = utf8('kint-kek-v1');
export const KEK_CHECK: Uint8Array = utf8('kint-kek-check-v1');
export const DEK_ID_INFO: Uint8Array = utf8('kint-dek-id-v1');
export const WRAP_AAD_PREFIX: Uint8Array = utf8('kint-wrap-v1');
export const LEAF_PREFIX: Uint8Array = utf8('kint-leaf-v1');
export const JOURNAL_KEY_PREFIX: Uint8Array = utf8('kint-journal-key-v1');

export const SCRYPT_N = 2 ** 17;
export const SCRYPT_R = 8;
export const SCRYPT_P = 1;
export const SCRYPT_DKLEN = 32;
export const SCRYPT_MAXMEM = 512 * 1024 * 1024;

export const SECP256K1_N =
  0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
export const SECP256K1_HALF_N = SECP256K1_N / 2n;

/** Wrap kinds. The enum is frozen; add at the end only. */
export const KEK_KIND_SIGNATURE = 0x01;
export const KEK_KIND_PASSPHRASE = 0x02;
/** Reserved: WebAuthn PRF. */
export const KEK_KIND_PRF = 0x03;
/** Reserved: EOA-owned smart account inner signature. */
export const KEK_KIND_SMART_ACCOUNT = 0x04;

/** Header flags. */
export const FLAG_SIGNATURE_WRAP_PASSPHRASE_SALTED = 0x01;
/** This epoch carries the FULL row set; a cold start may stop here. */
export const FLAG_SNAPSHOT = 0x02;

export const ENVELOPE_VERSION = 1;
export const EPOCH_VERSION = 1;

/** Padded-payload size buckets, in bytes. Monotone per space. */
export const BUCKETS = [4096, 8192, 16384, 32768, 65536, 98304] as const;

/** kind(1) | kek_tag(16) | wrap_nonce(12) | wrapped_dek(48) */
export const WRAP_LEN = 1 + 16 + 12 + 48;
/** version(1)|flags(1)|nonce(12)|rows_root(32)|dek_id(8)|bucket(4)|n_wraps(1) */
export const HEADER_FIXED_LEN = 1 + 1 + 12 + 32 + 8 + 4 + 1;
export const GCM_TAG_LEN = 16;

export const TIERS = ['entity', 'state', 'reference', 'journal'] as const;
export type Tier = (typeof TIERS)[number];

/** keccak256("kint-empty-v1"), the root of an empty state. */
export const EMPTY_ROOT: Uint8Array = keccak_256(utf8('kint-empty-v1'));

/** The length prefix that stands for a null column: uint32 0xFFFFFFFF. */
export const LP_NULL = 0xffffffff;

/** Thrown by everything in this package. Same shape as Python's KintCryptoError. */
export class KintCryptoError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'KintCryptoError';
  }
}
