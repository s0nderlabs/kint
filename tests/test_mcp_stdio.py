"""Talk to kint-server over real stdio with the MCP client: their eight tools plus ours."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def _run(coro):
    return asyncio.run(coro)


async def _session_calls(env, calls):
    params = StdioServerParameters(command=sys.executable, args=["-m", "kint.server"], env=env)
    out = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            out.append(sorted(t.name for t in tools.tools))
            for name, args in calls:
                r = await s.call_tool(name, args)
                text = "".join(c.text for c in r.content if getattr(c, "type", "") == "text")
                try:
                    out.append(json.loads(text))
                except Exception:
                    out.append(text)
    return out


def test_server_speaks_stdio_and_keeps_sibyl_tools(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update({
        "KINT_HOME": str(tmp_path / "kint"), "KINT_NO_KEYCHAIN": "1", "KINT_SESSION_PASSPHRASE": "x",
        "SIBYL_MEMORY_DB": str(tmp_path / "sibyl" / "memory.db"), "KINT_NO_WATCHER": "1",
        "KINT_TENANT": "stdio-tenant", "KINT_OFFLINE": "1", "KINT_CONTRACT": "0x" + "11" * 20,
        "KINT_RPC_URL": "http://127.0.0.1:9", "KINT_RPC_URL_2": "http://127.0.0.1:9",
        "PYTHONPATH": str(ROOT / "src"),
    })
    res = _run(_session_calls(env, [
        ("memory_remember", {"category": "rules", "name": "release-gate", "body": {"rule": "never ship on a Friday"}}),
        ("memory_search", {"query": "Friday"}),
        ("memory_status", {}),
        ("memory_connect", {}),
        ("memory_verify", {"query": "Friday"}),
        ("memory_push", {}),
        ("memory_history", {"tier": "entity", "key": "release-gate", "category": "rules"}),
    ]))
    names = res[0]
    for t in ("memory_remember", "memory_recall", "memory_search", "memory_list", "memory_forget",
              "memory_get_state", "memory_set_state", "memory_record_event"):
        assert t in names
    for t in ("memory_status", "memory_connect", "memory_pull", "memory_push", "memory_verify", "memory_history"):
        assert t in names
    remember, search, status, connect, verify, push, hist = res[1:]
    assert remember["ok"] is True
    assert search["count"] == 1 and search["results"][0]["key"] == "release-gate"
    assert status["connected"] is False and status["tenant"] == "stdio-tenant"
    assert status["cap"]["kint_bytes"] >= 0 and status["cap"]["volunteered_total"] >= status["cap"]["sibyl_bytes"]
    assert connect["connected"] is False and any("cast wallet sign" in s for s in connect["human_steps"])
    assert verify["decision"] == "refuse" and "never pulled or pushed" in verify["reason"]
    assert push["ok"] is False and push["error"] == "NOT_CONNECTED"
    assert hist["ok"] is True and hist["count"] == 0
