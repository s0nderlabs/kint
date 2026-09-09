# How each agent reads the memory (and how to wire it)

kint never connects to a harness. It connects to Sibyl's store, and harnesses already connect
to Sibyl. One store per machine, one session key per machine, one owner wallet.

Two doors:

| door | who | how memory is read | restore / verify |
|---|---|---|---|
| MCP (stdio) | Claude Code, Codex, Claude Desktop, Cursor, Hermes (`hermes mcp add`), OpenClaw | the harness calls Sibyl's eight `memory_*` tools, served by `kint-server` | `kint-server` pulls before it serves; `memory_verify` before acting; `memory_push` on quiet, on demand, on exit |
| SDK-direct | Hermes memory provider, LangGraph, any Python | the process opens `memory.db` itself | `kint pull` before launch, `kint push` after, `kint verify "query"` from a shell |

## One-time setup on a machine

```
uv tool install kint                 # or: pip install kint   (Python 3.10+)
kint session-key create              # this machine's key; fund it with a little ETH on Base
kint connect --owner 0x... --signature -        # EOA owners: see the pipe below
kint connect --owner 0x... --smart-account      # Base Account owners: vault passphrase
kint authorize page                  # Base Account: authorize the key from the browser
kint pull                            # restore (a fresh machine) or refresh
kint setup all                       # point Claude Code, Codex, Hermes at kint-server
```

EOA owners sign the frozen payload once per machine, never on argv:

```
kint canonical-payload --owner 0x... > kint-canonical.json
cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0x... --signature -
```

Pin the demo tenant for every harness with `kint setup <target> --env KINT_TENANT=kint-demo`;
without it kint uses the tenant from Sibyl's `credentials.json` (or Sibyl's default).

Three commands beyond the daily loop:

```
kint compact                         # ONE snapshot epoch holding the whole state; the next cold start stops there
kint pull --full                     # walk past snapshots when the older versions matter on this machine
cast wallet sign --data --from-file kint-canonical.json --ledger | kint rekey --signature -
                                     # rotate the data key: new key, new wraps, one snapshot epoch, a new recovery code
```

`kint rekey` needs every key that is to keep opening the vault (a wrap can only be made by whoever
holds its key), so pass `--smart-account` or `--add-passphrase` alongside the signature when the
vault has those wraps; it refuses and names any key it would otherwise drop, and `--drop-missing`
is how you say you meant it. There is deliberately no `memory_rekey` tool: those secrets are typed
in a terminal, never in an agent chat.

## Claude Code

`kint setup claude` runs
`claude mcp add --scope user kint -e PYTHONPATH=x -- /usr/bin/env -u PYTHONPATH /abs/path/kint-server`
(the `env -u` keeps a polluting `PYTHONPATH` out of the server). Remove Sibyl's own registration
if present (`claude mcp remove -s user sibyl-memory`): one store, one server, or the two servers
race on the same file. In a session: `memory_search` to recall, `memory_verify` before acting,
`memory_status` to see the head. Verified Sep 9 2026 with a non-interactive run:

```
claude -p 'call memory_status, then memory_search "Friday release", then memory_verify "Friday release"' \
  --allowedTools 'mcp__kint__memory_status,mcp__kint__memory_search,mcp__kint__memory_verify'
```
returned the owner, head seq 2 at block 51081880, the exact rule text, and decision `proceed`
with all three merkle proofs passing.

## Codex

`kint setup codex` appends to `~/.codex/config.toml` (Codex reads MCP servers from there):

```toml
[mcp_servers.kint]
command = "/abs/path/kint-server"
args = []

[mcp_servers.kint.env]
PYTHONPATH = ""
KINT_TENANT = "kint-demo"
```

Verified Sep 9 2026: in the interactive TUI the tools work as in Claude Code. Non-interactive
`codex exec` runs with `approval: never` inside its sandbox and cancels MCP calls that need an
escalation ("user cancelled MCP tool call"); `codex exec --sandbox danger-full-access` recalled
the exact rule, head seq 2 at block 51081880, decision `proceed`. Give the server a generous
`tool_timeout_sec` (a pull on a cold start can take a minute):

```toml
[mcp_servers.kint]
tool_timeout_sec = 180
startup_timeout_sec = 90
```

## Hermes

MCP door: `kint setup hermes` runs
`hermes mcp add kint --command /usr/bin/env --args PYTHONPATH= KINT_TENANT=kint-demo /abs/path/kint-server`.
Hermes connects to the server during `add` (discovery-first) and asks `Enable all 14 tools? [Y/n/select]`;
answer `Y`. Verified Sep 9 2026: `hermes chat -Q -q '...'` reported the owner, head seq 2 at
block 51081880, the exact rule text and decision `proceed`.
SDK door: Hermes's Sibyl memory provider reads `$HERMES_HOME/sibyl/memory.db` directly, so point
kint at the same file (`SIBYL_MEMORY_DB=$HERMES_HOME/sibyl/memory.db`), run `kint pull` before
`hermes chat` and `kint push` after. Refuse-before-act needs a tool call, so an SDK-door Hermes
gets the integrity check at pull time (every epoch is verified against the chain before a row is
replayed), not per recall.

## OpenClaw

`kint setup openclaw` runs
`openclaw mcp set kint '{"command":"/usr/bin/env","args":["PYTHONPATH=","KINT_TENANT=kint-demo","/abs/path/kint-server"]}'`,
which saves the definition into `~/.openclaw/openclaw.json` (OpenClaw backs the file up first;
`openclaw mcp list` shows `kint`). OpenClaw's embedded runtime launches the server and exposes the
same fourteen tools as `kint__memory_*`.

Verified Sep 9 2026 (OpenClaw 2026.4.10): a dedicated agent on a model with reliable tool calling,
`openclaw agents add kint-test --workspace ~/.openclaw/workspace-kint-test --model openrouter/anthropic/claude-sonnet-4.5 --non-interactive`,
then `openclaw agent --agent kint-test --local --message '...'`, called `kint__memory_status`,
`kint__memory_search` and `kint__memory_verify` and answered with the owner, head seq 2 at block
51081880, the exact rule text and decision `proceed`, 11 seconds after the prompt. Two things
that are OpenClaw's, not kint's: the default `openrouter/z-ai/glm-5.1` route returned tool-use
stops with no payload ("incomplete turn ... stopReason=toolUse payloads=0") on every message, and
a chain-polling plugin (`string`) made every CLI invocation take minutes; disable it for the test.
`openclaw agent` needs `--agent <id>`, `--session-id` or `--to` to pick a session.

## A VPS

Same as a laptop: `kint session-key create` (passphrase from `KINT_SESSION_PASSPHRASE`, no
Keychain), authorize it from the owner, fund it, `kint connect` once over SSH with a long TTL
(`KINT_KEY_TTL=30d`), then the agent pulls on start and pushes when quiet. A compromised VPS can
read that space (Sibyl's `memory.db` is already plaintext there); revoke its session key on the
contract and run `kint rekey` from a machine you trust. Everything anchored before that rotation
stays readable to whoever took the old key: a rotation protects what comes next, not what is
already on a public ledger.

## What `memory_verify` returns

```
decision: proceed | refuse
verdict:  Sibyl's typed verdict for the search (ok, no_match, abstained_on, gated, empty_store)
checks:   per hit: verified | drifted | unanchored | missing, the local leaf, the anchored leaf,
          the epoch and block that anchored it, the merkle proof against the anchored rows_root
```
A refusal names the block that anchored the last good value and the current head block, and is
written back as a Sibyl entity (`kint_refusal/...`) so the next fresh session sees it.
