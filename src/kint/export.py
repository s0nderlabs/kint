"""Export the four tiers the Sibyl SDK can write, by raw SQL, in rowid order.

The SDK has no enumeration for state or reference documents and no rowid
ordering anywhere (list_entities orders by updated_at DESC and clamps), so the
export reads the tables directly and read-only. The RESTORE path is the one
that goes through the SDK's write methods (kint.restore).

Not exported (documented): entity_relations, revenue_events, error_events,
archived_entities, flagged_actors, skill_proposals, learning_runs. The SDK
writes none of them on a normal store EXCEPT archived_entities, which Sibyl's
memory_forget writes: the row leaves the entities table (so the anchored state
is right) but the archived copy is not carried, and a restore replays the
forget as a plain delete.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .canon import Row, journal_content_key


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def export_rows(db_path: str | Path, tenant_id: str) -> list[Row]:
    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        return []
    rows: list[Row] = []
    conn = _connect_ro(db_path)
    try:
        for r in conn.execute(
            "SELECT rowid, category, name, status, body, updated_at FROM entities "
            "WHERE tenant_id = ? ORDER BY rowid", (tenant_id,)
        ):
            rows.append(Row(tier="entity", key=r["name"], category=r["category"], status=r["status"],
                            body=r["body"], ts=r["updated_at"], rowid=r["rowid"]))
        for r in conn.execute(
            "SELECT rowid, document_key, body, updated_at FROM state_documents "
            "WHERE tenant_id = ? ORDER BY rowid", (tenant_id,)
        ):
            rows.append(Row(tier="state", key=r["document_key"], body=r["body"], ts=r["updated_at"], rowid=r["rowid"]))
        for r in conn.execute(
            "SELECT rowid, doc_key, body, metadata, updated_at FROM reference_documents "
            "WHERE tenant_id = ? ORDER BY rowid", (tenant_id,)
        ):
            rows.append(Row(tier="reference", key=r["doc_key"], body=r["body"], meta=r["metadata"],
                            ts=r["updated_at"], rowid=r["rowid"]))
        seen: dict[str, int] = {}
        for r in conn.execute(
            "SELECT rowid, id, ts, evaluated, acted, forward, extra FROM journal_events "
            "WHERE tenant_id = ? ORDER BY rowid", (tenant_id,)
        ):
            base = journal_content_key(r["ts"], r["evaluated"], r["acted"], r["forward"], r["extra"])
            n = seen.get(base, 0)
            seen[base] = n + 1
            rows.append(Row(tier="journal", key=base if n == 0 else f"{base}:{n}",
                            ts=r["ts"], evaluated=r["evaluated"], acted=r["acted"], forward=r["forward"],
                            extra=r["extra"], rowid=r["rowid"], journal_id=r["id"]))
    finally:
        conn.close()
    return rows


def read_row(db_path: str | Path, tenant_id: str, tier: str, key: str, category: str | None = None) -> Row | None:
    """Re-read ONE row's exact stored TEXT by its Sibyl key (what memory_search returns).
    For the journal tier `key` is the Sibyl event id (uuid)."""
    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        return None
    conn = _connect_ro(db_path)
    try:
        if tier == "entity":
            r = conn.execute(
                "SELECT rowid, category, name, status, body, updated_at FROM entities "
                "WHERE tenant_id = ? AND category = ? AND name = ?", (tenant_id, category, key)
            ).fetchone()
            if r is None:
                return None
            return Row(tier="entity", key=r["name"], category=r["category"], status=r["status"],
                       body=r["body"], ts=r["updated_at"], rowid=r["rowid"])
        if tier == "state":
            r = conn.execute(
                "SELECT rowid, document_key, body, updated_at FROM state_documents "
                "WHERE tenant_id = ? AND document_key = ?", (tenant_id, key)
            ).fetchone()
            if r is None:
                return None
            return Row(tier="state", key=r["document_key"], body=r["body"], ts=r["updated_at"], rowid=r["rowid"])
        if tier == "reference":
            r = conn.execute(
                "SELECT rowid, doc_key, body, metadata, updated_at FROM reference_documents "
                "WHERE tenant_id = ? AND doc_key = ?", (tenant_id, key)
            ).fetchone()
            if r is None:
                return None
            return Row(tier="reference", key=r["doc_key"], body=r["body"], meta=r["metadata"],
                       ts=r["updated_at"], rowid=r["rowid"])
        if tier == "journal":
            r = conn.execute(
                "SELECT rowid, id, ts, evaluated, acted, forward, extra FROM journal_events "
                "WHERE tenant_id = ? AND id = ?", (tenant_id, key)
            ).fetchone()
            if r is None:
                return None
            # ordinal among rows with identical content, in rowid order (what export assigns)
            n = conn.execute(
                "SELECT COUNT(*) FROM journal_events WHERE tenant_id = ? AND rowid < ? AND ts IS ? "
                "AND evaluated IS ? AND acted IS ? AND forward IS ? AND extra IS ?",
                (tenant_id, r["rowid"], r["ts"], r["evaluated"], r["acted"], r["forward"], r["extra"])
            ).fetchone()[0]
            base = journal_content_key(r["ts"], r["evaluated"], r["acted"], r["forward"], r["extra"])
            return Row(tier="journal", key=base if n == 0 else f"{base}:{n}",
                       ts=r["ts"], evaluated=r["evaluated"], acted=r["acted"], forward=r["forward"],
                       extra=r["extra"], rowid=r["rowid"], journal_id=r["id"])
        raise ValueError(f"unknown tier {tier}")
    finally:
        conn.close()
