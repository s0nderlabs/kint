"""Regressions from the Sep 9 2026 code review."""

import json
import os

import pytest
from sibyl_memory_client import MemoryClient

from kint import canon, crypto, keys
from kint.export import export_rows, read_row
from kint.push import PushError, _chunk
from kint.restore import replay


def test_identical_journal_events_stay_distinct_rows(tmp_path):
    db = tmp_path / "memory.db"
    c = MemoryClient.local(str(db), tenant_id="t")
    for _ in range(3):
        c.write_event(acted={"kind": "decision", "body": {"what": "same"}}, ts="2026-05-01T09:00:00.000Z")
    rows = export_rows(db, "t")
    ids = {canon.row_id(r) for r in rows}
    assert len(rows) == 3 and len(ids) == 3
    keys_ = sorted(r.key for r in rows)
    assert ":" not in keys_[0] and keys_[1].endswith(":1") and keys_[2].endswith(":2")
    # read_row by uuid assigns the same ordinal the export did
    for ev in c.read_events(limit=10):
        rr = read_row(db, "t", "journal", ev["id"])
        assert rr is not None and canon.row_id(rr) in ids
    # replay reproduces three rows and the same root
    db2 = tmp_path / "m2.db"
    c2 = MemoryClient.local(str(db2), tenant_id="t")
    rep = replay(c2, rows, verify_db_path=db2, tenant_id="t")
    assert rep.ok and rep.written == 3
    assert canon.merkle_root(canon.leaves_of(export_rows(db2, "t"))) == canon.merkle_root(canon.leaves_of(rows))
    assert len(c2.read_events(limit=10)) == 3
    c.storage.close(); c2.storage.close()


def test_chunk_refuses_a_row_that_cannot_fit_and_splits_by_measured_size():
    big = canon.Row(tier="reference", key="blob", body=os.urandom(120_000).hex())
    with pytest.raises(PushError):
        _chunk([big], [])
    rows = [canon.Row(tier="reference", key=f"r{i}", body=os.urandom(20_000).hex()) for i in range(8)]
    chunks = _chunk(rows, [["entity", "c", "gone"]])
    assert len(chunks) >= 2
    assert chunks[0][1] == [["entity", "c", "gone"]] and all(ch[1] == [] for ch in chunks[1:])
    assert sum(len(ch[0]) for ch in chunks) == 8
    from kint.push import _compressed_size, MAX_COMPRESSED_PER_EPOCH
    assert all(_compressed_size(ch[0], ch[1]) <= MAX_COMPRESSED_PER_EPOCH for ch in chunks)


def test_ttl_env_edge_cases(monkeypatch):
    monkeypatch.setenv("KINT_KEY_TTL", "")
    assert keys._ttl_seconds() == keys.DEFAULT_TTL_SECONDS
    monkeypatch.setenv("KINT_KEY_TTL", "forever")
    assert keys._ttl_seconds() == keys.DEFAULT_TTL_SECONDS
    monkeypatch.setenv("KINT_KEY_TTL", "30d")
    assert keys._ttl_seconds() == 30 * 86400
    monkeypatch.setenv("KINT_KEY_TTL", "session")
    assert keys._ttl_seconds() is None


def test_verify_never_credits_an_unanchored_top_hit(tmp_path, monkeypatch):
    from kint.epoch import Mirror
    from kint.verify import verify
    monkeypatch.setenv("KINT_HOME", str(tmp_path / "kint"))
    db = tmp_path / "memory.db"
    client = MemoryClient.local(str(db), tenant_id="t")
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    space_hex = crypto.space_id("t").hex()
    m = Mirror.empty(space_hex, "t")
    m.apply(export_rows(db, "t"), [])
    m.seq, m.digest, m.block, m.anchored_root = 1, "ab" * 32, 100, m.root.hex()
    m.save()
    # a newer, unanchored row that Sibyl ranks first for the same words
    client.set_entity("rules", "release-gate-v2", {"rule": "Friday Friday Friday: ship on a Friday whenever"})
    res = verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=db, tenant="t", write_refusal=False)
    statuses = [c.status for c in res.checks]
    assert "unanchored" in statuses and "verified" in statuses
    assert res.decision == "proceed"
    assert "release-gate verified" in res.reason and "release-gate-v2 verified" not in res.reason
    if statuses[0] == "unanchored":
        assert "UNANCHORED" in res.reason and "release-gate-v2" in res.reason
    client.storage.close()


def test_recovery_code_is_bound_to_the_vault(tmp_path, monkeypatch):
    from kint.connect import ConnectError, connect_recovery, connect_smart_account
    from kint.push import save_wraps
    monkeypatch.setenv("KINT_HOME", str(tmp_path / "kint"))
    monkeypatch.setenv("KINT_NO_KEYCHAIN", "1")
    monkeypatch.setenv("KINT_SESSION_PASSPHRASE", "x")
    monkeypatch.setenv("KINT_OFFLINE", "1")
    keys._memory_only_dek.clear()
    owner = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
    r = connect_smart_account(owner, "t", "correct horse battery staple")
    assert r.fresh_vault
    good = crypto.decode_recovery_code(r.recovery_code)
    wrong = crypto.recovery_code(crypto.new_dek())
    with pytest.raises(ConnectError):
        connect_recovery(owner, "t", wrong)          # wraps exist, cached DEK differs: refused
    assert keys.cached_dek(crypto.space_id("t").hex()) == good
    ok = connect_recovery(owner, "t", r.recovery_code)
    assert ok.dek_source == "recovery code"
