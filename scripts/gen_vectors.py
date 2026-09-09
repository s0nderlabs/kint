#!/usr/bin/env python3
"""Generate js/test/vectors.json from kint.crypto, kint.canon and kint.epoch.

The TypeScript in js/ is a byte-for-byte port of the Python crypto, and the only
way to know that is to make the Python itself say what the bytes are. Everything
here is deterministic except the GCM nonces and the created_at timestamps, and
those are recorded in the file so the JS side can consume them.

Run:  env -u PYTHONPATH .venv/bin/python scripts/gen_vectors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from eth_abi import encode as abi_encode                     # noqa: E402
from eth_account import Account                              # noqa: E402
from eth_account.messages import encode_typed_data           # noqa: E402
from eth_utils import function_abi_to_4byte_selector, keccak, to_checksum_address  # noqa: E402

from kint import canon, crypto, epoch                        # noqa: E402

OUT = REPO / "js" / "test" / "vectors.json"

# The throwaway key from tests/test_crypto.py. Never used for anything real.
VEC_KEY = b"\x11" * 32
TENANT = "demo"
# A fixed DEK so the wraps and the dek_id are reproducible.
FIXED_DEK = b"\x22" * 32
SALT_PASSPHRASE = "café"                # non-ascii on purpose: UTF-8 as typed, no NFC
VAULT_PASSPHRASE = "correct horse battery"

NUL = chr(0)


def h(b: bytes) -> str:
    return b.hex()


def sign_derive(owner: str) -> bytes:
    """The one frozen EIP-712 signature. RFC 6979, so this is deterministic."""
    acct = Account.from_key(VEC_KEY)
    signable = encode_typed_data(full_message=crypto.typed_data(owner))
    return bytes(acct.sign_message(signable).signature)


def wrap_record(label: str, kind: int, kek: bytes) -> dict:
    w = crypto.wrap_dek(FIXED_DEK, kek, kind)
    return {
        "label": label,
        "kind": kind,
        "kek": h(kek),
        "tag": h(w.tag),
        "nonce": h(w.nonce),
        "wrapped": h(w.wrapped),
        "bytes": h(w.to_bytes()),
    }


def build_rows() -> tuple[list[canon.Row], dict]:
    """All four tiers, a null category/status/meta, accents, and a code-point trap.

    The trap: a key starting U+FB01 (LATIN SMALL LIGATURE FI) and a key starting
    U+1F525 (FIRE) sort one way by Unicode code point (Python) and the OTHER way
    by UTF-16 code unit (a naive JavaScript sort), because the astral character's
    first surrogate 0xD83D is below 0xFB01. Both keys share a category so the key
    alone decides.
    """
    j_ts = "2026-09-09T21:15:00Z"
    j_eval = "checked the deadlift plan against the recovery score"
    j_acted = "wrote the session back as an entity"
    j_forward = None
    j_extra = '{"tool":"kint","source":"journal"}'
    j_key = canon.journal_content_key(j_ts, j_eval, j_acted, j_forward, j_extra)

    rows = [
        canon.Row(tier="entity", key="zeta", category="person", status="active",
                  body='{"name":"zeta","note":"the plain ascii control"}'),
        canon.Row(tier="entity", key="\U0001f525hot", category="person", status=None,
                  body='{"name":"\U0001f525hot","note":"astral, and a null status"}'),
        canon.Row(tier="entity", key="ﬁrst", category="person", status="active",
                  body='{"name":"ﬁrst","note":"U+FB01, above the surrogate range"}'),
        canon.Row(tier="entity", key="café ünïcode", category=None, status=None,
                  body='{"name":"café ünïcode","tags":["ünïcode"]}'),
        canon.Row(tier="state", key="goal", body="ship kint before the deadline"),
        canon.Row(tier="reference", key="doc/readme", body="the readme text",
                  meta='{"source":"repo","path":"README.md"}'),
        canon.Row(tier="reference", key="doc/no-meta", body="a reference with no metadata", meta=None),
        canon.Row(tier="journal", key=j_key, ts=j_ts, evaluated=j_eval, acted=j_acted,
                  forward=j_forward, extra=j_extra),
    ]
    journal_inputs = {"ts": j_ts, "evaluated": j_eval, "acted": j_acted,
                      "forward": j_forward, "extra": j_extra, "key": j_key}
    return rows, journal_inputs


def row_records(rows: list[canon.Row]) -> list[dict]:
    return [
        {
            "row": r.to_wire(),
            "row_id": canon.row_id(r),
            "leaf": h(canon.leaf(r)),
        }
        for r in rows
    ]


def seal(rows: list[canon.Row], deleted: list, *, seq: int, prev: bytes, owner: str,
         space: bytes, wraps: list, state_root: bytes, n_rows: int, flags: int,
         snapshot: bool, previous_bucket: int = 0) -> dict:
    """One sealed epoch, with every field the JS side needs to reproduce the open."""
    plaintext = epoch.build_plaintext(TENANT, h(space), seq, h(prev), rows, deleted,
                                      state_root, n_rows, snapshot=snapshot)
    blob = crypto.seal_epoch(plaintext, dek=FIXED_DEK, wraps=wraps, owner=owner, space=space,
                             seq=seq, prev=prev, rows_root=state_root, flags=flags,
                             previous_bucket=previous_bucket)
    header, offset = crypto.Header.parse(blob)
    aad = crypto.epoch_aad(owner, space, seq, prev, header.bucket, header.rows_root, header.dek_id)
    return {
        "seq": seq,
        "prev": h(prev),
        "flags": flags,
        "snapshot_flag_set": bool(flags & crypto.FLAG_SNAPSHOT),
        "snapshot_in_plaintext": snapshot,
        "rows_root": h(state_root),
        "n_rows": n_rows,
        "plaintext": h(plaintext),
        "plaintext_utf8": plaintext.decode("utf-8"),
        "bucket": header.bucket,
        "aad": h(aad),
        "header": {
            "version": header.version,
            "flags": header.flags,
            "nonce": h(header.nonce),
            "rows_root": h(header.rows_root),
            "dek_id": h(header.dek_id),
            "bucket": header.bucket,
            "n_wraps": len(header.wraps),
            "length": offset,
        },
        "blob": h(blob),
        "digest": h(keccak(blob)),
    }


def push_calldata(owner: str, space: bytes, prev: bytes, ct: bytes) -> dict:
    abi = json.loads((REPO / "src" / "kint" / "EpochAnchor.abi.json").read_text())
    push_abi = next(e for e in abi if e.get("type") == "function" and e["name"] == "push")
    selector = function_abi_to_4byte_selector(push_abi)
    data = selector + abi_encode(
        ["address", "bytes32", "bytes32", "bytes"],
        [to_checksum_address(owner), space, prev, ct],
    )
    return {
        "selector": "0x" + h(selector),
        "data": "0x" + h(data),
        "owner": to_checksum_address(owner),
        "space": h(space),
        "prev": h(prev),
        "ct_keccak": h(keccak(ct)),
        "ct_length": len(ct),
    }


def main() -> int:
    owner = Account.from_key(VEC_KEY).address
    space = crypto.space_id(TENANT)
    sig = sign_derive(owner)

    kek_sig, tag_sig = crypto.derive_kek_from_signature(sig, owner, space)
    kek_salted, tag_salted = crypto.derive_kek_from_signature(
        sig, owner, space, passphrase=SALT_PASSPHRASE)
    kek_pass, tag_pass = crypto.derive_kek_from_passphrase(VAULT_PASSPHRASE, owner, space)

    wraps_meta = [
        wrap_record("signature", crypto.KEK_KIND_SIGNATURE, kek_sig),
        wrap_record("signature_salted", crypto.KEK_KIND_SIGNATURE, kek_salted),
        wrap_record("passphrase", crypto.KEK_KIND_PASSPHRASE, kek_pass),
    ]
    wraps = [crypto.Wrap(kind=w["kind"], tag=bytes.fromhex(w["tag"]),
                         nonce=bytes.fromhex(w["nonce"]), wrapped=bytes.fromhex(w["wrapped"]))
             for w in wraps_meta]
    # a wrap whose tag belongs to nobody: find_wrap must skip it
    foreign = crypto.wrap_dek(FIXED_DEK, bytes(range(32)), crypto.KEK_KIND_PRF)

    rows, journal_inputs = build_rows()
    leaves1 = canon.leaves_of(rows)
    root1 = canon.merkle_root(leaves1)
    ids1 = sorted(leaves1)

    proof_targets = [canon.row_id(rows[1]), canon.row_id(rows[6])]  # astral entity, null-meta reference
    proofs = [
        {
            "row_id": rid,
            "leaf": h(leaves1[rid]),
            "proof": [[sib, is_left] for sib, is_left in canon.merkle_proof(leaves1, rid)],
        }
        for rid in proof_targets
    ]

    epoch1 = seal(rows, [], seq=1, prev=bytes(32), owner=owner, space=space, wraps=wraps,
                  state_root=root1, n_rows=len(rows), flags=0, snapshot=False)

    # Epoch 2 is a GENUINE snapshot: its "rows" are the WHOLE state, one row of epoch 1
    # dropped and one row updated, and its rows_root is the root of exactly those rows.
    # "deleted" on a snapshot is informational (what went away since epoch 1, already
    # absent from "rows"), so a reader that ignores it still reaches the anchored root.
    changed = canon.Row(tier="entity", key="zeta", category="person", status="archived",
                        body='{"name":"zeta","note":"the body changed in epoch 2"}')
    deleted = [["entity", "person", "ﬁrst"]]
    deleted_ids = [f"{t}{NUL}{c or ''}{NUL}{k}" for t, c, k in deleted]

    state2 = {canon.row_id(r): r for r in rows}
    for rid in deleted_ids:
        state2.pop(rid, None)
    state2[canon.row_id(changed)] = changed
    snapshot_rows = list(state2.values())
    leaves2 = canon.leaves_of(snapshot_rows)
    root2 = canon.merkle_root(leaves2)

    prev2 = bytes.fromhex(epoch1["digest"])
    epoch2 = seal(snapshot_rows, deleted, seq=2, prev=prev2, owner=owner, space=space, wraps=wraps,
                  state_root=root2, n_rows=len(state2), flags=crypto.FLAG_SNAPSHOT, snapshot=True,
                  previous_bucket=epoch1["bucket"])
    epoch2["deleted"] = deleted
    epoch2["deleted_ids"] = deleted_ids
    epoch2["state_after"] = {
        "sorted_ids": sorted(leaves2),
        "leaves": {k: h(v) for k, v in leaves2.items()},
        "root": h(root2),
        "n_rows": len(state2),
    }

    ct1 = bytes.fromhex(epoch1["blob"])
    doc = {
        "_note": (
            "Generated by scripts/gen_vectors.py from kint.crypto/canon/epoch. "
            "Do not hand-edit. Regenerate with: "
            "env -u PYTHONPATH .venv/bin/python scripts/gen_vectors.py"
        ),
        "chain_id": crypto.CHAIN_ID,
        "owner": owner,
        "owner_key_note": "throwaway private key 0x11 repeated 32 times, never used for anything real",
        "tenant": TENANT,
        "space": h(space),
        "purpose": crypto.PURPOSE,
        "typed_data": crypto.typed_data(owner),
        "canonical_payload_json": crypto.canonical_payload_json(owner),
        "vault_digest": h(crypto.vault_digest(owner)),
        "derive_signature": h(sig),
        "kek_info": h(crypto.kek_info(owner, space)),
        "keks": {
            "signature": {"kind": crypto.KEK_KIND_SIGNATURE, "kek": h(kek_sig), "tag": h(tag_sig)},
            "signature_salted": {"kind": crypto.KEK_KIND_SIGNATURE, "passphrase": SALT_PASSPHRASE,
                                 "kek": h(kek_salted), "tag": h(tag_salted)},
            "passphrase": {"kind": crypto.KEK_KIND_PASSPHRASE, "passphrase": VAULT_PASSPHRASE,
                           "kek": h(kek_pass), "tag": h(tag_pass)},
        },
        "scrypt": {"N": crypto.SCRYPT_N, "r": crypto.SCRYPT_R, "p": crypto.SCRYPT_P, "dkLen": 32},
        "dek": h(FIXED_DEK),
        "dek_id": h(crypto.dek_id(FIXED_DEK)),
        "recovery_code": crypto.recovery_code(FIXED_DEK),
        "wraps": wraps_meta,
        "foreign_wrap": {"kind": foreign.kind, "tag": h(foreign.tag), "bytes": h(foreign.to_bytes())},
        "empty_root": h(canon.EMPTY_ROOT),
        "journal_key_inputs": journal_inputs,
        "rows": row_records(rows),
        "sorted_ids": ids1,
        "rows_root": h(root1),
        "proofs": proofs,
        "epoch1": epoch1,
        "epoch2": epoch2,
        "push_calldata": push_calldata(owner, space, bytes(32), ct1),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  owner        {owner}")
    print(f"  space        {h(space)}")
    print(f"  vault digest {doc['vault_digest']}")
    print(f"  rows         {len(rows)}  root {doc['rows_root']}")
    print(f"  epoch1       bucket {epoch1['bucket']}  blob {len(ct1)} bytes")
    print(f"  epoch2       bucket {epoch2['bucket']}  flags 0x{epoch2['flags']:02x}"
          f"  SNAPSHOT of {len(snapshot_rows)} rows  root {h(root2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
