import os

from kint import canon


def _rows(n):
    return [canon.Row(tier="entity", key=f"e{i}", category="c", body='{"i":%d}' % i) for i in range(n)]


def test_leaf_ignores_regenerated_timestamp_but_not_content():
    a = canon.Row(tier="entity", key="k", category="c", status=None, body='{"a":1,"b":2}', ts="2026-01-01")
    b = canon.Row(tier="entity", key="k", category="c", status=None, body='{"a":1,"b":2}', ts="2026-02-02")
    c = canon.Row(tier="entity", key="k", category="c", status=None, body='{"b":2,"a":1}', ts="2026-01-01")
    assert canon.leaf(a) == canon.leaf(b)
    assert canon.leaf(a) != canon.leaf(c)
    d = canon.Row(tier="entity", key="k", category="c", status="active", body='{"a":1,"b":2}')
    assert canon.leaf(a) != canon.leaf(d)


def test_journal_key_is_content_derived_and_ts_is_content():
    k1 = canon.journal_content_key("2026-01-01T00:00:00.000Z", None, '{"x":1}', None, None)
    k2 = canon.journal_content_key("2026-01-01T00:00:00.000Z", None, '{"x":1}', None, None)
    k3 = canon.journal_content_key("2026-01-01T00:00:00.001Z", None, '{"x":1}', None, None)
    assert k1 == k2 != k3
    r = canon.Row(tier="journal", key=k1, ts="2026-01-01T00:00:00.000Z", acted='{"x":1}')
    r2 = canon.Row(tier="journal", key=k1, ts="2026-01-01T00:00:00.000Z", acted='{"x":1}', evaluated="")
    assert canon.leaf(r) != canon.leaf(r2)  # None and "" are distinct


def test_merkle_root_and_proofs_all_sizes():
    assert canon.merkle_root({}) == canon.EMPTY_ROOT
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 16, 17):
        rows = _rows(n)
        leaves = canon.leaves_of(rows)
        root = canon.merkle_root(leaves)
        for r in rows:
            rid = canon.row_id(r)
            proof = canon.merkle_proof(leaves, rid)
            assert canon.verify_proof(leaves[rid], proof, root), (n, rid)
            assert not canon.verify_proof(os.urandom(32), proof, root)
        # order independent: the root is over sorted ids
        shuffled = dict(reversed(list(leaves.items())))
        assert canon.merkle_root(shuffled) == root


def test_root_changes_with_any_row():
    rows = _rows(5)
    root = canon.merkle_root(canon.leaves_of(rows))
    rows[2].body = '{"i":99}'
    assert canon.merkle_root(canon.leaves_of(rows)) != root


def test_wire_round_trip():
    r = canon.Row(tier="reference", key="doc", body="# hi", meta='{"a":1}', ts="t", rowid=7)
    w = r.to_wire()
    assert "rowid" not in w
    assert canon.Row.from_wire(w) == canon.Row(tier="reference", key="doc", body="# hi", meta='{"a":1}', ts="t")


def test_incomplete_mirror_refuses_verification(tmp_path, monkeypatch):
    """A mirror that skipped an epoch, or whose root drifted from the anchored root, must refuse."""
    import os
    from sibyl_memory_client import MemoryClient
    from kint import crypto
    from kint.epoch import Mirror
    from kint.verify import verify
    monkeypatch.setenv("KINT_HOME", str(tmp_path / "kint"))
    db = tmp_path / "memory.db"
    client = MemoryClient.local(str(db), tenant_id="t")
    client.set_entity("rules", "release-gate", {"rule": "never on a Friday"})
    space_hex = crypto.space_id("t").hex()
    from kint.export import export_rows
    rows = export_rows(db, "t")
    m = Mirror.empty(space_hex, "t")
    m.apply(rows, [])
    m.seq, m.digest, m.block = 3, "ab" * 32, 100
    m.anchored_root = m.root.hex()
    m.skipped = [2]
    m.save()
    res = verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=db, tenant="t", write_refusal=False)
    assert res.decision == "refuse" and "[2]" in res.reason
    m.skipped = []
    m.anchored_root = "cd" * 32
    m.save()
    res = verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=db, tenant="t", write_refusal=False)
    assert res.decision == "refuse" and "does not equal the rows_root" in res.reason
    m.anchored_root = m.root.hex()
    m.save()
    res = verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=db, tenant="t", write_refusal=False)
    assert res.decision == "proceed"
    client.storage.close()
