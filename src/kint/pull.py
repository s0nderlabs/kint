"""Pull: restore the memory from Base into the local Sibyl store, verifying every step.

Order of checks (each one before the next):
  1. FRESHNESS: the watermark floor; on a true cold start two independent RPCs
     must agree on the head (block number and digest said out loud).
  2. Refuse over unanchored local changes when the chain moved (a fork).
  3. Walk epochs from the head through prevBlock, stopping at the newest snapshot
     epoch (whose rows are the full state) unless full=True; for each: keccak(ct)
     == the event digest, prev continuity, header, AEAD (with the AAD that binds
     owner, space, seq, prev, bucket, rows_root, dek_id), plaintext sanity, and
     the header snapshot flag agreeing with the plaintext key.
  4. Replay rows through the SDK's write methods, then check the merkle root
     of the running state against the header's rows_root.
  An epoch that cannot be applied is a gap: the pull stops there and reports it, the mirror
  stays at the last applied epoch, and the next pull retries from that point. Row-level
  problems inside an applied epoch are reported as warnings; the rows_root check is what
  decides whether the store reproduces the anchored state.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eth_utils import keccak

from . import crypto, keys, paths
from .canon import leaf, merkle_root, row_id
from .chain import Anchor, ChainError, EpochEvent, Head, redact, secondary_rpc_url
from .epoch import (Mirror, cache_epoch, cached_ciphertext, head_lock, parse_plaintext, read_watermark,
                    write_watermark)
from .export import export_rows
from .push import diff
from .restore import replay



# Why an epoch could not be applied, as a kind the walk can act on. Only a failure a LATER
# snapshot GENUINELY supersedes may be walked past: this machine cannot OPEN the epoch (the bytes
# are not a kint epoch, or it is sealed under a key this machine does not hold), and a snapshot's
# rows are the whole state, so nothing is lost. Everything else means the chain was not read
# cleanly (a down, pruned or lying RPC, calldata that disagrees with the event, a broken prev
# chain) or the epoch opened and then contradicted the chain: those stop the pull where they are,
# so the next pull retries instead of the machine declaring itself complete over a gap it never read.
OPEN_UNREADABLE = "unreadable"   # not a kint epoch, or no key on this machine opens it
OPEN_CHAIN = "chain"             # the RPC failed, or what it served disagrees with the event
OPEN_CONTENT = "content"         # it opened, and its plaintext disagrees with the chain


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
    unopenable: list[dict[str, Any]] = field(default_factory=list)  # epochs sealed under a key this machine lacks
    backfilled: int = 0                                              # older epochs cached for history (full=True)
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
                log(f"pull: second RPC unavailable ({redact(str(e))}); KINT_ALLOW_SINGLE_RPC=1, continuing on one RPC")
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
         force_scan: bool = False, full: bool = False, log=print) -> PullReport:
    """client_factory() must return a MemoryClient bound to db_path (built AFTER any wipe).

    The walk stops at the newest snapshot epoch (its rows ARE the full state), so restore cost
    is bounded by the size of the memory, not its history. `full=True` walks past snapshots to
    the first epoch, which is what a machine wants when it also needs the older versions.
    """
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    db_path = Path(db_path).expanduser()
    rep = PullReport()
    memo: dict = {}   # one fetch + one header parse per epoch per pull
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
                               "(the head moved) and pulling would lose them. Save what you need out of the store "
                               "yourself, then `kint pull --discard-local` to drop this machine's unanchored changes "
                               "and take the chain's state.")
        if discard_local and db_path.exists():
            _wipe_store(db_path, log)
            mirror = None
        if mirror is not None and not mirror.skipped and (head.seq, head.digest.hex()) == (mirror.seq, mirror.digest):
            rep.message = f"up to date: head seq {head.seq} at block {head.block_number}"
            rep.rows_total = len(mirror.rows)
            write_watermark(space_hex, head.seq, head.digest.hex(), head.block_number)
            if full:
                _backfill_history(anchor, owner, space, space_hex, dek, kek, rep, memo, log, head=head)
                if rep.backfilled or rep.unopenable:
                    rep.message += (f"; {rep.backfilled} older epoch(s) cached for history"
                                    f"{f', {len(rep.unopenable)} sealed under a retired key stay closed' if rep.unopenable else ''}")
            return rep
        state = mirror or Mirror.empty(space_hex, tenant)
        if head.seq == 0:
            rep.message = "nothing anchored yet for this owner and space"
            state.save()
            return rep
        for _attempt in (0, 1):
            stop_when = None if full else (lambda ev: _is_snapshot_event(anchor, ev, owner, space, space_hex, memo))
            events = anchor.walk_epochs(owner, space, stop_seq=state.seq, head=head, stop_when=stop_when)
            events.reverse()  # oldest first
            # Epochs sealed under a data key this machine does not hold cannot be opened, and after a
            # `kint rekey` every epoch before the rotation is one of those. A rotation always writes a
            # snapshot, so start at the first epoch this key CAN open when that epoch is a snapshot
            # (its rows are the full state). Anything else stays a gap and is reported by name.
            rep.unopenable = []
            if events and not _key_opens(anchor, events[0], owner, space, space_hex, dek, kek, memo):
                i = next((n for n, e in enumerate(events)
                          if _key_opens(anchor, e, owner, space, space_hex, dek, kek, memo)), None)
                if i is not None and _is_snapshot_event(anchor, events[i], owner, space, space_hex, memo):
                    log(f"pull: epochs {events[0].seq} to {events[i - 1].seq} were sealed under a data key this "
                        f"machine does not hold (the key was rotated); restoring from snapshot epoch {events[i].seq}")
                    rep.unopenable = [{"seq": e.seq, "block": e.block_number, "tx": e.tx_hash,
                                       "reason": "sealed under a data key this machine does not hold (rotated)"}
                                      for e in events[:i]]
                    events = events[i:]
            client = client_factory()
            prev_digest = bytes.fromhex(state.digest)
            if events and events[0].seq > state.seq and _is_snapshot_event(anchor, events[0], owner, space, space_hex, memo):
                # the walk stopped at a snapshot: its prev is a digest this machine never applied, and the
                # prevBlock walk from the head is what vouches for it
                if prev_digest != events[0].prev:
                    log(f"pull: starting at snapshot epoch {events[0].seq}; the epochs before it are not needed to "
                        f"restore (`kint pull --full` walks them for the older versions)")
                prev_digest = events[0].prev
            state.skipped = []
            gap_at: int | None = None
            resume_from = 0
            for idx, ev in enumerate(events):
                if idx < resume_from:
                    continue   # subsumed by the snapshot this walk resumed at
                ok, why, kind, doc, blob, header = _open_one(anchor, ev, owner, space, prev_digest, dek, kek,
                                                             space_hex, memo)
                if not ok:
                    # An epoch that cannot be applied is a gap. A LATER snapshot carries the whole state,
                    # so when one is in this walk the restore resumes there (its prev comes from the
                    # prevBlock walk, exactly as on a cold start) instead of being wedged for good.
                    # ONLY for an epoch this machine cannot open: a failure to READ the chain (a down,
                    # pruned or lying RPC) is never superseded by a later snapshot, because nobody has
                    # seen what is in the epoch yet. Walking past that one would let a corrupt RPC talk
                    # this machine into calling its picture complete.
                    resume = None
                    if kind == OPEN_UNREADABLE:
                        resume = next((j for j in range(idx + 1, len(events))
                                       if _is_snapshot_event(anchor, events[j], owner, space, space_hex, memo)
                                       and _key_opens(anchor, events[j], owner, space, space_hex, dek, kek, memo)), None)
                    if resume is not None:
                        rep.skipped.append({"seq": ev.seq, "block": ev.block_number, "tx": ev.tx_hash,
                                            "reason": why, "superseded_by": events[resume].seq})
                        log(f"pull: cannot apply epoch {ev.seq} at block {ev.block_number}: {why}; snapshot epoch "
                            f"{events[resume].seq} carries the whole state, resuming there")
                        prev_digest = events[resume].prev
                        resume_from = resume
                        continue
                    # Nothing after it is applied: the mirror stays at the last applied epoch so the
                    # next pull retries from here (a transient RPC failure heals itself; a wrong key does not).
                    rep.skipped.append({"seq": ev.seq, "block": ev.block_number, "tx": ev.tx_hash, "reason": why})
                    log(f"pull: cannot apply epoch {ev.seq} at block {ev.block_number}: {why}; stopping here, "
                        f"{len(events) - idx - 1} later epoch(s) left for the next pull")
                    gap_at = ev.seq
                    break
                rows, deleted = doc["rows"], doc.get("deleted", [])
                write_rows = rows
                if header.flags & crypto.FLAG_SNAPSHOT:
                    # a snapshot's rows are the WHOLE state: whatever this machine holds and the snapshot
                    # does not is dropped, then the picture is rebuilt from the snapshot alone
                    present = {row_id(r) for r in rows}
                    dropped = []
                    for rid in state.rows:
                        if rid not in present:
                            tier, category, key = rid.split("\x00", 2)
                            dropped.append([tier, category or None, key])
                    state.rows.clear()
                    state.leaves.clear()
                    deleted = dropped
                    # a snapshot re-anchors rows this store may already hold byte for byte. Writing those
                    # again would DUPLICATE the append-only tiers (a journal event has no key to overwrite),
                    # so only the rows whose stored text differs are replayed; the rest are already right.
                    have = {row_id(r): leaf(r).hex() for r in export_rows(db_path, tenant)}
                    write_rows = [r for r in rows if have.get(row_id(r)) != leaf(r).hex()]
                    log(f"pull: snapshot epoch {ev.seq} replaces the local picture ({len(rows)} rows, "
                        f"{len(write_rows)} written, {len(dropped)} dropped)")
                rr = replay(client, write_rows, [tuple(d) for d in deleted], verify_db_path=db_path, tenant_id=tenant)
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
                            _epoch_meta(ev, header))
                state.seq, state.digest, state.block, state.bucket, state.tx = ev.seq, ev.digest.hex(), ev.block_number, header.bucket, ev.tx_hash
                state.anchored_root = header.rows_root.hex()
                state.save()
                write_watermark(space_hex, ev.seq, ev.digest.hex(), ev.block_number)
                rep.applied += 1
                log(f"pull: applied epoch {ev.seq} ({len(rows)} rows, {len(deleted)} deletions) from block {ev.block_number}")
                prev_digest = ev.digest
            if (not full and _attempt == 0 and gap_at is not None and rep.applied == 0 and events
                    and gap_at == events[0].seq and events[0].seq > state.seq
                    and _is_snapshot_event(anchor, events[0], owner, space, space_hex, memo)):
                # The walk stopped at an epoch whose header CLAIMS to be a snapshot, and that epoch
                # does not open (a forged flag, or a key that only opens the epochs before it). The
                # flag is not covered by the AAD, so it must never decide the restore: walk again
                # without stopping, apply everything that does open, and report the bad epoch.
                log(f"pull: epoch {gap_at} claims to be a snapshot but cannot be applied; walking the full "
                    f"history instead")
                rep.skipped = []
                state.skipped = []
                full = True
                continue
            break

        # definitive check on the store itself
        final_rows = export_rows(db_path, tenant)
        db_root = merkle_root(dict(_leaves(final_rows)))
        rep.root_ok = (db_root == state.root) and (state.anchored_root is None or state.root.hex() == state.anchored_root)
        rep.rows_total = len(final_rows)
        state.skipped = [gap_at] if gap_at is not None else []
        state.save()
        rep.head_seq, rep.head_digest, rep.head_block = state.seq, state.digest, state.block
        if full and gap_at is None:
            _backfill_history(anchor, owner, space, space_hex, dek, kek, rep, memo, log, head=head)
        gap = (f"; epoch {gap_at} could NOT be applied, the mirror stays at seq {state.seq}; pull again to retry "
               f"(a wrong key needs `kint connect`); push and verify refuse until it applies") if gap_at is not None else ""
        jumped = [s for s in rep.skipped if s.get("superseded_by")]
        if jumped:
            gap += ("; epoch(s) " + ", ".join(str(s["seq"]) for s in jumped) + " could not be applied but a later "
                    "snapshot carries the whole state, so this machine's picture is complete")
        warn = f"; {len(rep.warnings)} warning(s), see the report" if rep.warnings else ""
        closed = (f"; {len(rep.unopenable)} older epoch(s) sealed under a retired key stay closed on this machine"
                  if rep.unopenable else "")
        back = f"; {rep.backfilled} older epoch(s) cached for history" if rep.backfilled else ""
        rep.message = (f"restored {rep.applied} epoch(s), {rep.rows_total} rows; head seq {state.seq} at block "
                       f"{state.block}; store root {'matches' if rep.root_ok else 'DOES NOT match'} the anchored root"
                       f"{gap}{warn}{closed}{back}")
        return rep


def _epoch_meta(ev: EpochEvent, header: crypto.Header) -> dict[str, Any]:
    meta = {"seq": ev.seq, "digest": ev.digest.hex(), "prev": ev.prev.hex(), "prev_block": ev.prev_block,
            "block": ev.block_number, "tx": ev.tx_hash, "bucket": header.bucket, "rows_root": header.rows_root.hex(),
            "writer": ev.writer}
    if header.flags & crypto.FLAG_SNAPSHOT:
        meta["snapshot"] = True
    return meta


def _backfill_history(anchor: Anchor, owner: str, space: bytes, space_hex: str, dek: bytes | None,
                      kek: bytes | None, rep: PullReport, memo: dict, log, head: Head | None = None) -> None:
    """`full`: walk the WHOLE chain of epochs, head to genesis, and cache the plaintext of every
    one this machine has not decrypted yet, for history and at_block. A warm pull that stopped at
    a snapshot leaves gaps ABOVE the oldest cached epoch as well as below it, so the walk starts
    at the head and skips what is already cached. The store and the mirror are not touched (the
    current state is already complete); an epoch the key cannot open (sealed before a rotation)
    is reported, and the walk carries on past it because the chain, not the plaintext, vouches
    for the prev digests."""
    from .epoch import cached_epochs
    have = cached_epochs(space_hex)
    known = {seq for seq, _m, _d in have} | {u["seq"] for u in rep.unopenable}   # already cached or reported
    try:
        head = head or anchor.head(owner, space)
        if head.seq == 0 or known >= set(range(1, head.seq + 1)):
            return   # nothing on the chain, or every epoch is already accounted for
        low = min(known) if known else None
        low_meta = next((m for seq, m, _d in have if seq == low), None) if low else None
        if low and low > 1 and low_meta and known >= set(range(low, head.seq + 1)) and low_meta.get("prev"):
            # nothing is missing above the oldest cached epoch: walk only what lies below it
            start = Head(digest=bytes.fromhex(low_meta["prev"]), seq=low - 1, block_number=int(low_meta.get("prev_block") or 0))
            if start.block_number:
                events = anchor.walk_epochs(owner, space, stop_seq=0, head=start)
            else:
                events = anchor.walk_epochs(owner, space, stop_seq=0, head=head)
        else:
            events = anchor.walk_epochs(owner, space, stop_seq=0, head=head)
    except Exception as e:  # noqa: BLE001
        log(f"pull: could not walk the epoch history: {redact(str(e))}")
        return
    events.reverse()
    prev_digest = bytes(32)
    for ev in events:
        if ev.seq in known:
            prev_digest = ev.digest
            continue
        ok, why, _kind, doc, blob, header = _open_one(anchor, ev, owner, space, prev_digest, dek, kek, space_hex, memo)
        if ok:
            cache_epoch(space_hex, ev.seq, blob, _plain_bytes(blob, doc, dek, kek, owner, space, ev, prev_digest, header),
                        _epoch_meta(ev, header))
            rep.backfilled += 1
        else:
            rep.unopenable.append({"seq": ev.seq, "block": ev.block_number, "tx": ev.tx_hash, "reason": why})
        prev_digest = ev.digest
    if rep.backfilled or rep.unopenable:
        log(f"pull: history backfill: {rep.backfilled} older epoch(s) cached, {len(rep.unopenable)} could not be opened")


def _leaves(rows):
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


def _fetch_blob(anchor: Anchor, ev: EpochEvent, owner: str, space: bytes, space_hex: str,
                memo: dict | None = None) -> tuple[bytes | None, str]:
    """(ciphertext, why). The epoch cache first, then the transaction's calldata, always
    checked against the Epoch event before it is trusted or cached. `memo` (one per pull)
    keeps each epoch's verdict so the walk, the key check and the open share one fetch."""
    if memo is not None and ev.seq in memo:
        return memo[ev.seq]
    out = _fetch_blob_uncached(anchor, ev, owner, space, space_hex)
    if memo is not None:
        memo[ev.seq] = out
    return out


def _header_of(blob: bytes, memo: dict | None, seq: int) -> crypto.Header | None:
    key = ("hdr", seq)
    if memo is not None and key in memo:
        return memo[key]
    try:
        h = crypto.peek_header(blob)
    except Exception:  # noqa: BLE001
        h = None
    if memo is not None:
        memo[key] = h
    return h


def _fetch_blob_uncached(anchor: Anchor, ev: EpochEvent, owner: str, space: bytes, space_hex: str) -> tuple[bytes | None, str]:
    blob = cached_ciphertext(space_hex, ev.seq)
    if blob is not None and keccak(blob) == ev.digest:
        return blob, ""
    try:
        o, s, p, blob = anchor.epoch_ciphertext(ev.tx_hash)
    except Exception as e:  # noqa: BLE001
        return None, f"could not fetch calldata: {redact(str(e))}"
    if o != owner or s != space or p != ev.prev:
        return None, "calldata owner/space/prev disagree with the event"
    if keccak(blob) != ev.digest:
        return None, "keccak(ciphertext) != event digest"
    meta = {"seq": ev.seq, "digest": ev.digest.hex(), "prev": ev.prev.hex(), "block": ev.block_number,
            "tx": ev.tx_hash, "writer": ev.writer}
    old = paths.epochs_dir(space_hex) / f"{ev.seq:08d}.meta.json"
    if old.exists():
        try:
            meta = {**json.loads(old.read_text()), **meta}
        except Exception:  # noqa: BLE001
            pass
    cache_epoch(space_hex, ev.seq, blob, None, meta)
    return blob, ""


def _key_opens(anchor: Anchor, ev: EpochEvent, owner: str, space: bytes, space_hex: str,
               dek: bytes | None, kek: bytes | None, memo: dict | None = None) -> bool:
    """Whether the key on this machine can open this epoch at all (header check only, no AEAD).
    Anything that is not a key question answers True: _open_one reports those where they belong."""
    blob, _why = _fetch_blob(anchor, ev, owner, space, space_hex, memo)
    if blob is None:
        return True
    header = _header_of(blob, memo, ev.seq)
    if header is None:
        return True
    if dek is not None and crypto.dek_id(dek) == header.dek_id:
        return True
    return kek is not None and crypto.find_wrap(header.wraps, kek) is not None


def _is_snapshot_event(anchor: Anchor, ev: EpochEvent, owner: str, space: bytes, space_hex: str,
                       memo: dict | None = None) -> bool:
    """Header-flag peek used to stop a cold-start walk. A fetch failure is not a snapshot:
    the walk continues and _open_one reports the failure where it can be acted on."""
    blob, _why = _fetch_blob(anchor, ev, owner, space, space_hex, memo)
    if blob is None:
        return False
    header = _header_of(blob, memo, ev.seq)
    return header is not None and bool(header.flags & crypto.FLAG_SNAPSHOT)


def _open_one(anchor: Anchor, ev: EpochEvent, owner: str, space: bytes, prev_digest: bytes,
              dek: bytes | None, kek: bytes | None, space_hex: str, memo: dict | None = None):
    """Returns (ok, why, kind, doc, blob, header).

    `kind` is one of OPEN_UNREADABLE / OPEN_CHAIN / OPEN_CONTENT on a failure and "" on success.
    It is what decides whether a later snapshot may be resumed at; `why` is the sentence a human reads.
    """
    if ev.prev != prev_digest:
        return (False, f"prev continuity broken: event prev {ev.prev.hex()[:12]} != expected "
                f"{prev_digest.hex()[:12]}", OPEN_CHAIN, None, None, None)
    blob, why = _fetch_blob(anchor, ev, owner, space, space_hex, memo)
    if blob is None:
        return False, why, OPEN_CHAIN, None, None, None
    header = _header_of(blob, memo, ev.seq)
    if header is None:
        return False, "bad header: cannot parse", OPEN_UNREADABLE, None, blob, None
    try:
        d = dek if (dek is not None and crypto.dek_id(dek) == header.dek_id) else _dek_from_header(header, kek)
    except Exception as e:  # noqa: BLE001
        return False, f"wrap/dek: {e}", OPEN_UNREADABLE, None, blob, header
    try:
        header, pt = crypto.open_epoch(blob, dek=d, owner=owner, space=space, seq=ev.seq, prev=prev_digest)
    except Exception as e:  # noqa: BLE001
        return False, f"AEAD failed: {type(e).__name__}", OPEN_UNREADABLE, None, blob, header
    try:
        doc = parse_plaintext(pt)
    except Exception as e:  # noqa: BLE001
        return False, f"plaintext unreadable: {e}", OPEN_CONTENT, None, blob, header
    if doc.get("seq") != ev.seq or doc.get("space") != space_hex or doc.get("prev") != prev_digest.hex():
        return False, "plaintext seq/space/prev disagree with the chain", OPEN_CONTENT, None, blob, header
    if doc.get("rows_root") != header.rows_root.hex():
        return False, "plaintext rows_root disagrees with the header", OPEN_CONTENT, None, blob, header
    # the header flag is the authoritative signal and is NOT covered by the AAD, so it has to
    # agree with the plaintext key before either is acted on
    if bool(header.flags & crypto.FLAG_SNAPSHOT) != bool(doc.get("snapshot", False)):
        return False, "snapshot flag disagrees between header and plaintext", OPEN_CONTENT, None, blob, header
    if dek is None and d is not None:
        keys.cache_dek(space_hex, d)
    return True, "", "", doc, blob, header
