"""Snapshot epochs without a chain: the plaintext stays byte-identical when nothing asks for a
snapshot, the flag survives a round trip, and a full state that does not fit one epoch is refused
by name."""

import json
import time

import pytest

from kint import crypto, keys, paths, push as push_mod
from kint.canon import Row, leaves_of, merkle_root
from kint.epoch import EPOCH_VERSION, build_plaintext, parse_plaintext
from kint.export import export_rows
from kint.push import PushError, push, save_wraps

OWNER = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
TENANT = "snapshot-tenant"


def _rows():
    return [Row(tier="entity", key="alice", category="people", status="active",
                body='{"role":"reviewer"}', meta=None),
            Row(tier="state", key="priorities", category=None, status=None,
                body='{"top":["kint"]}', meta=None)]


def test_build_plaintext_is_byte_identical_without_a_snapshot():
    rows = _rows()
    root = merkle_root(leaves_of(rows))
    pt = build_plaintext(TENANT, "ab" * 32, 7, "cd" * 32, rows, [["entity", "people", "bob"]], root, 2)
    doc = json.loads(pt.decode("utf-8"))
    # the exact v1 document, written out by hand: no key added, no key reordered
    expected = {"v": EPOCH_VERSION, "tenant": TENANT, "space": "ab" * 32, "seq": 7, "prev": "cd" * 32,
                "rows": [r.to_wire() for r in rows], "deleted": [["entity", "people", "bob"]],
                "rows_root": root.hex(), "n_rows": 2, "created_at": doc["created_at"]}
    assert pt == json.dumps(expected, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert "snapshot" not in doc


def test_snapshot_key_is_present_only_when_asked_and_survives_parsing():
    rows = _rows()
    root = merkle_root(leaves_of(rows))
    plain = build_plaintext(TENANT, "ab" * 32, 1, "00" * 32, rows, [], root, 2)
    snap = build_plaintext(TENANT, "ab" * 32, 1, "00" * 32, rows, [], root, 2, snapshot=True)
    assert b'"snapshot":true' in snap and b'"snapshot"' not in plain
    assert len(snap) == len(plain) + len(b',"snapshot":true')
    assert parse_plaintext(snap)["snapshot"] is True
    assert parse_plaintext(plain)["snapshot"] is False


def test_seal_carries_the_flag_and_peek_reads_it_back():
    dek = crypto.new_dek()
    kek, _ = crypto.derive_kek_from_passphrase("correct horse battery staple", OWNER, crypto.space_id(TENANT))
    wraps = [crypto.wrap_dek(dek, kek, crypto.KEK_KIND_PASSPHRASE)]
    space = crypto.space_id(TENANT)
    blob = crypto.seal_epoch(b'{"v":1}', dek=dek, wraps=wraps, owner=OWNER, space=space, seq=1,
                             prev=bytes(32), rows_root=bytes(32), flags=crypto.FLAG_SNAPSHOT)
    assert crypto.peek_header(blob).flags & crypto.FLAG_SNAPSHOT
    plain = crypto.seal_epoch(b'{"v":1}', dek=dek, wraps=wraps, owner=OWNER, space=space, seq=1,
                              prev=bytes(32), rows_root=bytes(32))
    assert not crypto.peek_header(plain).flags & crypto.FLAG_SNAPSHOT


def _enrol(space_hex: str, wraps):
    keys.Enrolment(owner=OWNER, tenant_id=TENANT, space=space_hex, account_kind=keys.ACCOUNT_KIND_EOA,
                   signer=OWNER, chain_id=crypto.CHAIN_ID, kek_tags=[w.tag.hex() for w in wraps],
                   wrap_kinds=[w.kind for w in wraps], created_at=time.time(), contract=None,
                   created_here=False).save()


def test_push_refuses_a_snapshot_that_does_not_fit_one_epoch(tmp_path, monkeypatch, sibyl_store):
    client, db, tenant_id = sibyl_store
    from tests.conftest import seed
    seed(client)
    monkeypatch.setenv("KINT_HOME", str(tmp_path / "kint"))
    monkeypatch.setenv("KINT_NO_KEYCHAIN", "1")
    monkeypatch.setenv("KINT_SESSION_PASSPHRASE", "snapshot-test")
    monkeypatch.setenv("KINT_OFFLINE", "1")
    keys._memory_only_dek.clear()
    space_hex = crypto.space_id(tenant_id).hex()
    dek = crypto.new_dek()
    kek, _ = crypto.derive_kek_from_passphrase("pass", OWNER, crypto.space_id(tenant_id))
    wraps = [crypto.wrap_dek(dek, kek, crypto.KEK_KIND_PASSPHRASE)]
    save_wraps(space_hex, wraps)
    _enrol(space_hex, wraps)

    # far below what nine seeded rows compress to, so the refusal is the only outcome
    monkeypatch.setattr(push_mod, "MAX_COMPRESSED_PER_EPOCH", 600)
    with pytest.raises(PushError) as e:
        push(owner=OWNER, tenant=tenant_id, db_path=db, dek=dek, wraps=wraps, snapshot=True,
             dry_run=True, log=lambda *_: None)
    msg = str(e.value)
    assert "snapshots are single-epoch" in msg and "600 bytes" in msg
    assert str(push_mod._compressed_size(export_rows(db, tenant_id), [])) in msg
    assert "9 rows" in msg
    # no chain was touched and nothing was written: the mirror is still absent
    assert not paths.mirror_path(space_hex).exists()


def test_push_snapshot_dry_run_says_snapshot(tmp_path, monkeypatch, sibyl_store):
    client, db, tenant_id = sibyl_store
    from tests.conftest import seed
    seed(client)
    monkeypatch.setenv("KINT_HOME", str(tmp_path / "kint2"))
    monkeypatch.setenv("KINT_NO_KEYCHAIN", "1")
    monkeypatch.setenv("KINT_SESSION_PASSPHRASE", "snapshot-test")
    monkeypatch.setenv("KINT_OFFLINE", "1")
    keys._memory_only_dek.clear()
    space_hex = crypto.space_id(tenant_id).hex()
    dek = crypto.new_dek()
    kek, _ = crypto.derive_kek_from_passphrase("pass", OWNER, crypto.space_id(tenant_id))
    wraps = [crypto.wrap_dek(dek, kek, crypto.KEK_KIND_PASSPHRASE)]
    save_wraps(space_hex, wraps)
    _enrol(space_hex, wraps)

    class _NoChain:
        address = "0x0000000000000000000000000000000000000000"

        def head(self, owner, space):
            from kint.chain import Head
            return Head(bytes(32), 0, 0)

    rep = push(owner=OWNER, tenant=tenant_id, db_path=db, anchor=_NoChain(), dek=dek, wraps=wraps,
               snapshot=True, dry_run=True, log=lambda *_: None)
    assert "snapshot" in rep.message and rep.changed_rows == 9 and rep.deleted_rows == 0
    assert rep.pushed == 0


def test_rekey_cli_maps_bad_inputs_to_exit_2(tmp_path, monkeypatch, capsys):
    """A missing signature file or a non-hex signature is a `kint: ...` line and exit 2, never a traceback."""
    import io
    import sys as _sys
    from kint import cli
    monkeypatch.setenv("KINT_HOME", str(tmp_path / "kint"))
    monkeypatch.setenv("KINT_NO_KEYCHAIN", "1")
    monkeypatch.setenv("KINT_OFFLINE", "1")
    owner = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
    with pytest.raises(SystemExit) as e:
        cli.main(["--tenant", "t", "rekey", "--owner", owner, "--signature-file", str(tmp_path / "nope")])
    assert e.value.code == 2 and "kint:" in capsys.readouterr().err
    monkeypatch.setattr(_sys, "stdin", io.StringIO("not hex at all\n"))
    with pytest.raises(SystemExit) as e:
        cli.main(["--tenant", "t", "rekey", "--owner", owner, "--signature", "-"])
    assert e.value.code == 2 and "not hex" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["--tenant", "t", "rekey", "--owner", owner, "--signature", "-", "--passphrase-stdin"])
    assert e.value.code == 2 and "share stdin" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["--tenant", "t", "rekey", "--owner", owner])
    assert e.value.code == 2
