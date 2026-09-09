"""kint-server: Sibyl's MCP server, untouched, plus kint's tools.

    from sibyl_memory_mcp.server import build_server
    mcp = build_server()          # their eight tools, exactly as shipped
    + memory_status / memory_connect / memory_pull / memory_push / memory_verify / memory_history

Their eight tools use the ONE client kint builds (seeded into their module
cache), so the cap they enforce includes kint's own footprint. Before the
server starts serving, kint pulls whatever the chain has that this machine
has not seen. While serving, a quiet-period watcher pushes unanchored changes
(KINT_QUIET_SECONDS, default 300), and an exit hook pushes best effort.
"""

from __future__ import annotations

import atexit
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

from sibyl_memory_mcp.server import build_server

from . import crypto, keys, paths, store
from .chain import Anchor
from .connect import connect_recovery, connect_smart_account, session_key_info
from .epoch import Mirror
from .log import get_logger
from .push import ChainMoved, KeyExpired, PushError, push, unanchored_changes
from .pull import Fork, NotFresh, PullError, pull
from .verify import at_block, history, verify

_log = get_logger()
_state: dict[str, Any] = {"client": None, "db": None, "tenant": None, "owner": None, "space_hex": None,
                          "first_dirty": None, "last_change": None, "last_mtime": None, "pushing": False,
                          "last_size_check": 0.0}


def _env_num(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        _log.warning(f"{name}={raw!r} is not a number; using {default}")
        return default


def _db_mtime(db: Path) -> float:
    m = 0.0
    for suffix in ("", "-wal"):
        p = Path(str(db) + suffix)
        try:
            m = max(m, p.stat().st_mtime)
        except OSError:
            pass
    return m


def _owner() -> str | None:
    if _state["owner"]:
        return _state["owner"]
    e = keys.Enrolment.load(_state["space_hex"])
    if e:
        _state["owner"] = e.owner
    return _state["owner"]


def _client_factory():
    c = store.open_client(_state["db"], _state["tenant"])
    _state["client"] = c
    store.seed_sibyl_server_cache(c)
    return c


def _do_push(reason: str) -> dict[str, Any]:
    owner = _owner()
    if not owner:
        return {"ok": False, "error": "NOT_CONNECTED", "hint": "call memory_connect"}
    if _state["pushing"]:
        return {"ok": False, "error": "BUSY", "hint": "a push is already running"}
    _state["pushing"] = True
    try:
        rep = push(owner=owner, tenant=_state["tenant"], db_path=_state["db"], log=_log.info)
        _state["first_dirty"] = None
        _state["last_change"] = None
        return {"ok": True, "reason": reason, "pushed": rep.pushed, "changed_rows": rep.changed_rows,
                "deleted_rows": rep.deleted_rows, "head_seq": rep.head_seq, "head_digest": rep.head_digest,
                "epochs": rep.epochs, "message": rep.message}
    except KeyExpired as e:
        return {"ok": False, "error": "KEY_EXPIRED", "message": str(e), "hint": "run `kint connect` on this machine; nothing was dropped"}
    except ChainMoved as e:
        return {"ok": False, "error": "CHAIN_MOVED", "message": str(e), "hint": "call memory_pull first"}
    except PushError as e:
        return {"ok": False, "error": "PUSH_FAILED", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        _log.exception("push failed")
        return {"ok": False, "error": type(e).__name__, "message": str(e)}
    finally:
        _state["pushing"] = False


def _watcher() -> None:
    quiet = _env_num("KINT_QUIET_SECONDS", 300.0)
    poll = max(_env_num("KINT_POLL_SECONDS", 15.0), 1.0)
    size_trigger = _env_num("KINT_SIZE_TRIGGER_BYTES", 32 * 1024)
    db = Path(_state["db"])
    _state["last_mtime"] = _db_mtime(db)
    while True:
        time.sleep(poll)
        try:
            now = time.time()
            m = _db_mtime(db)
            if m != _state["last_mtime"]:
                _state["last_mtime"] = m
                _state["last_change"] = now
                if _state["first_dirty"] is None:
                    _state["first_dirty"] = now
                _log.info("watcher: store changed")
            if _state["first_dirty"] is None or not _owner() or keys.cached_dek(_state["space_hex"]) is None:
                continue
            quiet_for = now - (_state["last_change"] or now)
            big = False
            # the size trigger is checked once a minute while dirty, however busy the agent is
            if now - _state["last_size_check"] >= 60:
                _state["last_size_check"] = now
                try:
                    c, d = unanchored_changes(_state["tenant"], db)
                    if not (c or d):
                        _state["first_dirty"] = None
                        _state["last_change"] = None
                        continue
                    big = (c + d) * 400 > size_trigger
                except Exception:  # noqa: BLE001
                    pass
            if quiet_for >= quiet or big:
                _log.info(f"watcher: pushing ({'size' if big else 'quiet'} trigger)")
                r = _do_push("watcher")
                _log.info(f"watcher: push result {r.get('ok')} {r.get('message', r.get('error'))}")
        except Exception:  # noqa: BLE001
            _log.exception("watcher loop error")


def _bootstrap() -> None:
    owner = _owner()
    if not owner:
        _log.info("bootstrap: not connected (no enrolment); serving anyway, memory_connect explains")
        return
    if keys.cached_dek(_state["space_hex"]) is None:
        _log.info("bootstrap: data key not cached; serving without pull, memory_connect explains")
        return
    try:
        rep = pull(owner=owner, tenant=_state["tenant"], db_path=_state["db"], client_factory=_client_factory, log=_log.info)
        _log.info(f"bootstrap: {rep.message}")
    except Fork as e:
        _log.warning(f"bootstrap: fork, serving local store: {e}")
    except NotFresh as e:
        _log.warning(f"bootstrap: freshness refusal: {e}")
    except Exception as e:  # noqa: BLE001
        _log.warning(f"bootstrap: pull failed ({type(e).__name__}: {e}); serving local store")


def build_kint_server():
    mcp = build_server()
    db = paths.sibyl_db_path()
    tenant = store.resolve_tenant()
    _state.update({"db": db, "tenant": tenant, "space_hex": crypto.space_id(tenant).hex()})
    _client_factory()

    @mcp.tool()
    def memory_status() -> dict[str, Any]:
        """kint: where this memory lives and whether it is in step with Base.

        Returns the owner wallet, the space, the chain head (seq, digest, block), what this
        machine last anchored, how many rows changed since, the session key, whether the data
        key is cached, and the cap accounting (Sibyl's bytes, kint's bytes, the volunteered
        total against the same cap).
        """
        owner = _owner()
        out: dict[str, Any] = {"ok": True, "owner": owner, "tenant": tenant, "space": _state["space_hex"],
                               "db_path": str(db), "connected": owner is not None,
                               "data_key_cached": keys.cached_dek(_state["space_hex"]) is not None,
                               "cap": store.cap_numbers(db)}
        m = Mirror.load(_state["space_hex"])
        out["mirror"] = {"seq": m.seq, "digest": m.digest, "block": m.block, "rows": len(m.rows)} if m else None
        try:
            c, d = unanchored_changes(tenant, db)
            out["unanchored"] = {"changed": c, "deleted": d}
        except Exception as e:  # noqa: BLE001
            out["unanchored"] = {"error": str(e)}
        if owner:
            try:
                a = Anchor()
                h = a.head(owner, crypto.space_id(tenant))
                out["chain_head"] = {"seq": h.seq, "digest": h.digest.hex(), "block": h.block_number,
                                     "contract": a.address}
                out["in_step"] = bool(m and (m.seq, m.digest) == (h.seq, h.digest.hex()))
                out["session_key"] = session_key_info(a, owner)
            except Exception as e:  # noqa: BLE001
                out["chain_head"] = {"error": str(e)}
        return out

    @mcp.tool()
    def memory_connect(passphrase: str | None = None, recovery_code: str | None = None,
                       owner: str | None = None) -> dict[str, Any]:
        """kint: connect this machine to the wallet-owned vault, or say exactly what a human must do.

        With no arguments: reports whether this machine is connected and, if not, the one-line
        terminal command the human runs (sign one frozen EIP-712 message with the wallet, or
        enter the vault passphrase for a Base Account owner). With `passphrase` (smart-account
        owners) or `recovery_code`, connects directly; `owner` is required the first time.
        The derive signature itself is never accepted here: it is a secret and only travels
        through `kint connect --signature -` on stdin.
        """
        cur = _owner()
        if passphrase is None and recovery_code is None:
            if cur and keys.cached_dek(_state["space_hex"]) is not None:
                return {"ok": True, "connected": True, "owner": cur}
            return {"ok": True, "connected": False, "owner": cur, "human_steps": [
                "EOA wallet (Ledger, MetaMask, Rabby, keystore): kint canonical-payload --owner 0x... > kint-canonical.json && "
                "cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0x... --signature -",
                "Base Account / smart wallet owner: kint connect --owner 0x... --smart-account --passphrase-stdin",
                "Lost both? kint connect --owner 0x... --recovery-code-stdin",
            ]}
        owner = owner or cur
        if not owner:
            return {"ok": False, "error": "OWNER_REQUIRED"}
        try:
            if recovery_code is not None:
                r = connect_recovery(owner, tenant, recovery_code)
            else:
                r = connect_smart_account(owner, tenant, passphrase)
            _state["owner"] = r.owner
            out = {"ok": True, "owner": r.owner, "space": r.space, "kek_tag8": r.kek_tag8, "fresh_vault": r.fresh_vault,
                   "dek_source": r.dek_source}
            if r.recovery_code:
                out["recovery_code_file"] = str(paths.recovery_path(r.space))
                out["note"] = "a fresh vault was created; the recovery code is in that file, copy it somewhere safe"
            return out
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": type(e).__name__, "message": str(e)}

    @mcp.tool()
    def memory_pull(discard_local: bool = False, force_scan: bool = False) -> dict[str, Any]:
        """kint: restore/refresh this machine's Sibyl store from Base.

        Checks freshness first (watermark; two RPCs on a cold start), refuses over a fork
        (local unanchored changes while the chain moved) unless discard_local, then walks the
        epochs from the head, verifies each against the chain, decrypts, and replays the rows
        through Sibyl's own write methods. Reports every epoch it had to skip.
        """
        owner = _owner()
        if not owner:
            return {"ok": False, "error": "NOT_CONNECTED", "hint": "call memory_connect"}
        try:
            rep = pull(owner=owner, tenant=tenant, db_path=db, client_factory=_client_factory,
                       discard_local=discard_local, force_scan=force_scan, log=_log.info)
            return {"ok": True, "applied": rep.applied, "skipped": rep.skipped, "head_seq": rep.head_seq,
                    "head_digest": rep.head_digest, "head_block": rep.head_block, "rows_total": rep.rows_total,
                    "root_ok": rep.root_ok, "rpcs_agreed": rep.rpcs_agreed, "message": rep.message}
        except Fork as e:
            return {"ok": False, "error": "FORK", "message": str(e)}
        except NotFresh as e:
            return {"ok": False, "error": "NOT_FRESH", "message": str(e)}
        except PullError as e:
            return {"ok": False, "error": "PULL_FAILED", "message": str(e)}
        except Exception as e:  # noqa: BLE001
            _log.exception("pull failed")
            return {"ok": False, "error": type(e).__name__, "message": str(e)}

    @mcp.tool()
    def memory_push() -> dict[str, Any]:
        """kint: anchor every unanchored change now (diff against the last anchored epoch,
        compress, pad to a size bucket, encrypt to the wallet, one Base transaction per epoch
        from this machine's session key)."""
        return _do_push("tool")

    @mcp.tool()
    def memory_verify(query: str, limit: int = 5) -> dict[str, Any]:
        """kint: before acting on something recalled, verify it against Base and get a decision.

        Runs Sibyl's own memory_search for `query` (typed verdict included), re-reads the exact
        stored text of every hit, hashes it and checks it against the leaf this machine last saw
        anchored (merkle inclusion proof against the anchored rows_root). Returns
        decision = "proceed" or "refuse" with the reason. A row whose text no longer matches
        what the chain vouches for is refused, naming the block that anchored the last good
        value and the current head block, and the refusal is written back as a Sibyl entity
        (category kint_refusal) so the next fresh session sees it too.
        """
        client = _state["client"]
        try:
            res = verify(client, query=query, limit=limit, space_hex=_state["space_hex"], db_path=db, tenant=tenant)
            d = res.to_dict()
            d["ok"] = True
            return d
        except Exception as e:  # noqa: BLE001
            _log.exception("verify failed")
            return {"ok": False, "error": type(e).__name__, "message": str(e)}

    @mcp.tool()
    def memory_history(tier: str, key: str, category: str | None = None, block: int | None = None) -> dict[str, Any]:
        """kint: what this row held at every anchored epoch (temporal read Sibyl cannot do).

        tier is entity | state | reference; key is the entity name / state key / reference key;
        category is required for entities. Each version carries a block-height upper bound
        ("existed no later than block N"), never a wall-clock time. With `block`, returns the
        version that was live at that block.
        """
        try:
            if block is not None:
                v = at_block(_state["space_hex"], tier, key, category, block)
                return {"ok": True, "at_block": block, "version": v}
            hs = history(_state["space_hex"], tier, key, category)
            return {"ok": True, "versions": hs, "count": len(hs)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": type(e).__name__, "message": str(e)}

    return mcp


def main() -> None:
    mcp = build_kint_server()
    _bootstrap()
    if os.environ.get("KINT_NO_WATCHER") != "1":
        threading.Thread(target=_watcher, daemon=True, name="kint-watcher").start()

    def _exit_push(*_a):
        # best effort: diff the store against the mirror (push() returns at once when nothing changed)
        try:
            if _owner() and keys.cached_dek(_state["space_hex"]) is not None and not _state["pushing"]:
                _log.info("exit: pushing unanchored changes if any (best effort)")
                r = _do_push("exit")
                _log.info(f"exit: {r.get('message', r.get('error'))}")
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_exit_push)

    def _on_term(signum, _frame):
        _exit_push()
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _on_term)
        except (ValueError, OSError):
            pass
    _log.info(f"kint-server: serving Sibyl's tools plus kint's on stdio (tenant {_state['tenant']}, db {_state['db']})")
    mcp.run()


if __name__ == "__main__":
    main()
