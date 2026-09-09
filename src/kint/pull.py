"""Pull: restore the memory from Base into the local Sibyl store, verifying every step.

Order of checks (each one before the next):
  1. FRESHNESS: the watermark floor; on a true cold start two independent RPCs
     must agree on the head (block number and digest said out loud).
  2. Refuse over unanchored local changes when the chain moved (a fork).
  3. Walk epochs from the head through prevBlock; for each: keccak(ct) == the
     event digest, prev continuity, header, AEAD (with the AAD that binds
     owner, space, seq, prev, bucket, rows_root, dek_id), plaintext sanity.
  4. Replay rows through the SDK's write methods, then check the merkle root
     of the running state against the header's rows_root.
  An epoch that cannot be applied is a gap: the pull stops there and reports it, the mirror
  stays at the last applied epoch, and the next pull retries from that point. Row-level
  problems inside an applied epoch are reported as warnings; the rows_root check is what
  decides whether the store reproduces the anchored state.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eth_utils import keccak

from . import crypto, keys, paths
from .canon import merkle_root
from .chain import Anchor, ChainError, EpochEvent, Head, redact, secondary_rpc_url
from .epoch import (Mirror, cache_epoch, cached_ciphertext, head_lock, parse_plaintext, read_watermark,
                    write_watermark)
from .export import export_rows
from .push import diff
from .restore import replay



class PullError(Exception):
    pass


class Fork(PullError):
    """Local unanchored changes AND the chain moved."""


class NotFresh(PullError):
    """The RPC served a head older than what this machine already saw, or two RPCs disagree."""


@dataclass
class PullReport:
    applied: int = 0
    skipped: list[dict[str, Any]] = field(default_factory=list)    # the epoch a pull stopped at (a gap)
    warnings: list[dict[str, Any]] = field(default_factory=list)   # applied epochs with row or root problems
    head_seq: int = 0
    head_digest: str = ""
    head_block: int = 0
    rows_total: int = 0
    root_ok: bool | None = None
    restore_report: dict[str, Any] | None = None
    message: str = ""
    rpcs_agreed: bool | None = None


def _check_freshness(anchor: Anchor, owner: str, space: bytes, space_hex: str, log) -> tuple[Head, bool | None]:
    head = anchor.head(owner, space)
    wm = read_watermark(space_hex)
    agreed = None
    if wm is None:
        # cold start: an independent second opinion, which requires a DIFFERENT endpoint
        if _same_endpoint(anchor.rpc_url, secondary_rpc_url()):
            if os.environ.get("KINT_ALLOW_SINGLE_RPC") == "1":
                log(f"pull: cold start on ONE RPC ({redact(anchor.rpc_url)}); KINT_ALLOW_SINGLE_RPC=1, no second opinion")
                return head, None
            raise NotFresh(f"cold start needs a second, independent RPC and KINT_RPC_URL_2 resolves to the same endpoint "
                           f"as the primary ({redact(anchor.rpc_url)}). Set KINT_RPC_URL_2 to a different provider, or "
                           "KINT_ALLOW_SINGLE_RPC=1 to accept one RPC")
        try:
            second = Anchor(rpc_url=secondary_rpc_url(), address=anchor.address)
            h2 = second.head(owner, space)
            if (h2.seq, h2.digest) != (head.seq, head.digest):
                time.sleep(3)
                h2 = second.head(owner, space)
            agreed = (h2.seq, h2.digest) == (head.seq, head.digest)
            if not agreed:
                raise NotFresh(
                    f"two RPCs disagree on the head: {redact(anchor.rpc_url)} says seq {head.seq} "
                    f"({head.digest.hex()[:12]}) at block {head.block_number}, {redact(secondary_rpc_url())} says seq {h2.seq} "
                    f"({h2.digest.hex()[:12]}); refusing to restore from a contested head")
            log(f"pull: cold start, both RPCs agree: head seq {head.seq}, digest {head.digest.hex()[:16]}, "
                f"block {head.block_number}")
        except NotFresh:
            raise
        except Exception as e:  # noqa: BLE001
            if os.environ.get("KINT_ALLOW_SINGLE_RPC") == "1":
                log(f"pull: second RPC unavailable ({e}); KINT_ALLOW_SINGLE_RPC=1, continuing on one RPC")
            else:
                raise NotFresh(f"could not get a second opinion on the head from {redact(secondary_rpc_url())}: "
                               f"{type(e).__name__}. Set KINT_ALLOW_SINGLE_RPC=1 to accept a single RPC on this cold start") from e
    else:
        if head.seq < int(wm["seq"]) or (head.seq == int(wm["seq"]) and head.digest.hex() != wm["digest"]):
            raise NotFresh(
                f"the RPC served head seq {head.seq} ({head.digest.hex()[:12]}) but this machine already saw "
                f"seq {wm['seq']} ({wm['digest'][:12]}) at block {wm['block']}: stale or lying RPC, refusing")
    return head, agreed


def _same_endpoint(a: str, b: str) -> bool:
    from urllib.parse import urlsplit
    try:
        ua, ub = urlsplit(a), urlsplit(b)
        return (ua.hostname, ua.port, ua.path.rstrip("/")) == (ub.hostname, ub.port, ub.path.rstrip("/"))
    except Exception:
        return a == b


def _wipe_store(db_path: Path, log) -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            dest = p.with_name(p.name + f".kint-backup-{ts}")
            shutil.move(str(p), str(dest))
            log(f"pull: moved {p.name} aside to {dest.name}")


def pull(*, owner: str, tenant: str, db_path, client_factory, anchor: Anchor | None = None,
         dek: bytes | None = None, kek: bytes | None = None, discard_local: bool = False,
         force_scan: bool = False, log=print) -> PullReport:
    """client_factory() must return a MemoryClient bound to db_path (built AFTER any wipe)."""
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    db_path = Path(db_path).expanduser()
    rep = PullReport()
    with head_lock(space_hex):
        anchor = anchor or Anchor()
        dek = dek or keys.cached_dek(space_hex)
        if dek is None and kek is None:
            raise PullError("no data key on this machine: run `kint connect` (wallet signature, passphrase or recovery code) first")
        head, rep.rpcs_agreed = _check_freshness(anchor, owner, space, space_hex, log)
        rep.head_seq, rep.head_digest, rep.head_block = head.seq, head.digest.hex(), head.block_number
        mirror = Mirror.load(space_hex)
        local_rows = export_rows(db_path, tenant) if db_path.exists() else []
        if mirror is None and local_rows and not discard_local:
            raise Fork(f"the local store already holds {len(local_rows)} rows for tenant {tenant} and this machine "
                       "has no record of what the chain last saw. Refusing to merge blindly. Either move the store "
                       "aside yourself or run `kint pull --discard-local` (kint moves memory.db to a timestamped backup).")
        if mirror is not None:
            changed, deleted = diff(mirror, local_rows)
            if (changed or deleted) and (head.seq != mirror.seq or head.digest.hex() != mirror.digest):
                if not discard_local:
                    raise Fork(f"the chain moved to seq {head.seq} and this store has {len(changed)} changed and "
                               f"{len(deleted)} deleted rows that were never anchored: a fork. Push is impossible "
                               "(the head moved) and pulling would lose them. `kint pull --discard-local` throws "
                               "them away; `kint pull --rebase` replays them on top (stretch).")
        if discard_local and db_path.exists():
            _wipe_store(db_path, log)
            mirror = None
        if mirror is not None and not mirror.skipped and (head.seq, head.digest.hex()) == (mirror.seq, mirror.digest):
            rep.message = f"up to date: head seq {head.seq} at block {head.block_number}"
            rep.rows_total = len(mirror.rows)
            write_watermark(space_hex, head.seq, head.digest.hex(), head.block_number)
            return rep
        state = mirror or Mirror.empty(space_hex, tenant)
        if head.seq == 0:
            rep.message = "nothing anchored yet for this owner and space"
            state.save()
            return rep
        events = anchor.walk_epochs(owner, space, stop_seq=state.seq, head=head)
        events.reverse()  # oldest first
        client = client_factory()
        prev_digest = bytes.fromhex(state.digest)
        state.skipped = []
        gap_at: int | None = None
        for ev in events:
            ok, why, doc, blob, header = _open_one(anchor, ev, owner, space, prev_digest, dek, kek, space_hex)
            if not ok:
                # A gap. Nothing after it is applied: the mirror stays at the last applied epoch so the
                # next pull retries from here (a transient RPC failure heals itself; a wrong key does not).
                rep.skipped.append({"seq": ev.seq, "block": ev.block_number, "tx": ev.tx_hash, "reason": why})
                log(f"pull: cannot apply epoch {ev.seq} at block {ev.block_number}: {why}; stopping here, "
                    f"{len(events) - events.index(ev) - 1} later epoch(s) left for the next pull")
                gap_at = ev.seq
                break
            rows, deleted = doc["rows"], doc.get("deleted", [])
            rr = replay(client, rows, [tuple(d) for d in deleted], verify_db_path=db_path, tenant_id=tenant)
            state.apply(rows, deleted)
            running_root = state.root
            if running_root != header.rows_root:
                rep.warnings.append({"seq": ev.seq, "block": ev.block_number, "tx": ev.tx_hash,
                                     "reason": "rows_root mismatch after applying this epoch (the store does not "
                                               "reproduce the anchored state; verify will refuse; `pull --discard-local` rebuilds)"})
                log(f"pull: WARNING epoch {ev.seq}: running root {running_root.hex()[:16]} != anchored "
                    f"rows_root {header.rows_root.hex()[:16]}")
            if not rr.ok:
                rep.warnings.append({"seq": ev.seq, "block": ev.block_number, "tx": ev.tx_hash,
                                     "reason": f"replay: {len(rr.skipped)} row(s) not written, {len(rr.mismatched)} "
                                               "stored differently than anchored", "detail": rr.skipped + rr.mismatched})
                log(f"pull: WARNING epoch {ev.seq}: {len(rr.skipped)} row(s) not written, {len(rr.mismatched)} mismatched")
            cache_epoch(space_hex, ev.seq, blob, None if doc is None else _plain_bytes(blob, doc, dek, kek, owner, space, ev, prev_digest, header),
                        {"seq": ev.seq, "digest": ev.digest.hex(), "prev": ev.prev.hex(), "block": ev.block_number,
                         "tx": ev.tx_hash, "bucket": header.bucket, "rows_root": header.rows_root.hex(),
                         "writer": ev.writer})
            state.seq, state.digest, state.block, state.bucket, state.tx = ev.seq, ev.digest.hex(), ev.block_number, header.bucket, ev.tx_hash
            state.anchored_root = header.rows_root.hex()
            state.save()
            write_watermark(space_hex, ev.seq, ev.digest.hex(), ev.block_number)
            rep.applied += 1
            log(f"pull: applied epoch {ev.seq} ({len(rows)} rows, {len(deleted)} deletions) from block {ev.block_number}")
            prev_digest = ev.digest
        # definitive check on the store itself
        final_rows = export_rows(db_path, tenant)
        db_root = merkle_root(dict(_leaves(final_rows)))
        rep.root_ok = (db_root == state.root) and (state.anchored_root is None or state.root.hex() == state.anchored_root)
        rep.rows_total = len(final_rows)
        state.skipped = [gap_at] if gap_at is not None else []
        state.save()
        rep.head_seq, rep.head_digest, rep.head_block = state.seq, state.digest, state.block
        gap = (f"; epoch {gap_at} could NOT be applied, the mirror stays at seq {state.seq}; pull again to retry "
               f"(a wrong key needs `kint connect`); push and verify refuse until it applies") if gap_at is not None else ""
        warn = f"; {len(rep.warnings)} warning(s), see the report" if rep.warnings else ""
        rep.message = (f"restored {rep.applied} epoch(s), {rep.rows_total} rows; head seq {state.seq} at block "
                       f"{state.block}; store root {'matches' if rep.root_ok else 'DOES NOT match'} the anchored root{gap}{warn}")
        return rep


def _leaves(rows):
    from .canon import leaf, row_id
    for r in rows:
        yield row_id(r), leaf(r)


def _plain_bytes(blob, doc, dek, kek, owner, space, ev, prev_digest, header):
    # re-open to get the exact plaintext bytes for the cache (cheap; keeps _open_one simple)
    try:
        d = dek or _dek_from_header(header, kek)
        _, pt = crypto.open_epoch(blob, dek=d, owner=owner, space=space, seq=ev.seq, prev=prev_digest)
        return pt
    except Exception:
        return None


def _dek_from_header(header: crypto.Header, kek: bytes | None) -> bytes:
    if kek is None:
        raise crypto.KintCryptoError("no data key and no key-encryption key on this machine")
    w = crypto.find_wrap(header.wraps, kek)
    if w is None:
        raise crypto.KintCryptoError("no wrap in this epoch matches the key on this machine (kek_tag ladder)")
    return crypto.unwrap_dek(w, kek)


def _open_one(anchor: Anchor, ev: EpochEvent, owner: str, space: bytes, prev_digest: bytes,
              dek: bytes | None, kek: bytes | None, space_hex: str):
    """Returns (ok, why, doc, blob, header)."""
    if ev.prev != prev_digest:
        return False, f"prev continuity broken: event prev {ev.prev.hex()[:12]} != expected {prev_digest.hex()[:12]}", None, None, None
    blob = cached_ciphertext(space_hex, ev.seq)
    if blob is None or keccak(blob) != ev.digest:
        try:
            o, s, p, blob = anchor.epoch_ciphertext(ev.tx_hash)
        except Exception as e:  # noqa: BLE001
            return False, f"could not fetch calldata: {e}", None, None, None
        if o != owner or s != space or p != ev.prev:
            return False, "calldata owner/space/prev disagree with the event", None, None, None
    if keccak(blob) != ev.digest:
        return False, "keccak(ciphertext) != event digest", None, blob, None
    try:
        header = crypto.peek_header(blob)
    except Exception as e:  # noqa: BLE001
        return False, f"bad header: {e}", None, blob, None
    try:
        d = dek if (dek is not None and crypto.dek_id(dek) == header.dek_id) else _dek_from_header(header, kek)
    except Exception as e:  # noqa: BLE001
        return False, f"wrap/dek: {e}", None, blob, header
    try:
        header, pt = crypto.open_epoch(blob, dek=d, owner=owner, space=space, seq=ev.seq, prev=prev_digest)
    except Exception as e:  # noqa: BLE001
        return False, f"AEAD failed: {type(e).__name__}", None, blob, header
    try:
        doc = parse_plaintext(pt)
    except Exception as e:  # noqa: BLE001
        return False, f"plaintext unreadable: {e}", None, blob, header
    if doc.get("seq") != ev.seq or doc.get("space") != space_hex or doc.get("prev") != prev_digest.hex():
        return False, "plaintext seq/space/prev disagree with the chain", None, blob, header
    if doc.get("rows_root") != header.rows_root.hex():
        return False, "plaintext rows_root disagrees with the header", None, blob, header
    if dek is None and d is not None:
        keys.cache_dek(space_hex, d)
    return True, "", doc, blob, header
