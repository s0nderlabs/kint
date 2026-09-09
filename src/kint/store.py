"""The ONE MemoryClient kint and Sibyl's eight tools share, with the cap volunteered.

Sibyl's free-tier cap is per account and `aggregate_db_size` walks five paths
that kint's state is deliberately outside of. kint therefore builds the shared
client with a CapGate whose db_size_fn is Sibyl's own aggregate PLUS kint's
footprint (mirror, epochs cache, keys), so the store kint keeps counts against
the same cap Sibyl enforces. The gate is enforcement, not display: `kint
status` prints Sibyl's number, kint's number and the volunteered total.

Nothing in here touches the chain, an RPC or a signer: the cap gate runs
inside Sibyl's BEGIN IMMEDIATE write lock.
"""

from __future__ import annotations

import os
from pathlib import Path

from sibyl_memory_client import DEFAULT_TENANT, MemoryClient
from sibyl_memory_client._capcheck import CapGate, TierCache, aggregate_db_size
from sibyl_memory_client.storage import Storage
from sibyl_memory_mcp import server as sibyl_server

from . import paths


def load_credentials() -> dict:
    return sibyl_server._load_credentials()


def resolve_tenant(creds: dict | None = None) -> str:
    creds = creds if creds is not None else load_credentials()
    return os.environ.get("KINT_TENANT") or creds.get("tenant_id") or creds.get("account_id") or DEFAULT_TENANT


def volunteered_size_fn(db_path: Path):
    def fn() -> int:
        return aggregate_db_size(db_path) + paths.footprint_bytes()
    return fn


def open_client(db_path: str | Path | None = None, tenant_id: str | None = None) -> MemoryClient:
    """Build the shared client exactly the way Sibyl's server does, plus the volunteered cap."""
    creds = load_credentials()
    db_path = Path(db_path).expanduser() if db_path else paths.sibyl_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tenant = tenant_id or resolve_tenant(creds)
    tier = creds.get("tier", "free")
    storage = Storage(str(db_path))
    gate = CapGate(
        account_id=creds.get("account_id"),
        session_token=creds.get("session_token"),
        db_size_fn=volunteered_size_fn(db_path),
        local_tier_hint=tier,
        cache=TierCache(Path(storage.db_path).parent / "tier_cache.json"),
        credentials_claim={
            "account_id": creds.get("account_id"), "tenant_id": creds.get("tenant_id"),
            "tier": creds.get("tier"), "email": creds.get("email"), "wallet": creds.get("wallet"),
            "issued_at": creds.get("issued_at"),
        } if creds else None,
        credentials_signature=creds.get("signature") if creds else None,
    )
    return MemoryClient(
        storage, tenant_id=tenant, tier=tier, account_id=creds.get("account_id"),
        session_token=creds.get("session_token"), cap_gate=gate,
        credentials_claim=None, credentials_signature=None,
    )


def cap_numbers(db_path: str | Path | None = None) -> dict:
    """Sibyl's aggregate, kint's footprint, the volunteered total and the cap."""
    from sibyl_memory_client._capcheck import FREE_TIER_CAP_BYTES
    db_path = Path(db_path).expanduser() if db_path else paths.sibyl_db_path()
    sibyl = aggregate_db_size(db_path)
    kint = paths.footprint_bytes()
    return {"sibyl_bytes": sibyl, "kint_bytes": kint, "volunteered_total": sibyl + kint,
            "cap_bytes": FREE_TIER_CAP_BYTES, "db_path": str(db_path)}


def seed_sibyl_server_cache(client: MemoryClient) -> None:
    """Make Sibyl's eight tools use kint's client (and its cap gate) without touching their code."""
    with sibyl_server._client_lock:
        sibyl_server._client_cache["client"] = client
        sibyl_server._client_cache["creds_mtime"] = sibyl_server._credentials_mtime()
        sibyl_server._client_cache["creds_path_exists"] = sibyl_server.DEFAULT_CRED_PATH.exists()
