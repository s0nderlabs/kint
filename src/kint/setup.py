"""Point a harness at kint-server instead of sibyl-memory-mcp.

`kint setup` and `kint join` both call `register`; it returns the lines to print
instead of printing them, so both commands say exactly the same thing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

TARGETS = ["claude", "codex", "hermes", "openclaw"]


class SetupError(Exception):
    pass


def server_bin() -> str:
    """The kint-server executable: next to the running kint, else on PATH."""
    p = Path(sys.argv[0]).resolve().parent / "kint-server"
    if p.exists():
        return str(p)
    w = shutil.which("kint-server")
    if w:
        return str(Path(w).resolve())
    raise SetupError("kint-server not found next to kint or on PATH")


def expand_targets(target: str) -> list[str]:
    return list(TARGETS) if target == "all" else [target]


def register(targets: list[str], extra_env: dict[str, str], binpath: str) -> list[tuple[str, str, list[str]]]:
    """Register kint-server with each harness. Returns (target, status, lines) per target,
    status one of ok | skipped | failed; the lines are what the command prints, verbatim."""
    out: list[tuple[str, str, list[str]]] = []
    for t in targets:
        try:
            out.append(_one(t, extra_env, binpath))
        except Exception as e:  # noqa: BLE001
            out.append((t, "failed", [f"{t}: failed: {e}"]))
    return out


def _one(t: str, extra_env: dict[str, str], binpath: str) -> tuple[str, str, list[str]]:
    if t == "claude":
        if not shutil.which("claude"):
            return (t, "skipped", ["claude: CLI not found, skipped"])
        subprocess.run(["claude", "mcp", "remove", "-s", "user", "kint"], capture_output=True)
        cmd = ["claude", "mcp", "add", "--scope", "user", "kint", "-e", "PYTHONPATH=x"]
        for k, v in extra_env.items():
            cmd += ["-e", f"{k}={v}"]
        # PYTHONPATH=x: a non-empty dummy so the user's polluting PYTHONPATH is replaced, never inherited
        r = subprocess.run(cmd + ["--", "/usr/bin/env", "-u", "PYTHONPATH", binpath], capture_output=True, text=True)
        ok = r.returncode == 0
        return (t, "ok" if ok else "failed", [
            f"claude: {'registered kint (user scope)' if ok else 'failed: ' + (r.stderr or r.stdout)[:200]}",
            "  claude: `claude mcp remove -s user sibyl-memory` if Sibyl's own server is also registered (one store, one server)",
        ])
    if t == "codex":
        cfg = Path.home() / ".codex" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        text = cfg.read_text() if cfg.exists() else ""
        if "[mcp_servers.kint]" in text:
            return (t, "ok", ["codex: already configured"])
        if cfg.exists():
            shutil.copy(cfg, cfg.with_suffix(f".toml.bak-{int(time.time())}"))
        env_lines = "".join(f'{k} = "{v}"\n' for k, v in extra_env.items())
        block = f'\n[mcp_servers.kint]\ncommand = "{binpath}"\nargs = []\n\n[mcp_servers.kint.env]\nPYTHONPATH = ""\n{env_lines}'
        cfg.write_text(text.rstrip("\n") + "\n" + block)
        return (t, "ok", [f"codex: wrote [mcp_servers.kint] to {cfg}"])
    if t == "hermes":
        if not shutil.which("hermes"):
            return (t, "skipped", ["hermes: CLI not found, skipped"])
        hcmd = ["hermes", "mcp", "add", "kint", "--command", "/usr/bin/env"]
        hargs = ["PYTHONPATH="] + [f"{k}={v}" for k, v in extra_env.items()] + [binpath]
        r = subprocess.run(hcmd + ["--args"] + hargs, capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0
        return (t, "ok" if ok else "failed", [
            f"hermes: {'registered kint' if ok else 'failed: ' + (r.stderr or r.stdout)[:200]}",
            "  hermes: SDK-direct alternative: `kint pull` before launch, `kint push` after, store at $SIBYL_MEMORY_DB",
        ])
    if t == "openclaw":
        if not shutil.which("openclaw"):
            return (t, "skipped", ["openclaw: CLI not found, skipped"])
        spec = json.dumps({"command": "/usr/bin/env",
                           "args": ["PYTHONPATH="] + [f"{k}={v}" for k, v in extra_env.items()] + [binpath]})
        r = subprocess.run(["openclaw", "mcp", "set", "kint", spec], capture_output=True, text=True, timeout=120)
        o = "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "string-bridge" not in l)
        ok = r.returncode == 0
        return (t, "ok" if ok else "failed",
                [f"openclaw: {'saved MCP server kint (openclaw mcp set)' if ok else 'failed: ' + o[:200]}"])
    raise SetupError(f"unknown harness {t}")
