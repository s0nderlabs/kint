"""Canonical row identity, leaf hashes and the merkle root over a Sibyl store.

The leaf hashes the EXACT stored TEXT of a row (Sibyl's storage.dumps() keeps
insertion order on purpose; re-serialising would refuse every row on device
two). Timestamps that Sibyl regenerates on replay (entity, state and
reference updated_at) are NOT part of the leaf; the journal ts is content
(write_event takes it explicitly) and is.

Leaves are ordered by their canonical key, never by rowid, so every machine
computes the same root over the same content.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, asdict
from typing import Any

from eth_utils import keccak

from .crypto import LEAF_PREFIX

TIERS = ("entity", "state", "reference", "journal")
EMPTY_ROOT = keccak(b"kint-empty-v1")


@dataclass
class Row:
    tier: str
    key: str                      # entity name | state key | reference doc_key | journal content key
    category: str | None = None   # entities only
    status: str | None = None     # entities only
    body: str | None = None       # stored TEXT (entity/state/reference)
    meta: str | None = None       # reference metadata TEXT
    ts: str | None = None         # updated_at (regenerated on replay) or journal ts (content)
    evaluated: str | None = None  # journal TEXT columns
    acted: str | None = None
    forward: str | None = None
    extra: str | None = None
    rowid: int | None = None      # local only, never hashed
    journal_id: str | None = None  # local only, never hashed

    def to_wire(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("rowid", None)
        d.pop("journal_id", None)
        return d

    @classmethod
    def from_wire(cls, d: dict[str, Any]) -> "Row":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _lp(x: str | None) -> bytes:
    if x is None:
        return struct.pack(">I", 0xFFFFFFFF)
    b = x.encode("utf-8")
    return struct.pack(">I", len(b)) + b


def journal_content_key(ts: str, evaluated: str | None, acted: str | None,
                        forward: str | None, extra: str | None) -> str:
    """Journal rows get a new uuid on replay; identity is their content. A second identical
    event gets an ordinal suffix (":1", ":2", assigned by the exporter in rowid order) so
    identical events stay distinct rows; the first keeps the bare content key."""
    h = keccak(b"kint-journal-key-v1" + _lp(ts) + _lp(evaluated) + _lp(acted) + _lp(forward) + _lp(extra))
    return h.hex()


def row_id(row: Row) -> str:
    """Canonical identity string of a row (what the diff and the mirror key on)."""
    if row.tier not in TIERS:
        raise ValueError(f"unknown tier {row.tier}")
    return f"{row.tier}\x00{row.category or ''}\x00{row.key}"


def leaf(row: Row) -> bytes:
    if row.tier == "journal":
        pre = (LEAF_PREFIX + _lp("journal") + _lp(None) + _lp(row.key) + _lp(None)
               + _lp(row.ts) + _lp(row.evaluated) + _lp(row.acted) + _lp(row.forward) + _lp(row.extra))
    else:
        pre = (LEAF_PREFIX + _lp(row.tier) + _lp(row.category) + _lp(row.key) + _lp(row.status)
               + _lp(row.body) + _lp(row.meta))
    return keccak(pre)


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b)


def merkle_root(leaves_by_id: dict[str, bytes]) -> bytes:
    """Root over leaves sorted by canonical id. Odd node carried up unchanged."""
    if not leaves_by_id:
        return EMPTY_ROOT
    level = [leaves_by_id[k] for k in sorted(leaves_by_id)]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_hash_pair(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])
        level = nxt
    return level[0]


def merkle_proof(leaves_by_id: dict[str, bytes], target_id: str) -> list[tuple[str, bool]]:
    """Inclusion proof for target_id: list of (sibling_hex, sibling_is_left)."""
    ids = sorted(leaves_by_id)
    if target_id not in leaves_by_id:
        raise KeyError(target_id)
    idx = ids.index(target_id)
    level = [leaves_by_id[k] for k in ids]
    proof: list[tuple[str, bool]] = []
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_hash_pair(level[i], level[i + 1]))
        odd = len(level) % 2 == 1
        if odd:
            nxt.append(level[-1])
        if idx % 2 == 0:
            if idx + 1 < len(level):
                proof.append((level[idx + 1].hex(), False))
            # else: carried up, no sibling at this level
        else:
            proof.append((level[idx - 1].hex(), True))
        idx //= 2
        level = nxt
    return proof


def verify_proof(leaf_hash: bytes, proof: list[tuple[str, bool]], root: bytes) -> bool:
    h = leaf_hash
    for sib_hex, is_left in proof:
        sib = bytes.fromhex(sib_hex)
        h = _hash_pair(sib, h) if is_left else _hash_pair(h, sib)
    return h == root


def leaves_of(rows: list[Row]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for r in rows:
        out[row_id(r)] = leaf(r)
    return out
