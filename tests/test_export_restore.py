from sibyl_memory_client import MemoryClient

from kint import canon
from kint.export import export_rows, read_row
from kint.restore import replay
from tests.conftest import seed


def test_export_covers_four_tiers_in_rowid_order(sibyl_store):
    client, db, tenant = sibyl_store
    seed(client)
    rows = export_rows(db, tenant)
    tiers = [r.tier for r in rows]
    assert tiers == ["entity"] * 3 + ["state"] * 2 + ["reference"] * 2 + ["journal"] * 2
    assert [r.rowid for r in rows if r.tier == "entity"] == sorted(r.rowid for r in rows if r.tier == "entity")
    # exact stored TEXT, insertion order preserved by Sibyl's dumps()
    gate = next(r for r in rows if r.key == "release-gate")
    assert gate.body == '{"rule":"never ship on a Friday","since":"2026-05-01","owner":"elpabl0"}'
    assert gate.category == "rules"
    # unrelated tenant sees nothing
    assert export_rows(db, "other-tenant") == []


def test_read_row_matches_export(sibyl_store):
    client, db, tenant = sibyl_store
    seed(client)
    rows = {canon.row_id(r): r for r in export_rows(db, tenant)}
    got = read_row(db, tenant, "entity", "release-gate", "rules")
    assert canon.leaf(got) == canon.leaf(rows[canon.row_id(got)])
    st = read_row(db, tenant, "state", "priorities")
    assert canon.leaf(st) == canon.leaf(rows[canon.row_id(st)])
    ref = read_row(db, tenant, "reference", "runbook")
    assert canon.leaf(ref) == canon.leaf(rows[canon.row_id(ref)])
    ev_id = client.read_events(limit=1)[0]["id"]
    ev = read_row(db, tenant, "journal", ev_id)
    assert ev is not None and canon.leaf(ev) == canon.leaf(rows[canon.row_id(ev)])
    assert read_row(db, tenant, "entity", "nope", "rules") is None


def test_restore_is_content_exact_and_search_exact(sibyl_store, tmp_path):
    client, db, tenant = sibyl_store
    seed(client)
    rows = export_rows(db, tenant)
    root_a = canon.merkle_root(canon.leaves_of(rows))

    db2 = tmp_path / "second" / "memory.db"
    client2 = MemoryClient.local(str(db2), tenant_id=tenant)
    rep = replay(client2, rows, verify_db_path=db2, tenant_id=tenant)
    assert rep.ok, (rep.skipped, rep.mismatched)
    assert rep.written == len(rows)
    rows2 = export_rows(db2, tenant)
    assert canon.merkle_root(canon.leaves_of(rows2)) == root_a
    # body TEXT byte-identical for every row
    a = {canon.row_id(r): r for r in rows}
    b = {canon.row_id(r): r for r in rows2}
    assert set(a) == set(b)
    for rid in a:
        assert a[rid].body == b[rid].body
        assert a[rid].meta == b[rid].meta
        assert a[rid].status == b[rid].status
        if a[rid].tier == "journal":
            assert a[rid].ts == b[rid].ts
    # search-exact through Sibyl's own search, verdict included
    for q in ("Friday", "reviewer", "Runbook", "passphrase", "café"):
        h1 = client.search(q)
        h2 = client2.search(q)
        assert h1.verdict.code == h2.verdict.code
        def ident(h):
            # journal uuids regenerate on replay (documented); identity is the ts + body there
            return (h["tier"], h["ts"] if h["tier"] == "journal" else h["key"], h["category"])
        assert [ident(h) for h in h1] == [ident(h) for h in h2], q
    client2.storage.close()


def test_replay_reports_a_row_that_cannot_be_written(sibyl_store):
    client, db, tenant = sibyl_store
    bad = canon.Row(tier="entity", key="x", category="c", body="not json at all")
    rep = replay(client, [bad], verify_db_path=db, tenant_id=tenant)
    assert not rep.ok
    assert rep.skipped and "write failed" in rep.skipped[0]["reason"]
    assert rep.mismatched and rep.mismatched[0]["reason"] == "row missing after replay"


def test_delete_replays_for_entities_only(sibyl_store):
    client, db, tenant = sibyl_store
    seed(client)
    rep = replay(client, [], deletions=[("entity", "people", "bob"), ("state", None, "session")])
    assert rep.deleted == 1
    assert rep.skipped[0]["tier"] == "state"
    assert {r.key for r in export_rows(db, tenant) if r.tier == "entity"} == {"release-gate", "alice"}
