"""Regressions from the Sep 10 2026 capability audit.

Everything here runs against an in-memory EpochAnchor (FakeChain), never a real RPC and never
anvil: the point is the kint logic around the chain, not the chain.
"""

import json

import pytest
from eth_account import Account
from eth_utils import keccak
from sibyl_memory_client import MemoryClient

from kint import crypto, keys, paths
from kint.chain import EpochEvent, Head
from kint.epoch import Mirror

OWNER = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
TENANT = "audit-tenant"
JUNK = b"not a kint epoch at all, written by a leaked session key"


class FakeChain:
    """One block per epoch, prevBlock links, calldata kept: enough for push, pull and connect."""

    address = "0x000000000000000000000000000000000000dEaD"
    rpc_url = "http://127.0.0.1:1"

    def __init__(self, owner: str, space: bytes):
        self.owner, self.space = owner, space
        self.events: list[EpochEvent] = []
        self.blobs: dict[str, bytes] = {}
        self.block = 100

    # writes ------------------------------------------------------------
    def append(self, blob: bytes) -> EpochEvent:
        prev = self.events[-1].digest if self.events else bytes(32)
        prev_block = self.events[-1].block_number if self.events else 0
        self.block += 1
        digest = keccak(blob)
        ev = EpochEvent(owner=self.owner, space=self.space, writer=self.owner, seq=len(self.events) + 1,
                        prev=prev, digest=digest, prev_block=prev_block, block_number=self.block,
                        tx_hash="0x" + digest.hex())
        self.events.append(ev)
        self.blobs[ev.tx_hash] = blob
        return ev

    def push(self, account, owner, space, prev, ct):
        assert prev == (self.events[-1].digest if self.events else bytes(32)), "prev does not chain on the head"
        return self.append(ct).tx_hash

    def wait(self, tx_hash, confirmations: int = 1, timeout: int = 180):
        ev = next(e for e in self.events if e.tx_hash == tx_hash)
        return {"gasUsed": 21000, "effectiveGasPrice": 1, "l1Fee": 0, "totalWei": 21000,
                "blockNumber": ev.block_number, "status": 1}

    # reads -------------------------------------------------------------
    def head(self, owner, space) -> Head:
        if not self.events:
            return Head(bytes(32), 0, 0)
        e = self.events[-1]
        return Head(e.digest, e.seq, e.block_number)

    def epoch_at_block(self, owner, space, block_number):
        return [e for e in self.events if e.block_number == block_number]

    def epoch_ciphertext(self, tx_hash):
        ev = next(e for e in self.events if e.tx_hash == tx_hash)
        return self.owner, self.space, ev.prev, self.blobs[tx_hash]

    def walk_epochs(self, owner, space, *, stop_seq: int = 0, head: Head | None = None,
                    max_epochs: int = 100000, stop_when=None):
        head = head or self.head(owner, space)
        out = []
        for e in reversed(self.events[:head.seq]):
            if e.seq <= stop_seq or len(out) >= max_epochs:
                break
            out.append(e)
            if stop_when is not None and stop_when(e):
                break
        return out

    def can_write(self, owner, writer) -> bool:
        return True


class RefusesOneEpoch:
    """The same chain, with ONE epoch's calldata unfetchable: an RPC that is down, pruned or lying.

    Everything else is the real FakeChain, so the only difference from a healthy pull is that one
    epoch cannot be read at all: nobody has seen what is in it.
    """

    def __init__(self, chain: FakeChain, seq: int):
        self._chain, self._seq = chain, seq

    def __getattr__(self, name):
        return getattr(self._chain, name)

    def epoch_ciphertext(self, tx_hash):
        ev = next(e for e in self._chain.events if e.tx_hash == tx_hash)
        if ev.seq == self._seq:
            raise RuntimeError("connection reset by peer")
        return self._chain.epoch_ciphertext(tx_hash)


def _sealed(dek: bytes, wraps, space: bytes, seq: int, prev: bytes) -> bytes:
    return crypto.seal_epoch(b'{"v":1}', dek=dek, wraps=wraps, owner=OWNER, space=space, seq=seq,
                             prev=prev, rows_root=bytes(32))


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A clean kint home with no keychain, no network and a single-RPC cold start."""
    monkeypatch.setenv("KINT_HOME", str(tmp_path / "kint-a"))
    monkeypatch.setenv("KINT_NO_KEYCHAIN", "1")
    monkeypatch.setenv("KINT_SESSION_PASSPHRASE", "test-only-local-secret")
    monkeypatch.setenv("KINT_RPC_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("KINT_RPC_URL_2", "http://127.0.0.1:1")
    monkeypatch.setenv("KINT_ALLOW_SINGLE_RPC", "1")
    monkeypatch.delenv("KINT_OFFLINE", raising=False)
    monkeypatch.setattr(keys, "load_session_account", lambda: Account.create())
    keys._memory_only_dek.clear()
    return tmp_path


# ---------------------------------------------------------------------------
# HIGH B: a junk epoch at the head must not wedge the space
# ---------------------------------------------------------------------------

def test_chain_head_header_falls_back_to_the_newest_readable_epoch(machine):
    from kint.connect import ChainUnreadable, _chain_head_header
    space = crypto.space_id(TENANT)
    chain = FakeChain(OWNER, space)
    dek = crypto.new_dek()
    kek, _ = crypto.derive_kek_from_passphrase("correct horse battery staple", OWNER, space)
    wraps = [crypto.wrap_dek(dek, kek, crypto.KEK_KIND_PASSPHRASE)]
    chain.append(_sealed(dek, wraps, space, 1, bytes(32)))
    assert _chain_head_header(OWNER, space, chain).dek_id == crypto.dek_id(dek)

    chain.append(JUNK)   # a leaked session key appends one epoch nobody can open
    lines: list[str] = []
    header = _chain_head_header(OWNER, space, chain, log=lines.append)
    assert header.dek_id == crypto.dek_id(dek)
    assert any("not a readable kint epoch" in l for l in lines)

    only_junk = FakeChain(OWNER, space)
    only_junk.append(JUNK)
    with pytest.raises(ChainUnreadable):
        _chain_head_header(OWNER, space, only_junk)


def test_owner_can_snapshot_past_an_epoch_that_never_opens(machine):
    """push refuses over a skipped epoch, names the override, and the override chains on the head."""
    from kint.connect import connect_smart_account
    from kint.pull import pull
    from kint.push import PushError, push

    space = crypto.space_id(TENANT)
    space_hex = space.hex()
    chain = FakeChain(OWNER, space)
    quiet = lambda *_a, **_k: None

    connect_smart_account(OWNER, TENANT, "correct horse battery staple", anchor=chain)
    db = machine / "a.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    client.set_state("priorities", {"top": ["kint"]})

    rep = push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)
    assert rep.pushed == 1 and rep.head_seq == 1

    chain.append(JUNK)   # the leaked session key writes epoch 2
    pr = pull(owner=OWNER, tenant=TENANT, db_path=db, client_factory=lambda: client, anchor=chain, log=quiet)
    assert [s["seq"] for s in pr.skipped] == [2]
    assert Mirror.load(space_hex).skipped == [2]

    client.set_entity("rules", "second", {"rule": "written after the wedge"})
    with pytest.raises(PushError, match="over-skipped"):
        push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)
    with pytest.raises(PushError, match="over-skipped"):
        push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, snapshot=True, log=quiet)

    rep2 = push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, snapshot=True,
                override_skipped=True, log=quiet)
    assert rep2.pushed == 1 and rep2.head_seq == 3
    assert chain.events[-1].prev == chain.events[1].digest      # chained on the junk epoch
    m = Mirror.load(space_hex)
    assert m.skipped == [] and m.seq == 3 and m.complete
    client.storage.close()


def _anchor_the_store(db, space_hex: str) -> Mirror:
    """A mirror that says every row now in the store is what the chain vouches for."""
    from kint.export import export_rows
    m = Mirror.empty(space_hex, TENANT)
    m.apply(export_rows(db, TENANT), [])
    m.seq, m.digest, m.block, m.anchored_root = 1, "ab" * 32, 100, m.root.hex()
    m.save()
    return m


# ---------------------------------------------------------------------------
# HIGH A (minimum): an auto-push must not launder a row edited behind Sibyl's tools
# ---------------------------------------------------------------------------

def test_auto_push_is_held_for_a_row_edited_behind_sibyls_tools(machine):
    import sqlite3

    from kint import server

    space_hex = crypto.space_id(TENANT).hex()
    db = machine / "held.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    _anchor_the_store(db, space_hex)
    server._state.update({"db": db, "tenant": TENANT, "space_hex": space_hex, "held": None})
    server._watch_tool_writes(client)
    server._reset_drift_baseline()
    assert server._hold_reason() is None

    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday, ever"})
    assert server._hold_reason() is None      # an agent writing through the tools is ordinary work

    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE entities SET body = ? WHERE tenant_id = ? AND category = ? AND name = ?",
                 (json.dumps({"rule": "ship on a Friday"}), TENANT, "rules", "release-gate"))
    conn.commit()
    conn.close()
    why = server._hold_reason()
    assert why and "behind Sibyl's tools" in why and "release-gate" in why
    client.storage.close()


def test_auto_push_is_held_for_a_row_kint_already_refused(machine):
    from kint import server
    from kint.canon import leaf
    from kint.export import read_row
    from kint.verify import REFUSAL_CATEGORY

    space_hex = crypto.space_id(TENANT).hex()
    db = machine / "refused.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    _anchor_the_store(db, space_hex)
    server._state.update({"db": db, "tenant": TENANT, "space_hex": space_hex, "held": None})
    server._watch_tool_writes(client)
    server._reset_drift_baseline()

    # the drift happened before this server started (the baseline cannot tell), but a refusal names it
    client.set_entity("rules", "release-gate", {"rule": "ship on a Friday"})
    server._reset_drift_baseline()
    assert server._hold_reason() is None
    drifted = leaf(read_row(db, TENANT, "entity", "release-gate", "rules")).hex()
    client.set_entity(REFUSAL_CATEGORY, "entity-rules-release-gate-1", {
        "refused": True, "tier": "entity", "category": "rules", "key": "release-gate",
        "local_leaf": drifted, "reason": "drifted"}, status="refused")
    why = server._hold_reason()
    assert why and "already refused" in why
    client.storage.close()


def test_a_refusal_that_named_no_value_does_not_hold_the_row_for_good(machine):
    """HIGH 2 (Sep 10 review): verify refuses a MISSING row with local_leaf null. That refusal names
    no value, so it must not hold every later value of the row, including one written through
    Sibyl's own tools."""
    from kint import server
    from kint.canon import leaf
    from kint.export import read_row
    from kint.verify import REFUSAL_CATEGORY

    space_hex = crypto.space_id(TENANT).hex()
    db = machine / "named-nothing.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    _anchor_the_store(db, space_hex)
    server._state.update({"db": db, "tenant": TENANT, "space_hex": space_hex, "held": None})
    server._watch_tool_writes(client)
    server._reset_drift_baseline()

    client.set_entity(REFUSAL_CATEGORY, "entity-rules-release-gate-1", {
        "refused": True, "tier": "entity", "category": "rules", "key": "release-gate",
        "local_leaf": None, "anchored_leaf": None,
        "reason": "the row the search returned is no longer in the store"}, status="refused")
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday, ever"})
    assert server._hold_reason() is None      # written back through Sibyl's tools: ordinary work

    # a refusal that DOES name the value now in the store still holds the push
    drifted = leaf(read_row(db, TENANT, "entity", "release-gate", "rules")).hex()
    client.set_entity(REFUSAL_CATEGORY, "entity-rules-release-gate-2", {
        "refused": True, "tier": "entity", "category": "rules", "key": "release-gate",
        "local_leaf": drifted, "reason": "drifted"}, status="refused")
    why = server._hold_reason()
    assert why and "already refused" in why and "release-gate" in why
    client.storage.close()


def test_a_second_machine_pulls_full_past_the_epoch_that_never_opens(machine, monkeypatch):
    """`pull --full` walks the whole history and resumes at the snapshot that covers the gap."""
    from kint.connect import connect_smart_account
    from kint.export import export_rows
    from kint.canon import leaves_of, merkle_root
    from kint.pull import pull
    from kint.push import push

    space = crypto.space_id(TENANT)
    space_hex = space.hex()
    chain = FakeChain(OWNER, space)
    quiet = lambda *_a, **_k: None

    connect_smart_account(OWNER, TENANT, "correct horse battery staple", anchor=chain)
    db = machine / "a.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)
    chain.append(JUNK)
    pull(owner=OWNER, tenant=TENANT, db_path=db, client_factory=lambda: client, anchor=chain, log=quiet)
    client.set_state("priorities", {"top": ["kint", "sigil"]})
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, snapshot=True,
         override_skipped=True, log=quiet)
    want = merkle_root(leaves_of(export_rows(db, TENANT)))

    # a second machine: its own kint home, its own store, the same passphrase
    monkeypatch.setenv("KINT_HOME", str(machine / "kint-b"))
    keys._memory_only_dek.clear()
    r = connect_smart_account(OWNER, TENANT, "correct horse battery staple", anchor=chain)
    assert not r.fresh_vault and r.dek_source == "chain head header"
    db2 = machine / "b.db"
    client2 = MemoryClient.local(str(db2), tenant_id=TENANT)
    rep = pull(owner=OWNER, tenant=TENANT, db_path=db2, client_factory=lambda: client2, anchor=chain,
               full=True, log=quiet)
    assert any(s["seq"] == 2 and s.get("superseded_by") == 3 for s in rep.skipped)
    assert rep.applied == 2 and rep.root_ok and rep.head_seq == 3
    assert Mirror.load(space_hex).skipped == []
    assert merkle_root(leaves_of(export_rows(db2, TENANT))) == want
    client.storage.close()
    client2.storage.close()


# ---------------------------------------------------------------------------
# HIGH 1 (Sep 10 review): only an epoch this machine cannot OPEN may be resumed past
# ---------------------------------------------------------------------------

def test_pull_stops_at_an_epoch_the_rpc_would_not_serve_even_with_a_later_snapshot(machine, monkeypatch):
    """A later snapshot supersedes an epoch nobody can open. It does NOT supersede one nobody has
    READ: a lying or corrupt RPC must not talk this machine into calling its picture complete."""
    from kint.canon import leaves_of, merkle_root
    from kint.connect import connect_smart_account
    from kint.export import export_rows
    from kint.pull import pull
    from kint.push import push

    space = crypto.space_id(TENANT)
    space_hex = space.hex()
    chain = FakeChain(OWNER, space)
    quiet = lambda *_a, **_k: None

    connect_smart_account(OWNER, TENANT, "correct horse battery staple", anchor=chain)
    db = machine / "a.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)
    client.set_state("priorities", {"top": ["kint"]})
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)   # epoch 2
    client.set_entity("rules", "second", {"rule": "written before the snapshot"})
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, snapshot=True, log=quiet)
    assert chain.events[-1].seq == 3
    want = merkle_root(leaves_of(export_rows(db, TENANT)))

    # a second machine restores while epoch 2 cannot be fetched, although snapshot epoch 3 is right there
    monkeypatch.setenv("KINT_HOME", str(machine / "kint-b"))
    keys._memory_only_dek.clear()
    connect_smart_account(OWNER, TENANT, "correct horse battery staple", anchor=chain)
    db2 = machine / "b.db"
    client2 = MemoryClient.local(str(db2), tenant_id=TENANT)
    rep = pull(owner=OWNER, tenant=TENANT, db_path=db2, client_factory=lambda: client2,
               anchor=RefusesOneEpoch(chain, 2), full=True, log=quiet)
    assert rep.applied == 1 and rep.head_seq == 1
    assert [(s["seq"], s.get("superseded_by")) for s in rep.skipped] == [(2, None)]
    assert "could not fetch calldata" in rep.skipped[0]["reason"]
    assert Mirror.load(space_hex).skipped == [2]

    # the RPC heals: the same pull now applies both epochs and the store reproduces the anchored state
    rep2 = pull(owner=OWNER, tenant=TENANT, db_path=db2, client_factory=lambda: client2, anchor=chain,
                full=True, log=quiet)
    assert rep2.applied == 2 and rep2.head_seq == 3 and rep2.root_ok
    assert rep2.skipped == [] and Mirror.load(space_hex).skipped == []
    assert merkle_root(leaves_of(export_rows(db2, TENANT))) == want
    client.storage.close()
    client2.storage.close()


# ---------------------------------------------------------------------------
# MEDIUM 1 and 2: verify goes through Sibyl's precision gates and checks the head
# ---------------------------------------------------------------------------

def test_verify_refuses_on_a_verdict_plain_search_would_have_hidden(machine):
    """client.search is policy-free; memory_search (and now verify) abstains on an unsupported term."""
    from kint.verify import verify

    space_hex = crypto.space_id(TENANT).hex()
    db = machine / "verdict.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    _anchor_the_store(db, space_hex)

    assert client.search("Friday spaceship", limit=5).verdict.code.value == "ok"   # the policy-free ladder
    res = verify(client, query="Friday spaceship", limit=5, space_hex=space_hex, db_path=db, tenant=TENANT,
                 write_refusal=False)
    assert res.decision == "refuse" and res.verdict["code"] == "abstained_on"
    assert verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=db, tenant=TENANT,
                  write_refusal=False).decision == "proceed"
    client.storage.close()


def test_verify_refuses_when_the_chain_head_moved_past_the_mirror(machine):
    from kint.verify import verify

    space_hex = crypto.space_id(TENANT).hex()
    db = machine / "moved.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    m = _anchor_the_store(db, space_hex)

    in_step = {"seq": m.seq, "digest": m.digest, "block": m.block}
    assert verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=db, tenant=TENANT,
                  write_refusal=False, chain_head=in_step).decision == "proceed"
    moved = {"seq": m.seq + 1, "digest": "cd" * 32, "block": m.block + 12}
    res = verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=db, tenant=TENANT,
                 write_refusal=False, chain_head=moved)
    assert res.decision == "refuse"
    assert f"chain moved to seq {m.seq + 1} at block {m.block + 12}, pull first" in res.reason
    assert res.chain_head == moved
    client.storage.close()


# ---------------------------------------------------------------------------
# MEDIUM 9: a keyed RPC URL never reaches a tool result or a log
# ---------------------------------------------------------------------------

def test_redact_scrubs_a_keyed_rpc_url_out_of_exception_text():
    from kint.chain import redact

    key = "AbCdEf0123456789xyz"
    url = f"https://base-mainnet.g.alchemy.com/v2/{key}"
    assert key not in redact(url)
    text = (f"HTTPSConnectionPool(host='base-mainnet.g.alchemy.com', port=443): Max retries exceeded with url: "
            f"/v2/{key} (Caused by ConnectTimeoutError(..., '{url}'))")
    out = redact(text)
    assert key not in out and "/v2/<redacted>" in out
    assert "base-mainnet.g.alchemy.com" in out          # the host still says which endpoint failed
    assert redact("") == "" and redact("no url here at all") == "no url here at all"


# ---------------------------------------------------------------------------
# MEDIUM 5: a new session anchors what the last one was killed before pushing
# ---------------------------------------------------------------------------

def test_the_watcher_starts_dirty_when_an_earlier_session_left_rows_unanchored(machine):
    from kint import server

    space_hex = crypto.space_id(TENANT).hex()
    db = machine / "left.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday"})
    _anchor_the_store(db, space_hex)
    server._state.update({"db": db, "tenant": TENANT, "space_hex": space_hex,
                          "first_dirty": None, "last_change": None})
    server._seed_from_leftovers(db)
    assert server._state["first_dirty"] is None      # in step with the mirror: nothing to pick up

    client.set_state("priorities", {"top": ["kint"]})    # the session that wrote this never pushed
    server._seed_from_leftovers(db)
    assert server._state["first_dirty"] is not None and server._state["last_change"] is not None
    client.storage.close()


# ---------------------------------------------------------------------------
# MEDIUM 7: pull --full backfills the diff epochs a warm pull jumped over
# ---------------------------------------------------------------------------

def test_full_pull_backfills_the_epochs_a_warm_pull_jumped(machine, monkeypatch):
    from kint.connect import connect_smart_account
    from kint.epoch import cached_epochs
    from kint.pull import pull
    from kint.push import push
    from kint.verify import history

    space = crypto.space_id(TENANT)
    space_hex = space.hex()
    chain = FakeChain(OWNER, space)
    quiet = lambda *_a, **_k: None
    home_a, home_b = str(machine / "kint-a"), str(machine / "kint-b")

    connect_smart_account(OWNER, TENANT, "correct horse battery staple", anchor=chain)
    db = machine / "a.db"
    client = MemoryClient.local(str(db), tenant_id=TENANT)
    client.set_entity("rules", "release-gate", {"rule": "v1"})
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)

    # a second machine restores while the chain is one epoch long, then falls behind
    monkeypatch.setenv("KINT_HOME", home_b)
    keys._memory_only_dek.clear()
    connect_smart_account(OWNER, TENANT, "correct horse battery staple", anchor=chain)
    db2 = machine / "b.db"
    client2 = MemoryClient.local(str(db2), tenant_id=TENANT)
    pull(owner=OWNER, tenant=TENANT, db_path=db2, client_factory=lambda: client2, anchor=chain, log=quiet)

    monkeypatch.setenv("KINT_HOME", home_a)
    keys._memory_only_dek.clear()
    for v in ("v2", "v3"):
        client.set_entity("rules", "release-gate", {"rule": v})
        push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, snapshot=True, log=quiet)
    client.set_entity("rules", "release-gate", {"rule": "v5"})
    push(owner=OWNER, tenant=TENANT, db_path=db, anchor=chain, confirmations=1, log=quiet)

    monkeypatch.setenv("KINT_HOME", home_b)
    keys._memory_only_dek.clear()
    warm = pull(owner=OWNER, tenant=TENANT, db_path=db2, client_factory=lambda: client2, anchor=chain, log=quiet)
    assert warm.head_seq == 5
    assert {seq for seq, _m, _d in cached_epochs(space_hex)} == {1, 4, 5}   # 2 and 3 were jumped

    rep = pull(owner=OWNER, tenant=TENANT, db_path=db2, client_factory=lambda: client2, anchor=chain,
               full=True, log=quiet)
    assert rep.backfilled == 2
    assert {seq for seq, _m, _d in cached_epochs(space_hex)} == {1, 2, 3, 4, 5}
    rules = [h["body"] for h in history(space_hex, "entity", "release-gate", "rules")]
    assert json.loads(rules[1])["rule"] == "v2" and json.loads(rules[2])["rule"] == "v3"
    client.storage.close()
    client2.storage.close()
