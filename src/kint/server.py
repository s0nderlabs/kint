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
import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

from sibyl_memory_mcp.server import build_server

from . import crypto, keys, paths, store
from .canon import leaf, row_id
from .chain import Anchor, redact
from .connect import connect_recovery, connect_smart_account, session_key_info
from .epoch import Mirror
from .export import export_rows, read_row
from .log import get_logger
from .push import ChainMoved, KeyExpired, PushError, push, unanchored_changes
from .pull import Fork, NotFresh, PullError, pull
from .verify import REFUSAL_CATEGORY, at_block, history, verify

_log = get_logger()
_state: dict[str, Any] = {"client": None, "db": None, "tenant": None, "owner": None, "space_hex": None,
                          "first_dirty": None, "last_change": None, "last_mtime": None, "pushing": False,
                          "last_size_check": 0.0, "baseline": {}, "held": None, "terminating": False, "exit_pushed": False,
                          "replaying": 0, "retry_after": 0.0, "push_backoff": 0.0, "head_cache": None}


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
    _watch_tool_writes(c)
    _state["client"] = c
    store.seed_sibyl_server_cache(c)
    return c


# ---------------------------------------------------------------------------
# The drift hold: an auto-push must never launder a change made behind Sibyl's tools
# ---------------------------------------------------------------------------

def _note_tool_write(tier: str, key: str, category: str | None) -> None:
    """Move one row's baseline to what the tool path just wrote, so the same value is not
    later read as a change made behind Sibyl's back.

    Copy-on-write: tool calls run on their own threads and the hold check reads the whole
    baseline, so it is replaced wholesale instead of mutated under a reader.
    """
    rid = f"{tier}\x00{category or ''}\x00{key}"
    try:
        row = read_row(_state["db"], _state["tenant"], tier, key, category)
    except Exception:  # noqa: BLE001
        row = None
    base = dict(_state["baseline"] or {})
    if row is None:
        base.pop(rid, None)
    else:
        base[rid] = leaf(row).hex()
    _state["baseline"] = base


def _watch_tool_writes(client) -> None:
    """Follow every row this server's OWN tool path writes.

    Sibyl's eight tools and kint's own use this one client, so a row whose stored text changed
    while the server was running WITHOUT a write through them changed behind their back (edited
    straight in SQLite, say). Nothing here says anything about a row that changed before this
    server started: that is not knowable, and a push is never held on that ground alone.
    """
    def wrap(name: str, rid_of) -> None:
        original = getattr(client, name, None)
        if original is None:
            return

        def wrapped(*a, **k):
            out = original(*a, **k)
            if _state.get("replaying"):
                return out   # a pull's replay rebuilds the whole baseline once when it returns
            try:
                tier, key, category = rid_of(*a, **k)
                if key:
                    _note_tool_write(tier, key, category)
            except Exception:  # noqa: BLE001
                pass
            return out

        setattr(client, name, wrapped)

    wrap("set_entity", lambda category=None, name=None, *a, **k: ("entity", name, category))
    wrap("archive_entity", lambda category=None, name=None, *a, **k: ("entity", name, category))
    wrap("delete_entity", lambda category=None, name=None, *a, **k: ("entity", name, category))
    wrap("set_state", lambda key=None, *a, **k: ("state", key, None))
    wrap("set_reference", lambda key=None, *a, **k: ("reference", key, None))


def _store_leaves() -> dict[str, str]:
    try:
        return {row_id(r): leaf(r).hex() for r in export_rows(_state["db"], _state["tenant"])}
    except Exception:  # noqa: BLE001
        return {}


def _reset_drift_baseline() -> None:
    """What the store held the last time kint and the chain agreed about it."""
    _state["baseline"] = _store_leaves()


def _pull_then_rebaseline(**kw):
    """A pull replays rows through the same wrapped client the tools use; the per-row drift
    bookkeeping is pointless there (the baseline is rebuilt wholesale right after) and quadratic,
    so it is switched off for the duration and rebuilt once."""
    _state["replaying"] = (_state.get("replaying") or 0) + 1
    try:
        rep = pull(**kw)
    finally:
        _state["replaying"] -= 1
    _reset_drift_baseline()
    _renew_data_key()
    return rep


def _renew_data_key() -> None:
    """Move the cached data key's deadline forward. The cache has a TTL (KINT_KEY_TTL, 24 h by
    default) and a server that is being used should never lapse into serving without a pull or an
    auto-push: every successful pull and push renews it."""
    try:
        dek = keys.cached_dek(_state["space_hex"])
        if dek is not None:
            keys.cache_dek(_state["space_hex"], dek)
    except Exception:  # noqa: BLE001
        _log.debug("could not renew the data key cache deadline")


HEAD_CACHE_SECONDS = 30.0   # a verify reuses the last head read this long; an RPC is never asked once per decision
HEAD_READ_TIMEOUT = 3       # seconds; the decision beat must not hang on a dead endpoint


def _chain_head_best_effort() -> dict[str, Any] | None:
    """The chain head for this space, or None when it cannot be read (never a verdict).
    Read here, outside every Sibyl write transaction, and handed to verify as data. Cached for
    HEAD_CACHE_SECONDS, failures included, so a burst of verifies costs one short RPC read."""
    if os.environ.get("KINT_OFFLINE") == "1":
        return None
    owner = _owner()
    if not owner:
        return None
    now = time.time()
    cached = _state.get("head_cache")
    if cached and now - cached[0] < HEAD_CACHE_SECONDS:
        return cached[1]
    try:
        h = Anchor(timeout=HEAD_READ_TIMEOUT).head(owner, crypto.space_id(_state["tenant"]))
        value = {"seq": h.seq, "digest": h.digest.hex(), "block": h.block_number}
    except Exception as e:  # noqa: BLE001
        _log.info(f"chain head unavailable ({type(e).__name__}: {redact(str(e))}); "
                  "verifying against the local mirror only")
        value = None
    _state["head_cache"] = (now, value)
    return value


def _refused_leaves(rows) -> dict[str, str]:
    """row_id -> the exact leaf a kint_refusal entity refused, from the refusals in the store.

    A refusal whose local_leaf is empty named no value at all (verify refuses a row that is MISSING
    with local_leaf null), so it is skipped here: it says nothing about the value the row holds now,
    and holding every later value of that row forever would make one refusal wedge the row for good.
    """
    out: dict[str, str] = {}
    for r in rows:
        if r.tier != "entity" or r.category != REFUSAL_CATEGORY or not r.body:
            continue
        try:
            b = json.loads(r.body)
        except Exception:  # noqa: BLE001
            continue
        refused_leaf = b.get("local_leaf")
        if b.get("refused") and b.get("tier") and b.get("key") and refused_leaf:
            out[f"{b['tier']}\x00{b.get('category') or ''}\x00{b['key']}"] = refused_leaf
    return out


def _name_of(rid: str) -> str:
    tier, category, key = rid.split("\x00", 2)
    return f"{tier} {(category + '/') if category else ''}{key}"


def _hold_reason() -> str | None:
    """Why this push must NOT go to the chain, or None.

    Two grounds, both about a row whose stored text no longer matches the leaf this machine last
    saw anchored: kint already refused exactly this value (a kint_refusal entity names it), or the
    row changed while this server was running without any write through its own tool path.
    """
    mirror = Mirror.load(_state["space_hex"])
    if mirror is None or mirror.seq == 0:
        return None
    try:
        rows = export_rows(_state["db"], _state["tenant"])
    except Exception as e:  # noqa: BLE001
        # a store that cannot be read cannot be checked for drift, and an unchecked push is
        # exactly what this hold exists to prevent: fail closed
        _log.error("hold check: the store could not be read: %s: %s", type(e).__name__, redact(str(e)))   # never a raw traceback: an RPC error carries the keyed URL
        return ("refusing to anchor: the store could not be read to check for drift. Nothing was anchored and "
                "nothing was dropped; check the store, then `kint push` from your own terminal.")
    current = {row_id(r): leaf(r).hex() for r in rows}
    # one snapshot: tool threads move the baseline while this runs (copy-on-write, so the dict
    # this holds is never the one being replaced)
    baseline = dict(_state["baseline"] or {})
    refused = _refused_leaves(rows)
    refused_rows, behind_rows = [], []
    for rid, lf in current.items():
        anchored = mirror.leaves.get(rid)
        if anchored is None or anchored == lf:
            continue   # never anchored yet, or unchanged since it was: not drift
        if refused.get(rid) == lf:
            refused_rows.append(rid)
        elif baseline.get(rid) not in (None, lf):
            behind_rows.append(rid)
    for rid, base in baseline.items():
        if rid not in current and mirror.leaves.get(rid) == base:
            behind_rows.append(rid)
    if not refused_rows and not behind_rows:
        return None
    parts = []
    if refused_rows:
        parts.append(f"{len(refused_rows)} row(s) kint already refused ({', '.join(_name_of(r) for r in refused_rows[:3])})")
    if behind_rows:
        parts.append(f"{len(behind_rows)} row(s) changed behind Sibyl's tools while this server was running "
                     f"({', '.join(_name_of(r) for r in behind_rows[:3])})")
    return ("refusing to anchor: " + " and ".join(parts) + ". Anchoring would make the chain vouch for a value "
            "kint cannot account for. Check the store, then `kint push` from your own terminal (or `kint pull "
            "--discard-local` to restore the anchored value).")


def _do_push(reason: str, snapshot: bool = False) -> dict[str, Any]:
    owner = _owner()
    if not owner:
        return {"ok": False, "error": "NOT_CONNECTED", "hint": "call memory_connect"}
    if _state["pushing"]:
        return {"ok": False, "error": "BUSY", "hint": "a push is already running"}
    hold = _hold_reason()
    if hold:
        if not (_state["held"] and _state["held"].get("message") == hold):
            _log.warning(f"push HELD ({reason}): {hold}")
        _state["held"] = {"message": hold, "reason": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        return {"ok": False, "error": "HELD", "message": hold,
                "hint": "nothing was anchored and nothing was dropped; memory_verify still refuses the row"}
    _state["held"] = None
    _state["pushing"] = True
    try:
        rep = push(owner=owner, tenant=_state["tenant"], db_path=_state["db"], snapshot=snapshot, log=_log.info)
        _state["first_dirty"] = None
        _state["last_change"] = None
        _reset_drift_baseline()
        _renew_data_key()
        return {"ok": True, "reason": reason, "pushed": rep.pushed, "changed_rows": rep.changed_rows,
                "deleted_rows": rep.deleted_rows, "head_seq": rep.head_seq, "head_digest": rep.head_digest,
                "epochs": rep.epochs, "message": rep.message}
    except KeyExpired as e:
        return {"ok": False, "error": "KEY_EXPIRED", "message": redact(str(e)), "hint": "run `kint connect` on this machine; nothing was dropped"}
    except ChainMoved as e:
        return {"ok": False, "error": "CHAIN_MOVED", "message": redact(str(e)), "hint": "call memory_pull first"}
    except PushError as e:
        return {"ok": False, "error": "PUSH_FAILED", "message": redact(str(e))}
    except Exception as e:  # noqa: BLE001
        _log.error("push failed: %s: %s", type(e).__name__, redact(str(e)))   # never a raw traceback: an RPC error carries the keyed URL
        return {"ok": False, "error": type(e).__name__, "message": redact(str(e))}
    finally:
        _state["pushing"] = False


def _seed_from_leftovers(db: Path) -> None:
    """An earlier session may have been killed before its exit push finished (Claude Code allows
    about 500 ms). Those rows are still unanchored, and this session is the one that can anchor
    them, so the watcher starts dirty instead of waiting for the next write."""
    try:
        c, d = unanchored_changes(_state["tenant"], db)
    except Exception:  # noqa: BLE001
        _log.debug("watcher: could not count unanchored changes at start")
        return
    if c or d:
        _state["first_dirty"] = _state["last_change"] = time.time()
        _log.info(f"watcher: {c} changed and {d} deleted row(s) were left unanchored by an earlier session; "
                  f"they are pushed at the next quiet period")


def _watcher() -> None:
    quiet = _env_num("KINT_QUIET_SECONDS", 300.0)
    poll = max(_env_num("KINT_POLL_SECONDS", 15.0), 1.0)
    size_trigger = _env_num("KINT_SIZE_TRIGGER_BYTES", 32 * 1024)
    db = Path(_state["db"])
    _state["last_mtime"] = _db_mtime(db)
    _seed_from_leftovers(db)
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
            if (quiet_for >= quiet or big) and now >= _state.get("retry_after", 0.0):
                _log.info(f"watcher: pushing ({'size' if big else 'quiet'} trigger)")
                r = _do_push("watcher")
                _log.info(f"watcher: push result {r.get('ok')} {r.get('message', r.get('error'))}")
                if r.get("error") == "HELD":
                    # wait for the store to change again instead of retrying the same held push
                    _state["first_dirty"] = None
                    _state["last_change"] = None
                    _state["push_backoff"] = 0.0
                elif r.get("ok"):
                    _state["push_backoff"] = 0.0
                else:
                    # an unauthorized key, a moved chain, a dead RPC: the same failure every poll is
                    # a round trip wasted every 15 s, so each failure doubles the wait (1 min to 1 h)
                    _state["push_backoff"] = min(max(2 * _state.get("push_backoff", 0.0), 60.0), 3600.0)
                    _state["retry_after"] = now + _state["push_backoff"]
                    _log.info(f"watcher: next push attempt in {int(_state['push_backoff'])} s")
        except Exception as e:  # noqa: BLE001
            _log.error("watcher loop error: %s: %s", type(e).__name__, redact(str(e)))   # never a raw traceback: an RPC error carries the keyed URL


def _bootstrap() -> None:
    owner = _owner()
    if not owner:
        _log.info("bootstrap: not connected (no enrolment); serving anyway, memory_connect explains")
        return
    if keys.cached_dek(_state["space_hex"]) is None:
        _log.info("bootstrap: data key not cached; serving without pull, memory_connect explains")
        return
    try:
        rep = _pull_then_rebaseline(owner=owner, tenant=_state["tenant"], db_path=_state["db"],
                                    client_factory=_client_factory, log=_log.info)
        _log.info(f"bootstrap: {rep.message}")
    except Fork as e:
        _log.warning(f"bootstrap: fork, serving local store: {redact(str(e))}")
    except NotFresh as e:
        _log.warning(f"bootstrap: freshness refusal: {redact(str(e))}")
    except Exception as e:  # noqa: BLE001
        _log.warning(f"bootstrap: pull failed ({type(e).__name__}: {redact(str(e))}); serving local store")


def build_kint_server():
    mcp = build_server()
    db = paths.sibyl_db_path()
    tenant = store.resolve_tenant()
    _state.update({"db": db, "tenant": tenant, "space_hex": crypto.space_id(tenant).hex()})
    _client_factory()
    _reset_drift_baseline()

    @mcp.tool()
    def memory_status() -> dict[str, Any]:
        """kint: where this memory lives and whether it is in step with Base.

        Returns the owner wallet, the space, the chain head (seq, digest, block), what this
        machine last anchored, how many rows changed since, the session key, whether the data
        key is cached, whether a push is being HELD (a row changed behind Sibyl's tools or kint
        already refused it), and the cap accounting (Sibyl's bytes, kint's bytes, the volunteered
        total against the same cap).
        """
        owner = _owner()
        try:
            h = _hold_reason()
            _state["held"] = ({"message": h, "reason": (_state["held"] or {}).get("reason", "status"),
                               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} if h else None)
        except Exception:  # noqa: BLE001
            pass
        out: dict[str, Any] = {"ok": True, "owner": owner, "tenant": tenant, "space": _state["space_hex"],
                               "db_path": str(db), "connected": owner is not None,
                               "data_key_cached": keys.cached_dek(_state["space_hex"]) is not None,
                               "held": _state["held"], "cap": store.cap_numbers(db)}
        m = Mirror.load(_state["space_hex"])
        out["mirror"] = {"seq": m.seq, "digest": m.digest, "block": m.block, "rows": len(m.rows)} if m else None
        try:
            c, d = unanchored_changes(tenant, db)
            out["unanchored"] = {"changed": c, "deleted": d}
        except Exception as e:  # noqa: BLE001
            out["unanchored"] = {"error": redact(str(e))}
        if owner:
            try:
                a = Anchor()
                h = a.head(owner, crypto.space_id(tenant))
                out["chain_head"] = {"seq": h.seq, "digest": h.digest.hex(), "block": h.block_number,
                                     "contract": a.address}
                out["in_step"] = bool(m and (m.seq, m.digest) == (h.seq, h.digest.hex()))
                out["session_key"] = session_key_info(a, owner)
            except Exception as e:  # noqa: BLE001
                out["chain_head"] = {"error": redact(str(e))}
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
            return {"ok": False, "error": type(e).__name__, "message": redact(str(e))}

    @mcp.tool()
    def memory_pull(discard_local: bool = False, force_scan: bool = False, full: bool = False) -> dict[str, Any]:
        """kint: restore/refresh this machine's Sibyl store from Base.

        Checks freshness first (watermark; two RPCs on a cold start), refuses over a fork
        (local unanchored changes while the chain moved) unless discard_local, then walks the
        epochs from the head, verifies each against the chain, decrypts, and replays the rows
        through Sibyl's own write methods. Reports every epoch it had to skip. The walk stops
        at the newest snapshot epoch (its rows are the whole state); `full` walks past snapshots
        to the first epoch, which is what you want when the older versions matter too.
        """
        owner = _owner()
        if not owner:
            return {"ok": False, "error": "NOT_CONNECTED", "hint": "call memory_connect"}
        try:
            rep = _pull_then_rebaseline(owner=owner, tenant=tenant, db_path=db, client_factory=_client_factory,
                                        discard_local=discard_local, force_scan=force_scan, full=full, log=_log.info)
            return {"ok": True, "applied": rep.applied, "skipped": rep.skipped, "head_seq": rep.head_seq,
                    "head_digest": rep.head_digest, "head_block": rep.head_block, "rows_total": rep.rows_total,
                    "root_ok": rep.root_ok, "rpcs_agreed": rep.rpcs_agreed, "unopenable": rep.unopenable,
                    "backfilled": rep.backfilled, "message": rep.message}
        except Fork as e:
            return {"ok": False, "error": "FORK", "message": redact(str(e))}
        except NotFresh as e:
            return {"ok": False, "error": "NOT_FRESH", "message": redact(str(e))}
        except PullError as e:
            return {"ok": False, "error": "PULL_FAILED", "message": redact(str(e))}
        except Exception as e:  # noqa: BLE001
            _log.error("pull failed: %s: %s", type(e).__name__, redact(str(e)))   # never a raw traceback: an RPC error carries the keyed URL
            return {"ok": False, "error": type(e).__name__, "message": redact(str(e))}

    @mcp.tool()
    def memory_push(snapshot: bool = False) -> dict[str, Any]:
        """kint: anchor every unanchored change now (diff against the last anchored epoch,
        compress, pad to a size bucket, encrypt to the wallet, one Base transaction per epoch
        from this machine's session key).

        With `snapshot`, anchor ONE epoch carrying the whole state instead of the diff (the
        same thing `kint compact` does), even when nothing changed: a restore on a new machine
        can then stop at that epoch instead of replaying the whole history.

        A push is HELD (error "HELD", nothing anchored, nothing dropped) when a row that the
        chain already vouches for changed behind Sibyl's tools while this server was running, or
        when kint already refused exactly that value: the chain must never be made to vouch for a
        change kint cannot account for. memory_status carries the same reason.
        """
        return _do_push("tool", snapshot=snapshot)

    # There is deliberately no memory_rekey tool. Rotating the data key needs the wallet
    # signature or the vault passphrase, and those never travel through an agent chat:
    # `kint rekey` reads them on stdin in the human's own terminal.

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
            res = verify(client, query=query, limit=limit, space_hex=_state["space_hex"], db_path=db, tenant=tenant,
                         chain_head=_chain_head_best_effort())
            d = res.to_dict()
            d["ok"] = True
            return d
        except Exception as e:  # noqa: BLE001
            _log.error("verify failed: %s: %s", type(e).__name__, redact(str(e)))   # never a raw traceback: an RPC error carries the keyed URL
            return {"ok": False, "error": type(e).__name__, "message": redact(str(e))}

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
            return {"ok": False, "error": type(e).__name__, "message": redact(str(e))}

    return mcp


def main() -> None:
    mcp = build_kint_server()
    # the bootstrap pull talks to an RPC, and a hung endpoint must never keep the tools from
    # being listed: it runs on its own thread and gets a wall-clock budget, after which the
    # server serves and the pull carries on behind it
    boot = threading.Thread(target=_bootstrap, daemon=True, name="kint-bootstrap")
    boot.start()
    boot.join(_env_num("KINT_BOOTSTRAP_SECONDS", 20.0))
    if boot.is_alive():
        _log.warning("bootstrap: still running; serving now, the pull finishes in the background")
    if os.environ.get("KINT_NO_WATCHER") != "1":
        threading.Thread(target=_watcher, daemon=True, name="kint-watcher").start()

    def _exit_push(*_a):
        # Best effort, and no more than that: this runs once, only while the process is still
        # unwinding (a killed process anchors nothing), and it anchors nothing when the push is
        # HELD or when the store already matches the mirror. Whatever it does not anchor stays
        # unanchored in the store, and the next session picks it up (_seed_from_leftovers).
        if _state["exit_pushed"]:
            return
        _state["exit_pushed"] = True
        try:
            if _owner() and keys.cached_dek(_state["space_hex"]) is not None and not _state["pushing"]:
                _log.info("exit: pushing unanchored changes if any (best effort)"
                          + (", after a termination signal" if _state["terminating"] else ""))
                r = _do_push("exit")
                _log.info(f"exit: {r.get('message', r.get('error'))}")
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_exit_push)

    def _on_term(signum, _frame):
        # NOTHING that touches the chain runs in the handler: it can fire in the middle of a
        # Sibyl write transaction. Unwind first; the atexit hook then runs the exit push once,
        # after the tool's transaction has finished.
        _state["terminating"] = True
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
