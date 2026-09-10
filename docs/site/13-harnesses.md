---
slug: harnesses
title: Harnesses
description: The two doors into kint, what kint setup writes for each harness, and what was verified on each one.
group: Operate
order: 13
source: 'src/kint/cli.py'
---

# One store per machine, one server in front of it.

kint never connects to a harness: it wraps Sibyl's store, and harnesses already talk to Sibyl. This page covers the two doors in, what `kint setup` writes for each harness, and what was verified.

## Two doors

| door | harnesses | how memory is read | restore and verify |
|---|---|---|---|
| MCP (stdio) | Claude Code, Codex, Hermes (`hermes mcp add`), OpenClaw, any other MCP client | the harness calls Sibyl's eight `memory_*` tools, served by `kint-server` next to kint's six | `kint-server` pulls on start; `memory_verify` before acting; `memory_push` on quiet, on demand, on exit |
| SDK-direct | Hermes's Sibyl memory provider, LangGraph, any Python process | the process opens Sibyl's `memory.db` itself | `kint pull` before launch, `kint push` after, `kint verify "query"` from a shell |

The MCP door is the one that refuses before the agent acts: `memory_verify` is a tool call inside the session. An SDK-direct process gets the integrity check at pull time instead, where every epoch is verified against the chain before a row is replayed. Both doors read and write the same kind of file, so a machine can use either, one store at a time.

`kint-server` takes no flags. It speaks MCP on stdio and logs to stderr and `~/.kint/kint.log`, never stdout. When the machine is connected and the data key is cached, it pulls on start and waits for that pull up to `KINT_BOOTSTRAP_SECONDS` (20 by default) before it lists its tools; a longer pull finishes behind the server (see [kint-server pulls before it serves](/docs/new-machine#kint-server-pulls-before-it-serves)).

## kint setup

```sh
kint setup all --env KINT_TENANT=kint-demo
```

The target is `all`, `claude`, `codex`, `hermes` or `openclaw`; `all` runs the four in that order. `--env KEY=VALUE` is repeatable and every value must contain `=`. Setup looks for `kint-server` next to the `kint` binary, then on `PATH`, and writes its resolved absolute path into each registration. Without it, setup stops with `kint: kint-server not found next to kint or on PATH`. A target whose CLI is missing prints `<target>: CLI not found, skipped` (Codex needs no CLI: setup writes its file), and a target that fails prints `<target>: failed: ...` while the rest carry on:

```text
claude: registered kint (user scope)
  claude: `claude mcp remove -s user sibyl-memory` if Sibyl's own server is also registered (one store, one server)
codex: wrote [mcp_servers.kint] to <home>/.codex/config.toml
hermes: registered kint
  hermes: SDK-direct alternative: `kint pull` before launch, `kint push` after, store at $SIBYL_MEMORY_DB
openclaw: saved MCP server kint (openclaw mcp set)
```

Every registration keeps your shell's `PYTHONPATH` out of the server, because a polluting one shadows the tool's environment. Claude Code gets `-e PYTHONPATH=x` (a dummy that replaces the inherited value) and launches through `/usr/bin/env -u PYTHONPATH`. Codex sets `PYTHONPATH = ""`. Hermes and OpenClaw launch `/usr/bin/env PYTHONPATH= ... kint-server`.

> **Warning.** `--env` values are written into the harness's own configuration in plain text: `~/.codex/config.toml`, Claude Code's MCP registration, Hermes's and OpenClaw's server definitions. Put the tenant and the store path there, never the derive signature, a vault passphrase or a recovery code.

`kint join` runs the same registration as its last step: every harness it finds by default, `--setup <name>` for one, `--no-setup` for none, with `KINT_TENANT` always pinned to the tenant it joined, plus any `--env KEY=VALUE` ([One command: kint join](/docs/new-machine#one-command-kint-join)).

## Pin the tenant

`kint-server` resolves its own tenant: `KINT_TENANT`, else `tenant_id` then `account_id` from Sibyl's `credentials.json`, else Sibyl's default tenant. The global `--tenant` and `--db` flags stop at the CLI, so `kint --tenant kint-demo setup claude` does not pin anything. Pin both through `--env`:

```sh
kint setup all --env KINT_TENANT=kint-demo --env SIBYL_MEMORY_DB=/abs/path/memory.db
```

The space is derived from the tenant, and the vault is keyed by owner and tenant together. A harness that starts `kint-server` under another tenant reads a different chain of epochs, and on a tenant this machine never connected, the server serves without pulling. Sibyl's eight tools write through kint's client, so `KINT_TENANT` picks their tenant too.

## Claude Code

`kint setup claude` first removes any user-scope `kint` registration, silently, then runs:

```sh
claude mcp add --scope user kint -e PYTHONPATH=x -e KINT_TENANT=kint-demo -- /usr/bin/env -u PYTHONPATH /abs/path/kint-server
```

Running it again replaces the registration, which is how you change an `--env` value. The tools show up as `mcp__kint__memory_status`, `mcp__kint__memory_search` and so on.

Remove Sibyl's own registration if it is there: `claude mcp remove -s user sibyl-memory`. One store, one server, or the two servers race on the same file. The same goes for every other harness: wherever `kint-server` is registered, Sibyl's own server should not be. A second writer on the store while `kint-server` runs (Sibyl's server, another harness's `kint-server`, an SDK-direct process) also makes its updates to anchored rows read as changes behind Sibyl's tools, and the server holds its pushes (`HELD`) until those rows are anchored.

Setup registers at user scope only. For project scope, register by hand. Keep the `-e` flags after the name, as setup does:

```sh
claude mcp add --scope project kint -e PYTHONPATH=x -e KINT_TENANT=kint-demo -- /usr/bin/env -u PYTHONPATH /abs/path/kint-server
```

That writes `.mcp.json` in the project, and Claude Code asks you to approve it until the folder is trusted.

Verified Sep 9 2026 with a non-interactive run:

```sh
claude -p 'call memory_status, then memory_search "Friday release", then memory_verify "Friday release"' \
  --allowedTools 'mcp__kint__memory_status,mcp__kint__memory_search,mcp__kint__memory_verify'
```

It returned the owner, head seq 2 at block 51081880, the exact rule text, and decision `proceed` with all three merkle proofs passing.

## Codex

`kint setup codex` copies `~/.codex/config.toml` to `config.toml.bak-<unix time>` and appends:

```toml
[mcp_servers.kint]
command = "/abs/path/kint-server"
args = []

[mcp_servers.kint.env]
PYTHONPATH = ""
KINT_TENANT = "kint-demo"
```

If the file already has a `[mcp_servers.kint]` table, setup prints `codex: already configured` and changes nothing, so edit the file by hand to change an env value later.

Give the server room. It waits up to `KINT_BOOTSTRAP_SECONDS` (20 by default) for its startup pull before it lists its tools, and `memory_push` and `memory_pull` wait for Base confirmations. Add the two timeouts to the same table, above the `env` table (a second `[mcp_servers.kint]` header is a TOML error):

```toml
[mcp_servers.kint]
command = "/abs/path/kint-server"
args = []
tool_timeout_sec = 180
startup_timeout_sec = 90
```

For one run, `-c mcp_servers.kint.tool_timeout_sec=180` sets the tool timeout on the command line.

Verified Sep 9 2026 (Codex 0.130): in the interactive TUI the tools work as in Claude Code. Non-interactive `codex exec` runs with `approval: never` inside its sandbox and cancels MCP calls that need an escalation, reported as "user cancelled MCP tool call". A 180-second timeout under the default sandbox still cancelled, so the cause is the sandbox policy, not a timeout. `codex exec --sandbox danger-full-access` recalled the exact rule, head seq 2 at block 51081880, decision `proceed`.

## Hermes

### The MCP door

`kint setup hermes` runs:

```sh
hermes mcp add kint --command /usr/bin/env --args PYTHONPATH= KINT_TENANT=kint-demo /abs/path/kint-server
```

Setup passes `PYTHONPATH=` to `env` rather than `-u PYTHONPATH`, which Hermes's argument parser does not accept inside `--args`. Hermes connects to the server during `add` (discovery first) and asks `Enable all 14 tools? [Y/n/select]`; answer `Y`. Setup gives that command 60 seconds and captures its output, so the question may not show. If setup prints `hermes: failed:` with a timeout, run the line above yourself and answer `Y`.

Verified Sep 9 2026 (Hermes 0.8.0): `hermes chat -Q -q '...'` reported the owner, head seq 2 at block 51081880, the exact rule text and decision `proceed`.

### The SDK door

Hermes's Sibyl memory provider opens its store directly: `$HERMES_HOME/sibyl/memory.db`, with `HERMES_HOME` defaulting to `~/.hermes`, and a profile's store at `$HERMES_HOME/sibyl/profiles/<profile>/memory.db`. Point kint at the same file and wrap the session:

```sh
export SIBYL_MEMORY_DB="${HERMES_HOME:-$HOME/.hermes}/sibyl/memory.db"
kint pull
hermes chat
kint push
```

`kint --db PATH` does the same for a single command. Use the tenant you connected with (`KINT_TENANT` or `kint --tenant`). `kint verify "query"` exits 0 on `proceed` and 1 on `refuse`, so a wrapper script can gate an action on it. Pick one door per Hermes store: the MCP door's server reads `SIBYL_MEMORY_DB` too, and defaults to `~/.sibyl-memory/memory.db`, not the provider's file. A provider writing the same file while `kint-server` runs makes the server hold its pushes.

## OpenClaw

`kint setup openclaw` runs:

```sh
openclaw mcp set kint '{"command":"/usr/bin/env","args":["PYTHONPATH=","KINT_TENANT=kint-demo","/abs/path/kint-server"]}'
```

OpenClaw backs up `~/.openclaw/openclaw.json`, then saves the definition into it, and `openclaw mcp list` shows `kint`. Setup allows the command 120 seconds and drops lines from OpenClaw's `string-bridge` plugin out of what it prints. OpenClaw's embedded runtime launches the server and exposes the same fourteen tools as `kint__memory_*`.

Verified Sep 9 2026 (OpenClaw 2026.4.10), on a dedicated agent with a model that calls tools reliably:

```sh
openclaw agents add kint-test --workspace ~/.openclaw/workspace-kint-test --model openrouter/anthropic/claude-sonnet-4.5 --non-interactive
openclaw agent --agent kint-test --local --message '...'
```

It called `kint__memory_status`, `kint__memory_search` and `kint__memory_verify` and answered with the owner, head seq 2 at block 51081880, the exact rule text and decision `proceed`, 11 seconds after the prompt.

Three things that are OpenClaw's, not kint's. The model matters: the default `openrouter/z-ai/glm-5.1` route returned tool-use stops with no payload ("incomplete turn ... stopReason=toolUse payloads=0") on every message, so test with a model that has reliable tool calling. A chain-polling plugin (`string`) made every CLI invocation take minutes; disable it for the test. And `openclaw agent` needs `--agent <id>`, `--session-id` or `--to` to pick a session.

## Any other MCP client

Claude Desktop, Cursor and other stdio MCP clients were not tested, but `kint-server` is a plain stdio server and needs nothing a client does not already give Sibyl's. Most clients take a JSON server entry; this one uses the launch line `kint setup openclaw` saves:

```json
{
  "mcpServers": {
    "kint": {
      "command": "/usr/bin/env",
      "args": ["PYTHONPATH=", "KINT_TENANT=kint-demo", "/abs/path/kint-server"]
    }
  }
}
```

Use the absolute path to `kint-server` (`command -v kint-server` prints one), set the timeouts the client offers generously for the startup pull and for push calls, and remove the client's Sibyl entry.

## A VPS

A server is a machine like a laptop, with three differences.

- **No Keychain.** The session key's passphrase comes from `KINT_SESSION_PASSPHRASE`, else a `~/.kint/local.secret` file (mode 0600) created on first use. The same secret encrypts the cached data key, so `kint connect` and the `kint-server` your harness starts must see the same value. Leaving the variable unset and letting both read `local.secret` is the simplest way.
- **A long cache.** The data key cache lasts `KINT_KEY_TTL` (default `24h`), read when you connect, and `kint-server` renews it after every successful pull and push with the `KINT_KEY_TTL` in its own environment. Connect once over SSH with `KINT_KEY_TTL=30d` for an unattended machine, and register the server with the same value (`--env KINT_KEY_TTL=30d`). Do not use `session` there: it keeps the data key in the memory of the `kint connect` process, which exits. When the cache expires anyway, the watcher stops pushing and `memory_push` returns `KEY_EXPIRED`; run `kint connect` again, nothing is dropped.
- **Authorize from elsewhere.** `kint authorize page` binds 127.0.0.1 on the machine that runs it. On a VPS, `kint authorize payload` then `submit` fits better: sign the typed data with the owner wallet on your own machine and pipe the signature to `kint authorize submit ... --signature -` on the server. Fund the session key with a little ETH on Base.

Without a Keychain, kint reads and sends through a public Base endpoint unless `KINT_RPC_URL` is set, and a cold start asks a second, different endpoint (`KINT_RPC_URL_2`); see [Configuration](/docs/configuration). Then register the harness as above: the agent pulls on start and pushes when quiet.

A compromised VPS can read that space; Sibyl's `memory.db` is already plaintext there. Revoke its session key on the contract ([Expiry and revocation](/docs/keys#expiry-and-revocation)) and run [`kint rekey`](/docs/keys#rotate-the-data-key) from a machine you trust. Everything anchored before that rotation stays readable to whoever took the old key: a rotation protects what comes next, not what is already on a public ledger.

Read [For agents](/docs/agents) next.

Source: [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/store.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/store.py), [`src/kint/paths.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/paths.py), [`src/kint/keys.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/keys.py), [`docs/agents.md`](https://github.com/s0nderlabs/kint/blob/main/docs/agents.md).
