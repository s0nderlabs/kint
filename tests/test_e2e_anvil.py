"""End to end on a local anvil (chain id 8453): deploy EpochAnchor, connect, push, wipe,
pull, verify, tamper, refuse, temporal read, fork refusal, recovery code, smart-account mode."""

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

from kint import crypto, keys, paths, store
from kint.chain import Anchor
from kint.connect import connect_eoa, connect_recovery, connect_smart_account
from kint.epoch import Mirror, write_watermark
from kint.pull import Fork, NotFresh, pull
from kint.push import ChainMoved, push
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
