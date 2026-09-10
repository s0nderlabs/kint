"""`kint join`: the read half of onboarding as one command.

Session key, connect, restore, harness registration. It writes NOTHING to the
chain and spends nothing: a wiped machine is back to reading its memory with
one command and one secret. Writing (funding the session key, authorizing it
under the owner) stays the explicit `kint authorize` step, because that is
where the money is.

Every step reads real state first, so a second run resumes instead of minting:
an existing session key is kept, a cached data key is reused, a store already
at the head restores nothing, a harness already registered says so.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from eth_utils import to_checksum_address

from . import crypto, keys, paths, setup, store
from .chain import Anchor, redact
from .connect import (MIN_SESSION_BALANCE_WEI, ConnectError, ConnectResult, connect_eoa, connect_recovery,
                      connect_smart_account, session_key_info)
from .pull import Fork, NotFresh, PullError, PullReport, pull

METHOD_PASSPHRASE = "passphrase"   # Base Account owners: the vault passphrase
METHOD_SIGNATURE = "signature"     # EOA owners: the one frozen EIP-712 signature
METHOD_RECOVERY = "recovery"       # either: the grouped recovery code

class JoinError(Exception):
    def __init__(self, step: str, message: str, code: int = 2):
        super().__init__(message)
        self.step = step
        self.code = code


@dataclass
class JoinOptions:
    owner: str
    tenant: str
    tenant_source: str                 # "--tenant" | "KINT_TENANT" | "credentials.json" | "Sibyl's default"
    db_path: Path
    method: str
    secret: str                        # read by the CLI from stdin or an unlinked file, never argv
    eoa_passphrase: str | None = None  # EOA mode: the passphrase that salts the wallet key
    new_vault: bool = False            # allowed to start a vault when the chain holds no epochs
    discard_local: bool = False        # move a local store aside instead of refusing the merge
    full: bool = False                 # walk past snapshots for the older versions
    setup_targets: list[str] = field(default_factory=list)   # empty: no harness registration
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass
class JoinReport:
    session_key: str = ""
    session_key_created: bool = False
    connect: ConnectResult | None = None
    head_seq: int = 0
    head_block: int = 0
    pull: PullReport | None = None
    restored: bool = False
    setup: list[tuple[str, str, list[str]]] = field(default_factory=list)
    writes_on: bool = False
    steps: list[str] = field(default_factory=list)   # the steps that completed, in order


def tenant_source(explicit: str | None) -> tuple[str, str]:
    """The tenant this machine will join and where it came from, so the banner can say so.
    A wrong tenant is a different space, which is a different vault."""
    if explicit:
        return explicit, "--tenant"
    if os.environ.get("KINT_TENANT"):
        return os.environ["KINT_TENANT"], "KINT_TENANT"
    creds = store.load_credentials()
    if creds.get("tenant_id") or creds.get("account_id"):
        return store.resolve_tenant(creds), "credentials.json"
    return store.resolve_tenant(creds), "Sibyl's default"


def _tilde(p: Path) -> str:
    """A path as the user would type it: the home directory folded back to ~."""
    try:
        return "~/" + str(Path(p).expanduser().resolve().relative_to(Path.home().resolve()))
    except (ValueError, OSError):
        return str(p)


def run(opts: JoinOptions, log: Callable[[str], Any] = print) -> JoinReport:
    rep = JoinReport()
    try:
        owner = to_checksum_address(opts.owner)   # pull compares it byte for byte with the checksummed calldata owner
    except Exception as e:  # noqa: BLE001
        raise JoinError("owner", f"{opts.owner!r} is not an Ethereum address") from e
    space = crypto.space_id(opts.tenant)
    space_hex = space.hex()

    # ---- banner: what this machine is about to join ----
    try:
        anchor = Anchor()
    except Exception as e:  # noqa: BLE001
        raise JoinError("chain", f"cannot reach Base: {redact(str(e))}") from e
    log(f"join: owner {owner}")
    log(f"      tenant {opts.tenant} (from {opts.tenant_source}), space {space_hex[:16]}")
    log(f"      contract {anchor.address}, store {_tilde(opts.db_path)}")
    log("      this command writes nothing to the chain")

    # ---- 1. session key: this machine's own key, reused when it exists ----
    if keys.session_key_exists():
        rep.session_key = keys.session_key_address() or ""
        log(f"session key: {rep.session_key} (kept)")
    else:
        rep.session_key = keys.create_session_key()
        rep.session_key_created = True
        log(f"session key: {rep.session_key} (created; it signs epochs for this machine and can never decrypt)")
    rep.steps.append("session key")

    # ---- 2. the head: does this vault exist? ----
    try:
        head = anchor.head(owner, space)
    except Exception as e:  # noqa: BLE001
        raise JoinError("chain", f"cannot read the head for {owner} in space {space_hex[:16]}: {redact(str(e))}") from e
    rep.head_seq, rep.head_block = head.seq, head.block_number
    if head.seq == 0 and not opts.new_vault:
        raise JoinError("vault",
                        f"no epochs under {owner} in space {space_hex[:16]} (tenant {opts.tenant}, from "
                        f"{opts.tenant_source}). If you anchored under a different tenant, pass --tenant; "
                        "to start a new vault here on purpose, pass --new-vault")
    log(f"vault: {'no epochs yet, starting one' if head.seq == 0 else f'head epoch {head.seq} at block {head.block_number}'}")
    rep.steps.append("vault")

    # ---- 3. connect: the secret becomes the data key on this machine ----
    try:
        if opts.method == METHOD_PASSPHRASE:
            r = connect_smart_account(owner, opts.tenant, opts.secret, anchor=anchor)
        elif opts.method == METHOD_SIGNATURE:
            sig = crypto.hex_signature(opts.secret)
            r = connect_eoa(owner, opts.tenant, sig, passphrase=opts.eoa_passphrase, anchor=anchor)
        elif opts.method == METHOD_RECOVERY:
            r = connect_recovery(owner, opts.tenant, opts.secret, anchor=anchor)
        else:
            raise JoinError("connect", f"unknown method {opts.method}")
    except (ConnectError, crypto.KintCryptoError) as e:
        raise JoinError("connect", str(e)) from e
    rep.connect = r
    log(f"connected: key tag {r.kek_tag8}, data key from {r.dek_source}")
    if r.fresh_vault:
        log(f"fresh vault: recovery code written to {_tilde(paths.recovery_path(r.space))}")
        log("copy that code somewhere that is not this machine; push refuses until the file exists")
    rep.steps.append("connect")

    # ---- 4. restore: replay every epoch through Sibyl's own write methods ----
    if head.seq == 0:
        log("restore: nothing to restore, the vault starts here")
    else:
        def factory():
            return store.open_client(opts.db_path, opts.tenant)
        try:
            rep.pull = pull(owner=owner, tenant=opts.tenant, db_path=opts.db_path, client_factory=factory,
                            anchor=anchor, discard_local=opts.discard_local, full=opts.full, log=log)
        except Fork as e:
            raise JoinError("restore", f"{e} (or run kint join again with --discard-local)", 4) from e
        except NotFresh as e:
            raise JoinError("restore", str(e), 6) from e
        except PullError as e:
            raise JoinError("restore", str(e), 5) from e
        except keys.KeyError_ as e:
            raise JoinError("restore", str(e), 3) from e
        rep.restored = rep.pull.applied > 0
        log(f"restore: {rep.pull.message}")
        for s in rep.pull.skipped:
            log(f"  SKIPPED epoch {s.get('seq')} block {s.get('block')}: {s.get('reason')}"
                + (f" (snapshot epoch {s['superseded_by']} carries the whole state, the pull carried on)"
                   if s.get("superseded_by") else ""))
        for u in rep.pull.unopenable:
            log(f"  CLOSED epoch {u.get('seq')} block {u.get('block')}: {u.get('reason')}")
    rep.steps.append("restore")

    # ---- 5. harnesses: every one on this machine reads Sibyl Memory through kint-server ----
    if opts.setup_targets:
        env = {"KINT_TENANT": opts.tenant, **opts.extra_env}   # pin the tenant the vault was joined under
        try:
            binpath = setup.server_bin()
        except setup.SetupError as e:
            log(f"harnesses: skipped, {e}")
        else:
            rep.setup = setup.register(opts.setup_targets, env, binpath)
            for _t, _st, lines in rep.setup:
                for line in lines:
                    log(line)
    else:
        log("harnesses: not registered (--no-setup)")
    rep.steps.append("harnesses")

    # ---- 6. report: where this machine stands and the one thing left before it can write ----
    info = session_key_info(anchor, owner)
    bal = info.get("balance_wei")
    auth = info.get("authorized")
    rep.writes_on = bool(auth) and bal is not None and bal >= MIN_SESSION_BALANCE_WEI
    if rep.writes_on:
        exp = info.get("expiry") or 0
        log(f"writes: on, session key authorized until {time.strftime('%Y-%m-%d', time.gmtime(exp))} "
            f"with {bal / 1e18:.6f} ETH")
    else:
        need = []
        if bal is None or bal < MIN_SESSION_BALANCE_WEI:
            need.append(f"put a few cents of ETH on {rep.session_key} (Base)")
        if not auth:
            need.append("kint authorize page" if r.account_kind == keys.ACCOUNT_KIND_SMART_ACCOUNT
                        else "kint authorize direct (KINT_OWNER_KEY) or kint authorize payload then submit")
        log("writes: off until the session key is funded and authorized by the owner; reads work now")
        log("next: " + ", then ".join(need))
    rep.steps.append("report")
    return rep
