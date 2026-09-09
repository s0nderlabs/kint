"""Restore rows into a Sibyl store THROUGH the SDK's own write methods.

set_entity / set_state / set_reference / write_event, in the exported rowid
order. Content-exact and search-exact for the four tiers the SDK writes;
uuids and entity/state/reference timestamps regenerate; the journal ts
survives through write_event's explicit argument. After replay every row is
re-read and its leaf compared, so a row that did not come back byte-exact is
reported, never silently accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sibyl_memory_client.storage import loads

from .canon import Row, leaf, row_id
from .export import export_rows


@dataclass
class RestoreReport:
    written: int = 0
    deleted: int = 0
    skipped: list[dict[str, Any]] = field(default_factory=list)
    mismatched: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.skipped and not self.mismatched


def write_row(client, row: Row) -> None:
    if row.tier == "entity":
        client.set_entity(row.category, row.key, loads(row.body), status=row.status)
    elif row.tier == "state":
        client.set_state(row.key, loads(row.body))
    elif row.tier == "reference":
        client.set_reference(row.key, row.body if row.body is not None else "",
                             metadata=loads(row.meta) if row.meta is not None else None)
    elif row.tier == "journal":
        client.write_event(
            evaluated=loads(row.evaluated), acted=loads(row.acted),
            forward=loads(row.forward), extra=loads(row.extra), ts=row.ts,
        )
    else:
        raise ValueError(f"unknown tier {row.tier}")


def delete_row(client, tier: str, category: str | None, key: str) -> bool:
    """Only entities have an SDK delete. The other tiers are never deleted by Sibyl."""
    if tier == "entity":
        return bool(client.delete_entity(category, key))
    return False


def replay(client, rows: list[Row], deletions: list[tuple[str, str | None, str]] = (),
           *, verify_db_path: str | Path | None = None, tenant_id: str | None = None) -> RestoreReport:
    rep = RestoreReport()
    for tier, category, key in deletions:
        try:
            if delete_row(client, tier, category, key):
                rep.deleted += 1
            else:
                rep.skipped.append({"tier": tier, "category": category, "key": key,
                                    "reason": "no SDK delete for this tier"})
        except Exception as e:  # noqa: BLE001
            rep.skipped.append({"tier": tier, "category": category, "key": key, "reason": f"delete failed: {e}"})
    for row in rows:
        try:
            write_row(client, row)
            rep.written += 1
        except Exception as e:  # noqa: BLE001
            rep.skipped.append({"tier": row.tier, "category": row.category, "key": row.key,
                                "reason": f"write failed: {type(e).__name__}: {e}"})
    if verify_db_path is not None and tenant_id is not None:
        wanted = {row_id(r): leaf(r) for r in rows}
        have = {row_id(r): leaf(r) for r in export_rows(verify_db_path, tenant_id)}
        for rid, want in wanted.items():
            got = have.get(rid)
            if got != want:
                tier, category, key = rid.split("\x00", 2)
                rep.mismatched.append({"tier": tier, "category": category or None, "key": key,
                                       "reason": "stored text differs from the anchored leaf after replay"
                                       if got else "row missing after replay"})
    return rep
