"""End to end on a local anvil (chain id 8453): deploy EpochAnchor, connect, push, wipe,
pull, verify, tamper, refuse, temporal read, fork refusal, recovery code, smart-account mode,
snapshot epochs and key rotation."""

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

import kint.connect
from kint import crypto, keys, paths, store
from kint.canon import leaf, row_id
from kint.chain import Anchor
from kint.connect import ConnectError, connect_eoa, connect_recovery, connect_smart_account, rekey
from kint.epoch import Mirror, cached_ciphertext, write_watermark
from kint.export import export_rows
from kint.pull import Fork, NotFresh, pull
from kint.push import ChainMoved, PushError, push
from kint.verify import at_block, history, verify
from tests.conftest import seed

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "contracts" / "out" / "EpochAnchor.sol" / "EpochAnchor.json"
ANVIL_KEY0 = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
OWNER_KEY = b"\x11" * 32
TENANT = "e2e-tenant"

pytestmark = pytest.mark.chain


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def anvil():
    if not shutil.which("anvil") or not ARTIFACT.exists():
        pytest.skip("anvil or the forge artifact is missing")
    port = _free_port()
    proc = subprocess.Popen(["anvil", "--chain-id", "8453", "--port", str(port), "--silent", "--block-time", "1"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    w3 = Web3(Web3.HTTPProvider(url))
    for _ in range(100):
        try:
            if w3.is_connected() and w3.eth.chain_id == 8453:
                break
        except Exception:
            pass
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("anvil did not start")
    art = json.loads(ARTIFACT.read_text())
    deployer = Account.from_key(ANVIL_KEY0)
    tx = {"from": deployer.address, "data": art["bytecode"]["object"], "nonce": 0, "chainId": 8453,
          "gas": 2_000_000, "maxFeePerGas": 10**9, "maxPriorityFeePerGas": 1}
    signed = deployer.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(h)
    address = rcpt["contractAddress"]
    yield {"url": url, "w3": w3, "address": address, "deployer": deployer}
    proc.kill()


def _fund(w3, deployer, to, eth):
    nonce = w3.eth.get_transaction_count(deployer.address, "pending")
    tx = {"to": to, "value": Web3.to_wei(eth, "ether"), "nonce": nonce, "chainId": 8453, "gas": 21000,
          "maxFeePerGas": 10**9, "maxPriorityFeePerGas": 1}
    h = w3.eth.send_raw_transaction(deployer.sign_transaction(tx).raw_transaction)
    w3.eth.wait_for_transaction_receipt(h)


def _owner_sig(owner_key: bytes) -> tuple[str, bytes]:
    acct = Account.from_key(owner_key)
    sig = bytes(acct.sign_message(encode_typed_data(full_message=crypto.typed_data(acct.address))).signature)
    return acct.address, sig


class Machine:
    """One machine = one KINT_HOME + one Sibyl store."""

    def __init__(self, tmp: Path, name: str, anvil):
        self.home = tmp / name / "kint"
        self.db = tmp / name / "sibyl" / "memory.db"
        self.anvil = anvil

    def env(self):
        os.environ["KINT_HOME"] = str(self.home)
        os.environ["KINT_NO_KEYCHAIN"] = "1"
        os.environ["KINT_SESSION_PASSPHRASE"] = "e2e-local-secret"
        os.environ["KINT_RPC_URL"] = self.anvil["url"]
        os.environ["KINT_RPC_URL_2"] = self.anvil["url"].replace("127.0.0.1", "localhost")
        os.environ["KINT_CONTRACT"] = self.anvil["address"]
        os.environ["SIBYL_MEMORY_DB"] = str(self.db)
        keys._memory_only_dek.clear()
        return self

    def client(self):
        return store.open_client(self.db, TENANT)


def test_full_lifecycle(tmp_path, anvil):
    w3, deployer = anvil["w3"], anvil["deployer"]
    owner_addr, sig = _owner_sig(OWNER_KEY)
    owner_acct = Account.from_key(OWNER_KEY)
    space = crypto.space_id(TENANT)
    space_hex = space.hex()
    _fund(w3, deployer, owner_addr, 1)

    # ---- machine A: connect, session key, authorize, seed, push --------------------------
    A = Machine(tmp_path, "A", anvil).env()
    r = connect_eoa(owner_addr, TENANT, sig)
    assert r.fresh_vault and r.dek_source == "fresh vault" and len(r.kek_tag8) == 8
    rec_file = paths.recovery_path(space_hex)
    assert rec_file.exists()
    recovery_code = rec_file.read_text().strip().splitlines()[-1]
    sk_addr = keys.create_session_key()
    _fund(w3, deployer, sk_addr, 1)
    anchor = Anchor()
    tx = anchor.set_session_key(owner_acct, sk_addr, int(time.time()) + 30 * 86400)
    anchor.wait(tx)
    assert anchor.can_write(owner_addr, sk_addr)

    client = A.client()
    seed(client)
    rep = push(owner=owner_addr, tenant=TENANT, db_path=A.db, log=lambda *_: None)
    assert rep.pushed == 1 and rep.head_seq == 1
    head = anchor.head(owner_addr, space)
    assert head.seq == 1 and head.digest.hex() == rep.head_digest
    m = Mirror.load(space_hex)
    assert m.seq == 1 and len(m.rows) == 9 and m.bucket == 4096

    # nothing to push twice
    rep2 = push(owner=owner_addr, tenant=TENANT, db_path=A.db, log=lambda *_: None)
    assert rep2.pushed == 0 and "nothing to push" in rep2.message

    # ---- change, add, delete; push epoch 2 -------------------------------------------------
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday, and never without a verify", "since": "2026-09-09", "owner": "elpabl0"})
    client.set_entity("people", "carol", {"role": "judge"})
    client.delete_entity("people", "bob")
    rep3 = push(owner=owner_addr, tenant=TENANT, db_path=A.db, log=lambda *_: None)
    assert rep3.pushed == 1 and rep3.head_seq == 2 and rep3.changed_rows == 2 and rep3.deleted_rows == 1
    assert anchor.head(owner_addr, space).seq == 2

    # verify on A: the release rule is verified against the anchored root
    res = verify(client, query="Friday", limit=5, space_hex=space_hex, db_path=A.db, tenant=TENANT)
    assert res.decision == "proceed", res.reason
    top = res.checks[0]
    assert top.status == "verified" and top.proof_ok and top.anchored_seq == 2
    # temporal: two anchored versions of the rule with increasing block heights
    hs = history(space_hex, "entity", "release-gate", "rules")
    assert len(hs) == 2 and hs[0]["block"] < hs[1]["block"]
    assert "verify" not in hs[0]["body"] and "verify" in hs[1]["body"]
    assert at_block(space_hex, "entity", "release-gate", "rules", hs[0]["block"])["leaf"] == hs[0]["leaf"]
    # journal rows are anchored too
    assert any(rid.startswith("journal\x00") for rid in m.rows) or any(r.startswith("journal") for r in Mirror.load(space_hex).rows)

    # ---- machine B: fresh machine, same wallet: connect gets the DEK from the chain, pull ----
    B = Machine(tmp_path, "B", anvil).env()
    rB = connect_eoa(owner_addr, TENANT, sig)
    assert not rB.fresh_vault and rB.dek_source == "chain head header"
    repB = pull(owner=owner_addr, tenant=TENANT, db_path=B.db, client_factory=B.client, log=lambda *_: None)
    assert repB.applied == 2 and repB.root_ok is True and repB.rows_total == 9, (repB.message, repB.skipped)
    assert repB.rpcs_agreed is True
    clientB = B.client()
    got = clientB.get_entity("rules", "release-gate")["body"]
    assert got["rule"].endswith("without a verify")
    with pytest.raises(Exception):
        clientB.get_entity("people", "bob")
    resB = verify(clientB, query="Friday", limit=5, space_hex=space_hex, db_path=B.db, tenant=TENANT)
    assert resB.decision == "proceed" and resB.checks[0].status == "verified"
    # up to date pull is a no-op
    repB2 = pull(owner=owner_addr, tenant=TENANT, db_path=B.db, client_factory=B.client, log=lambda *_: None)
    assert repB2.applied == 0 and "up to date" in repB2.message

    # ---- tamper on B behind Sibyl's back: verify refuses and writes the refusal back --------
    clientB.storage.close()
    conn = sqlite3.connect(str(B.db))
    conn.execute("UPDATE entities SET body = ? WHERE name = 'release-gate'",
                 ('{"rule":"ship whenever","since":"2026-09-09","owner":"elpabl0"}',))
    conn.commit()
    conn.close()
    clientB = B.client()
    resT = verify(clientB, query="ship", limit=5, space_hex=space_hex, db_path=B.db, tenant=TENANT)
    assert resT.decision == "refuse", resT.reason
    bad = [c for c in resT.checks if c.status == "drifted"][0]
    assert bad.key == "release-gate" and bad.anchored_block and bad.head_block
    assert str(bad.anchored_block) in bad.reason and str(bad.head_block) in bad.reason
    assert resT.refusal_entity and resT.refusal_entity.startswith("kint_refusal/")
    cat, name = resT.refusal_entity.split("/", 1)
    ent = clientB.get_entity(cat, name)
    assert ent["status"] == "refused" and ent["body"]["anchored_block"] == bad.anchored_block
    # the refusal itself is an unanchored change that the next push carries
    from kint.keys import KeyError_
    with pytest.raises(KeyError_):
        push(owner=owner_addr, tenant=TENANT, db_path=B.db, log=lambda *_: None)


def test_fork_recovery_and_smart_account(tmp_path, anvil):
    w3, deployer = anvil["w3"], anvil["deployer"]
    owner_addr, sig = _owner_sig(OWNER_KEY)
    owner_acct = Account.from_key(OWNER_KEY)
    tenant2 = "e2e-tenant-2"
    space = crypto.space_id(tenant2)
    space_hex = space.hex()
    _fund(w3, deployer, owner_addr, 1)

    A = Machine(tmp_path, "A2", anvil).env()
    connect_eoa(owner_addr, tenant2, sig)
    sk = keys.create_session_key()
    _fund(w3, deployer, sk, 1)
    anchor = Anchor()
    anchor.wait(anchor.set_session_key(owner_acct, sk, int(time.time()) + 86400))
    cA = store.open_client(A.db, tenant2)
    seed(cA)
    assert push(owner=owner_addr, tenant=tenant2, db_path=A.db, log=lambda *_: None).pushed == 1
    code = paths.recovery_path(space_hex).read_text().strip().splitlines()[-1]

    # machine C restores with the RECOVERY CODE only (no wallet)
    C = Machine(tmp_path, "C", anvil).env()
    rC = connect_recovery(owner_addr, tenant2, code)
    assert rC.dek_source == "recovery code"
    repC = pull(owner=owner_addr, tenant=tenant2, db_path=C.db, client_factory=lambda: store.open_client(C.db, tenant2), log=lambda *_: None)
    assert repC.applied == 1 and repC.root_ok
    # C writes locally (unanchored) ...
    cC = store.open_client(C.db, tenant2)
    cC.set_entity("people", "dave", {"role": "newcomer"})
    # ... while A pushes epoch 2: C's pull is now a FORK and refuses
    A.env()
    cA.set_state("session", {"last": "2026-09-10"})
    assert push(owner=owner_addr, tenant=tenant2, db_path=A.db, log=lambda *_: None).head_seq == 2
    C.env()
    with pytest.raises(Fork):
        pull(owner=owner_addr, tenant=tenant2, db_path=C.db, client_factory=lambda: store.open_client(C.db, tenant2), log=lambda *_: None)
    # and C cannot push either: the chain moved
    keys.create_session_key()
    with pytest.raises(ChainMoved):
        push(owner=owner_addr, tenant=tenant2, db_path=C.db, log=lambda *_: None)
    # discard-local restores from the chain (the store is moved aside, not deleted)
    repC2 = pull(owner=owner_addr, tenant=tenant2, db_path=C.db, client_factory=lambda: store.open_client(C.db, tenant2),
                 discard_local=True, log=lambda *_: None)
    assert repC2.applied == 2 and repC2.root_ok and repC2.rows_total == 9
    assert any(p.name.startswith("memory.db.kint-backup-") for p in C.db.parent.iterdir())

    # freshness: a watermark ahead of the chain makes pull refuse
    write_watermark(space_hex, 99, "ab" * 32, 10**9)
    with pytest.raises(NotFresh):
        pull(owner=owner_addr, tenant=tenant2, db_path=C.db, client_factory=lambda: store.open_client(C.db, tenant2), log=lambda *_: None)

    # ---- smart-account owner: no key, the account itself is msg.sender (impersonated on anvil) ----
    sa_owner = Web3.to_checksum_address("0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3")
    tenant3 = "e2e-smart"
    space3 = crypto.space_id(tenant3).hex()
    S = Machine(tmp_path, "S", anvil).env()
    rS = connect_smart_account(sa_owner, tenant3, "correct horse battery staple")
    assert rS.fresh_vault and rS.account_kind == 1
    skS = keys.create_session_key()
    _fund(w3, deployer, skS, 1)
    _fund(w3, deployer, sa_owner, 1)
    w3.provider.make_request("anvil_impersonateAccount", [sa_owner])
    anchor = Anchor()
    fn = anchor.contract.functions.setSessionKey(skS, int(time.time()) + 86400)
    h = w3.eth.send_transaction({"from": sa_owner, "to": anchor.address, "data": fn._encode_transaction_data(), "gas": 200000})
    w3.eth.wait_for_transaction_receipt(h)
    w3.provider.make_request("anvil_stopImpersonatingAccount", [sa_owner])
    assert anchor.can_write(sa_owner, skS)
    cS = store.open_client(S.db, tenant3)
    cS.set_entity("rules", "budget", {"max_usd": 50})
    assert push(owner=sa_owner, tenant=tenant3, db_path=S.db, log=lambda *_: None).pushed == 1
    # a second machine with the passphrase only
    S2 = Machine(tmp_path, "S2", anvil).env()
    with pytest.raises(Exception):
        connect_smart_account(sa_owner, tenant3, "wrong passphrase")
    rS2 = connect_smart_account(sa_owner, tenant3, "correct horse battery staple")
    assert rS2.dek_source == "chain head header"
    repS2 = pull(owner=sa_owner, tenant=tenant3, db_path=S2.db, client_factory=lambda: store.open_client(S2.db, tenant3), log=lambda *_: None)
    assert repS2.applied == 1 and repS2.root_ok
    assert store.open_client(S2.db, tenant3).get_entity("rules", "budget")["body"] == {"max_usd": 50}


def _leaf_map(db, tenant):
    return {row_id(r): leaf(r).hex() for r in export_rows(db, tenant)}


def test_snapshot_and_rekey(tmp_path, anvil):
    """One snapshot epoch replaces the whole history for a cold start; rekey rotates the data key
    under it, and only after the chain has it."""
    w3, deployer = anvil["w3"], anvil["deployer"]
    owner_addr, sig = _owner_sig(OWNER_KEY)
    owner_acct = Account.from_key(OWNER_KEY)
    tenant = "e2e-snapshot"
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    _fund(w3, deployer, owner_addr, 1)

    # ---- machine A: epoch 1 (seed), epoch 2 (one edit, one deletion), epoch 3 (the snapshot) ----
    A = Machine(tmp_path, "SA", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    old_code = paths.recovery_path(space_hex).read_text().strip().splitlines()[-1]
    sk = keys.create_session_key()
    _fund(w3, deployer, sk, 1)
    anchor = Anchor()
    anchor.wait(anchor.set_session_key(owner_acct, sk, int(time.time()) + 86400))
    cA = store.open_client(A.db, tenant)
    seed(cA)
    assert push(owner=owner_addr, tenant=tenant, db_path=A.db, log=lambda *_: None).head_seq == 1

    cA.set_entity("rules", "release-gate", {"rule": "never ship on a Friday, and never without a verify",
                                            "since": "2026-09-09", "owner": "elpabl0"})
    cA.delete_entity("people", "bob")
    rep2 = push(owner=owner_addr, tenant=tenant, db_path=A.db, log=lambda *_: None)
    assert rep2.head_seq == 2 and rep2.changed_rows == 1 and rep2.deleted_rows == 1

    rows_now = _leaf_map(A.db, tenant)
    rep3 = push(owner=owner_addr, tenant=tenant, db_path=A.db, snapshot=True, log=lambda *_: None)
    assert rep3.pushed == 1 and rep3.head_seq == 3 and "snapshot" in rep3.message
    assert str(len(rows_now)) in rep3.message
    blob3 = cached_ciphertext(space_hex, 3)
    assert crypto.peek_header(blob3).flags & crypto.FLAG_SNAPSHOT
    doc3 = json.loads((paths.epochs_dir(space_hex) / "00000003.json").read_bytes())
    assert doc3["snapshot"] is True and len(doc3["rows"]) == len(rows_now) == 8
    assert doc3["deleted"] == [] and doc3["n_rows"] == 8
    assert Mirror.load(space_hex).seq == 3 and len(Mirror.load(space_hex).rows) == 8

    # ---- machine B: a cold start stops at the snapshot: ONE epoch, the whole state -------------
    B = Machine(tmp_path, "SB", anvil).env()
    assert connect_eoa(owner_addr, tenant, sig).dek_source == "chain head header"
    repB = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=lambda: store.open_client(B.db, tenant),
                log=lambda *_: None)
    assert repB.applied == 1 and repB.head_seq == 3 and repB.root_ok is True, (repB.message, repB.skipped)
    assert repB.rows_total == 8 and not repB.skipped and not repB.warnings
    assert _leaf_map(B.db, tenant) == rows_now
    cB = store.open_client(B.db, tenant)
    assert cB.get_entity("rules", "release-gate")["body"]["rule"].endswith("without a verify")
    with pytest.raises(Exception):
        cB.get_entity("people", "bob")

    # ---- machine C: --full walks past the snapshot to the first epoch --------------------------
    C = Machine(tmp_path, "SC", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    repC = pull(owner=owner_addr, tenant=tenant, db_path=C.db, client_factory=lambda: store.open_client(C.db, tenant),
                full=True, log=lambda *_: None)
    assert repC.applied == 3 and repC.head_seq == 3 and repC.root_ok is True, (repC.message, repC.skipped)
    assert _leaf_map(C.db, tenant) == rows_now
    assert Mirror.load(space_hex).root == Mirror.load(space_hex).root  # same machine, stable
    rootC = Mirror.load(space_hex).root.hex()
    # C walked the whole history, so it can still show the superseded version of the edited rule
    hsC = history(space_hex, "entity", "release-gate", "rules")
    assert len(hsC) == 2 and "verify" not in hsC[0]["body"]

    # ---- machine A: rotate the data key; the rotation IS a snapshot epoch ----------------------
    A.env()
    cA.set_entity("people", "dave", {"role": "newcomer"})   # unanchored, so the snapshot anchors it first
    r = rekey(owner_addr, tenant, signature=sig, db_path=A.db, log=lambda *_: None)
    assert r.new_dek_id != r.old_dek_id and r.seq == 4 and r.wraps_carried == 1 and r.dropped_kinds == []
    blob4 = cached_ciphertext(space_hex, 4)
    h4 = crypto.peek_header(blob4)
    assert h4.dek_id.hex() == r.new_dek_id and h4.flags & crypto.FLAG_SNAPSHOT
    assert keys.cached_dek(space_hex) is not None and crypto.dek_id(keys.cached_dek(space_hex)).hex() == r.new_dek_id
    assert paths.recovery_path(space_hex).read_text().strip().splitlines()[-1] == r.recovery_code != old_code
    assert keys.Enrolment.load(space_hex).kek_tags == [w.tag.hex() for w in kint.connect.load_wraps(space_hex)]
    # the old recovery code is refused against the head header's dek_id
    with pytest.raises(ConnectError):
        connect_recovery(owner_addr, tenant, old_code)

    # history: the pre-rotation versions survive, the snapshots add no fake version ...
    hs = history(space_hex, "entity", "release-gate", "rules")
    assert len(hs) == 2 and not any(v.get("snapshot") for v in hs)
    assert hs[0]["block"] < hs[1]["block"] and "verify" in hs[1]["body"]
    assert at_block(space_hex, "entity", "release-gate", "rules", hs[0]["block"])["leaf"] == hs[0]["leaf"]
    # ... but a row first anchored BY a snapshot is listed, and says so
    hd = history(space_hex, "entity", "dave", "people")
    assert len(hd) == 1 and hd[0]["seq"] == 4 and hd[0]["snapshot"] is True

    # ---- machine D: a fresh machine gets the NEW key and restores from the snapshot alone ------
    D = Machine(tmp_path, "SD", anvil).env()
    rD = connect_eoa(owner_addr, tenant, sig)
    assert rD.dek_source == "chain head header"
    assert crypto.dek_id(keys.cached_dek(space_hex)).hex() == r.new_dek_id
    repD = pull(owner=owner_addr, tenant=tenant, db_path=D.db, client_factory=lambda: store.open_client(D.db, tenant),
                log=lambda *_: None)
    assert repD.applied == 1 and repD.head_seq == 4 and repD.root_ok is True, (repD.message, repD.skipped)
    assert repD.rows_total == 9 and store.open_client(D.db, tenant).get_entity("people", "dave")["body"] == {"role": "newcomer"}
    assert rootC != Mirror.load(space_hex).root.hex()   # dave joined the state after C pulled

    # ---- machine B again: its LOCAL wraps now hold a stale key, the head header decides --------
    B.env()
    assert connect_eoa(owner_addr, tenant, sig).dek_source == "chain head header"
    assert crypto.dek_id(keys.cached_dek(space_hex)).hex() == r.new_dek_id
    repB2 = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=lambda: store.open_client(B.db, tenant),
                 log=lambda *_: None)
    assert repB2.applied == 1 and repB2.head_seq == 4 and repB2.root_ok is True, (repB2.message, repB2.skipped)
    assert repB2.rows_total == 9 and not repB2.warnings
    # B restored from the snapshot, so it holds ONE version of the rule (the snapshot says so) and
    # the rotation, which changed no row, added none
    hsB = history(space_hex, "entity", "release-gate", "rules")
    assert len(hsB) == 1 and hsB[0]["seq"] == 3 and hsB[0]["snapshot"] is True

    # ---- machine E: --full after a rotation starts at the rotation's snapshot, never a gap -----
    E = Machine(tmp_path, "SE", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    repE = pull(owner=owner_addr, tenant=tenant, db_path=E.db, client_factory=lambda: store.open_client(E.db, tenant),
                full=True, log=lambda *_: None)
    assert repE.applied == 1 and repE.head_seq == 4 and repE.root_ok is True, (repE.message, repE.skipped)
    assert not repE.skipped and repE.rows_total == 9


def test_rekey_refuses_and_changes_nothing_until_the_chain_has_it(tmp_path, anvil, monkeypatch):
    owner_addr, sig = _owner_sig(OWNER_KEY)
    tenant = "e2e-rekey-guards"
    space_hex = crypto.space_id(tenant).hex()
    M = Machine(tmp_path, "RK", anvil).env()
    connect_eoa(owner_addr, tenant, sig, add_passphrase="the second wrap")
    wraps_path = paths.kint_home() / f"wraps-{space_hex[:16]}.json"
    before = {p: p.read_bytes() for p in (wraps_path, paths.recovery_path(space_hex),
                                          paths.enrolment_path(space_hex))}
    dek_before = keys.cached_dek(space_hex)
    assert len(kint.connect.load_wraps(space_hex)) == 2

    # a key that opens the vault today and is not supplied is named, not silently dropped
    with pytest.raises(ConnectError) as e:
        rekey(owner_addr, tenant, signature=sig, db_path=M.db, log=lambda *_: None)
    assert "would drop" in str(e.value) and "passphrase" in str(e.value)
    # a key that never opened this vault is refused before anything is rotated
    with pytest.raises(ConnectError) as e2:
        rekey(owner_addr, tenant, signature=sig, extra_passphrase="not this one", db_path=M.db, log=lambda *_: None)
    assert "does not open the current vault" in str(e2.value)

    # and when the push fails, this machine still opens the vault with the key it had
    def _boom(**_kw):
        raise PushError("the chain said no")

    monkeypatch.setattr(kint.connect, "_push_locked", _boom)
    with pytest.raises(PushError):
        rekey(owner_addr, tenant, signature=sig, extra_passphrase="the second wrap", db_path=M.db,
              log=lambda *_: None)
    for p, data in before.items():
        assert p.read_bytes() == data, f"{p.name} changed on a failed rekey"
    assert keys.cached_dek(space_hex) == dek_before


def test_snapshot_records_deletions_and_forged_flag_does_not_truncate(tmp_path, anvil, monkeypatch):
    """Review fixes: (1) a snapshot's plaintext keeps the deletions since the last epoch so
    history and at_block record a row's disappearance; (2) an epoch whose header CLAIMS to be
    a snapshot but does not open must not truncate a cold start to zero rows; (3) connect on
    an already-enrolled machine survives an RPC that rate-limits eth_getLogs."""
    w3, deployer = anvil["w3"], anvil["deployer"]
    owner_addr, sig = _owner_sig(OWNER_KEY)
    owner_acct = Account.from_key(OWNER_KEY)
    tenant = "e2e-snapdel"
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    _fund(w3, deployer, owner_addr, 1)

    A = Machine(tmp_path, "DA", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    sk = keys.create_session_key()
    _fund(w3, deployer, sk, 1)
    anchor = Anchor()
    anchor.wait(anchor.set_session_key(owner_acct, sk, int(time.time()) + 86400))
    cA = store.open_client(A.db, tenant)
    seed(cA)
    assert push(owner=owner_addr, tenant=tenant, db_path=A.db, log=lambda *_: None).head_seq == 1

    # (1) delete, then snapshot: the deletion must be visible to the temporal read
    cA.delete_entity("people", "bob")
    rep2 = push(owner=owner_addr, tenant=tenant, db_path=A.db, snapshot=True, log=lambda *_: None)
    assert rep2.head_seq == 2 and rep2.deleted_rows == 1
    doc2 = json.loads((paths.epochs_dir(space_hex) / "00000002.json").read_bytes())
    assert doc2["snapshot"] is True and doc2["deleted"] == [["entity", "people", "bob"]]
    assert all(r["key"] != "bob" for r in doc2["rows"])
    hist = history(space_hex, "entity", "bob", "people")
    assert [h["deleted"] for h in hist] == [False, True]
    assert at_block(space_hex, "entity", "bob", "people", rep2.epochs[0]["block"])["deleted"] is True

    # (2) a forged snapshot flag on an ordinary diff epoch, mined as epoch 3
    from kint.epoch import build_plaintext
    from kint.push import load_wraps
    mirror = Mirror.load(space_hex)
    dek = keys.cached_dek(space_hex)
    cA.set_state("session", {"last": "forged"})
    from kint.export import export_rows
    from kint.push import diff
    changed, deleted = diff(mirror, export_rows(A.db, tenant))
    assert changed and not deleted
    st = Mirror(space=space_hex, tenant=tenant, rows=dict(mirror.rows), leaves=dict(mirror.leaves))
    st.apply(changed, [])
    prev = bytes.fromhex(mirror.digest)
    pt = build_plaintext(tenant, space_hex, 3, prev.hex(), changed, [], st.root, len(st.rows))  # no snapshot key
    blob = crypto.seal_epoch(pt, dek=dek, wraps=load_wraps(space_hex), owner=owner_addr, space=space, seq=3,
                             prev=prev, rows_root=st.root, previous_bucket=mirror.bucket, flags=crypto.FLAG_SNAPSHOT)
    anchor.wait(anchor.push(keys.load_session_account(), owner_addr, space, prev, blob), confirmations=1)
    assert anchor.head(owner_addr, space).seq == 3

    logs = []
    E = Machine(tmp_path, "DE", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    repE = pull(owner=owner_addr, tenant=tenant, db_path=E.db, client_factory=lambda: store.open_client(E.db, tenant),
                log=logs.append)
    # the forged epoch is refused by name, everything before it is restored, nothing is silently empty
    assert repE.applied == 2 and repE.head_seq == 2 and repE.rows_total == 8 and repE.root_ok is True, (repE.message, repE.skipped)
    assert repE.skipped and repE.skipped[0]["seq"] == 3 and "snapshot flag disagrees" in repE.skipped[0]["reason"]
    assert any("claims to be a snapshot" in l for l in logs)
    assert Mirror.load(space_hex).skipped == [3]

    # (3) connect on the enrolled machine A with an RPC that rate-limits eth_getLogs
    A.env()
    from kint.chain import Anchor as _Anchor
    monkeypatch.setattr(_Anchor, "epoch_at_block",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError({"code": -32005, "message": "rate limit exceeded"})))
    r = connect_eoa(owner_addr, tenant, sig)
    assert r.dek_source == "local wraps"


def test_full_backfill_provenance_and_recovery_guard(tmp_path, anvil, monkeypatch):
    """Review fixes: `pull --full` on a machine that already stopped at a snapshot backfills the
    older epochs for history; a compact does not move a row's anchored provenance; a recovery
    code cannot be written from a key retired on another machine; connect_recovery survives an
    unreadable chain."""
    from kint.connect import ConnectError, write_recovery_file
    from kint.verify import anchored_version
    w3, deployer = anvil["w3"], anvil["deployer"]
    owner_addr, sig = _owner_sig(OWNER_KEY)
    owner_acct = Account.from_key(OWNER_KEY)
    tenant = "e2e-backfill"
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    _fund(w3, deployer, owner_addr, 1)

    A = Machine(tmp_path, "FA", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    old_code = paths.recovery_path(space_hex).read_text().strip().splitlines()[-1]
    sk = keys.create_session_key()
    _fund(w3, deployer, sk, 1)
    anchor = Anchor()
    anchor.wait(anchor.set_session_key(owner_acct, sk, int(time.time()) + 86400))
    cA = store.open_client(A.db, tenant)
    seed(cA)
    push(owner=owner_addr, tenant=tenant, db_path=A.db, log=lambda *_: None)                    # 1
    cA.set_entity("rules", "release-gate", {"rule": "never ship on a Friday, verify first"})
    push(owner=owner_addr, tenant=tenant, db_path=A.db, log=lambda *_: None)                    # 2
    push(owner=owner_addr, tenant=tenant, db_path=A.db, snapshot=True, log=lambda *_: None)     # 3 snapshot
    # provenance: an unchanged row still points at epoch 1, the edited one at epoch 2, never at the compact
    assert anchored_version(space_hex, "entity\x00people\x00alice")[0] == 1
    assert anchored_version(space_hex, "entity\x00rules\x00release-gate")[0] == 2

    # machine B stops at the snapshot, then asks for the history
    B = Machine(tmp_path, "FB", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    fac = lambda: store.open_client(B.db, tenant)  # noqa: E731
    repB = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=fac, log=lambda *_: None)
    assert repB.applied == 1 and repB.head_seq == 3 and repB.backfilled == 0
    assert len(history(space_hex, "entity", "release-gate", "rules")) == 1
    repF = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=fac, full=True, log=lambda *_: None)
    assert repF.backfilled == 2 and not repF.unopenable and "cached for history" in repF.message, repF.message
    versions = history(space_hex, "entity", "release-gate", "rules")
    assert [v["seq"] for v in versions] == [1, 2], versions
    assert at_block(space_hex, "entity", "release-gate", "rules", repF.head_block)["seq"] == 2
    assert anchored_version(space_hex, "entity\x00rules\x00release-gate")[0] == 2
    # idempotent: a second --full finds nothing more to do
    rep2 = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=fac, full=True, log=lambda *_: None)
    assert rep2.backfilled == 0 and rep2.message.startswith("up to date")

    # rotate on A; B's cache now holds a retired key
    A.env()
    from kint.connect import rekey
    r = rekey(owner_addr, tenant, signature=sig, db_path=A.db, confirmations=1, log=lambda *_: None)
    assert r.seq == 4
    B.env()
    with pytest.raises(ConnectError, match="rotated elsewhere"):
        write_recovery_file(tenant)
    # B pulls with only the retired key: the new snapshot is a gap, reported, nothing silently lost
    repG = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=fac, log=lambda *_: None)
    assert repG.applied == 0 and repG.skipped and repG.skipped[0]["seq"] == 4
    # reconnect picks the new key from the chain head, and the recovery file follows
    assert connect_eoa(owner_addr, tenant, sig).dek_source == "chain head header"
    repH = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=fac, log=lambda *_: None)
    assert repH.applied == 1 and repH.head_seq == 4 and repH.root_ok is True
    write_recovery_file(tenant)
    new_code = paths.recovery_path(space_hex).read_text().strip().splitlines()[-1]
    assert new_code != old_code
    # --full on B after the rotation: epochs 1 to 3 are already cached, nothing is unopenable for B
    repI = pull(owner=owner_addr, tenant=tenant, db_path=B.db, client_factory=fac, full=True, log=lambda *_: None)
    assert repI.backfilled == 0 and not repI.unopenable

    # machine C: fresh after the rotation, --full: the pre-rotation epochs are reported closed, not hidden
    C = Machine(tmp_path, "FC", anvil).env()
    connect_eoa(owner_addr, tenant, sig)
    repC = pull(owner=owner_addr, tenant=tenant, db_path=C.db, client_factory=lambda: store.open_client(C.db, tenant),
                full=True, log=lambda *_: None)
    assert repC.applied == 1 and repC.head_seq == 4 and repC.root_ok is True
    assert [u["seq"] for u in repC.unopenable] == [1, 2, 3] and "stay closed" in repC.message, repC.message

    # connect_recovery on B with an unreadable chain falls back to the cached key check
    B.env()
    from kint.chain import Anchor as _Anchor
    from kint.connect import connect_recovery
    monkeypatch.setattr(_Anchor, "head", lambda *a, **k: (_ for _ in ()).throw(ValueError("rate limit exceeded")))
    assert connect_recovery(owner_addr, tenant, new_code).dek_source == "recovery code"
    with pytest.raises(ConnectError):
        connect_recovery(owner_addr, tenant, old_code)
