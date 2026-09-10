"""Push: diff the store against the last anchored mirror and anchor the changes.

Never per write, never inside Sibyl's write transaction. Anchor after the
write returned; the export reads the store read-only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from eth_utils import keccak

from . import crypto, keys, paths
from .canon import Row, leaf, leaves_of, merkle_root, row_id
from .chain import Anchor, ChainError, redact
from .epoch import Mirror, build_plaintext, cache_epoch, head_lock, write_watermark
from .export import export_rows

MAX_COMPRESSED_PER_EPOCH = 90 * 1024   # measured gzip size per epoch; the largest bucket is 96 KB minus the header


class PushError(Exception):
    pass


class KeyExpired(PushError):
    """No usable data key on this machine: epochs are buffered, nothing is dropped."""


class ChainMoved(PushError):
    """Another machine pushed under this owner: pull first (refuse-and-tell)."""


@dataclass
class PushReport:
    pushed: int = 0
    epochs: list[dict[str, Any]] = field(default_factory=list)
    changed_rows: int = 0
    deleted_rows: int = 0
    head_seq: int = 0
    head_digest: str = ""
    message: str = ""


def diff(mirror: Mirror, rows: list[Row]) -> tuple[list[Row], list[list[str]]]:
    current = {row_id(r): r for r in rows}
    changed = [r for rid, r in current.items() if mirror.leaves.get(rid) != leaf(r).hex()]
    deleted = []
    for rid in mirror.leaves:
        if rid not in current:
            tier, category, key = rid.split("\x00", 2)
            deleted.append([tier, category or None, key])
    return changed, deleted


def _compressed_size(rows: list[Row], deleted: list[list[str]]) -> int:
    import json
    doc = {"rows": [r.to_wire() for r in rows], "deleted": deleted}
    return len(crypto.compress(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))) + 512


def _chunk(rows: list[Row], deleted: list[list[str]]) -> list[tuple[list[Row], list[list[str]]]]:
    """Split a change set so each epoch's MEASURED gzip size stays under the largest bucket.
    A single row that does not fit on its own is refused by name, never crashed on."""
    if not rows:
        return [([], deleted)]
    for r in rows:
        if _compressed_size([r], []) > MAX_COMPRESSED_PER_EPOCH:
            raise PushError(f"row {r.tier} {(r.category + '/') if r.category else ''}{r.key} compresses to more than "
                            f"{MAX_COMPRESSED_PER_EPOCH // 1024} KB on its own and cannot fit one epoch; shrink or split it "
                            "in Sibyl (push refuses until then, nothing else is blocked)")
    chunks: list[tuple[list[Row], list[list[str]]]] = []
    cur: list[Row] = []
    for r in rows:
        if cur and _compressed_size(cur + [r], deleted if not chunks else []) > MAX_COMPRESSED_PER_EPOCH:
            chunks.append((cur, deleted if not chunks else []))
            cur = []
        cur.append(r)
    chunks.append((cur, deleted if not chunks else []))
    return chunks


def _head_bucket(anchor: Anchor, owner: str, space: bytes, head) -> int | None:
    """The head epoch's published size bucket, or None when the head is not a kint epoch at all
    (junk appended by a leaked key carries no bucket to ratchet from)."""
    try:
        evs = anchor.epoch_at_block(owner, space, head.block_number)
        ev = next(e for e in evs if e.seq == head.seq)
        _, _, _, blob = anchor.epoch_ciphertext(ev.tx_hash)
    except Exception as e:  # noqa: BLE001
        raise PushError(f"cannot read the head epoch to chain on it: {redact(str(e))}") from e
    try:
        return crypto.peek_header(blob).bucket
    except Exception:  # noqa: BLE001
        return None


def push(*, owner: str, tenant: str, db_path, anchor: Anchor | None = None, dek: bytes | None = None,
         wraps: list[crypto.Wrap] | None = None, confirmations: int = 2, dry_run: bool = False,
         snapshot: bool = False, override_skipped: bool = False, log=print) -> PushReport:
    """Anchor the diff since the last epoch, or (snapshot=True) the whole state as ONE epoch.

    A snapshot re-anchors every row under the current data key and carries FLAG_SNAPSHOT, so a
    cold start can stop there instead of replaying the whole history. It is written even when
    the diff is empty (that is the point of `kint compact` and of a key rotation).

    `override_skipped` (snapshots only, and only from the owner's own terminal) anchors that
    snapshot on top of the CHAIN head even though this machine could not apply the epoch(s) it
    stopped at: the recovery path when an epoch that will never open sits between the mirror and
    the head.
    """
    space_hex = crypto.space_id(tenant).hex()
    with head_lock(space_hex):
        return _push_locked(owner=owner, tenant=tenant, db_path=db_path, anchor=anchor, dek=dek, wraps=wraps,
                            confirmations=confirmations, dry_run=dry_run, snapshot=snapshot,
                            override_skipped=override_skipped, log=log)


def _push_locked(*, owner: str, tenant: str, db_path, anchor: Anchor | None = None, dek: bytes | None = None,
                 wraps: list[crypto.Wrap] | None = None, confirmations: int = 2, dry_run: bool = False,
                 snapshot: bool = False, override_skipped: bool = False, log=print) -> PushReport:
    """push() with the head lock already held by the caller (rekey keeps it across its local
    writes so no other process can seal an epoch under the retired key in between)."""
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    rep = PushReport()
    enrol = keys.Enrolment.load(space_hex)
    if enrol is None:
        raise PushError("this machine is not connected to a vault: run `kint connect` first")
    rec = paths.recovery_path(space_hex)
    if enrol.created_here and (not rec.exists() or rec.stat().st_size == 0):
        raise PushError(f"refusing to push: this machine created the vault but its recovery code file is gone "
                        f"({rec}); run `kint recovery-code` to write it again, copy it somewhere safe, then push")
    dek = dek or keys.cached_dek(space_hex)
    if dek is None:
        raise KeyExpired("the data key on this machine has expired or is missing: `kint connect` again; "
                         "nothing was dropped, the changes stay in the store until the next push")
    wraps = wraps or load_wraps(space_hex)
    if not wraps:
        raise PushError("no key wraps recorded for this space; connect again")
    mirror = Mirror.load(space_hex) or Mirror.empty(space_hex, tenant)
    # the override is scoped to exactly the wedge it exists for: a snapshot, asked for by the owner,
    # on a machine whose last pull reported an epoch it could not apply
    override = bool(override_skipped and snapshot and mirror.skipped)
    if mirror.skipped and not override:
        raise PushError(f"refusing to push: this machine could not apply epoch(s) {mirror.skipped} on its last pull, "
                        "so its picture of the memory is incomplete. Pull again (or connect with a key that opens them). "
                        "If that epoch can never be applied (a leaked session key wrote it), the owner can anchor a "
                        "snapshot over it from this machine's own store: `kint compact --over-skipped`.")
    rows = export_rows(db_path, tenant)
    if snapshot:
        # the full state in one epoch, whatever the diff says. The deletions since the last
        # epoch still travel in the plaintext: they are informational for a reader (the rows
        # are already absent from `rows`) but history and at_block need them to record a
        # row's disappearance.
        _, deleted = diff(mirror, rows)
        changed = rows
        rep.changed_rows, rep.deleted_rows = len(changed), len(deleted)
        size = _compressed_size(changed, deleted)
        if size > MAX_COMPRESSED_PER_EPOCH:
            raise PushError(
                f"the full state ({len(changed)} rows) compresses to {size} bytes, more than the "
                f"{MAX_COMPRESSED_PER_EPOCH} bytes one epoch can carry, and snapshots are single-epoch: "
                "keep anchoring ordinary epochs (`kint push`), or shrink the memory in Sibyl. Nothing else "
                "is blocked; a restore just walks more epochs.")
    else:
        changed, deleted = diff(mirror, rows)
        rep.changed_rows, rep.deleted_rows = len(changed), len(deleted)
        if not changed and not deleted:
            rep.message = "nothing to push: the store matches the last anchored epoch"
            rep.head_seq, rep.head_digest = mirror.seq, mirror.digest
            return rep
    anchor = anchor or Anchor()
    head = anchor.head(owner, space)
    if (head.seq != mirror.seq or head.digest.hex() != mirror.digest) and override:
        # the owner said so: chain this snapshot on the head digest, whatever sits between the
        # mirror and the head. The snapshot carries the whole local state, so a machine that
        # pulls afterwards stops there and never needs the epoch this one could not apply.
        log(f"push: OVERRIDE, anchoring a snapshot on top of chain head seq {head.seq} "
            f"({head.digest.hex()[:12]}) although this machine stopped at seq {mirror.seq}"
            + (f" and could not apply epoch(s) {mirror.skipped}" if mirror.skipped else ""))
    elif head.seq != mirror.seq or head.digest.hex() != mirror.digest:
        raise ChainMoved(
            f"the chain head for this space is seq {head.seq} ({head.digest.hex()[:12]}) but this machine "
            f"last saw seq {mirror.seq} ({mirror.digest[:12]}): another machine pushed. Run `kint pull` first "
            "to take the chain's state (it refuses over unanchored local changes; `kint pull --discard-local` "
            "drops this machine's unanchored changes and takes the chain's state anyway)."
        )
    if dry_run:
        rep.message = (f"dry run: one snapshot epoch carrying all {len(changed)} rows would be anchored"
                       if snapshot else
                       f"dry run: {len(changed)} changed rows and {len(deleted)} deletions would be anchored")
        return rep
    session = keys.load_session_account()
    if not anchor.can_write(owner, session.address):
        raise PushError(f"session key {session.address} is not authorized for owner {owner}: "
                        "authorize it (kint authorize) and fund it")
    # a snapshot starts from an EMPTY mirror: its rows are the whole state, so its rows_root
    # must be the root of exactly those rows and nothing carried over
    state = (Mirror(space=space_hex, tenant=tenant) if snapshot else
             Mirror(space=space_hex, tenant=tenant, rows=dict(mirror.rows), leaves=dict(mirror.leaves)))
    prev = head.digest if override else bytes.fromhex(mirror.digest)
    seq = head.seq if override else mirror.seq
    bucket = mirror.bucket
    if override and head.seq > 0:
        # the published bucket never shrinks: chaining on the head means ratcheting from ITS bucket,
        # not from the older epoch this machine stopped at
        head_bucket = _head_bucket(anchor, owner, space, head)
        if head_bucket:
            bucket = max(bucket, head_bucket)
    for chunk_rows, chunk_deleted in ([(changed, deleted)] if snapshot else _chunk(changed, deleted)):
        seq += 1
        state.apply(chunk_rows, chunk_deleted)
        rows_root = state.root
        pt = build_plaintext(tenant, space_hex, seq, prev.hex(), chunk_rows, chunk_deleted, rows_root,
                             len(state.rows), snapshot=snapshot)
        try:
            blob = crypto.seal_epoch(pt, dek=dek, wraps=wraps, owner=owner, space=space, seq=seq, prev=prev,
                                     rows_root=rows_root, previous_bucket=bucket,
                                     flags=crypto.FLAG_SNAPSHOT if snapshot else 0)
        except crypto.KintCryptoError as e:
            raise PushError(f"epoch {seq} could not be sealed: {e}") from e
        bucket = crypto.peek_header(blob).bucket
        digest = keccak(blob)
        log(f"push: {'SNAPSHOT ' if snapshot else ''}epoch {seq}, {len(chunk_rows)} rows, "
            f"{len(chunk_deleted)} deletions, bucket {bucket} B, {len(blob)} B calldata")
        tx = anchor.push(session, owner, space, prev, blob)
        cost = anchor.wait(tx, confirmations=confirmations)
        evs = [e for e in anchor.epoch_at_block(owner, space, cost["blockNumber"]) if e.seq == seq]
        if not evs or evs[0].digest != digest:
            raise ChainError(f"epoch {seq} landed but the Epoch event digest does not match what was sent")
        meta = {"seq": seq, "digest": digest.hex(), "prev": prev.hex(), "block": cost["blockNumber"],
                "tx": tx, "bucket": bucket, "rows_root": rows_root.hex(), "writer": session.address,
                "cost": cost}
        if snapshot:
            meta["snapshot"] = True
        cache_epoch(space_hex, seq, blob, pt, meta)
        state.seq, state.digest, state.block, state.bucket, state.tx = seq, digest.hex(), cost["blockNumber"], bucket, tx
        state.anchored_root = rows_root.hex()
        state.save()
        write_watermark(space_hex, seq, digest.hex(), cost["blockNumber"])
        rep.epochs.append({"seq": seq, "tx": tx, "block": cost["blockNumber"], "digest": digest.hex(),
                           "bucket": bucket, "rows": len(chunk_rows), "deleted": len(chunk_deleted),
                           "snapshot": snapshot, "cost_wei": cost["totalWei"], "gas_used": cost["gasUsed"],
                           "l1_fee": cost["l1Fee"]})
        rep.pushed += 1
        prev = digest
    rep.head_seq, rep.head_digest = seq, prev.hex()
    rep.message = (f"anchored a snapshot epoch: seq {seq} carries all {len(changed)} rows, so a restore can "
                   f"stop there" if snapshot else f"anchored {rep.pushed} epoch(s); head seq {seq}")
    return rep


def load_wraps(space_hex: str) -> list[crypto.Wrap]:
    p = paths.kint_home() / f"wraps-{space_hex[:16]}.json"
    if not p.exists():
        return []
    import json
    return [crypto.Wrap.from_bytes(bytes.fromhex(h)) for h in json.loads(p.read_text())]


def save_wraps(space_hex: str, wraps: list[crypto.Wrap]) -> None:
    import json
    paths.write_private(paths.kint_home() / f"wraps-{space_hex[:16]}.json",
                        json.dumps([w.to_bytes().hex() for w in wraps]).encode())


def unanchored_changes(tenant: str, db_path) -> tuple[int, int]:
    """(changed, deleted) row counts versus the mirror, for status and for pull's refusal."""
    space_hex = crypto.space_id(tenant).hex()
    mirror = Mirror.load(space_hex) or Mirror.empty(space_hex, tenant)
    changed, deleted = diff(mirror, export_rows(db_path, tenant))
    return len(changed), len(deleted)
