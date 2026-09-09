/**
 * The vectors the Python itself produced. Regenerate with:
 *   env -u PYTHONPATH .venv/bin/python scripts/gen_vectors.py
 */

export interface WrapVector {
  label: string;
  kind: number;
  kek: string;
  tag: string;
  nonce: string;
  wrapped: string;
  bytes: string;
}

export interface KekVector {
  kind: number;
  kek: string;
  tag: string;
  passphrase?: string;
}

export interface RowVector {
  row: Record<string, string | null>;
  row_id: string;
  leaf: string;
}

export interface ProofVector {
  row_id: string;
  leaf: string;
  proof: [string, boolean][];
}

export interface EpochVector {
  seq: number;
  prev: string;
  flags: number;
  snapshot_flag_set: boolean;
  snapshot_in_plaintext: boolean;
  rows_root: string;
  n_rows: number;
  plaintext: string;
  plaintext_utf8: string;
  bucket: number;
  aad: string;
  header: {
    version: number;
    flags: number;
    nonce: string;
    rows_root: string;
    dek_id: string;
    bucket: number;
    n_wraps: number;
    length: number;
  };
  blob: string;
  digest: string;
  deleted?: [string, string | null, string][];
  deleted_ids?: string[];
  state_after?: {
    sorted_ids: string[];
    leaves: Record<string, string>;
    root: string;
    n_rows: number;
  };
}

export interface Vectors {
  chain_id: number;
  owner: string;
  tenant: string;
  space: string;
  purpose: string;
  typed_data: unknown;
  canonical_payload_json: string;
  vault_digest: string;
  derive_signature: string;
  kek_info: string;
  keks: { signature: KekVector; signature_salted: KekVector; passphrase: KekVector };
  scrypt: { N: number; r: number; p: number; dkLen: number };
  dek: string;
  dek_id: string;
  recovery_code: string;
  wraps: WrapVector[];
  foreign_wrap: { kind: number; tag: string; bytes: string };
  empty_root: string;
  journal_key_inputs: {
    ts: string;
    evaluated: string;
    acted: string;
    forward: string | null;
    extra: string;
    key: string;
  };
  rows: RowVector[];
  sorted_ids: string[];
  rows_root: string;
  proofs: ProofVector[];
  epoch1: EpochVector;
  epoch2: EpochVector;
  push_calldata: {
    selector: string;
    data: string;
    owner: string;
    space: string;
    prev: string;
    ct_keccak: string;
    ct_length: number;
  };
}

export const V: Vectors = (await Bun.file(
  new URL('./vectors.json', import.meta.url),
).json()) as Vectors;
