"""`kint join` on a local anvil: one command puts a wiped machine back to reading its memory,
writes nothing to the chain, refuses to mint a vault by accident, and resumes on a re-run."""

import os
import time
from pathlib import Path

import pytest
from web3 import Web3

from kint import crypto, keys, paths, setup, store
from kint.chain import Anchor
from kint.join import JoinError, JoinOptions, run, tenant_source
from kint.push import push
from test_e2e_anvil import Machine, _fund, _owner_sig, anvil  # noqa: F401  (the module-scoped anvil fixture)

pytestmark = pytest.mark.chain

SA_OWNER = Web3.to_checksum_address("0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3")
PASS = "correct horse battery staple"


def _opts(m: Machine, tenant: str, **kw) -> JoinOptions:
    base = dict(owner=SA_OWNER, tenant=tenant, tenant_source="--tenant", db_path=m.db, method="passphrase",
                secret=PASS, setup_targets=[])
    base.update(kw)
    return JoinOptions(**base)


def _quiet(*_a, **_k):
    pass


def test_join_smart_account_lane(tmp_path, anvil):
    w3, deployer = anvil["w3"], anvil["deployer"]
    tenant = "join-smart"
    space = crypto.space_id(tenant)

    _fund(w3, deployer, SA_OWNER, 1)   # the account pays for its own setSessionKey later; also settles anvil past genesis

    # ---- a machine with nothing: join refuses to start a vault unless told to ----
    A = Machine(tmp_path, "JA", anvil).env()
    with pytest.raises(JoinError) as ei:
        run(_opts(A, tenant), log=_quiet)
    assert ei.value.step == "vault" and "--new-vault" in str(ei.value) and "--tenant" in str(ei.value)
    assert keys.session_key_exists()   # the key was minted before the refusal and is kept for the retry

    # ---- first machine, on purpose: fresh vault, still no chain write ----
    rA = run(_opts(A, tenant, new_vault=True), log=_quiet)
    assert rA.connect.fresh_vault and rA.pull is None and not rA.restored
    assert paths.recovery_path(space.hex()).exists()
    assert not rA.writes_on
    assert Anchor().head(SA_OWNER, space).seq == 0
    lines = []
    run(_opts(A, tenant, new_vault=True), log=lines.append)   # re-run: nothing minted twice
    assert any("(kept)" in l for l in lines) and any("local wraps" in l for l in lines)
    assert any(l.startswith("next: put a few cents") for l in lines)

    # ---- the owner funds and authorizes the key, the agent writes, push anchors ----
    skA = keys.session_key_address()
    _fund(w3, deployer, skA, 1)
    w3.provider.make_request("anvil_impersonateAccount", [SA_OWNER])
    anchor = Anchor()
    fn = anchor.contract.functions.setSessionKey(skA, int(time.time()) + 86400)
    h = w3.eth.send_transaction({"from": SA_OWNER, "to": anchor.address, "data": fn._encode_transaction_data(), "gas": 200000})
    w3.eth.wait_for_transaction_receipt(h)
    w3.provider.make_request("anvil_stopImpersonatingAccount", [SA_OWNER])
    cA = store.open_client(A.db, tenant)
    cA.set_entity("rules", "release-gate", {"rule": "never on a Friday"})
    cA.set_state("session", {"last": "2026-09-10"})
    assert push(owner=SA_OWNER, tenant=tenant, db_path=A.db, log=_quiet).pushed == 1
    head_before = Anchor().head(SA_OWNER, space)
    assert head_before.seq == 1

    # ---- a wiped machine: one command, one secret, back to reading; the chain untouched ----
    B = Machine(tmp_path, "JB", anvil).env()
    out = []
    rB = run(_opts(B, tenant), log=out.append)
    assert rB.session_key_created and rB.session_key != skA
    assert rB.connect.dek_source == "chain head header"
    assert rB.pull.applied == 1 and rB.pull.root_ok and rB.restored
    assert store.open_client(B.db, tenant).get_entity("rules", "release-gate")["body"] == {"rule": "never on a Friday"}
    assert not rB.writes_on and any(l.startswith("writes: off") for l in out)
    head_after = Anchor().head(SA_OWNER, space)
    assert (head_after.seq, head_after.digest) == (head_before.seq, head_before.digest)
    assert Anchor().balance(rB.session_key) == 0 and not Anchor().can_write(SA_OWNER, rB.session_key)
    assert any("writes nothing to the chain" in l for l in out)

    # ---- re-run on the same machine: resumes, restores nothing new ----
    rB2 = run(_opts(B, tenant), log=_quiet)
    assert not rB2.session_key_created and rB2.session_key == rB.session_key
    assert rB2.pull.applied == 0 and rB2.connect.dek_source == "local wraps"

    # ---- the wrong secret stops at connect, before anything is restored ----
    C = Machine(tmp_path, "JC", anvil).env()
    with pytest.raises(JoinError) as ei:
        run(_opts(C, tenant, secret="wrong passphrase"), log=_quiet)
    assert ei.value.step == "connect" and not C.db.exists()

    # ---- the recovery code from the first machine opens it on a fourth ----
    A.env()
    code = [l for l in paths.recovery_path(space.hex()).read_text().splitlines() if l.strip()][-1].strip()
    D = Machine(tmp_path, "JD", anvil).env()
    rD = run(_opts(D, tenant, method="recovery", secret=code), log=_quiet)
    assert rD.connect.dek_source == "recovery code" and rD.pull.applied == 1
    assert store.open_client(D.db, tenant).get_state("session")["body"] == {"last": "2026-09-10"}


def test_join_eoa_signature_and_harness_env(tmp_path, anvil, monkeypatch):
    tenant = "join-eoa"
    owner, sig = _owner_sig(b"\x22" * 32)
    E = Machine(tmp_path, "JE", anvil).env()
    # the harness step writes real config: give it a throwaway HOME and a fake server path
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(setup, "server_bin", lambda: "/opt/fake/kint-server")
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)   # no claude, hermes or openclaw here
    out = []
    r = run(JoinOptions(owner=owner, tenant=tenant, tenant_source="KINT_TENANT", db_path=E.db, method="signature",
                        secret="0x" + sig.hex(), new_vault=True, setup_targets=["claude", "codex"],
                        extra_env={"KINT_KEY_TTL": "30d"}), log=out.append)
    assert r.connect.fresh_vault and r.connect.account_kind == keys.ACCOUNT_KIND_EOA
    st = {t: s for t, s, _ in r.setup}
    assert st == {"claude": "skipped", "codex": "ok"}
    cfg = (tmp_path / "home" / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.kint]" in cfg and f'KINT_TENANT = "{tenant}"' in cfg and 'KINT_KEY_TTL = "30d"' in cfg
    assert 'command = "/opt/fake/kint-server"' in cfg
    assert any("kint authorize direct" in l for l in out)   # an EOA owner is pointed at the EOA authorization
    # a second run says the harness is already there instead of writing a second block
    r2 = run(JoinOptions(owner=owner, tenant=tenant, tenant_source="KINT_TENANT", db_path=E.db, method="signature",
                         secret="0x" + sig.hex(), new_vault=True, setup_targets=["codex"]), log=_quiet)
    assert r2.setup == [("codex", "ok", ["codex: already configured"])]
    assert cfg == (tmp_path / "home" / ".codex" / "config.toml").read_text()


def test_tenant_source_names_where_the_tenant_came_from(monkeypatch, tmp_path):
    assert tenant_source("kint-demo") == ("kint-demo", "--tenant")
    monkeypatch.setenv("KINT_TENANT", "from-env")
    assert tenant_source(None) == ("from-env", "KINT_TENANT")
    monkeypatch.delenv("KINT_TENANT")
    monkeypatch.setattr(store, "load_credentials", lambda: {"tenant_id": "from-creds"})
    assert tenant_source(None) == ("from-creds", "credentials.json")
    monkeypatch.setattr(store, "load_credentials", lambda: {})
    t, src = tenant_source(None)
    assert src == "Sibyl's default" and t == store.DEFAULT_TENANT
