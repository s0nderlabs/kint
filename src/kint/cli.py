"""kint: the thin CLI over the same functions the MCP server exposes.

Only the commands that need a shell: the connect pipe (a signature on stdin),
the key rotation (same pipe, same secrecy rules), the session key,
push/pull/compact/verify/status/doctor for SDK-direct harnesses such as Hermes,
and `kint setup` to point Claude Code, Codex, Hermes and OpenClaw at
kint-server instead of sibyl-memory-mcp.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

from . import crypto, keys, paths, setup, store
from .chain import Anchor, authorization_typed_data, redact, sign_authorization
from .connect import (ConnectError, connect_eoa, connect_recovery, connect_smart_account, doctor,
                      read_secret, rekey, session_key_info)
from .epoch import Mirror
from .join import JoinError, JoinOptions, tenant_source
from .join import run as join_run
from .push import ChainMoved, KeyExpired, PushError, push, unanchored_changes
from .pull import Fork, NotFresh, PullError, pull
from .verify import at_block, history, verify


def _err(msg: str, code: int = 2) -> None:
    sys.stdout.flush()   # keep the error after the progress lines when stdout is a pipe
    print(f"kint: {msg}", file=sys.stderr)
    sys.exit(code)


def _tenant(args) -> str:
    return args.tenant or store.resolve_tenant()


def _db(args) -> Path:
    return Path(args.db).expanduser() if args.db else paths.sibyl_db_path()


def _owner(args, tenant: str) -> str:
    if getattr(args, "owner", None):
        return args.owner
    e = keys.Enrolment.load(crypto.space_id(tenant).hex())
    if e:
        return e.owner
    _err("no owner known on this machine: pass --owner 0x... or run kint connect")


def _fmt_bytes(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.2f} MB"


# ---------------------------------------------------------------------------

def cmd_canonical_payload(args):
    sys.stdout.write(crypto.canonical_payload_json(args.owner))


def cmd_connect(args):
    tenant = _tenant(args)
    if not args.owner:
        _err("--owner 0x... is required")
    try:
        if args.recovery_code_stdin:
            code = read_secret("-", "recovery code")
            r = connect_recovery(args.owner, tenant, code)
        elif args.smart_account:
            pw = getpass.getpass("vault passphrase: ") if not args.passphrase_stdin else read_secret("-", "passphrase")
            r = connect_smart_account(args.owner, tenant, pw)
        else:
            src = args.signature or args.signature_file
            if not src:
                _err("give the derive signature with --signature - (stdin) or --signature-file PATH; never on argv")
            if args.passphrase_stdin and args.signature == "-":
                _err("--passphrase-stdin and --signature - cannot share stdin: use --passphrase-prompt, or --signature-file")
            sig = crypto.hex_signature(read_secret(src, "signature"))
            pw = None
            if args.passphrase_stdin:
                pw = read_secret("-", "passphrase")
            elif args.passphrase_prompt:
                pw = getpass.getpass("vault passphrase (salts the wallet key): ")
            add = getpass.getpass("extra passphrase wrap (empty to skip): ") if args.add_passphrase else None
            r = connect_eoa(args.owner, tenant, sig, passphrase=pw, add_passphrase=add or None)
    except (ConnectError, crypto.KintCryptoError) as e:
        _err(str(e))
    print(f"connected: owner {r.owner}")
    print(f"space {r.space[:16]}  key tag {r.kek_tag8}  data key from {r.dek_source}")
    if r.fresh_vault:
        print(f"fresh vault: recovery code written to {paths.recovery_path(r.space)}")
        print("copy that code somewhere that is not this machine; push refuses until the file exists")
    sk = keys.session_key_address()
    print(f"session key: {sk or 'none yet (kint session-key create)'}")


def cmd_session_key(args):
    if args.action == "create":
        if keys.session_key_exists():
            print(f"exists: {keys.session_key_address()}")
            return
        print(f"created: {keys.create_session_key()}")
        print("fund it with a little ETH on Base and authorize it from the owner (kint authorize ...)")
    elif args.action == "rotate":
        print(f"rotated: {keys.rotate_session_key()}")
    else:
        tenant = _tenant(args)
        owner = None
        e = keys.Enrolment.load(crypto.space_id(tenant).hex())
        owner = args.owner or (e.owner if e else None)
        a = None
        try:
            a = Anchor()
        except Exception:
            pass
        print(json.dumps(session_key_info(a, owner), indent=1))


def cmd_authorize(args):
    tenant = _tenant(args)
    owner = _owner(args, tenant)
    a = Anchor()
    key = keys.session_key_address()
    if not key:
        _err("no session key on this machine: kint session-key create")
    expiry = int(time.time()) + int(args.days) * 86400
    if args.action == "payload":
        nonce = a.auth_nonce(owner)
        deadline = int(time.time()) + 300
        td = authorization_typed_data(a.address, owner, key, expiry, nonce, deadline)
        sys.stdout.write(json.dumps(td, separators=(",", ":")) + "\n")
        print(f"# nonce {nonce}, deadline {deadline}, expiry {expiry}; sign with: cast wallet sign --data --from-file <this file>",
              file=sys.stderr)
        print(f"# then: kint authorize submit --deadline {deadline} --expiry {expiry} --signature -", file=sys.stderr)
    elif args.action == "burn-nonce":
        # consume the owner's authorization nonce on chain (cancels any signed, unsubmitted authorization);
        # the same effect as setSessionKey/revokeSessionKey from the owner, exposed for completeness
        from eth_account import Account
        pk = os.environ.get("KINT_OWNER_KEY")
        if not pk:
            _err("kint authorize burn-nonce reads the owner key from KINT_OWNER_KEY (env), never argv")
        acct = Account.from_key(pk)
        if acct.address.lower() != owner.lower():
            _err(f"KINT_OWNER_KEY is {acct.address}, not the owner {owner}")
        tx = a.set_session_key(acct, key, a.session_key_expiry(owner, key))
        a.wait(tx)
        print(f"nonce consumed: authNonce({owner}) is now {a.auth_nonce(owner)}")
    elif args.action == "submit":
        sig = crypto.hex_signature(read_secret(args.signature or "-", "signature"))
        sess = keys.load_session_account()
        tx = a.set_session_key_by_sig(sess, owner, key, int(args.expiry), int(args.deadline), sig)
        print(f"submitted {tx}")
        cost = a.wait(tx)
        print(f"authorized {key} under {owner} until {time.strftime('%Y-%m-%d', time.gmtime(int(args.expiry)))}; "
              f"cost {cost['totalWei'] / 1e18:.8f} ETH, block {cost['blockNumber']}")
    elif args.action == "page":
        from .page import serve_authorize_page
        print(f"open this page in the browser where your Base Account is logged in (owner {owner}):", flush=True)
        res = serve_authorize_page(owner, key, expiry, a.address, on_url=lambda u: print(f"  {u}", flush=True))
        if not res:
            _err("no result from the page (timeout)")
        if not res.get("ok"):
            _err(f"page reported failure: {res.get('error')}")
        print(f"page reported {res.get('result')}; polling the chain for canWrite({owner}, {key})")
        for _ in range(120):
            if a.can_write(owner, key):
                print(f"authorized: {key} may push under {owner} until {time.strftime('%Y-%m-%d', time.gmtime(expiry))}")
                return
            time.sleep(3)
        _err("the chain does not show the authorization yet; check the transaction and run `kint session-key show`")
    elif args.action == "direct":
        from eth_account import Account
        pk = os.environ.get("KINT_OWNER_KEY")
        if not pk:
            _err("kint authorize direct reads the owner key from KINT_OWNER_KEY (env), never argv")
        acct = Account.from_key(pk)
        if acct.address.lower() != owner.lower():
            _err(f"KINT_OWNER_KEY is {acct.address}, not the owner {owner}")
        tx = a.set_session_key(acct, key, expiry)
        print(f"submitted {tx}")
        cost = a.wait(tx)
        print(f"authorized {key} under {owner}; cost {cost['totalWei'] / 1e18:.8f} ETH, block {cost['blockNumber']}")


def cmd_push(args):
    tenant = _tenant(args)
    owner = _owner(args, tenant)
    try:
        rep = push(owner=owner, tenant=tenant, db_path=_db(args), dry_run=args.dry_run, confirmations=args.confirmations)
    except KeyExpired as e:
        _err(str(e), 3)
    except ChainMoved as e:
        _err(str(e), 4)
    except PushError as e:
        _err(str(e), 5)
    except keys.KeyError_ as e:
        _err(str(e), 3)
    print(rep.message)
    for e in rep.epochs:
        print(f"  epoch {e['seq']}: tx {e['tx']} block {e['block']} bucket {e['bucket']} B rows {e['rows']} "
              f"del {e['deleted']} cost {e['cost_wei'] / 1e18:.8f} ETH")


def cmd_compact(args):
    """One snapshot epoch carrying the whole state, so a cold start stops there."""
    tenant = _tenant(args)
    owner = _owner(args, tenant)
    try:
        rep = push(owner=owner, tenant=tenant, db_path=_db(args), dry_run=args.dry_run,
                   confirmations=args.confirmations, snapshot=True,
                   override_skipped=getattr(args, "over_skipped", False))
    except KeyExpired as e:
        _err(str(e), 3)
    except ChainMoved as e:
        _err(str(e), 4)
    except PushError as e:
        _err(str(e), 5)
    except keys.KeyError_ as e:
        _err(str(e), 3)
    print(rep.message)
    for e in rep.epochs:
        print(f"  epoch {e['seq']}: tx {e['tx']} block {e['block']} bucket {e['bucket']} B rows {e['rows']} "
              f"del {e['deleted']} cost {e['cost_wei'] / 1e18:.8f} ETH")


def cmd_rekey(args):
    tenant = _tenant(args)
    owner = _owner(args, tenant)
    sig = pw = sa = add = None
    src = args.signature or args.signature_file
    if not src and not args.smart_account:
        _err("give the key(s) that open the vault: --signature - (stdin) or --signature-file PATH, and/or "
             "--smart-account; never on argv")
    if args.passphrase_stdin and args.signature == "-":
        _err("--passphrase-stdin and --signature - cannot share stdin: use --passphrase-prompt, or --signature-file")
    try:
        if src:
            sig = crypto.hex_signature(read_secret(src, "signature"))
            if args.passphrase_stdin:
                pw = read_secret("-", "passphrase")
            elif args.passphrase_prompt:
                pw = getpass.getpass("vault passphrase (salts the wallet key): ")
        if args.smart_account:
            # --passphrase-stdin feeds one secret: the salt when a signature is given, else this one
            sa = read_secret("-", "passphrase") if (args.passphrase_stdin and not src) else getpass.getpass("vault passphrase: ")
        if args.add_passphrase:
            add = getpass.getpass("extra passphrase wrap (empty to skip): ") or None
        r = rekey(owner, tenant, signature=sig, passphrase=pw, smart_account_passphrase=sa,
                  extra_passphrase=add, drop_missing=args.drop_missing, over_skipped=args.over_skipped,
                  db_path=_db(args), confirmations=args.confirmations)
    except (ConnectError, crypto.KintCryptoError) as e:
        _err(str(e))
    except KeyExpired as e:
        _err(str(e), 3)
    except ChainMoved as e:
        _err(str(e), 4)
    except PushError as e:
        _err(str(e), 5)
    except keys.KeyError_ as e:
        _err(str(e), 3)
    print(f"rekeyed: data key {r.old_dek_id} -> {r.new_dek_id}")
    print(f"snapshot epoch {r.seq} anchored, tx {r.tx}")
    print(f"{r.wraps_carried} key(s) carried over"
          + (f"; dropped {', '.join(r.dropped_kinds)}" if r.dropped_kinds else ""))
    print(f"new recovery code written to {paths.recovery_path(crypto.space_id(tenant).hex())}")
    print("the old recovery code no longer opens this vault; copy the new one somewhere that is not this machine")


def cmd_pull(args):
    tenant = _tenant(args)
    owner = _owner(args, tenant)
    db = _db(args)

    def factory():
        return store.open_client(db, tenant)

    try:
        rep = pull(owner=owner, tenant=tenant, db_path=db, client_factory=factory,
                   discard_local=args.discard_local, force_scan=args.force_scan, full=args.full)
    except Fork as e:
        _err(str(e), 4)
    except NotFresh as e:
        _err(str(e), 6)
    except PullError as e:
        _err(str(e), 5)
    except keys.KeyError_ as e:
        _err(str(e), 3)
    print(rep.message)
    if rep.rpcs_agreed is not None:
        print(f"cold start: two RPCs agreed on the head: {rep.rpcs_agreed}")
    for s in rep.skipped:
        print(f"  SKIPPED epoch {s.get('seq')} block {s.get('block')}: {s.get('reason')}"
              + (f" (snapshot epoch {s['superseded_by']} carries the whole state, the pull carried on)"
                 if s.get("superseded_by") else ""))
    for u in rep.unopenable:
        print(f"  CLOSED epoch {u.get('seq')} block {u.get('block')}: {u.get('reason')}")
    if rep.backfilled:
        print(f"  {rep.backfilled} older epoch(s) cached for history")


def _chain_head(tenant: str) -> dict | None:
    """The chain head for this space, best effort: a verify against a mirror the chain has moved
    past is a verify against a stale picture. Never a verdict, never fatal."""
    if os.environ.get("KINT_OFFLINE") == "1":
        return None
    e = keys.Enrolment.load(crypto.space_id(tenant).hex())
    if not e:
        return None
    try:
        h = Anchor().head(e.owner, crypto.space_id(tenant))
        return {"seq": h.seq, "digest": h.digest.hex(), "block": h.block_number}
    except Exception as ex:  # noqa: BLE001
        print(f"kint: chain head unavailable ({redact(str(ex))}); verifying against the local mirror only",
              file=sys.stderr)
        return None


def cmd_verify(args):
    tenant = _tenant(args)
    db = _db(args)
    client = store.open_client(db, tenant)
    res = verify(client, query=args.query, limit=args.limit, space_hex=crypto.space_id(tenant).hex(), db_path=db,
                 tenant=tenant, write_refusal=not args.no_write, chain_head=_chain_head(tenant))
    if args.json:
        print(json.dumps(res.to_dict(), indent=1))
        return
    print(f"query: {res.query}")
    print(f"sibyl verdict: {res.verdict.get('code')}  hits: {len(res.hits)}")
    for c in res.checks:
        print(f"  {c.status:10s} {c.tier} {(c.category + '/') if c.category else ''}{c.key}: {c.reason}")
    print(f"DECISION: {res.decision.upper()}: {res.reason}")
    if res.refusal_entity:
        print(f"refusal written back as Sibyl entity {res.refusal_entity}")
    sys.exit(0 if res.decision == "proceed" else 1)


def cmd_history(args):
    tenant = _tenant(args)
    sh = crypto.space_id(tenant).hex()
    if args.block is not None:
        print(json.dumps(at_block(sh, args.tier, args.key, args.category, args.block), indent=1))
    else:
        for v in history(sh, args.tier, args.key, args.category):
            if v.get("deleted"):
                print(f"epoch {v['seq']} block <= {v['block']}: DELETED")
            else:
                print(f"epoch {v['seq']} block <= {v['block']} leaf {v['leaf'][:16]}: {v['body']}")


def cmd_status(args):
    tenant = _tenant(args)
    db = _db(args)
    sh = crypto.space_id(tenant).hex()
    e = keys.Enrolment.load(sh)
    print(f"tenant {tenant}  space {sh[:16]}  store {db}")
    print(f"owner {e.owner if e else 'not connected'}  data key {'cached' if keys.cached_dek(sh) else 'absent'}")
    m = Mirror.load(sh)
    print(f"last anchored on this machine: seq {m.seq if m else 0} block {m.block if m else 0} rows {len(m.rows) if m else 0}")
    try:
        c, d = unanchored_changes(tenant, db)
        print(f"unanchored: {c} changed, {d} deleted")
    except Exception as ex:  # noqa: BLE001
        print(f"unanchored: ? ({redact(str(ex))})")
    if e:
        try:
            a = Anchor()
            h = a.head(e.owner, crypto.space_id(tenant))
            same = m is not None and (m.seq, m.digest) == (h.seq, h.digest.hex())
            print(f"chain head: seq {h.seq} digest {h.digest.hex()[:16]} block {h.block_number} "
                  f"({'in step' if same else 'NOT in step: pull or push'})  contract {a.address}")
            sk = session_key_info(a, e.owner)
            if sk["exists"]:
                print(f"session key {sk['address']} balance {sk.get('balance_eth', '?')} ETH authorized {sk.get('authorized')}")
        except Exception as ex:  # noqa: BLE001
            print(f"chain: unavailable ({redact(str(ex))})")
    n = store.cap_numbers(db)
    print("cap accounting (the same 5 MiB free cap Sibyl enforces):")
    print(f"  sibyl stores      {_fmt_bytes(n['sibyl_bytes'])}")
    print(f"  kint state        {_fmt_bytes(n['kint_bytes'])}   (mirror, epoch cache, keys; volunteered)")
    print(f"  enforced total    {_fmt_bytes(n['volunteered_total'])} of {_fmt_bytes(n['cap_bytes'])}")


def cmd_recovery_code(args):
    from .connect import write_recovery_file
    try:
        p = write_recovery_file(_tenant(args))
    except ConnectError as e:
        _err(str(e))
    print(f"written to {p} (mode 0600); copy it somewhere that is not this machine")


def cmd_doctor(args):
    tenant = _tenant(args)
    rows = doctor(args.owner, tenant, _db(args))
    bad = 0
    for name, st, detail in rows:
        mark = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}[st]
        bad += st == "fail"
        print(f"[{mark}] {name:20s} {detail}")
    sys.exit(1 if bad else 0)


def cmd_export(args):
    from .export import export_rows
    tenant = _tenant(args)
    for r in export_rows(_db(args), tenant):
        print(json.dumps(r.to_wire(), ensure_ascii=False))


def cmd_setup(args):
    try:
        binpath = setup.server_bin()
    except setup.SetupError as e:
        _err(str(e))
    extra_env = dict(kv.split("=", 1) for kv in (args.env or []))
    for _t, _st, lines in setup.register(setup.expand_targets(args.target), extra_env, binpath):
        for line in lines:
            print(line)


def cmd_join(args):
    """One command for the read half: session key, connect, restore, harnesses. No chain writes."""
    tenant, source = tenant_source(args.tenant_sub or args.tenant)
    if not args.owner:
        _err("--owner 0x... is required")
    chosen = [f for f, v in (("--base-account", args.base_account), ("--signature", args.signature),
                             ("--signature-file", args.signature_file), ("--recovery-code-stdin", args.recovery_code_stdin)) if v]
    if len(chosen) != 1:
        _err("choose exactly one of --base-account, --signature -, --signature-file PATH, --recovery-code-stdin")
    eoa_pw = None
    try:
        if args.base_account:
            method = "passphrase"
            secret = read_secret("-", "passphrase") if args.passphrase_stdin else getpass.getpass("vault passphrase: ")
        elif args.recovery_code_stdin:
            method = "recovery"
            secret = read_secret("-", "recovery code")
        else:
            method = "signature"
            src = args.signature or args.signature_file
            if args.passphrase_stdin and args.signature == "-":
                _err("--passphrase-stdin and --signature - cannot share stdin: use --passphrase-prompt, or --signature-file")
            secret = read_secret(src, "signature")
            if args.passphrase_stdin:
                eoa_pw = read_secret("-", "passphrase")
            elif args.passphrase_prompt:
                eoa_pw = getpass.getpass("vault passphrase (salts the wallet key): ")
    except ConnectError as e:
        _err(str(e))
    if not secret:
        _err("empty secret")
    db = Path(args.db_sub).expanduser() if args.db_sub else _db(args)
    targets = [] if args.no_setup else setup.expand_targets(args.setup)
    opts = JoinOptions(owner=args.owner, tenant=tenant, tenant_source=source, db_path=db, method=method,
                       secret=secret, eoa_passphrase=eoa_pw, new_vault=args.new_vault,
                       discard_local=args.discard_local, full=args.full, setup_targets=targets,
                       extra_env=dict(kv.split("=", 1) for kv in (args.env or [])))
    try:
        join_run(opts)
    except JoinError as e:
        _err(f"join stopped at {e.step}: {e}", e.code)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="kint", description="Sibyl Memory that outlives the laptop.")
    p.add_argument("--tenant", help="Sibyl tenant id (default: credentials.json or Sibyl's default)")
    p.add_argument("--db", help="Sibyl store path (default: $SIBYL_MEMORY_DB or ~/.sibyl-memory/memory.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("canonical-payload", help="print the frozen EIP-712 payload for cast wallet sign --data --from-file")
    s.add_argument("--owner", required=True)
    s.set_defaults(fn=cmd_canonical_payload)

    s = sub.add_parser("connect", help="connect this machine to the vault (signature on stdin, passphrase, or recovery code)")
    s.add_argument("--owner")
    s.add_argument("--signature", help="'-' reads the 65-byte hex signature from stdin")
    s.add_argument("--signature-file", help="file read then unlinked")
    s.add_argument("--smart-account", action="store_true", help="owner is a smart account (Base Account): key from a passphrase")
    s.add_argument("--passphrase-stdin", action="store_true")
    s.add_argument("--passphrase-prompt", action="store_true", help="EOA mode: salt the wallet key with a passphrase (2FA)")
    s.add_argument("--add-passphrase", action="store_true", help="EOA mode: also add a passphrase wrap for the data key")
    s.add_argument("--recovery-code-stdin", action="store_true")
    s.set_defaults(fn=cmd_connect)

    s = sub.add_parser("session-key", help="create | show | rotate this machine's session key")
    s.add_argument("action", choices=["create", "show", "rotate"])
    s.add_argument("--owner")
    s.set_defaults(fn=cmd_session_key)

    s = sub.add_parser("authorize", help="authorize this machine's session key under the owner")
    s.add_argument("action", choices=["payload", "submit", "direct", "page", "burn-nonce"])
    s.add_argument("--owner")
    s.add_argument("--days", default="30")
    s.add_argument("--signature", help="submit: '-' for stdin")
    s.add_argument("--expiry")
    s.add_argument("--deadline")
    s.set_defaults(fn=cmd_authorize)

    s = sub.add_parser("push", help="anchor unanchored changes on Base")
    s.add_argument("--owner")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--confirmations", type=int, default=2)
    s.set_defaults(fn=cmd_push)

    s = sub.add_parser("compact", help="anchor ONE snapshot epoch with the whole state (a cold start stops there)")
    s.add_argument("--owner")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--over-skipped", action="store_true",
                   help="anchor the snapshot on the chain head even though the last pull stopped at an epoch this "
                        "machine could not apply (the owner's recovery path past an epoch that will never open)")
    s.add_argument("--confirmations", type=int, default=2)
    s.set_defaults(fn=cmd_compact)

    s = sub.add_parser("rekey", help="rotate the data key: new key, new wraps, one snapshot epoch, a new recovery code")
    s.add_argument("--owner")
    s.add_argument("--signature", help="'-' reads the 65-byte hex signature from stdin")
    s.add_argument("--signature-file", help="file read then unlinked")
    s.add_argument("--smart-account", action="store_true",
                   help="carry over the vault passphrase wrap (prompted); combine with --signature to carry both")
    s.add_argument("--passphrase-stdin", action="store_true",
                   help="read ONE passphrase from stdin: the salt when a signature is given, else the vault passphrase")
    s.add_argument("--passphrase-prompt", action="store_true", help="EOA mode: the passphrase that salts the wallet key")
    s.add_argument("--add-passphrase", action="store_true", help="also carry over the extra passphrase wrap")
    s.add_argument("--drop-missing", action="store_true",
                   help="rotate even though a key that opens the vault today was not supplied (it stops opening new epochs)")
    s.add_argument("--over-skipped", action="store_true",
                   help="rotate even though the last pull stopped at an epoch this machine could not apply: the new "
                        "snapshot chains on the chain head")
    s.add_argument("--confirmations", type=int, default=2)
    s.set_defaults(fn=cmd_rekey)

    s = sub.add_parser("pull", help="restore or refresh the store from Base")
    s.add_argument("--owner")
    s.add_argument("--discard-local", action="store_true", help="move the local store aside and restore from the chain")
    s.add_argument("--force-scan", action="store_true")
    s.add_argument("--full", action="store_true",
                   help="walk past snapshot epochs to the first epoch (the whole history, not just the current state)")
    s.set_defaults(fn=cmd_pull)

    s = sub.add_parser("verify", help="search through Sibyl, verify the hits against Base, decide")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-write", action="store_true", help="do not write a refusal entity")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("history", help="every anchored version of a row (block-height bound)")
    s.add_argument("tier", choices=["entity", "state", "reference"])
    s.add_argument("key")
    s.add_argument("--category")
    s.add_argument("--block", type=int)
    s.set_defaults(fn=cmd_history)

    s = sub.add_parser("status", help="head, mirror, unanchored changes, cap accounting")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("recovery-code", help="write the recovery code file from the cached data key")
    s.set_defaults(fn=cmd_recovery_code)

    s = sub.add_parser("doctor", help="check every moving part")
    s.add_argument("--owner")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("export", help="dump the four tiers as JSON lines (debug)")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("setup", help="point a harness at kint-server")
    s.add_argument("target", choices=["all", "claude", "codex", "hermes", "openclaw"])
    s.add_argument("--env", action="append", help="KEY=VALUE for the server process (repeatable), e.g. KINT_TENANT=kint-demo")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("join", help="one command for the read half: session key, connect, restore, harnesses; writes nothing to the chain")
    s.add_argument("--owner", help="the wallet that owns the memory")
    s.add_argument("--tenant", dest="tenant_sub", help="Sibyl tenant id (same as the global --tenant)")
    s.add_argument("--db", dest="db_sub", help="Sibyl store path (same as the global --db)")
    s.add_argument("--base-account", action="store_true", help="owner is a Base Account: the vault passphrase is the key (prompted)")
    s.add_argument("--passphrase-stdin", action="store_true", help="read the passphrase from stdin instead of prompting")
    s.add_argument("--passphrase-prompt", action="store_true", help="EOA mode: the passphrase that salts the wallet key")
    s.add_argument("--signature", help="EOA owners: '-' reads the 65-byte hex derive signature from stdin")
    s.add_argument("--signature-file", help="EOA owners: file holding the signature, read then unlinked")
    s.add_argument("--recovery-code-stdin", action="store_true", help="either owner: the recovery code on stdin")
    s.add_argument("--new-vault", action="store_true", help="allowed to start a vault when the chain holds no epochs for this owner and tenant")
    s.add_argument("--discard-local", action="store_true", help="move a local store aside and restore from the chain")
    s.add_argument("--full", action="store_true", help="walk past snapshot epochs for the older versions")
    s.add_argument("--setup", default="all", choices=["all", "claude", "codex", "hermes", "openclaw"], help="which harnesses to register (default all)")
    s.add_argument("--no-setup", action="store_true", help="register no harness")
    s.add_argument("--env", action="append", help="KEY=VALUE for the server process (repeatable); KINT_TENANT is always set")
    s.set_defaults(fn=cmd_join)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
