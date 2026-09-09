"""Epoch plaintext format, the local mirror, the epoch cache and the watermark.

Epoch plaintext (before gzip, padding and AES-GCM):
    {"v": 1, "tenant": ..., "space": hex, "seq": n, "prev": hex,
     "rows": [wire rows that changed], "deleted": [[tier, category, key], ...],
     "rows_root": hex (merkle root of the FULL state after this epoch),
     "n_rows": total rows after this epoch, "created_at": iso}

Mirror: what this machine believes the chain last saw: the full row set,
its leaves, the root, and the head (seq, digest, block, bucket).
Epoch cache: ciphertext and decrypted plaintext per seq, a pure cache that
also feeds the temporal read (what a row held at an earlier block).
Watermark: the freshness floor (seq, digest, block); never decreases.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .canon import Row, leaf, merkle_root, row_id

EPOCH_VERSION = 1


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Mirror
# ---------------------------------------------------------------------------

@dataclass
class Mirror:
    space: str
    tenant: str
    seq: int = 0
    digest: str = "00" * 32
    block: int = 0
    bucket: int = 0
    tx: str | None = None
    anchored_root: str | None = None                                 # rows_root the chain vouches for at seq
    skipped: list[int] = field(default_factory=list)                 # epochs this machine could not apply
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)   # row_id -> wire row
    leaves: dict[str, str] = field(default_factory=dict)             # row_id -> leaf hex

    @property
    def root(self) -> bytes:
        return merkle_root({k: bytes.fromhex(v) for k, v in self.leaves.items()})

    @property
    def complete(self) -> bool:
        """True when every epoch up to seq was applied and the local root equals the anchored one."""
        return not self.skipped and self.anchored_root is not None and self.root.hex() == self.anchored_root

    def leaf_bytes(self) -> dict[str, bytes]:
        return {k: bytes.fromhex(v) for k, v in self.leaves.items()}

    def apply(self, rows: list[Row], deleted: list[list[str]]) -> None:
        for tier, category, key in deleted:
            rid = f"{tier}\x00{category or ''}\x00{key}"
            self.rows.pop(rid, None)
            self.leaves.pop(rid, None)
        for r in rows:
            rid = row_id(r)
            self.rows[rid] = r.to_wire()
            self.leaves[rid] = leaf(r).hex()

    def save(self) -> None:
        data = {"space": self.space, "tenant": self.tenant, "seq": self.seq, "digest": self.digest,
                "block": self.block, "bucket": self.bucket, "tx": self.tx, "anchored_root": self.anchored_root,
                "skipped": self.skipped, "rows": self.rows, "leaves": self.leaves}
        paths.write_private(paths.mirror_path(self.space), json.dumps(data).encode())

    @classmethod
    def load(cls, space_hex: str) -> "Mirror | None":
        p = paths.mirror_path(space_hex)
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return cls(**d)

    @classmethod
    def empty(cls, space_hex: str, tenant: str) -> "Mirror":
        return cls(space=space_hex, tenant=tenant)


# ---------------------------------------------------------------------------
# Watermark and lock
# ---------------------------------------------------------------------------

def read_watermark(space_hex: str) -> dict[str, Any] | None:
    p = paths.watermark_path(space_hex)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def write_watermark(space_hex: str, seq: int, digest_hex: str, block: int) -> None:
    cur = read_watermark(space_hex)
    if cur and int(cur.get("seq", 0)) > seq:
        return  # never decreases
    paths.write_private(paths.watermark_path(space_hex),
                        json.dumps({"seq": seq, "digest": digest_hex, "block": block, "at": now_iso()}).encode())


@contextmanager
def head_lock(space_hex: str, timeout: float = 30.0):
    """One pusher/puller per space per machine (two sessions, one store)."""
    p = paths.lock_path(space_hex)
    fd = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.time() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() > deadline:
                    raise TimeoutError("another kint process holds the head lock for this space")
                time.sleep(0.2)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ---------------------------------------------------------------------------
# Epoch plaintext and cache
# ---------------------------------------------------------------------------

def build_plaintext(tenant: str, space_hex: str, seq: int, prev_hex: str, rows: list[Row],
                    deleted: list[list[str]], rows_root: bytes, n_rows: int) -> bytes:
    doc = {"v": EPOCH_VERSION, "tenant": tenant, "space": space_hex, "seq": seq, "prev": prev_hex,
           "rows": [r.to_wire() for r in rows], "deleted": deleted, "rows_root": rows_root.hex(),
           "n_rows": n_rows, "created_at": now_iso()}
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_plaintext(data: bytes) -> dict[str, Any]:
    doc = json.loads(data.decode("utf-8"))
    if doc.get("v") != EPOCH_VERSION:
        raise ValueError(f"unsupported epoch version {doc.get('v')}")
    doc["rows"] = [Row.from_wire(r) for r in doc.get("rows", [])]
    return doc


def cache_epoch(space_hex: str, seq: int, ct: bytes, plaintext: bytes | None, meta: dict[str, Any]) -> None:
    d = paths.epochs_dir(space_hex)
    paths.write_private(d / f"{seq:08d}.bin", ct)
    if plaintext is not None:
        paths.write_private(d / f"{seq:08d}.json", plaintext)
    paths.write_private(d / f"{seq:08d}.meta.json", json.dumps(meta).encode())


def cached_ciphertext(space_hex: str, seq: int) -> bytes | None:
    p = paths.epochs_dir(space_hex) / f"{seq:08d}.bin"
    return p.read_bytes() if p.exists() else None


def cached_epochs(space_hex: str) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    """(seq, meta, plaintext doc) for every cached decrypted epoch, ascending."""
    d = paths.epochs_dir(space_hex)
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".meta.json"):
            continue
        seq = int(p.stem)
        meta_p = d / f"{seq:08d}.meta.json"
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        try:
            doc = parse_plaintext(p.read_bytes())
        except Exception:
            continue
        out.append((seq, meta, doc))
    return out
