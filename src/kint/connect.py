"""The wallet layer: connect this machine to a vault, session keys, doctor.

Three connect modes:
  EOA (the human's own wallet, Ledger, MetaMask, Rabby, a foundry keystore):
      kint canonical-payload --owner 0x... > kint-canonical.json
      cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0x... --signature -
    The signature arrives on stdin or from a file that is read then unlinked,
    never on argv. kint prints only the owner and the first 8 hex of the
    kek_tag, never the signature, the KEK or the DEK.
  Smart account (a Base Account / Coinbase Smart Wallet owns the vault):
      kint connect --owner 0xBaseAccount --smart-account --passphrase-stdin
    No derive signature exists for a passkey-owned account; the vault key
    comes from a passphrase (kind 0x02) stretched with scrypt.
  Recovery code (the second independent path to the data key):
      kint connect --owner 0x... --recovery-code-stdin

On a fresh vault the DEK is generated here, wrapped, and the recovery code is
written to ~/.kint/RECOVERY-<space>.txt; push refuses until that file exists.
On a machine that restores an existing vault, the DEK is unwrapped from the
head epoch's own header on the chain.

`rekey` rotates the data key itself: a new DEK, new wraps under the same keys
(every one of them has to be supplied, a wrap needs its KEK), one snapshot
epoch sealed under the new key, and a new recovery code. It is a CLI command,
never an MCP tool: the secrets that open a vault do not travel through a chat.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_utils import to_checksum_address

from . import crypto, keys, paths
from .chain import Anchor, ChainError, redact
from .epoch import Mirror, head_lock
from .push import _push_locked, load_wraps, save_wraps


class ConnectError(Exception):
    pass


class ChainUnreadable(ConnectError):
    """The chain could not be read (RPC down, rate limited, pruned). Never a security verdict."""


def _write_recovery(owner: str, space_hex: str, dek: bytes) -> Path:
    """The one place the recovery file is written (fresh vault, `kint recovery-code`, rekey)."""
    p = paths.recovery_path(space_hex)
    paths.write_private(p, (f"kint recovery code for owner {owner}, space {space_hex}\n"
                            f"Keep this somewhere that is not this machine. It opens the vault without the wallet.\n\n"
                            f"{crypto.recovery_code(dek)}\n").encode())
    return p


def read_secret(source: str, what: str = "signature") -> str:
    """'-' reads stdin; a path is read then unlinked. Never argv."""
    if source == "-":
        data = sys.stdin.read()
    else:
        p = Path(source).expanduser()
        if not p.exists():
            raise ConnectError(f"{what} file {p} does not exist")
        data = p.read_text()
        try:
            p.unlink()
        except OSError:
            pass
    data = data.strip()
    if not data:
        raise ConnectError(f"empty {what}")
    return data


@dataclass
class ConnectResult:
    owner: str
    space: str
    kek_tag8: str
    fresh_vault: bool
    recovery_code: str | None
    dek_source: str
    account_kind: int


def _chain_head_header(owner: str, space: bytes, anchor: Anchor | None) -> crypto.Header | None:
    """The head epoch's header, when the chain already has epochs for this owner and space."""
    try:
        anchor = anchor or Anchor()
        head = anchor.head(owner, space)
    except Exception as e:  # noqa: BLE001
        raise ChainUnreadable(f"cannot read the chain head: {e}") from e
    if head.seq == 0:
        return None
    try:
        evs = [e for e in anchor.epoch_at_block(owner, space, head.block_number) if e.seq == head.seq]
        if not evs:
            raise ChainUnreadable("the head says there are epochs but none was found at its block")
        _, _, _, blob = anchor.epoch_ciphertext(evs[0].tx_hash)
    except ChainUnreadable:
        raise
    except Exception as e:  # noqa: BLE001
        raise ChainUnreadable(f"cannot read the head epoch: {e}") from e
    if crypto.keccak(blob) != evs[0].digest:
        raise ConnectError("head ciphertext digest does not match the Epoch event")
    return crypto.peek_header(blob)


def _finish(owner: str, tenant: str, space: bytes, kek: bytes | None, tag: bytes | None, kind: int,
            account_kind: int, dek: bytes | None, wraps: list[crypto.Wrap], fresh: bool, dek_source: str,
            extra_passphrase: str | None, anchor: Anchor | None) -> ConnectResult:
    space_hex = space.hex()
    recovery = None
    if dek is None:
        raise ConnectError("no data key could be obtained")
    if fresh:
        recovery = crypto.recovery_code(dek)
        _write_recovery(owner, space_hex, dek)
    if extra_passphrase and kind != crypto.KEK_KIND_PASSPHRASE:
        pk, _ = crypto.derive_kek_from_passphrase(extra_passphrase, owner, space)
        if crypto.find_wrap(wraps, pk) is None:
            wraps.append(crypto.wrap_dek(dek, pk, crypto.KEK_KIND_PASSPHRASE))
    save_wraps(space_hex, wraps)
    keys.cache_dek(space_hex, dek)
    enrol = keys.Enrolment(
        owner=owner, tenant_id=tenant, space=space_hex, account_kind=account_kind, signer=owner,
        chain_id=crypto.CHAIN_ID, kek_tags=[w.tag.hex() for w in wraps], wrap_kinds=[w.kind for w in wraps],
        created_at=time.time(), contract=(anchor.address if anchor else None), created_here=fresh,
    )
    enrol.save()
    if Mirror.load(space_hex) is None:
        Mirror.empty(space_hex, tenant).save()
    return ConnectResult(owner=owner, space=space_hex, kek_tag8=(tag.hex()[:8] if tag else "none"),
                         fresh_vault=fresh, recovery_code=recovery, dek_source=dek_source, account_kind=account_kind)


def _dek_for(owner: str, space: bytes, kek: bytes, kind: int, anchor: Anchor | None, allow_fresh: bool):
    """Find the DEK: local wraps, then the chain head header, else a fresh vault.

    The local wraps only win while they hold the CURRENT data key: after a `kint rekey` on another
    machine they hold a stale one, which opens nothing sealed after the rotation. When the chain
    can be read, the head epoch's own header decides. When it cannot, the local key is the best
    this machine has and connect stays offline-usable.
    """
    space_hex = space.hex()
    local = load_wraps(space_hex)
    w = crypto.find_wrap(local, kek) if local else None
    header = None
    if os.environ.get("KINT_OFFLINE") != "1":
        try:
            header = _chain_head_header(owner, space, anchor)
        except ChainUnreadable:
            if w is None:
                raise
            header = None   # cannot ask the chain; fall back to the key this machine already has
    local_dek = crypto.unwrap_dek(w, kek) if w is not None else None
    if local_dek is not None and (header is None or crypto.dek_id(local_dek) == header.dek_id):
        return local_dek, local, False, "local wraps"
    if w is not None and header is not None and crypto.find_wrap(header.wraps, kek) is None:
        raise ConnectError(
            f"the data key of this vault was rotated and this key (tag {crypto.kek_tag(kek).hex()[:8]}) was not "
            "carried over: it opens the epochs sealed before the rotation and nothing after it. Connect with a key "
            "that was carried over, or with the recovery code written by that rotation.")
    if header is not None:
        w = crypto.find_wrap(header.wraps, kek)
        if w is None:
            raise ConnectError(
                f"this key (tag {crypto.kek_tag(kek).hex()[:8]}) does not open the vault anchored under {owner}: "
                "the wraps in the head epoch carry different tags. Wrong wallet, wrong passphrase, or wrong tenant. "
                "The recovery code still opens it: kint connect --recovery-code-stdin")
        return crypto.unwrap_dek(w, kek), list(header.wraps), False, "chain head header"
    if local:
        raise ConnectError("local wraps exist but none matches this key, and the chain has no epochs yet")
    if not allow_fresh:
        raise ConnectError("no vault found for this owner and space")
    dek = crypto.new_dek()
    return dek, [crypto.wrap_dek(dek, kek, kind)], True, "fresh vault"


def connect_eoa(owner: str, tenant: str, signature: bytes, *, passphrase: str | None = None,
                add_passphrase: str | None = None, anchor: Anchor | None = None) -> ConnectResult:
    owner = to_checksum_address(owner)
    space = crypto.space_id(tenant)
    kek, tag = crypto.derive_kek_from_signature(signature, owner, space, passphrase=passphrase)
    dek, wraps, fresh, src = _dek_for(owner, space, kek, crypto.KEK_KIND_SIGNATURE, anchor, allow_fresh=True)
    return _finish(owner, tenant, space, kek, tag, crypto.KEK_KIND_SIGNATURE, keys.ACCOUNT_KIND_EOA,
                   dek, wraps, fresh, src, add_passphrase, anchor)


def connect_smart_account(owner: str, tenant: str, passphrase: str, *, anchor: Anchor | None = None) -> ConnectResult:
    owner = to_checksum_address(owner)
    space = crypto.space_id(tenant)
    kek, tag = crypto.derive_kek_from_passphrase(passphrase, owner, space)
    dek, wraps, fresh, src = _dek_for(owner, space, kek, crypto.KEK_KIND_PASSPHRASE, anchor, allow_fresh=True)
    return _finish(owner, tenant, space, kek, tag, crypto.KEK_KIND_PASSPHRASE, keys.ACCOUNT_KIND_SMART_ACCOUNT,
                   dek, wraps, fresh, src, None, anchor)


def connect_recovery(owner: str, tenant: str, code: str, *, anchor: Anchor | None = None,
                     account_kind: int = keys.ACCOUNT_KIND_EOA) -> ConnectResult:
    owner = to_checksum_address(owner)
    space = crypto.space_id(tenant)
    dek = crypto.decode_recovery_code(code)
    space_hex = space.hex()
    wraps = load_wraps(space_hex)
    want = crypto.dek_id(dek)
    # The code's own checksum only proves it was typed correctly. Bind it to THIS vault before
    # caching it: the chain head header, else a cached epoch header, else the cached data key.
    header = None
    if os.environ.get("KINT_OFFLINE") != "1":
        try:
            header = _chain_head_header(owner, space, anchor)
        except ChainUnreadable:
            header = None   # the offline checks below still bind the code to this vault
    if header is not None:
        if header.dek_id != want:
            raise ConnectError("this recovery code does not belong to the vault anchored under this owner")
        wraps = list(header.wraps)
    else:
        from .epoch import cached_epochs
        checked = False
        cached = keys.cached_dek(space_hex)
        if cached is not None:
            checked = True
            if crypto.dek_id(cached) != want:
                raise ConnectError("this recovery code does not match the data key already on this machine")
        for _seq, meta, _doc in cached_epochs(space_hex)[-1:]:
            ctp = paths.epochs_dir(space_hex) / f"{_seq:08d}.bin"
            if ctp.exists():
                checked = True
                if crypto.peek_header(ctp.read_bytes()).dek_id != want:
                    raise ConnectError("this recovery code does not belong to the vault cached on this machine")
        if not checked:
            raise ConnectError("nothing to check this recovery code against: no epochs on the chain, no cached epoch, "
                               "no cached key. A recovery code cannot start a vault; connect with the wallet or passphrase")
        if not wraps:
            raise ConnectError("no key wraps on this machine and none on the chain: connect with the wallet or passphrase")
    return _finish(owner, tenant, space, None, None, 0, account_kind, dek, wraps, False, "recovery code", None, anchor)


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------

_KIND_NAMES = {
    crypto.KEK_KIND_SIGNATURE: "wallet signature",
    crypto.KEK_KIND_PASSPHRASE: "passphrase",
    crypto.KEK_KIND_PRF: "webauthn prf",
    crypto.KEK_KIND_SMART_ACCOUNT: "smart account",
}


def _kind_name(kind: int) -> str:
    return _KIND_NAMES.get(kind, f"kind 0x{kind:02x}")


@dataclass
class RekeyResult:
    old_dek_id: str
    new_dek_id: str
    seq: int
    tx: str | None
    recovery_code: str
    dropped_kinds: list[str]
    wraps_carried: int


def rekey(owner: str, tenant: str, *, signature: bytes | None = None, passphrase: str | None = None,
          smart_account_passphrase: str | None = None, extra_passphrase: str | None = None,
          drop_missing: bool = False, anchor: Anchor | None = None, db_path,
          confirmations: int = 2, log=print) -> RekeyResult:
    """Rotate the data key: a new DEK, new wraps under the SAME keys, one snapshot epoch, a new
    recovery code.

    Every key that is to keep opening the vault must be supplied here, because a wrap can only be
    made by whoever holds its KEK. Nothing local changes until the snapshot epoch is on the chain:
    if the push fails, this machine still opens the vault with the key it had.

    Epochs sealed before the rotation stay readable to whoever held the old key. That is a
    property of a public ledger, not something a rotation can undo.
    """
    owner = to_checksum_address(owner)
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    enrol = keys.Enrolment.load(space_hex)
    if enrol is None:
        raise ConnectError("this machine is not connected to the vault: `kint connect` first "
                           "(rekey rotates the key of a vault this machine can already open)")
    with head_lock(space_hex):
        return _rekey_locked(owner, tenant, space, enrol, signature=signature, passphrase=passphrase,
                             smart_account_passphrase=smart_account_passphrase, extra_passphrase=extra_passphrase,
                             drop_missing=drop_missing, anchor=anchor, db_path=db_path,
                             confirmations=confirmations, log=log)


def _rekey_locked(owner: str, tenant: str, space: bytes, enrol, *, signature, passphrase, smart_account_passphrase,
                  extra_passphrase, drop_missing, anchor, db_path, confirmations, log) -> RekeyResult:
    space_hex = space.hex()
    header = _chain_head_header(owner, space, anchor) if os.environ.get("KINT_OFFLINE") != "1" else None
    # The chain head header is the set of keys a NEW machine sees, so it decides what must be
    # carried over; the local file only speaks when the chain has no epochs yet.
    current = list(header.wraps) if header is not None else load_wraps(space_hex)
    if not current:
        raise ConnectError("no key wraps for this space on this machine and none on the chain: connect first")

    supplied: list[tuple[int, bytes, str]] = []   # (kind, kek, how it was given)
    if signature is not None:
        kek, _ = crypto.derive_kek_from_signature(signature, owner, space, passphrase=passphrase)
        supplied.append((crypto.KEK_KIND_SIGNATURE, kek, "the wallet signature"))
    if smart_account_passphrase is not None:
        kek, _ = crypto.derive_kek_from_passphrase(smart_account_passphrase, owner, space)
        supplied.append((crypto.KEK_KIND_PASSPHRASE, kek, "the vault passphrase"))
    if extra_passphrase is not None:
        kek, _ = crypto.derive_kek_from_passphrase(extra_passphrase, owner, space)
        supplied.append((crypto.KEK_KIND_PASSPHRASE, kek, "the extra passphrase"))
    if not supplied:
        raise ConnectError("rekey needs at least one key to carry over: give the wallet signature "
                           "(--signature -), the vault passphrase (--smart-account) or the extra "
                           "passphrase (--add-passphrase)")
    for _kind, kek, how in supplied:
        if crypto.find_wrap(current, kek) is None:
            raise ConnectError(f"this key does not open the current vault (tag {crypto.kek_tag(kek).hex()[:8]}, "
                               f"from {how}): rekey re-wraps the keys that work today, it cannot add a key that "
                               "never did. Check the wallet, the passphrase and the tenant.")
    dek = crypto.unwrap_dek(crypto.find_wrap(current, supplied[0][1]), supplied[0][1])
    if header is not None and crypto.dek_id(dek) != header.dek_id:
        raise ConnectError("the wraps on this machine open a different data key than the one the head epoch "
                           "was sealed with: `kint connect` again (or `kint pull`) before rotating")

    by_tag: dict[str, tuple[int, bytes]] = {}
    for kind, kek, _how in supplied:
        by_tag.setdefault(crypto.kek_tag(kek).hex(), (kind, kek))
    missing = [w for w in current if w.tag.hex() not in by_tag]
    dropped_kinds = [f"{_kind_name(w.kind)} (tag {w.tag.hex()[:8]})" for w in missing]
    if missing and not drop_missing:
        raise ConnectError(
            f"rekey would drop {len(missing)} key(s) that open this vault today: {', '.join(dropped_kinds)}. "
            "Supply them in the same command, or pass --drop-missing to rotate without them (they keep opening "
            "the epochs sealed before the rotation and open nothing after it).")

    new_dek = crypto.new_dek()
    new_wraps = [crypto.wrap_dek(new_dek, by_tag[w.tag.hex()][1], w.kind) for w in current if w.tag.hex() in by_tag]
    log(f"rekey: {len(new_wraps)} key(s) carried over"
        + (f", dropping {', '.join(dropped_kinds)}" if dropped_kinds else "")
        + "; anchoring one snapshot epoch under the new data key")
    rep = _push_locked(owner=owner, tenant=tenant, db_path=db_path, anchor=anchor, dek=new_dek, wraps=new_wraps,
                       snapshot=True, confirmations=confirmations, log=log)

    # only now, with the new key on the chain, does anything on this machine change; the head
    # lock is still held, so no other process on this machine can seal under the retired key
    save_wraps(space_hex, new_wraps)
    keys.cache_dek(space_hex, new_dek)
    _write_recovery(owner, space_hex, new_dek)
    enrol.kek_tags = [w.tag.hex() for w in new_wraps]
    enrol.wrap_kinds = [w.kind for w in new_wraps]
    enrol.save()
    return RekeyResult(old_dek_id=crypto.dek_id(dek).hex(), new_dek_id=crypto.dek_id(new_dek).hex(),
                       seq=rep.head_seq, tx=(rep.epochs[-1]["tx"] if rep.epochs else None),
                       recovery_code=crypto.recovery_code(new_dek), dropped_kinds=dropped_kinds,
                       wraps_carried=len(new_wraps))


# ---------------------------------------------------------------------------
# Session key helpers
# ---------------------------------------------------------------------------

def session_key_info(anchor: Anchor | None = None, owner: str | None = None) -> dict[str, Any]:
    addr = keys.session_key_address()
    info: dict[str, Any] = {"address": addr, "path": str(paths.session_key_path()), "exists": addr is not None}
    if addr and anchor is not None:
        try:
            info["balance_wei"] = anchor.balance(addr)
            info["balance_eth"] = info["balance_wei"] / 1e18
            if owner:
                info["authorized"] = anchor.can_write(owner, addr)
                info["expiry"] = anchor.session_key_expiry(owner, addr)
        except Exception as e:  # noqa: BLE001
            info["error"] = str(e)
    return info


def doctor(owner: str | None, tenant: str, db_path) -> list[tuple[str, str, str]]:
    """(check, status, detail) rows. Status is ok | warn | fail."""
    import platform
    rows: list[tuple[str, str, str]] = []
    try:
        import sibyl_memory_client, sibyl_memory_mcp
        rows.append(("sibyl", "ok", f"client {getattr(sibyl_memory_client, '__version__', '?')}, mcp {getattr(sibyl_memory_mcp, '__version__', '?')}"))
    except Exception as e:  # noqa: BLE001
        rows.append(("sibyl", "fail", str(e)))
    home = paths.kint_home()
    mode = oct(home.stat().st_mode & 0o777)
    rows.append(("kint home", "ok" if mode == "0o700" else "warn", f"{home} mode {mode}"))
    db = Path(db_path).expanduser()
    rows.append(("sibyl store", "ok" if db.exists() else "warn", f"{db} {'exists' if db.exists() else 'absent (fresh machine)'}"))
    for bad in (Path.home() / ".sibyl-memory",):
        try:
            if home.resolve().is_relative_to(bad.resolve()):
                rows.append(("kint home placement", "fail", f"{home} is inside {bad}, a path Sibyl's cap walk sizes"))
        except Exception:
            pass
    space_hex = crypto.space_id(tenant).hex()
    enrol = keys.Enrolment.load(space_hex)
    rows.append(("enrolment", "ok" if enrol else "warn", f"owner {enrol.owner}, kind {enrol.account_kind}" if enrol else "not connected: run kint connect"))
    owner = owner or (enrol.owner if enrol else None)
    dek = keys.cached_dek(space_hex)
    rows.append(("data key", "ok" if dek else "warn", "cached and valid" if dek else "absent or expired (kint connect)"))
    rec = paths.recovery_path(space_hex)
    if rec.exists() and rec.stat().st_size:
        rows.append(("recovery code", "ok", str(rec)))
    elif enrol and enrol.created_here:
        rows.append(("recovery code", "fail", "missing on the machine that created the vault: push refuses; run kint recovery-code"))
    else:
        rows.append(("recovery code", "ok", "not on this machine (the vault was created elsewhere); kint recovery-code writes a copy"))
    anchor = None
    try:
        anchor = Anchor()
        cid = anchor.chain_id()
        rows.append(("rpc primary", "ok" if cid == crypto.CHAIN_ID else "fail", f"{redact(anchor.rpc_url)} chain {cid}, block {anchor.block_number()}"))
    except Exception as e:  # noqa: BLE001
        rows.append(("rpc primary", "fail", str(e)[:120]))
    try:
        from .chain import secondary_rpc_url
        a2 = Anchor(rpc_url=secondary_rpc_url(), address=anchor.address if anchor else None)
        same = a2.rpc_url == (anchor.rpc_url if anchor else None)
        rows.append(("rpc secondary", "warn" if same else "ok", f"{redact(secondary_rpc_url())} block {a2.block_number()}" + (" (SAME as primary: no second opinion on a cold start)" if same else "")))
    except Exception as e:  # noqa: BLE001
        rows.append(("rpc secondary", "warn", str(e)[:120]))
    if anchor is not None:
        try:
            rows.append(("contract", "ok" if anchor.has_code(anchor.address) else "fail", f"{anchor.address} {'has code' if anchor.has_code(anchor.address) else 'has NO code'}"))
        except Exception as e:  # noqa: BLE001
            rows.append(("contract", "fail", str(e)[:120]))
    sk = session_key_info(anchor, owner)
    if not sk["exists"]:
        rows.append(("session key", "warn", "none: kint session-key create"))
    else:
        bal = sk.get("balance_eth")
        auth = sk.get("authorized")
        st = "ok" if (bal and bal > 0.00002 and auth) else "warn"
        rows.append(("session key", st, f"{sk['address']} balance {bal if bal is not None else '?'} ETH, authorized {auth}"))
    if owner and anchor is not None:
        try:
            head = anchor.head(owner, crypto.space_id(tenant))
            m = Mirror.load(space_hex)
            same = m is not None and (m.seq, m.digest) == (head.seq, head.digest.hex())
            rows.append(("head", "ok" if same else "warn", f"chain seq {head.seq} block {head.block_number}; mirror seq {m.seq if m else 'none'}{' (in step)' if same else ' (pull or push needed)'}"))
        except Exception as e:  # noqa: BLE001
            rows.append(("head", "warn", str(e)[:120]))
    try:
        from .push import unanchored_changes
        c, d = unanchored_changes(tenant, db)
        rows.append(("unanchored changes", "ok" if not (c or d) else "warn", f"{c} changed, {d} deleted rows since the last anchored epoch"))
    except Exception as e:  # noqa: BLE001
        rows.append(("unanchored changes", "warn", str(e)[:120]))
    rows.append(("python", "ok", f"{platform.python_version()} {'(PYTHONPATH is set: run with env -u PYTHONPATH)' if os.environ.get('PYTHONPATH') else ''}".strip()))
    return rows


def write_recovery_file(tenant: str) -> Path:
    """Write ~/.kint/RECOVERY-<space>.txt from the cached data key (any connected machine)."""
    space_hex = crypto.space_id(tenant).hex()
    dek = keys.cached_dek(space_hex)
    if dek is None:
        raise ConnectError("no data key cached on this machine: kint connect first")
    enrol = keys.Enrolment.load(space_hex)
    if enrol is not None and os.environ.get("KINT_OFFLINE") != "1":
        # a key rotated on another machine leaves this cache holding a retired key; a recovery
        # code for it would open nothing sealed since
        try:
            header = _chain_head_header(enrol.owner, bytes.fromhex(space_hex), None)
        except ChainUnreadable:
            header = None
        if header is not None and crypto.dek_id(dek) != header.dek_id:
            raise ConnectError("the data key cached on this machine is not the one the head epoch was sealed with "
                               "(the key was rotated elsewhere): `kint connect` again, then write the recovery code")
    return _write_recovery(enrol.owner if enrol else "?", space_hex, dek)
