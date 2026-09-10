---
slug: new-machine
title: Restore on a new machine
description: Wipe the machine, connect the wallet, pull: every step a restore takes and every check it makes.
group: Get started
order: 3
source: 'src/kint/pull.py'
---

# A new machine comes back knowing what the old one knew.

The disk is gone and the wallet is not. This page walks the restore end to end and, for each step, says what kint checks against Base and what makes it refuse.

## What you need

The steps: install, a session key for this machine, `kint connect` again, `kint pull`. Restoring and reading never send a transaction; the one transaction on this page authorizes the new session key, and a machine that only restores and reads can skip it until it needs to write. You need:

- **The owner.** The wallet address that owns the memory. An EOA owner signs the same frozen EIP-712 message again, a Base Account owner types the vault passphrase, and the recovery code opens the vault when neither is at hand.
- **The tenant.** The memory lives in a space, `keccak256("kint-space-v1" || tenant)`, so a different tenant is a different memory. kint takes it from `--tenant` (given before the subcommand), else `KINT_TENANT`, else `tenant_id` or `account_id` in Sibyl's `credentials.json`, else Sibyl's default tenant.
- **For writing only:** a little ETH on Base for this machine's session key.

## Install

```sh
uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0
```

That puts `kint` and `kint-server` on your PATH (Python 3.10 or newer). If your shell sets `PYTHONPATH`, run them with it unset (`env -u PYTHONPATH kint ...`); `kint setup` keeps it out of every harness registration for that reason: Claude Code starts the server through `/usr/bin/env -u PYTHONPATH`, and Codex, Hermes and OpenClaw start it with `PYTHONPATH` set empty.

The Sibyl store kint restores into is `$SIBYL_MEMORY_DB`, else `~/.sibyl-memory/memory.db` (`--db` overrides it for one command). kint's own state goes to `$KINT_HOME`, else `~/.kint`.

## One command: kint join

`kint join` runs the read half of this page in one go: this machine's session key, connect, restore, and harness registration. It writes nothing to the chain and spends nothing. Give it the owner and exactly one secret:

```sh
kint join --owner 0xYourBaseAccount --base-account            # prompts: vault passphrase:
kint canonical-payload --owner 0xYOU > kint-canonical.json
cast wallet sign --data --from-file kint-canonical.json --ledger | kint join --owner 0xYOU --signature -
kint join --owner 0xYOU --recovery-code-stdin
```

It prints what it is about to join first: the owner, the tenant and where that came from (`--tenant`, `KINT_TENANT`, `credentials.json` or Sibyl's default), the space, the contract and the store. Then, in order:

1. **Session key.** An existing one is kept; otherwise one is created.
2. **Vault.** It reads the head. With no epochs under that owner and tenant it stops and says so (pass `--tenant` if you anchored under another one); only `--new-vault` lets it start a vault here.
3. **Connect.** The same three ways in as `kint connect`, described below.
4. **Restore.** The same pull as `kint pull`, with `--discard-local` and `--full` passed through.
5. **Harnesses.** It registers kint-server with every harness it finds (`--setup claude`, `codex`, `hermes` or `openclaw` for one, `--no-setup` for none), always with `KINT_TENANT` pinned to the tenant it joined, plus any `--env KEY=VALUE`.
6. **Report.** `writes: on` when the session key is authorized and holds at least 0.00002 ETH, otherwise `writes: off until the session key is funded and authorized by the owner; reads work now` and the next step.

A failure stops it with `join stopped at <step>: <message>`, and the exit code says where: 4 for a fork, 6 for a freshness refusal and 5 for another pull refusal, as `kint pull` uses them, and 2 when it stops before the restore. Every step reads the state first, so running it again resumes rather than starting over. Writing stays a separate, deliberate step: fund the session key and authorize it, as in the next section. The rest of this page is what each step does, by hand.

On a wiped machine against the demo vault (a Base Account owner, `--no-setup`), it took 4.6 seconds:

```text
$ kint --tenant kint-demo join --owner 0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3 --base-account
vault passphrase:
join: owner 0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3
      tenant kint-demo (from --tenant), space bd2a3b5b8f3fb4c8
      contract 0xa22E03f7a4145Bf4909a83595C90a38E14d79600, store ~/.sibyl-memory/memory.db
      this command writes nothing to the chain
session key: 0xA43874410423cf3482Ec63193c94eB71106AA1FF (created; it signs epochs for this machine and can never decrypt)
vault: head epoch 1 at block 51082012
connected: key tag 14e3812b, data key from chain head header
pull: cold start, both RPCs agree: head seq 1, digest b64dcde033b03249, block 51082012
pull: applied epoch 1 (5 rows, 0 deletions) from block 51082012
restore: restored 1 epoch(s), 5 rows; head seq 1 at block 51082012; store root matches the anchored root
harnesses: not registered (--no-setup)
writes: off until the session key is funded and authorized by the owner; reads work now
next: put a few cents of ETH on 0xA43874410423cf3482Ec63193c94eB71106AA1FF (Base), then kint authorize page
```

Run again on the same machine, it keeps the key (`(kept)`), takes the data key `from local wraps` and reports `restore: up to date`.

## A session key for this machine

The old machine's session key went with its disk. Every machine signs its own Base transactions with its own key:

```sh
kint session-key create
```

It prints `created: 0x...` and writes a V3 scrypt keystore to `~/.kint/session.key` (mode 0600). The keystore passphrase comes from `KINT_SESSION_PASSPHRASE` when it is set, else the macOS Keychain item `dev.kint-session-key` (created on first use), else a `local.secret` file under `~/.kint`. The key signs transactions to EpochAnchor and nothing else; it can never decrypt. Send it a little ETH on Base.

Then the owner authorizes it on the contract. Until `kint connect` has run there is no enrolment on this machine, so pass `--owner`. `--days` sets the expiry (default 30).

| command | who signs | what happens |
|---|---|---|
| `kint authorize payload`, then `submit` | the owner, over typed data | `payload` prints the `SessionKeyAuthorization` typed data on stdout and the exact `submit` line on stderr, with a deadline 300 seconds out; `submit` reads the signature on stdin and the session key sends `setSessionKeyBySig`, paying its own gas |
| `kint authorize direct` | the owner key in `KINT_OWNER_KEY` | the owner sends `setSessionKey` itself; the key is read from the environment, never argv |
| `kint authorize page` | a Base Account, in the browser | a loopback page where the account sends `setSessionKey`; kint then polls `canWrite` on the chain |

For an EOA owner on a hardware wallet:

```sh
kint authorize payload --owner 0xYOU > kint-auth.json
cast wallet sign --data --from-file kint-auth.json --ledger | kint authorize submit --owner 0xYOU --deadline <D> --expiry <E> --signature -
```

`kint session-key show --owner 0xYOU` prints the address, the balance, whether it is authorized and until when (after `kint connect`, the owner comes from the enrolment). If the old machine was lost rather than wiped, its key stays authorized until its expiry. The contract's `revokeSessionKey(key)`, sent from the owner, drops it in the same block; kint v0.3.0 has no command for that call. Then consider `kint rekey` from a machine you trust ([Keys and custody](/docs/keys)).

## Connect again

The same three ways in as on the first machine. An EOA owner (Ledger, MetaMask, Rabby, a foundry keystore) signs the frozen payload again, and the derive signature travels on stdin, never argv:

```sh
kint canonical-payload --owner 0xYOU > kint-canonical.json
cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0xYOU --signature -
```

A Base Account owner types the vault passphrase instead (`kint connect --owner 0xYourBaseAccount --smart-account`), and with neither at hand the recovery code opens the vault (`kint connect --owner 0xYOU --recovery-code-stdin`). Both have their own sections below: [The Base Account passphrase](/docs/new-machine#the-base-account-passphrase) and [The recovery code](/docs/new-machine#the-recovery-code).

A fresh machine has no local key wraps, so the data key comes out of the chain. kint reads the head for this owner and space, finds that epoch's `Epoch` event at its block, fetches the push transaction's calldata, checks `keccak256(ciphertext)` against the event digest, and parses the header. If the head epoch's bytes are on the chain but do not parse as a kint header (an epoch a leaked session key wrote, say), kint walks back through `prevBlock`, at most 32 epochs, and uses the newest epoch whose header parses: those are the wraps a new machine can open. The header carries the data key wrapped once per key that opens the vault. kint derives this machine's key-encryption key from your signature or passphrase, compares its 16-byte tag with each wrap's tag, and unwraps only the one that matches. The wraps are saved under `~/.kint`, the data key is cached (encrypted at rest, 24 hours by default, `KINT_KEY_TTL`), and connect prints:

```text
connected: owner 0x...
space <first 16 hex>  key tag <first 8 hex>  data key from chain head header
session key: 0x...
```

It never prints the signature, the key-encryption key or the data key. What makes it refuse:

- No wrap matches: `this key (tag ...) does not open the vault anchored under 0x...: the wraps in the head epoch carry different tags. Wrong wallet, wrong passphrase, or wrong tenant.` The message ends by pointing at the recovery code.
- A head epoch whose header parses but carries wraps none of your keys open gets that same refusal. Only a header that does not parse is stepped over; the way past the other kind is a snapshot anchored over it from a machine that still holds the data key ([Epochs on Base](/docs/epochs#an-epoch-nobody-can-open)).
- The ciphertext does not hash to its event: `ciphertext digest does not match the Epoch event`. The RPC served bytes the event does not vouch for, and connect never walks past that.
- The chain cannot be read: `cannot read the chain head: ...`, `cannot read the head epoch: ...` or `cannot fetch the calldata of epoch N: ...`. That is a transport failure, never a security verdict; try again or change the RPC. A walk back that finds no header that parses within 32 epochs also ends with `cannot read the head epoch`.

If the vault was created with a passphrase salting the wallet key (`--passphrase-prompt`), give the same passphrase here or the tag will not match. `--passphrase-stdin` and `--signature -` cannot share stdin: use `--passphrase-prompt`, or `--signature-file`.

> **Warning.** If connect prints `fresh vault: recovery code written to ...`, it found no epochs for this owner and tenant and started a new, empty vault. On a machine meant to restore, that means the wrong tenant or the wrong owner address, or `KINT_OFFLINE=1`, which skips the chain read. Stop, fix it, connect again with the chain reachable, then run `kint recovery-code` so the recovery file on this machine holds the real vault's code. `kint join` refuses in this case unless you pass `--new-vault`.

## Pull

```sh
kint pull
```

Pull needs the cached data key (without it: "no data key on this machine: run `kint connect` ... first") and takes the head lock for the space, so two kint processes on one machine never pull or push the same space at once. It waits up to 30 seconds for the lock, then fails with `another kint process holds the head lock for this space`. `--owner` overrides the enrolled owner; `--force-scan` is accepted and passed through, but pull does not act on it in v0.3.0. The steps below run in the order the code runs them.

### Freshness: two endpoints on a cold start

A cold start is a pull with no watermark for this space, which is every first pull on a fresh machine. kint reads the head (seq, digest, block) from the primary RPC and asks a second endpoint for the same head:

- **Primary:** `KINT_RPC_URL`, else on macOS the Alchemy key in the Keychain item `dev.api.alchemy` (`KINT_NO_KEYCHAIN=1` turns that off), else `https://mainnet.base.org`.
- **Second:** `KINT_RPC_URL_2`, else `https://base-rpc.publicnode.com` when the primary is `https://mainnet.base.org` (a trailing slash counts as the same URL), else `https://mainnet.base.org`.

Every JSON-RPC call gives up after `KINT_RPC_TIMEOUT` seconds (default 10). A call web3 marks as safe to repeat is tried once more after 0.1 seconds on a connection error, an HTTP error or a timeout, so a dead endpoint is reported after two tries.

The second must not be the same host, port and path as the first, or pull refuses before asking. If the two disagree on seq or digest, kint waits 3 seconds and asks the second once more; still different, it refuses with `two RPCs disagree on the head: ...; refusing to restore from a contested head`. If the second cannot be reached, it refuses with `could not get a second opinion on the head from ...`. `KINT_ALLOW_SINGLE_RPC=1` accepts one RPC when the second is the same endpoint or unreachable, and says so in the output; it never overrides a disagreement. Wherever kint reports an error (a tool result, a log line, a CLI message), every URL in it keeps its scheme, host and port and loses the rest (`https://host/<redacted>`), and the path and query of each endpoint kint is configured with are scrubbed wherever they appear, so an API key in the URL stays out. kint-server logs an unexpected push, pull or verify failure as its error type and the redacted message, never a raw traceback; the CLI still prints a Python traceback, on your own terminal, for an error it does not catch.

After the first applied epoch, the watermark (seq, digest, block) exists and never decreases. Every later pull refuses a head older than it, or the same seq with a different digest: `... stale or lying RPC, refusing`.

### The fork check

This runs before anything is written. `kint connect` leaves an empty mirror, this machine's record of what the chain last saw. If the Sibyl store here already holds rows for this tenant (Sibyl was used on this machine before kint, say), those rows were never anchored and the chain has moved past the mirror, so pull refuses: `the chain moved to seq N and this store has X changed and Y deleted rows that were never anchored: a fork.` A store with rows and no mirror at all is refused too (`Refusing to merge blindly`). The same refusal protects a machine that wrote locally while another machine anchored: its push fails because the head moved, and its pull refuses instead of losing the local rows.

`kint pull --discard-local` resolves it. It moves `memory.db`, `memory.db-wal` and `memory.db-shm` aside to `<name>.kint-backup-<YYYYmmdd-HHMMSS>` next to the store (moved, not deleted) and restores from the chain. The refusal says as much: push is impossible because the head moved, and pulling would lose the rows, so save what you need out of the store yourself before you discard. A rebase (a row-level merge over a fork) is not built ([Limits and threat model](/docs/limits)).

### The walk

kint walks backwards from the head through the `prevBlock` field of each `Epoch` event, one exact-block `eth_getLogs` per epoch, so no RPC range cap is ever hit. It stops at the newest snapshot epoch (header flag `0x02`, written by `kint compact`, `memory_push(snapshot=true)` and every `kint rekey`), because a snapshot's rows are the whole state. Then it applies the epochs oldest first. When it starts at a snapshot, the epochs before it are never opened; the prevBlock links from the head vouch for the snapshot's place in the chain.

### What every epoch must pass

In this order. The first failure makes the epoch a gap (see [Gaps](/docs/new-machine#gaps)).

1. **Continuity.** The event's `prev` equals the digest of the epoch applied just before it.
2. **Ciphertext.** From the local epoch cache only if it still hashes to the event digest; otherwise from the push transaction's calldata. That transaction must be addressed to EpochAnchor and call `push`, its decoded owner, space and prev must match the event, and `keccak256(ciphertext)` must equal the event digest.
3. **Header.** It parses as envelope version 1.
4. **Key.** The cached data key's id (the first 8 bytes of HMAC-SHA256 keyed with the data key over `kint-dek-id-v1`) equals the header's `dek_id`.
5. **AEAD.** The ciphertext is exactly the bucket plus a 16-byte tag, and AES-256-GCM opens it under the AAD `keccak256(abi.encode(chainId, owner, space, seq, prev, bucket, rows_root, dek_id))` with chain id 8453. A byte changed after anchoring already failed step 2; a ciphertext altered before it was anchored fails here, and so does an epoch replayed under another owner, space or position.
6. **Plaintext.** It unpads, decompresses and parses as version 1; its seq, space and prev agree with the chain, and its `rows_root` agrees with the header.
7. **Snapshot flag.** The header flag agrees with the plaintext's `snapshot` key. The flag is not covered by the AAD, so the two must agree before either is acted on.

Then the rows are replayed, and two more checks run on the result:

8. **Leaf re-read.** Every replayed row is read back from the store and its leaf (keccak256 over the exact stored text) compared with the anchored one: `stored text differs from the anchored leaf after replay`, or `row missing after replay`.
9. **Running root.** The merkle root of this machine's picture after the epoch equals the header's `rows_root`.

A failure at 8 or 9 is a warning, not a gap: the epoch is applied, pull prints a `pull: WARNING epoch N: ...` line for it, and the summary counts the warnings. At the end kint exports the whole store once more and compares its root with the mirror's and the anchored one; that is the `store root matches the anchored root` in the summary line.

### Replay through Sibyl's write methods

Rows go back into the store through the SDK, never raw SQL: `set_entity`, `set_state`, `set_reference` and `write_event`. Deletions run first. Only entities have an SDK delete (`delete_entity`); a deletion in another tier is reported as `no SDK delete for this tier`.

| on replay | what happens |
|---|---|
| row content: key, category, status, body, reference metadata | exact; it is what the leaf hashes |
| the journal `ts` | survives: passed to `write_event` explicitly, and part of the leaf |
| uuids, a journal event's id included | regenerate; a journal row's identity is its content, and two identical events stay two rows |
| entity, state and reference `updated_at` | regenerate; not part of the leaf |

A snapshot epoch replaces the local picture: rows it does not hold are deleted where the SDK can delete them, and only rows whose stored text differs are written, so an append-only journal event is never written twice.

### What it prints

```text
pull: cold start, both RPCs agree: head seq <seq>, digest <16 hex>, block <block>
pull: applied epoch <seq> (<rows> rows, <deletions> deletions) from block <block>
restored <n> epoch(s), <rows> rows; head seq <seq> at block <block>; store root matches the anchored root
cold start: two RPCs agreed on the head: True
```

After that come one `SKIPPED` line per gap and one `CLOSED` line per epoch sealed under a retired key. Exit codes: 4 for a fork, 6 for a freshness refusal, 5 for any other refusal (a missing data key included). A gap is not an error: pull exits 0 and prints the `SKIPPED` line. The demo tenant `kint-demo` has two ordinary epochs, epoch 1 with 14 rows at [block 51081867](https://basescan.org/tx/0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455) and epoch 2, the release rule rewritten, at [block 51081880](https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729); neither is a snapshot, so a cold start of that tenant walks and applies both.

### What the machine now holds

```text
~/.kint/
├── session.key               this machine's session key
├── enrol-<space>.json        owner, tenant, account kind, key tags
├── wraps-<space>.json        the key wraps, taken from the head epoch's header
├── vault-<space>.aes         the data key, encrypted at rest, with a TTL
├── mirror-<space>.json       what this machine believes the chain last saw
├── watermark-<space>.json    the freshness floor: seq, digest, block
├── head-<space>.lock         one pusher or puller per space per machine
└── epochs/
    └── <space>/
        ├── 00000001.bin          the ciphertext, as read from calldata
        ├── 00000001.json         the decrypted plaintext (history reads this)
        └── 00000001.meta.json    seq, digest, prev, block, tx, bucket, rows_root, writer
```

`<space>` is the first 16 hex characters of the space id. Every file is written with mode 0600.

## Snapshots and --full

Stopping at the newest snapshot bounds restore cost by the size of the memory, not its history. The price is history on this machine: `kint history` and `memory_history` read the local epoch cache, so versions older than the snapshot are not there. The log says so: "pull: starting at snapshot epoch N; the epochs before it are not needed to restore (`kint pull --full` walks them for the older versions)".

`kint pull --full` walks past snapshots to the first epoch. On a machine that already restored, it backfills: it walks from the head to the first epoch and fetches, checks and caches every epoch this machine has not decrypted yet, including the diff epochs an earlier pull jumped when it stopped at a newer snapshot, and it leaves the store and the mirror alone (`N older epoch(s) cached for history`). When every epoch is already cached or reported, it returns without walking. An epoch it cannot open is listed as `CLOSED` with its reason, and the walk carries on past it. The backfill runs only when the pull itself ended without a gap.

A snapshot flag cannot cut a restore short. If the epoch the walk stopped at claims to be a snapshot and does not open, pull logs `pull: epoch N claims to be a snapshot but cannot be applied; walking the full history instead`, applies the epochs before it, stops there, and reports the bad epoch as a gap.

## Gaps

When an epoch fails a check, the pull stops there. Nothing after it is applied, the mirror stays at the last applied epoch, and the epoch is recorded as skipped:

```text
  SKIPPED epoch <seq> block <block>: <reason>
```

The next pull retries from that point: a transient RPC failure heals itself, a wrong key does not (connect again). Until the gap applies, push refuses (`this machine could not apply epoch(s) [N] on its last pull, so its picture of the memory is incomplete`) and verify refuses (`this machine's picture of the memory is not the one the chain vouches for`). A partial picture is never anchored over or acted on.

One kind of failure does not stop a walk that goes past snapshots (`--full`). When this machine cannot open the epoch at all (its header does not parse, no key here opens it, or AES-GCM refuses it) and a later snapshot in the same walk opens, that snapshot carries the whole state, so the pull resumes there and ends complete:

```text
  SKIPPED epoch <seq> block <block>: <reason> (snapshot epoch <s> carries the whole state, the pull carried on)
```

A read failure (the RPC would not serve the calldata, served calldata that disagrees with the event, or the prev links break) and an epoch that opened and contradicts the chain always stop the pull, because nobody has seen what is in that epoch. An epoch that will never open, with no later snapshot, stays a gap until the owner anchors a snapshot over it; the push refusal names `kint compact --over-skipped` ([Epochs on Base](/docs/epochs#an-epoch-nobody-can-open)).

## Epochs sealed under a retired key

`kint rekey` rotates the data key and anchors one snapshot epoch under the new one ([Keys and custody](/docs/keys)). A new machine gets the new key from the head header, and the walk starts at the rotation's snapshot (or a newer one). The epochs before it carry a different `dek_id`, and this machine holds no key for them. With `--full` on a cold start they are listed and left closed:

```text
  CLOSED epoch <seq> block <block>: sealed under a data key this machine does not hold (rotated)
```

and the summary ends `N older epoch(s) sealed under a retired key stay closed on this machine`. They stay readable to whoever held the old key: a rotation protects what comes next, not what is already on a public ledger. The old recovery code stops opening the vault from the rotation's snapshot on.

## The recovery code

The recovery code is the data key itself: base32 of the key plus a 2-byte SHA-256 checksum, in groups of four. The machine that created the vault wrote it to `~/.kint/RECOVERY-<space>.txt`, and every `kint rekey` writes a new one.

```sh
kint connect --owner 0xYOU --recovery-code-stdin
```

The checksum catches a typo (`recovery code checksum failed (typo?)`). Then the code is bound to this vault: its key id must equal the `dek_id` of the newest readable epoch (normally the head), or connect refuses with `this recovery code does not belong to the vault anchored under this owner`. The wraps come from the head header, so this machine can still push later, and connect reports `key tag none` and `data key from recovery code`. A recovery code cannot start a vault: with no epochs on the chain and nothing cached here, it refuses.

A restored machine does not hold the recovery file. `kint recovery-code` writes a copy from the cached data key, and refuses when that key was rotated on another machine. Push only insists on the file on the machine that created the vault.

## The Base Account passphrase

A Base Account (Coinbase Smart Wallet) has no deterministic derive signature, so its vault key comes from a passphrase: scrypt over the passphrase, salted with the owner address (N = 2^17, r = 8, p = 1), then HKDF.

```sh
kint connect --owner 0xYourBaseAccount --smart-account     # prompts: vault passphrase:
kint session-key create
kint authorize page
kint pull
```

A wrong passphrase is refused by the key tag before any decrypt: the tag is compared first, and a wrap is never trial-decrypted. `--passphrase-stdin` reads the passphrase from stdin instead of the prompt. `kint authorize page` serves one page on 127.0.0.1 with a random port and a 32-byte token in the path. The page connects the account, checks it is the expected owner, and the account sends `setSessionKey` itself (on an account that has never sent a transaction, that one also deploys it). kint waits up to 15 minutes for the page's result, then polls `canWrite(owner, key)`. No passphrase, signature or key crosses the page. On Base mainnet, Base Account `0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3` authorized a machine this way, and that machine then anchored [an epoch under it at block 51082012](https://basescan.org/tx/0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12).

`memory_connect` also accepts `passphrase` and `recovery_code` (with `owner` the first time). Prefer the terminal: anything typed into an agent chat lands in the transcript.

## kint-server pulls before it serves

`kint-server` builds Sibyl's server with their eight tools unmodified plus kint's six, starts the startup pull on its own thread, and waits for it up to `KINT_BOOTSTRAP_SECONDS` (default 20). Then it starts the quiet-period watcher and serves on stdio. A pull still running at that point (a slow cold start, a slow RPC) finishes in the background. Until it does, Sibyl's tools answer from the store as far as the pull has got, `memory_pull` and `memory_push` wait for its head lock (up to 30 seconds), and `memory_verify` refuses while the chain head is past this machine's mirror. A refusal never keeps it from serving:

| state at start | what the server does |
|---|---|
| no enrolment | serves; `memory_connect` returns the terminal steps |
| data key not cached, or expired | serves without pulling |
| a fork | logs the refusal and serves the local store |
| a freshness refusal | logs it and serves |
| any other pull failure | logs it and serves the local store |
| a pull still running after `KINT_BOOTSTRAP_SECONDS` | logs `bootstrap: still running; serving now, the pull finishes in the background` and serves |

Logs go to stderr and `~/.kint/kint.log`, never stdout, which the MCP transport owns. So a wiped machine can come back two ways: connect and pull in the terminal, then start the harness; or connect in the terminal and let the first `kint-server` start do the cold start. The server serves within about `KINT_BOOTSTRAP_SECONDS` of starting however slow the RPC is, so set a harness's startup timeout above that (Codex: `startup_timeout_sec`), and give `memory_pull` room with its tool timeout (`tool_timeout_sec`). Inside a session, `memory_pull` runs the same code with `discard_local` and `full`, and returns `FORK`, `NOT_FRESH` or `PULL_FAILED` where the CLI returns an exit code. [Harnesses](/docs/harnesses) covers `kint setup`.

## Check it

```text
$ kint status
owner 0xC635e6Eb223aE14143E23cEEa9440bC773dc87Ec  data key cached
last anchored on this machine: seq 2 block 51081880 rows <n>
chain head: seq 2 digest 7df5378a8c4fa866 block 51081880 (in step)  contract 0xa22E03f7a4145Bf4909a83595C90a38E14d79600
```

Those are three of `kint status`'s lines on the demo tenant: the mirror and the head agree. Then `kint verify "release rule"` (or `memory_verify` from the agent) searches through Sibyl's gated search, checks that the chain head is still the one this machine pulled, re-reads each hit's stored text and proves it against the anchored `rows_root`, and `kint doctor` checks every moving part, including whether the second RPC is the same as the first. What the restored agent does with a row it recalls is [Verify before acting](/docs/verify).

Read [How it works](/docs/how-it-works) next.

Source: [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/restore.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/restore.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/epoch.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/epoch.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py).
