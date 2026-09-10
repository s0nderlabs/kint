---
slug: quickstart
title: Quickstart
description: Install kint, connect the wallet, authorize this machine's session key, and anchor the first epoch.
group: Get started
order: 2
source: 'src/kint/cli.py'
---

# Five minutes, once per machine.

This page takes one machine from nothing to a wallet-owned Sibyl store whose changes land on Base. The human part: sign the key message (or type the vault passphrase), authorize this machine, and fund its session key.

## Before you start

You create a session key, connect the wallet, authorize the key, point your harness at `kint-server`, and watch the first epoch anchor. You need:

- **Python 3.10 or newer** and `uv`. kint is not on PyPI yet; it installs from the tagged repository.
- **A wallet that owns the memory.** Either an EOA that can sign EIP-712 typed data through foundry's `cast` (a Ledger with `--ledger`, a Trezor with `--trezor`, a foundry keystore with `--account <name>`), or a Base Account (Coinbase Smart Wallet), which uses a vault passphrase instead of a signature.
- **A little ETH on Base** for this machine's session key. It pays the gas for every epoch it anchors. `kint doctor` warns while the balance is at or below 0.00002 ETH, or while the key is not authorized.
- **A Sibyl store.** kint wraps the file at `$SIBYL_MEMORY_DB`, else `~/.sibyl-memory/memory.db`. The global `--db PATH` flag overrides it for one command.
- **A tenant.** The global `--tenant` flag wins, and it goes before the command: `kint --tenant my-tenant connect ...`. Without it kint takes `KINT_TENANT`, else `tenant_id` or `account_id` from Sibyl's `credentials.json` (`$SIBYL_CREDENTIALS`, else `~/.sibyl-memory/credentials.json`), else Sibyl's default tenant.

The vault is keyed by owner and tenant together, so use the same tenant in the terminal and in the harness (step 5).

Joining a vault that already exists from another machine? After the install, `kint join` does the session key, the connect, the restore and the harness registration in one command and writes nothing to the chain; see [One command: kint join](/docs/new-machine#one-command-kint-join). This page is the first machine, where the vault starts.

## 1. Install

```sh
uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0
```

That puts two binaries on your PATH: `kint` (the CLI) and `kint-server` (Sibyl's MCP server with kint's tools added). If your shell exports `PYTHONPATH`, it shadows the tool's environment; run the binaries as `env -u PYTHONPATH kint ...`. For the same reason, `kint setup` keeps it out of every harness registration: Claude Code launches the server through `/usr/bin/env -u PYTHONPATH`, and Codex, Hermes and OpenClaw start it with `PYTHONPATH` set empty.

## 2. Create this machine's session key

```sh
kint session-key create
```

```text
created: 0x<session key address>
fund it with a little ETH on Base and authorize it from the owner (kint authorize ...)
```

The key is a plain EOA stored as a V3 scrypt keystore at `~/.kint/session.key` (mode 0600). On macOS its passphrase lives in the Keychain item `dev.kint-session-key`, created on first use; on a server, set `KINT_SESSION_PASSPHRASE`. The session key signs Base transactions to EpochAnchor and nothing else. It can never decrypt the memory. A second `create` prints `exists: 0x...` and changes nothing; `kint session-key rotate` replaces the key and keeps the old keystore as `session.key.old`.

Send a little ETH on Base to the printed address. `kint session-key show` prints JSON: the address, its balance and, once connected (or with `--owner 0x...`), whether it is authorized and its expiry as a unix time.

## 3. Connect the wallet

Connecting derives this machine's key from the wallet and, on a fresh vault, generates the data key and writes the recovery code.

### An EOA owner

Print the frozen EIP-712 payload, sign it with `cast`, and pipe the signature straight into `kint connect` on stdin:

```sh
kint canonical-payload --owner 0xYOU > kint-canonical.json
cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0xYOU --signature -
```

The message carries two fields, your address and a `purpose` string the wallet shows you: "kint-memory-v1: signing this reveals your memory encryption key. Only sign it in a kint terminal or page you opened yourself." On a fresh vault the output is:

```text
connected: owner 0xYOU
space <first 16 hex of the space>  key tag <8 hex>  data key from fresh vault
fresh vault: recovery code written to <home>/.kint/RECOVERY-<first 16 hex of the space>.txt
copy that code somewhere that is not this machine; push refuses until the file exists
session key: 0x<session key address>
```

On a vault that already has epochs, on a machine with no key wraps of its own yet, `data key from` reads `chain head header`: the data key comes out of the head epoch's own header on Base, and no recovery code is written. When the head epoch is not a readable kint epoch (any authorized session key can append bytes that are not one), connect takes the wraps from the newest epoch before it whose header parses, looking back through at most the 31 epochs before the head. A fetch that fails, or calldata whose digest disagrees with the `Epoch` event, is never walked past: connect refuses instead.

> **Warning.** The derive signature is the key itself. A leaked one opens every epoch this wallet has anchored, and it cannot be revoked. kint reads it only from stdin (`--signature -`) or from a file it reads and then deletes (`--signature-file PATH`), never from argv, and never through an agent tool. Never paste it anywhere else.

Three optional flags in EOA mode:

- `--passphrase-prompt` salts the wallet key with a passphrase (a second factor). The same passphrase is then needed alongside the signature to open the vault.
- `--add-passphrase` prompts for an extra passphrase and adds a second wrap of the data key under it, so the vault also opens with that passphrase alone (on another machine, once the next epoch carries the new wrap in its header).
- `--passphrase-stdin` reads the salt passphrase from stdin instead. It cannot share stdin with `--signature -`; kint refuses that combination and tells you to use `--passphrase-prompt` or `--signature-file`.

### A Base Account owner

A passkey-owned account has no deterministic signature to derive a key from, so its vault key is a passphrase, stretched with scrypt and salted with the owner address:

```sh
kint connect --owner 0xYourBaseAccount --smart-account
```

kint prompts `vault passphrase: `. To feed it from a pipe or a secrets manager instead, add `--passphrase-stdin`. The output has the same shape as above. The `memory_connect` tool also accepts a `passphrase` argument, but anything typed into an agent chat lands in the transcript; connect from the terminal.

## 4. Authorize the session key

The owner tells EpochAnchor that this machine's session key may append epochs under its name, for `--days` days (default `30`). `kint authorize` needs a session key on this machine and a known owner (from `kint connect`, or `--owner 0x...`). Pick one mode:

| mode | who sends the transaction | use it when |
|---|---|---|
| `direct` | the owner EOA, from `KINT_OWNER_KEY` | the owner key is at hand on this machine |
| `page` | the Base Account, from a browser page | the owner is a Base Account |
| `payload` then `submit` | the session key, carrying the owner's signature | the owner signs offline (a Ledger) and should not pay gas |
| `burn-nonce` | the owner EOA, from `KINT_OWNER_KEY` | cancelling a signed authorization that was never submitted |

**Direct.** kint reads the owner key from the environment, never argv, and refuses when it is not the owner's key (`KINT_OWNER_KEY is 0x..., not the owner 0x...`):

```sh
KINT_OWNER_KEY=0x... kint authorize direct
```

```text
submitted 0x<tx hash>
authorized 0x<session key> under 0xYOU; cost <eth> ETH, block <block>
```

**Page, for a Base Account.** kint serves one page on `127.0.0.1` at a random port with a 32-byte token in the path, and prints the URL:

```sh
kint authorize page
```

```text
open this page in the browser where your Base Account is logged in (owner 0xYourBaseAccount):
  http://127.0.0.1:<port>/kint/<token>
```

On the page, connect the Base Account (it refuses any other address), then press Authorize. The account sends `setSessionKey` to EpochAnchor itself; if it has never sent a transaction, that one also deploys it. Nothing secret crosses the page. kint then polls `canWrite` on the chain every 3 seconds, up to 120 times, and prints `authorized: 0x<session key> may push under 0xYourBaseAccount until <date>`. The page server gives up after 15 minutes without a result. The page loads the Base Account SDK from esm.sh at a pinned version (`@base-org/account@2.5.10`) with no integrity check, so that CDN is trusted for this one transaction; see [Limits and threat model](/docs/limits).

**Payload, then submit.** kint prints the authorization typed data on stdout and the exact follow-up on stderr. The owner signs it; the session key submits it and pays the gas:

```sh
kint authorize payload > kint-auth.json
# nonce <n>, deadline <unix time>, expiry <unix time>; sign with: cast wallet sign --data --from-file <this file>
# then: kint authorize submit --deadline <unix time> --expiry <unix time> --signature -
cast wallet sign --data --from-file kint-auth.json --ledger \
  | kint authorize submit --deadline <unix time> --expiry <unix time> --signature -
```

The deadline is 300 seconds after `payload` runs. The typed data uses its own EIP-712 domain (`kint EpochAnchor`, bound to the contract address), so an authorization signature can never double as the derive signature. On success: `authorized 0x<session key> under 0xYOU until <date>; cost <eth> ETH, block <block>`.

**Burn the nonce.** Every owner transaction to `setSessionKey` consumes the owner's authorization nonce, which voids any signed authorization still waiting to be submitted. `KINT_OWNER_KEY=0x... kint authorize burn-nonce` does exactly that without changing this key's expiry, and prints `nonce consumed: authNonce(0xYOU) is now <n>`. Like `direct`, it refuses when `KINT_OWNER_KEY` is not the owner's key, before sending anything.

## 5. Point the harness at kint-server

```sh
kint setup claude --env KINT_TENANT=my-tenant
```

The target is one of `claude`, `codex`, `hermes`, `openclaw` or `all`; `--env KEY=VALUE` (repeatable) is passed to the server process. Pass `--env KINT_TENANT=...` whenever you connected with `--tenant` or `KINT_TENANT`: the server resolves its own tenant and does not see the flag you gave the CLI.

- `claude` registers `kint` at user scope and prints `claude: registered kint (user scope)`. If Sibyl's own server is also registered, remove it (`claude mcp remove -s user sibyl-memory`): one store, one server. For project scope, register by hand: `claude mcp add --scope project kint -e PYTHONPATH=x -e KINT_TENANT=... -- /usr/bin/env -u PYTHONPATH /abs/path/kint-server` (writes `.mcp.json`; Claude Code asks you to approve it until the folder is trusted).
- `codex` appends `[mcp_servers.kint]` to `~/.codex/config.toml`, after copying the old file to `config.toml.bak-<unix time>`.
- `hermes` runs `hermes mcp add kint ...`; `openclaw` runs `openclaw mcp set kint ...`.

When the `claude`, `hermes` or `openclaw` CLI is missing, that target is skipped with `<target>: CLI not found, skipped`; `codex` only edits its config file, and prints `codex: already configured` when the block is already there. Each harness has quirks worth knowing; see [Harnesses](/docs/harnesses).

`kint-server` lists its tools within `KINT_BOOTSTRAP_SECONDS` of starting (default 20), even when an RPC hangs: its first pull runs on its own thread and finishes behind the running server. Each RPC call gives up after `KINT_RPC_TIMEOUT` seconds (default 10) and is retried at most twice, with a short backoff, on a connection, HTTP or timeout error.

## 6. The first write

Start a session and ask the agent to remember something. The write goes through Sibyl's own tool, unmodified, for example:

```text
memory_remember(category="rules", name="release-gate", body={"rule": "never ship on a Friday"})
```

Their eight tools run unmodified against the same store (the one difference is the cap they enforce, which now also counts kint's own footprint), and kint never touches the chain inside a Sibyl write. `kint status` now counts the row under `unanchored: <n> changed, 0 deleted`. On a fresh vault nothing is anchored yet, so every row already in the store counts too. If the agent calls `memory_connect` on a machine that is not connected, it gets back the terminal commands from step 3 instead of an error.

## 7. The first push

Three things push, and all three diff the store against the last anchored epoch:

- **On quiet.** While `kint-server` runs, a watcher checks the store every `KINT_POLL_SECONDS` (default 15) and pushes once it has been quiet for `KINT_QUIET_SECONDS` (default 300). Once a minute it also estimates the pending change at 400 bytes a row and pushes early when that passes `KINT_SIZE_TRIGGER_BYTES` (default 32768). A server that starts with rows an earlier session left unanchored counts them as pending and pushes them at its first quiet period. When the server stops, on SIGTERM or SIGHUP included, it tries one more push after the running tool call has unwound; a harness that kills the process outright anchors nothing, and those rows wait for the next session. `KINT_NO_WATCHER=1` turns the watcher off.
- **From the agent.** `memory_push` anchors now and returns `pushed`, `head_seq`, `head_digest` and the epochs.
- **From a shell.** `kint push` (add `--dry-run` to see the counts first; `--confirmations` defaults to 2):

```text
push: epoch 1, <n> rows, 0 deletions, bucket <bucket> B, <bytes> B calldata
anchored 1 epoch(s); head seq 1
  epoch 1: tx 0x<tx hash> block <block> bucket <bucket> B rows <n> del 0 cost <eth> ETH
```

A 4 KB epoch costs about 0.000002 ETH on Base. When nothing changed, push says `nothing to push: the store matches the last anchored epoch` and sends nothing.

The watcher, the exit hook and `memory_push` run one check first. When a row the chain vouches for changed while `kint-server` was running without a write through Sibyl's tools (edited straight in SQLite, say), or still holds exactly the value a `memory_verify` refusal named, the push is held: error `HELD`, nothing anchored, nothing dropped. The message starts `refusing to anchor:`, names up to three rows, and ends by pointing you at `kint push` from your own terminal, or `kint pull --discard-local` to restore the anchored value. The watcher then waits for the store to change again instead of retrying. `kint push` and `kint compact` never run this check: once you have looked at the row, the terminal is how you anchor it.

Push also refuses, and says why:

- when the session key is not authorized;
- when the data key cache has expired (`KINT_KEY_TTL`, default `24h`). `kint-server` moves that deadline forward after every successful pull and push, so it lapses only after that long without either. Run `kint connect` again; nothing is dropped;
- when another machine pushed first. Run `kint pull`; the message names `kint pull --discard-local` for a store that holds unanchored changes;
- when this machine created the vault but its recovery code file is missing;
- when the last pull stopped at an epoch this machine could not apply ([Gaps](/docs/new-machine#gaps)). If that epoch will never open, because a leaked session key wrote it, revoke the key and run `kint compact --over-skipped` from this machine. It anchors a snapshot of this store on top of the chain head, and every later pull resumes there.

The CLI exits 3 for a missing key, 4 when the chain moved, 5 for other refusals.

## 8. Check it

```sh
kint status
```

```text
tenant <tenant>  space <first 16 hex>  store <store path>
owner 0xYOU  data key cached
last anchored on this machine: seq 1 block <block> rows <n>
unanchored: 0 changed, 0 deleted
chain head: seq 1 digest <16 hex> block <block> (in step)  contract 0xa22E03f7a4145Bf4909a83595C90a38E14d79600
session key 0x<session key> balance <eth> ETH authorized True
cap accounting (the same 5 MiB free cap Sibyl enforces):
  sibyl stores      <size>
  kint state        <size>   (mirror, epoch cache, keys; volunteered)
  enforced total    <size> of 5.00 MB
```

`in step` means this machine's mirror matches the chain head; otherwise it reads `NOT in step: pull or push`. From the agent, `memory_status` returns the same picture as JSON, and its `held` field carries the message, the reason (`watcher`, `exit`, `tool` or `status`) and the time while `kint-server` is holding a push, or `null`. `kint doctor` checks every moving part and prints one `[ok  ]`, `[WARN]` or `[FAIL]` row each: Sibyl's packages, `~/.kint` and its mode, the Sibyl store, the enrolment, the cached data key, the recovery code, the primary and secondary RPC (keyed URLs are redacted), the contract's code, the session key's balance and authorization, the head against the mirror, unanchored changes, and whether `PYTHONPATH` is set, plus a failing placement row if `KINT_HOME` sits inside `~/.sibyl-memory`. It exits 1 if any row fails.

## Where the recovery code lands

A fresh vault writes the recovery code to `~/.kint/RECOVERY-<first 16 hex of the space>.txt` (under `KINT_HOME` when set), mode 0600:

```text
kint recovery code for owner 0xYOU, space <64 hex>
Keep this somewhere that is not this machine. It opens the vault without the wallet.

<recovery code>
```

It is the second, independent way to the data key: `kint connect --owner 0xYOU --recovery-code-stdin` opens the vault with neither the wallet nor the passphrase, once there is something to check the code against (an epoch on the chain, or an epoch or data key cached on the machine). `memory_connect` also accepts a `recovery_code` argument, but anything typed into an agent chat lands in the transcript; use the terminal. Copy the code off the machine now. On the machine that created the vault, push refuses while the file is missing or empty; `kint recovery-code` writes it again from the cached data key. After the quickstart, `~/.kint` holds:

```text
~/.kint/
├── session.key                 the session key (V3 scrypt keystore)
├── enrol-<space16>.json        owner, tenant and key tags for this space
├── wraps-<space16>.json        the data key, wrapped under each key that opens it
├── vault-<space16>.aes         the cached data key, encrypted, with a TTL
├── RECOVERY-<space16>.txt      the recovery code (fresh vault only)
├── mirror-<space16>.json       what this machine last anchored
├── watermark-<space16>.json    the newest head this machine has seen
├── head-<space16>.lock         one pusher or puller per space
├── kint.log                    kint-server's log
└── epochs/<space16>/           every epoch's ciphertext, plaintext and metadata
```

Every state file is written with mode 0600 and the directory is 0700; `kint.log` alone takes your umask's default mode, and the 0700 directory keeps it private. With `KINT_KEY_TTL=session` the data key stays in memory and no `vault-*.aes` is written. On a machine without the macOS Keychain (or with `KINT_NO_KEYCHAIN=1`) and without `KINT_SESSION_PASSPHRASE`, a `local.secret` file holds the passphrase that protects the session key and the data key cache. None of it sits under the paths Sibyl's cap accounting walks, and all of it is counted into that cap anyway (the `kint state` line above).

Read [Restore on a new machine](/docs/new-machine) next.

Source: [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/keys.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/keys.py), [`src/kint/page.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/page.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py), [`src/kint/paths.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/paths.py).
