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
from .chain import Anchor, ChainError
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


def push(*, owner: str, tenant: str, db_path, anchor: Anchor | None = None, dek: bytes | None = None,
         wraps: list[crypto.Wrap] | None = None, confirmations: int = 2, dry_run: bool = False,
         log=print) -> PushReport:
    space = crypto.space_id(tenant)
    space_hex = space.hex()
    rep = PushReport()
    with head_lock(space_hex):
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
        if mirror.skipped:
            raise PushError(f"refusing to push: this machine could not apply epoch(s) {mirror.skipped} on its last pull, "
                            "so its picture of the memory is incomplete. Pull again (or connect with a key that opens them).")
        rows = export_rows(db_path, tenant)
        changed, deleted = diff(mirror, rows)
        rep.changed_rows, rep.deleted_rows = len(changed), len(deleted)
        if not changed and not deleted:
            rep.message = "nothing to push: the store matches the last anchored epoch"
            rep.head_seq, rep.head_digest = mirror.seq, mirror.digest
            return rep
        anchor = anchor or Anchor()
        head = anchor.head(owner, space)
        if head.seq != mirror.seq or head.digest.hex() != mirror.digest:
            raise ChainMoved(
                f"the chain head for this space is seq {head.seq} ({head.digest.hex()[:12]}) but this machine "
                f"last saw seq {mirror.seq} ({mirror.digest[:12]}): another machine pushed. Run `kint pull` first "
                "(refuses over unanchored local changes; `kint pull --rebase` replays them on top)."
            )
        if dry_run:
            rep.message = f"dry run: {len(changed)} changed rows and {len(deleted)} deletions would be anchored"
            return rep
        session = keys.load_session_account()
        if not anchor.can_write(owner, session.address):
            raise PushError(f"session key {session.address} is not authorized for owner {owner}: "
                            "authorize it (kint authorize) and fund it")
        state = Mirror(space=space_hex, tenant=tenant, rows=dict(mirror.rows), leaves=dict(mirror.leaves))
        prev = bytes.fromhex(mirror.digest)
        seq = mirror.seq
        bucket = mirror.bucket
        for chunk_rows, chunk_deleted in _chunk(changed, deleted):
            seq += 1
            state.apply(chunk_rows, chunk_deleted)
            rows_root = state.root
            pt = build_plaintext(tenant, space_hex, seq, prev.hex(), chunk_rows, chunk_deleted, rows_root, len(state.rows))
            try:
                blob = crypto.seal_epoch(pt, dek=dek, wraps=wraps, owner=owner, space=space, seq=seq, prev=prev,
                                         rows_root=rows_root, previous_bucket=bucket)
            except crypto.KintCryptoError as e:
                raise PushError(f"epoch {seq} could not be sealed: {e}") from e
            bucket = crypto.peek_header(blob).bucket
            digest = keccak(blob)
            log(f"push: epoch {seq}, {len(chunk_rows)} rows, {len(chunk_deleted)} deletions, bucket {bucket} B, "
                f"{len(blob)} B calldata")
            tx = anchor.push(session, owner, space, prev, blob)
            cost = anchor.wait(tx, confirmations=confirmations)
            evs = [e for e in anchor.epoch_at_block(owner, space, cost["blockNumber"]) if e.seq == seq]
            if not evs or evs[0].digest != digest:
                raise ChainError(f"epoch {seq} landed but the Epoch event digest does not match what was sent")
            cache_epoch(space_hex, seq, blob, pt, {"seq": seq, "digest": digest.hex(), "prev": prev.hex(),
                                                   "block": cost["blockNumber"], "tx": tx, "bucket": bucket,
                                                   "rows_root": rows_root.hex(), "writer": session.address,
                                                   "cost": cost})
            state.seq, state.digest, state.block, state.bucket, state.tx = seq, digest.hex(), cost["blockNumber"], bucket, tx
            state.anchored_root = rows_root.hex()
            state.save()
            write_watermark(space_hex, seq, digest.hex(), cost["blockNumber"])
            rep.epochs.append({"seq": seq, "tx": tx, "block": cost["blockNumber"], "digest": digest.hex(),
                               "bucket": bucket, "rows": len(chunk_rows), "deleted": len(chunk_deleted),
                               "cost_wei": cost["totalWei"], "gas_used": cost["gasUsed"], "l1_fee": cost["l1Fee"]})
            rep.pushed += 1
            prev = digest
        rep.head_seq, rep.head_digest = seq, prev.hex()
        rep.message = f"anchored {rep.pushed} epoch(s); head seq {seq}"
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
