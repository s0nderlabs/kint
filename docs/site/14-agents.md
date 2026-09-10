---
slug: agents
title: For agents
description: How an AI agent installs and drives kint for a human, and what must always go back to that human.
group: Operate
order: 14
source: 'src/kint/server.py'
---

# You run the tools; the human holds the keys.

You are an agent, and a human asked you to set up or use kint. This page says what you can do for them, what must go back to them, and what never goes through the chat.

## If you only read one line

**kint is not on PyPI yet (install it from the git tag), run it with `PYTHONPATH` unset, call `memory_verify` before you act on anything you recalled (push your own edits first), and never ask the human for the wallet signature, the vault passphrase or the recovery code in chat.**

## The install gotchas

kint is not on PyPI yet, so an install by bare name (`uv tool install kint`, `pip install kint`) does not get this project. Install from the tag instead (Python 3.10 or newer):

```sh
uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0
```

That puts two binaries on `PATH`: `kint`, the CLI, and `kint-server`, the MCP server a harness launches.

If the user's shell sets `PYTHONPATH`, Python puts its entries ahead of the tool's own packages, so the binaries must run with it unset: `env -u PYTHONPATH kint ...`. `kint doctor` notes it on its last row, `python`: `(PYTHONPATH is set: run with env -u PYTHONPATH)`. `kint setup` keeps it out of every registration it writes: Claude Code gets `-e PYTHONPATH=x -- /usr/bin/env -u PYTHONPATH <kint-server>`, Codex gets `PYTHONPATH = ""` in its env table, and Hermes and OpenClaw launch the server through `/usr/bin/env PYTHONPATH=`.

Four more things trip agents up:

- **One store, one server.** `kint-server` serves Sibyl's eight tools itself. If Sibyl's own server is also registered, remove it (`claude mcp remove -s user sibyl-memory` for Claude Code); `kint setup claude` prints that reminder.
- **User scope only.** `kint setup claude` registers at user scope. A project-scoped registration is done by hand; [Harnesses](/docs/harnesses#claude-code) has the line.
- **The tenant.** kint uses `KINT_TENANT`, else `tenant_id` or `account_id` from Sibyl's `credentials.json`, else Sibyl's default. Pin it per harness with `kint setup <target> --env KINT_TENANT=<tenant>`. The CLI's `--tenant` and `--db` flags go before the command: `kint --tenant kint-demo status`.
- **`kint setup` edits the user's harness configs.** Say so before you run it. For Claude Code it removes any existing user-scope `kint` entry and adds it again. For Codex it copies `~/.codex/config.toml` to `config.toml.bak-<unix time>` first, and does nothing if a `[mcp_servers.kint]` block is already there.

## What you can do for the user

- Install kint and run `kint setup <target>`, where target is `all`, `claude`, `codex`, `hermes` or `openclaw`, with `--env KEY=VALUE` as often as needed.
- Create this machine's session key: `kint session-key create`. It prints the new address. The key only signs transactions to the contract; it can never decrypt.
- Print the payloads the human will sign: `kint canonical-payload --owner 0x...` (the frozen EIP-712 message) and `kint authorize payload --owner 0x...` (the session-key authorization; it prints the next step on stderr). Neither payload is a secret. What the wallet returns when it signs the first one is.
- Diagnose: `kint doctor` (exits 1 when any row says FAIL), `kint status`, `memory_status`, and the log at `~/.kint/kint.log`.
- Recall with Sibyl's tools, check with `memory_verify`, read old versions with `memory_history`, and push or pull with `memory_push` and `memory_pull`.
- Write the recovery-code file again on a connected machine: `kint recovery-code`. Tell the human where it is. Do not open it.

On a machine joining a vault that already exists, `kint join --owner 0x...` with exactly one secret (`--signature -` piped from the wallet, `--base-account` which prompts for the passphrase, or `--recovery-code-stdin`) creates the session key, connects, restores and registers the harnesses, and writes nothing to the chain. The human supplies the secret in their own terminal; `writes: off` in its report means the session key still needs funding and authorizing. A failure prints `join stopped at <step>: <message>` ([One command: kint join](/docs/new-machine#one-command-kint-join)).

## What must go back to the human

These steps need a wallet, a secret or money. Hand the human the command and wait.

| step | why it is theirs | what they run |
|---|---|---|
| Sign once per machine (EOA owner) | the signature is the key to their memory | the canonical-payload and `cast wallet sign` pipe into `kint connect --signature -` |
| Type the vault passphrase (Base Account owner) | it derives the key | `kint connect --owner 0x... --smart-account` (it prompts), or with `--passphrase-stdin` |
| Fund the session key | it pays for every push | send a little ETH on Base to the address `kint session-key create` printed |
| Authorize the session key | only the owner can | `kint authorize page` (Base Account, in the browser), or `payload`, sign, then `submit` |
| Keep the recovery code | it opens the vault when the wallet and passphrase are gone | copy `~/.kint/RECOVERY-<space16>.txt` somewhere that is not this machine |
| Rotate the data key | it needs every key that should keep working | `kint rekey`, in their terminal; there is no rekey tool |

Some details that change what you tell them:

- Fund before `kint authorize submit`: that transaction is sent by the session key itself. `kint doctor` warns until the balance is above 0.00002 ETH and the key is authorized.
- `kint authorize payload` stamps a deadline 300 seconds out, so the human signs and submits within five minutes or prints a fresh payload.
- An authorization runs for `--days` (default 30). The contract's `canWrite` is true only while the expiry is in the future, so after that pushes fail until they authorize again. `memory_status` shows `session_key.expiry`.
- `kint authorize direct` and `kint authorize burn-nonce` read the owner's private key from `KINT_OWNER_KEY`. That is the human's to set in their own shell, never yours to ask for.
- On the machine that created the vault, push refuses while the recovery-code file is missing or empty. After a `kint rekey`, the old code no longer opens the vault and a new file is written.

## Never ask for a secret in chat

`memory_connect` does accept two secrets. Called with `passphrase` (a Base Account owner) or `recovery_code`, it connects directly, and `owner` is required the first time (without one it answers `OWNER_REQUIRED`). It never accepts the derive signature: that travels on stdin through `kint connect --signature -` (or in a file that `--signature-file` reads and then deletes), never on argv.

Do not use the two it accepts. Anything a human types into an agent chat lands in the transcript, and a tool call's arguments are part of it. Call `memory_connect` with no arguments instead. If the machine is not connected, it returns `connected: false` and `human_steps`: three lines, each a label and then a command for the human's own terminal. The commands are:

```sh
kint canonical-payload --owner 0x... > kint-canonical.json && cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0x... --signature -
kint connect --owner 0x... --smart-account --passphrase-stdin
kint connect --owner 0x... --recovery-code-stdin
```

The first is for an EOA wallet, the second for a Base Account or smart wallet owner, the third for the day both are lost. The server looks for the enrolment and the cached key on every call, so once the human has connected, your next `memory_status` sees it without a restart. Then call `memory_pull`: the server only pulls on its own at startup.

> **Warning.** The derive signature is not a login. The frozen EIP-712 message says so in its `purpose` field: "kint-memory-v1: signing this reveals your memory encryption key. Only sign it in a kint terminal or page you opened yourself." A phished derive signature is a permanent key. Never ask the human to paste it, never read `~/.kint/session.key`, the vault cache or the recovery file into the conversation, and never read the macOS Keychain.

## The tool-call recipe

1. **`memory_status` first.** Read `connected`, `data_key_cached`, `in_step`, `unanchored`, `held`, `chain_head` (an `error` key there means the chain could not be read) and `session_key` (`exists`, `authorized`, `balance_eth`, `expiry`). If `connected` or `data_key_cached` is false, go to `memory_connect` with no arguments. If `held` is not `null`, kint-server is refusing to push: tell the human its `message`. The cached key expires after `KINT_KEY_TTL`, 24 hours by default, and every successful pull and push renews it.
2. **`memory_pull` when `in_step` is false.** The chain head is not what this machine last saw anchored: another machine pushed, or this one has not pulled yet. With unanchored changes here, the pull answers `FORK`, which is the human's call. `memory_verify` refuses while the head is past this machine's mirror, so bring the mirror up to the head first.
3. **Recall with Sibyl's tools.** `memory_search`, `memory_recall` and `memory_get_state` work as they always did. Their results are what the store holds now, not what the chain vouches for.
4. **`memory_verify` before acting on a recalled row.** Pass the query, not a row key: it runs the same search `memory_search` runs (Sibyl's `multi_record_search`, precision gates included) and checks the top `limit` hits (default 5, where `memory_search` defaults to 10). Act only when `decision` is `proceed`, and only on the row the `reason` names.
5. **Write with Sibyl's tools.** kint anchors after the write has returned. While the server runs, a watcher pushes once the store has been quiet for `KINT_QUIET_SECONDS` (default 300), or sooner when the change set is large. To verify a row you just changed, `memory_push` first: an unpushed edit to an anchored row is refused as `drifted`, and that refusal holds every kint-server push until the human runs `kint push`.
6. **`memory_push` when a task is done**, so the next machine sees it now rather than after the quiet period. `memory_push(snapshot=true)` anchors one epoch that holds the whole state.
7. **`memory_history` for "what did this say before".** Pass `tier` (`entity`, `state` or `reference`), `key`, `category` for entities, and optionally `block`.

```text
memory_status()
memory_search(query="release rule")
memory_verify(query="release rule")            # act only on decision "proceed"
memory_remember(category="rules", name="release-gate", body={...})
memory_push()
```

`memory_history` reads the decrypted epochs cached on this machine. On a machine whose restore stopped at a snapshot epoch, older versions appear only after `memory_pull(full=true)`. Report each version's block as an upper bound: the row existed no later than block N. Never turn it into a wall-clock time.

## Reading a memory_verify result

```text
ok              true when the check ran; a refusal still has ok: true
decision        "proceed" or "refuse"
reason          one sentence: the row and the block it rests on, or why it refused
verdict         Sibyl's search verdict: code, returned, recovery, tokens, explain
hits            what the search returned: tier, key, category, snippet, rank, ts
checks          one per hit: tier, key, category, status, local_leaf, anchored_leaf, anchored_seq,
                anchored_block, anchored_tx, head_seq, head_block, rows_root, proof, proof_ok, reason
refusal_entity  "kint_refusal/<name>" when a refusal was written back, else null
chain_head      the head read for this check: seq, digest, block; null when not read
```

`ok: false` means the check itself failed (`error` holds the exception name), which is not a proceed either. Each check has one of four statuses:

| status | meaning |
|---|---|
| `verified` | the stored text hashes to the leaf anchored on Base and the merkle proof against the anchored `rows_root` passes |
| `drifted` | the stored text no longer matches the anchored leaf, or the proof failed; your own edit to an already anchored row reads this way until it is pushed |
| `unanchored` | the row is new since the last anchored epoch; nothing on the chain vouches for it yet |
| `missing` | the row the search returned is no longer in the store |

The decision is `refuse` when Sibyl's verdict is not `ok` (`abstained_on`, `negation_abstain`, `gated`, `empty_store` or `no_match`) or there are no hits, when this machine has no mirror (it never connected, pulled or pushed; the reason says "never pulled or pushed"), when its mirror is incomplete (a skipped epoch, or a root that does not equal the anchored one), when the chain head moved past the mirror (the reason starts "chain moved to seq N at block B, pull first"), when any hit is `drifted` or `missing` (even if another hit verified), or when every hit is `unanchored`. Otherwise it is `proceed`, and the reason names the top verified row, for example `entity rules/release-gate verified against rows_root 390336ff71dbcb85 anchored at epoch 2, block 51081880`. That epoch and block are the head this machine last saw; the epoch that last changed the row is in the check's `anchored_seq` and `anchored_block`. If higher-ranked hits were unanchored, the reason adds a `NOTE` naming them: act on the verified row and push before relying on the others.

What to do on refuse:

- Do not act on the row. Tell the human, and quote the reason: a drift names the epoch and block that anchored the last good value, and the head epoch and block.
- Match the fix to the reason. Unanchored rows: `memory_push`, then verify again. "Never pulled or pushed", "pull again" or "chain moved ... pull first": `memory_pull`, then verify again. A verdict that is not `ok`: there was nothing to act on, so rephrase the query (on `abstained_on`, drop the word in `verdict.tokens[0]`) or ask.
- A drifted row is a human decision. If the change was theirs and intended, `kint push` in their terminal anchors it; `memory_push` answers `HELD` while the refused value is in the store. If it was not, `kint pull --discard-local` moves the store aside and restores from the chain, taking every unanchored change into the backup with it; a plain pull reports "up to date" and leaves the drift in place.
- The first `drifted` or `missing` hit is written back as a Sibyl entity (category `kint_refusal`, status `refused`, named `<tier>-<category or none>-<key>-<unix time>`) so the next fresh session sees it. While the row still holds the refused value, every kint-server push answers `HELD`; the entity itself is anchored by the first push that goes through. The other refusals write nothing. The tool always writes it; `kint verify --no-write` is the CLI's way to skip it.

## Anti-patterns to avoid

- **Do NOT** treat `memory_search` or `memory_recall` output as checked. Only `memory_verify` decides.
- **Do NOT** push past a refusal or a `HELD`. `memory_push` is held on a refused value, and `kint push` from a shell is not held: it anchors whatever the store holds, including a drifted row, so it is the human's decision.
- **Do NOT** run `kint compact --over-skipped` or `kint rekey --over-skipped` yourself. They anchor this machine's store as the whole state on top of an epoch that will never open: the owner's recovery step, after revoking the session key that wrote it. There is deliberately no tool argument for it.
- **Do NOT** run `memory_pull(discard_local=true)` or `kint pull --discard-local` without the human. It moves `memory.db` (and its `-wal` and `-shm` files) aside to `<name>.kint-backup-<YYYYmmdd-HHMMSS>`, so every unanchored change leaves the live store and survives only in that backup.
- **Do NOT** suggest `kint pull --rebase`. There is no such flag: `kint pull` takes `--owner`, `--discard-local`, `--force-scan` and `--full`.
- **Do NOT** rely on `force_scan`. `memory_pull` and `kint pull` accept it, and v0.3.0's pull never reads it.
- **Do NOT** look for a rekey tool. There is deliberately none: the secrets that rotate the key are typed in a terminal.
- **Do NOT** tell the user reading costs gas. Restoring and reading never send a transaction.
- **Do NOT** start a second push while one runs. The tool answers `BUSY`, and a second process waits up to 30 seconds for the head lock, then fails.
- **Do NOT** promise a restore without a key. The wallet signature, a passphrase that has a wrap, or the recovery code opens the vault; kint has no reset.
- **Do NOT** set `KINT_KEY_TTL=session` and expect a terminal `kint connect` to reach the server. With `session` the key lives only in the memory of the process that connected.

## Common errors and fixes

Tool errors come back as `{"ok": false, "error": ...}`, usually with a `message`, a `hint`, or both. The error is a code (`NOT_CONNECTED`) or, for anything else, the exception's class name (`ConnectError`).

| error | where | fix |
|---|---|---|
| `NOT_CONNECTED`, hint `call memory_connect` | `memory_push`, `memory_pull` | `memory_connect` with no arguments; give the human the `human_steps` |
| `OWNER_REQUIRED` | `memory_connect` with a secret | this machine has no owner yet; the human connects in their terminal with `--owner` |
| `KEY_EXPIRED`: `the data key on this machine has expired or is missing` | push | the human runs `kint connect` again; nothing was dropped |
| `CHAIN_MOVED`: `... another machine pushed.`, hint `call memory_pull first` | push | `memory_pull`; with unanchored changes here it answers `FORK` (below), which is the human's call |
| `BUSY`, hint `a push is already running` | `memory_push` | wait, then `memory_status` |
| `HELD`: `refusing to anchor: ...`, hint `nothing was anchored and nothing was dropped; memory_verify still refuses the row` | `memory_push` (the watcher and the exit push log the same) | stop and tell the human the `message`: they check the rows it names, then run `kint push` (anchor the value) or `kint pull --discard-local` (restore the anchored value, dropping every unanchored change) in their terminal |
| `PUSH_FAILED`: `session key 0x... is not authorized for owner 0x...` | push | the human funds and authorizes it (`kint authorize`); also the message after the expiry passes |
| `PUSH_FAILED`: `refusing to push: this machine created the vault but its recovery code file is gone` | push | `kint recovery-code`, the human copies it off the machine, then push |
| `PUSH_FAILED`: `refusing to push: this machine could not apply epoch(s) [...] on its last pull` | push | `memory_pull` again; a wrong key needs `kint connect`. An epoch that will never open (a leaked session key wrote it) is the owner's to clear: they revoke the key, then run `kint compact --over-skipped` in their terminal |
| `PUSH_FAILED`: `row ... compresses to more than 90 KB on its own and cannot fit one epoch` | push | shrink or split that row in Sibyl; nothing else is blocked |
| `PUSH_FAILED`: `the full state (N rows) compresses to ... snapshots are single-epoch` | `memory_push(snapshot=true)` | push without `snapshot`; a restore just walks more epochs |
| `KeyError_`: `no session key on this machine` | push | `kint session-key create`, then fund and authorize |
| `TimeoutError`: `another kint process holds the head lock for this space` | push, pull | another push or pull is running on this machine; wait and retry |
| `FORK`: `the chain moved to seq N and this store has ... rows that were never anchored: a fork` | pull | the human decides: `discard_local` moves the store aside and restores; the unanchored rows are then only in the backup |
| `FORK`: `the local store already holds N rows for tenant T and this machine has no record of what the chain last saw` | pull | wrong tenant, or a store from before kint; the human moves it aside or uses `--discard-local` |
| `NOT_FRESH`: `cold start needs a second, independent RPC and KINT_RPC_URL_2 resolves to the same endpoint` | pull | the human sets `KINT_RPC_URL_2` to another provider, or accepts one RPC with `KINT_ALLOW_SINGLE_RPC=1` |
| `NOT_FRESH`: `could not get a second opinion on the head from ...` | pull | the second RPC did not answer on a cold start; the human fixes `KINT_RPC_URL_2`, or accepts one RPC with `KINT_ALLOW_SINGLE_RPC=1` |
| `NOT_FRESH`: `two RPCs disagree on the head` | pull | wait and retry; do not override it |
| `NOT_FRESH`: `... stale or lying RPC, refusing` | pull | the RPC served a head older than this machine already saw; use another endpoint |
| `PULL_FAILED`: `no data key on this machine` | pull | `memory_connect` with no arguments |
| `ConnectError`: `this key (tag ...) does not open the vault anchored under 0x...` | connect | wrong wallet, passphrase or tenant; the recovery code still opens it |
| `ConnectError`: `this recovery code does not belong to the vault anchored under this owner` | connect | check the owner and the tenant |
| `KintCryptoError`: `recovery code checksum failed (typo?)` | connect | the code was mistyped; the human types it again |
| `ChainUnreadable`: `cannot read the chain head` | connect | an RPC problem, never a security verdict; retry or set `KINT_RPC_URL` |
| `kint: derive signature recovers to 0x..., expected 0x...; refusing to derive a key from it` | CLI connect | the wallet that signed is not `--owner`, or the payload was for another owner |
| `kint: give the derive signature with --signature - (stdin) or --signature-file PATH; never on argv` | CLI connect | pipe the signature in; never put it on the command line |
| `kint: --passphrase-stdin and --signature - cannot share stdin` | CLI connect, rekey | use `--passphrase-prompt` or `--signature-file` |
| `kint: no owner known on this machine: pass --owner 0x... or run kint connect` | CLI | pass `--owner`, or connect first |

When you script the CLI, the exit codes carry the same information. Any `kint:` error exits 2 unless noted. `push`, `compact` and `rekey` exit 3 for a missing data key or session key, 4 when the chain moved, 5 for any other push failure. `pull` exits 4 for a fork, 6 for a freshness refusal, and 5 for any other failed pull (a missing data key included). `kint verify` exits 0 on proceed and 1 on refuse, except with `--json`, which exits 0 either way: read `decision`. A head-lock timeout (`TimeoutError`) or a chain failure during a push (`ChainError`) is not caught by the CLI and ends in a Python traceback.

## Where state lives

Everything kint keeps is under `KINT_HOME` (default `~/.kint`), mode 0700. Every state file is written 0600; `kint.log` is created with the default file mode. `<space16>` is the first 16 hex characters of the space id, `keccak256("kint-space-v1" || tenant_id)`; `memory_status` returns the full id as `space`.

```text
~/.kint/
├── session.key                  this machine's session key, a V3 scrypt keystore
├── session.key.old              the previous key, after kint session-key rotate
├── local.secret                 the local passphrase, only when no Keychain is used
├── enrol-<space16>.json         the enrolment: owner, tenant, space, key tags
├── vault-<space16>.aes          the data key, encrypted at rest, with an expiry
├── wraps-<space16>.json         the wrapped data keys, one per unlock path
├── RECOVERY-<space16>.txt       the recovery code: copy it off the machine
├── mirror-<space16>.json        what this machine last saw anchored: rows, leaves, anchored root
├── watermark-<space16>.json     the highest head this machine has seen; never decreases
├── head-<space16>.lock          one pusher or puller per space per machine
├── kint.log                     kint's log (stderr gets the same lines)
└── epochs/
    └── <space16>/
        ├── 00000001.bin         the ciphertext, as sent to Base
        ├── 00000001.json        the decrypted plaintext, which memory_history reads
        └── 00000001.meta.json   seq, digest, prev, block, tx, bucket, rows_root, writer
```

The Sibyl store itself is at `SIBYL_MEMORY_DB` (default `~/.sibyl-memory/memory.db`), and it is plaintext, as it always was. On macOS the local passphrase that protects `session.key` and the vault cache is kept in the Keychain item `dev.kint-session-key` unless `KINT_SESSION_PASSPHRASE` is set (a server) or `KINT_NO_KEYCHAIN=1`. The full list of variables is in [Configuration](/docs/configuration#every-variable).

Read [Built on Sibyl Memory](/docs/sibyl) next.

Source: [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/keys.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/keys.py), [`src/kint/verify.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/verify.py), [`src/kint/paths.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/paths.py).
