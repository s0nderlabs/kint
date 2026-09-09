import os
import pytest
from pathlib import Path


@pytest.fixture
def sibyl_store(tmp_path):
    """A fresh Sibyl store + client in a temp dir, isolated from ~/.sibyl-memory."""
    from sibyl_memory_client import MemoryClient
    db = tmp_path / "memory.db"
    client = MemoryClient.local(str(db), tenant_id="demo-tenant")
    yield client, db, "demo-tenant"
    try:
        client.storage.close()
    except Exception:
        pass


def seed(client):
    """Write through all four tiers the way an agent would."""
    client.set_entity("rules", "release-gate", {"rule": "never ship on a Friday", "since": "2026-05-01", "owner": "elpabl0"})
    client.set_entity("people", "alice", {"role": "reviewer", "tz": "WIB"}, status="active")
    client.set_entity("people", "bob", ["a", "list", "body"])
    client.set_state("priorities", {"top": ["kint", "sigil"], "note": "unicode ok: café ünïcode"})
    client.set_state("session", {"last": "2026-09-09"})
    client.set_reference("runbook", "# Runbook\n\nStep one. Step two.", metadata={"format": "md", "v": 2})
    client.set_reference("plain", "just text")
    client.write_event(acted={"kind": "decision", "body": {"what": "chose passphrase wrap"}},
                       extra={"category": "rules", "name": "release-gate"}, ts="2026-09-09T10:00:00.000Z")
    client.write_event(evaluated={"q": "ship?"}, forward={"next": "verify first"}, ts="2026-09-09T10:00:01.000Z")
