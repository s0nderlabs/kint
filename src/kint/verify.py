"""The decision beat: verify what Sibyl's search returns against the chain, and refuse.

memory_verify(query):
  1. client.search(query)  (Sibyl's own ladder, four FTS5 indexes + the shadow fallback)
     returns hits WITH a typed verdict from verdicts.py. No hit, or a non-OK
     verdict, means there is nothing to key a decision on: refuse.
  2. For every hit re-read the EXACT stored TEXT by the key the search returned,
     hash it (kint.canon.leaf) and compare with the leaf this machine last saw
     anchored (the mirror), with a merkle inclusion proof against the anchored
     rows_root of the head epoch.
  3. A row whose current text does not match its anchored leaf is refused with
     a typed reason naming the block that anchored the value it drifted from,
     and the block of the current head. The refusal is written back as a Sibyl
     entity (category kint_refusal) so the next fresh session sees it too.
  4. Temporal: history(row) lists what the row held at every epoch that
     changed it, with a block-height upper bound ("no later than block N"),
     never a wall-clock "as of".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

from sibyl_memory_client.verdicts import VerdictCode

from . import crypto
from .canon import Row, leaf, merkle_proof, row_id, verify_proof
from .epoch import Mirror, cached_epochs
from .export import read_row

REFUSAL_CATEGORY = "kint_refusal"


@dataclass
class RowCheck:
    tier: str
    key: str
    category: str | None
    status: str                     # verified | drifted | unanchored | missing
    local_leaf: str | None = None
    anchored_leaf: str | None = None
    anchored_seq: int | None = None
    anchored_block: int | None = None
    anchored_tx: str | None = None
    head_seq: int | None = None
    head_block: int | None = None
    rows_root: str | None = None
    proof: list[list[Any]] | None = None
    proof_ok: bool | None = None
    reason: str = ""


@dataclass
class VerifyResult:
    query: str
    verdict: dict[str, Any]
    decision: str                   # proceed | refuse
    reason: str
    hits: list[dict[str, Any]] = field(default_factory=list)
    checks: list[RowCheck] = field(default_factory=list)
    refusal_entity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _verdict_dict(v) -> dict[str, Any]:
    out = {"code": v.code.value if hasattr(v.code, "value") else str(v.code), "returned": getattr(v, "returned", None)}
    for k in ("recovery", "tokens", "gate"):
        val = getattr(v, k, None)
        if val is not None:
            out[k] = val.value if hasattr(val, "value") else val
    try:
        from sibyl_memory_client.verdicts import explain
        out["explain"] = explain(v)
    except Exception:
        pass
    return out


def anchored_version(space_hex: str, rid: str) -> tuple[int, int, str, str] | None:
    """(seq, block, tx, leaf_hex) of the LAST epoch that changed this row, from the epoch cache."""
    last = None
    for seq, meta, doc in cached_epochs(space_hex):
        for r in doc["rows"]:
            if row_id(r) == rid:
                last = (seq, int(meta.get("block", 0)), meta.get("tx", ""), leaf(r).hex())
        for d in doc.get("deleted", []):
            if f"{d[0]}\x00{d[1] or ''}\x00{d[2]}" == rid:
                last = (seq, int(meta.get("block", 0)), meta.get("tx", ""), None)
    return last


def history(space_hex: str, tier: str, key: str, category: str | None = None) -> list[dict[str, Any]]:
    """Every anchored version of a row, oldest first, each with its block-height upper bound."""
    rid = f"{tier}\x00{category or ''}\x00{key}"
    out = []
    for seq, meta, doc in cached_epochs(space_hex):
        for r in doc["rows"]:
            if row_id(r) == rid:
                out.append({"seq": seq, "block": int(meta.get("block", 0)), "tx": meta.get("tx"),
                            "leaf": leaf(r).hex(), "body": r.body if r.tier != "journal" else
                            {"ts": r.ts, "evaluated": r.evaluated, "acted": r.acted, "forward": r.forward, "extra": r.extra},
                            "status": r.status, "deleted": False})
        for d in doc.get("deleted", []):
            if f"{d[0]}\x00{d[1] or ''}\x00{d[2]}" == rid:
                out.append({"seq": seq, "block": int(meta.get("block", 0)), "tx": meta.get("tx"), "deleted": True})
    return out


def at_block(space_hex: str, tier: str, key: str, category: str | None, block: int) -> dict[str, Any] | None:
    """The version of a row live at `block` (the last anchored version with block <= the given block)."""
    live = None
    for v in history(space_hex, tier, key, category):
        if v["block"] <= block:
            live = v
    return live


def check_row(mirror: Mirror, space_hex: str, db_path, tenant: str, hit: dict[str, Any]) -> RowCheck:
    tier, key, category = hit["tier"], hit["key"], hit.get("category")
    row = read_row(db_path, tenant, tier, key, category)
    if row is None:
        return RowCheck(tier, key, category, "missing", reason="the row the search returned is no longer in the store")
    rid = row_id(row)
    local = leaf(row).hex()
    anchored = mirror.leaves.get(rid)
    chk = RowCheck(tier, row.key, category, "unanchored", local_leaf=local, anchored_leaf=anchored,
                   head_seq=mirror.seq, head_block=mirror.block, rows_root=mirror.anchored_root or mirror.root.hex())
    ver = anchored_version(space_hex, rid)
    if ver:
        chk.anchored_seq, chk.anchored_block, chk.anchored_tx, _ = ver
    if anchored is None:
        chk.reason = "this row was written after the last anchored epoch; nothing on the chain vouches for it yet (push first)"
        return chk
    if anchored == local:
        proof = merkle_proof(mirror.leaf_bytes(), rid)
        chk.proof = [[h, is_left] for h, is_left in proof]
        chk.proof_ok = verify_proof(bytes.fromhex(local), proof, mirror.root)
        chk.status = "verified" if chk.proof_ok else "drifted"
        chk.reason = ("stored text matches the leaf anchored on Base" if chk.proof_ok
                      else "leaf matches but the inclusion proof against the anchored rows_root failed")
        return chk
    chk.status = "drifted"
    chk.reason = (f"the stored text of this row no longer matches what was anchored: the chain vouches for "
                  f"{anchored[:16]} (epoch {chk.anchored_seq}, no later than block {chk.anchored_block}), "
                  f"the store now holds {local[:16]} (unanchored, head epoch {mirror.seq} at block {mirror.block})")
    return chk


def verify(client, *, query: str, limit: int, space_hex: str, db_path, tenant: str,
           write_refusal: bool = True) -> VerifyResult:
    results = client.search(query, limit=limit)
    verdict = _verdict_dict(results.verdict)
    hits = [{"tier": h["tier"], "key": h["key"], "category": h.get("category"), "snippet": h.get("snippet"),
             "rank": h.get("rank"), "ts": h.get("ts")} for h in results]
    if results.verdict.code != VerdictCode.OK or not hits:
        return VerifyResult(query=query, verdict=verdict, decision="refuse",
                            reason=f"no ranked candidate to act on: Sibyl's verdict is {verdict['code']}", hits=hits)
    mirror = Mirror.load(space_hex)
    if mirror is None:
        return VerifyResult(query=query, verdict=verdict, decision="refuse",
                            reason="this machine has never pulled or pushed: nothing on the chain has been checked",
                            hits=hits)
    if mirror.seq > 0 and not mirror.complete:
        why = (f"epochs {mirror.skipped} could not be applied on the last pull" if mirror.skipped else
               "the local mirror's root does not equal the rows_root anchored on the chain")
        return VerifyResult(query=query, verdict=verdict, decision="refuse",
                            reason=f"this machine's picture of the memory is not the one the chain vouches for: {why}; pull again",
                            hits=hits)
    checks = [check_row(mirror, space_hex, db_path, tenant, h) for h in hits]
    bad = [c for c in checks if c.status in ("drifted", "missing")]
    unanchored = [c for c in checks if c.status == "unanchored"]
    res = VerifyResult(query=query, verdict=verdict, decision="proceed", reason="", hits=hits, checks=checks)
    if bad:
        c = bad[0]
        res.decision = "refuse"
        res.reason = (f"{c.tier} {c.category + '/' if c.category else ''}{c.key}: {c.reason}")
        if write_refusal:
            res.refusal_entity = write_refusal_entity(client, query, c)
    elif unanchored and not any(c.status == "verified" for c in checks):
        res.decision = "refuse"
        res.reason = "every candidate is unanchored: nothing on the chain vouches for it yet; push, then verify"
    else:
        top = next(c for c in checks if c.status == "verified")
        ahead = [c for c in checks[:checks.index(top)] if c.status == "unanchored"]
        res.reason = (f"{top.tier} {top.category + '/' if top.category else ''}{top.key} verified against "
                      f"rows_root {top.rows_root[:16]} anchored at epoch {top.head_seq}, block {top.head_block}")
        if ahead:
            names = ", ".join(f"{c.tier} {(c.category + '/') if c.category else ''}{c.key}" for c in ahead)
            res.reason += (f"; NOTE {len(ahead)} higher-ranked hit(s) are UNANCHORED and not vouched for by the chain "
                           f"({names}): act on the verified row, push before relying on the others")
    return res


def write_refusal_entity(client, query: str, c: RowCheck) -> str:
    name = f"{c.tier}-{(c.category or 'none')}-{c.key}-{int(time.time())}"[:200]
    client.set_entity(REFUSAL_CATEGORY, name, {
        "refused": True, "query": query, "tier": c.tier, "category": c.category, "key": c.key,
        "reason": c.reason, "local_leaf": c.local_leaf, "anchored_leaf": c.anchored_leaf,
        "anchored_seq": c.anchored_seq, "anchored_block": c.anchored_block, "anchored_tx": c.anchored_tx,
        "head_seq": c.head_seq, "head_block": c.head_block, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, status="refused")
    return f"{REFUSAL_CATEGORY}/{name}"
