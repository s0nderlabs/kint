# Changelog

All notable changes to kint are recorded here. Format based on Keep a Changelog.

## [0.3.0] - 2026-09-10

One command to join a machine (`kint join`), pushes held instead of laundered when a row drifted,
a recovery path past an epoch that never opens, the documentation site, and the web app.

### Added

- `kint join`: the read half of onboarding in one command (session key, connect, restore, harness
  registration), writing nothing to the chain; it refuses an empty head unless `--new-vault`, names the
  tenant and where it came from, pins `KINT_TENANT` in every registration, and resumes on a re-run.
- `web/`: the Next.js site (the landing page, the `/app` memory viewer that decrypts in the browser on
  the kint-core code, and `/docs`), deployed at kint.s0nderlabs.xyz from `main`.
- Documentation: sixteen chapters in `docs/site/` rendered by `scripts/build_docs.py` into the site's
  `/docs` (each page also served as raw markdown) plus `llms.txt` and `llms-full.txt` for agents. README
  rewritten with a judges' walkthrough and a live on-chain check; `SECURITY.md`; `docs/judge.md`
  regenerated against the current code.
- `kint compact --over-skipped` and `kint rekey --over-skipped`: the owner's recovery path past an epoch
  this machine can never open (a leaked session key wrote it); CLI only, never a tool argument.
- `memory_status` reports `held` when kint-server is holding a push; `KINT_RPC_TIMEOUT` and
  `KINT_BOOTSTRAP_SECONDS`.

### Changed

- kint-server holds its own pushes (error `HELD`, nothing anchored, nothing dropped) when a row the chain
  vouches for changed behind Sibyl's tools while it ran, or when kint already refused exactly that
  value; `kint push` from a terminal is the human's escape hatch.
- `memory_verify` and `kint verify` go through Sibyl's gated `multi_record_search` (the call
  `memory_search` makes) and refuse when the chain head moved past this machine's last pull; the
  server reads that head at most once every 30 seconds with a 3 second timeout, so the decision beat
  never hangs on a dead RPC.
- A pull resumes past an epoch that never opens when a later snapshot carries the whole state; connect
  and rekey read the newest readable epoch past a junk head, and only a non-kint epoch is ever walked
  past (unreadable or lying calldata stops the walk).
- The cached data key is renewed while kint-server runs; changes an earlier session left unanchored are
  pushed at the next quiet period; a failing auto-push backs off (one minute doubling to an hour) instead
  of retrying every poll; a hung RPC no longer stalls the server start.
- A pull's replay no longer runs the per-row drift bookkeeping (the baseline is rebuilt once when it
  returns), so a restore is linear in the number of rows.
- `kint setup` prints what it printed before; its body moved to `src/kint/setup.py`, shared with `kint join`.
- `kint doctor` and `kint join` use the same session-key balance floor (`MIN_SESSION_BALANCE_WEI`,
  0.00002 ETH); CLI errors flush stdout first so they land after the progress lines in a pipe.
- The fork and chain-moved messages name the real flags (`kint pull`, `kint pull --discard-local`).

### Fixed

- Keyed RPC URLs no longer reach a tool result or a log: every exception string is redacted and the
  server logs no raw tracebacks.
- `kint join` checksums the owner before the restore compares it with the calldata, so a lowercase
  address restores instead of refusing every epoch.
- A snapshot anchored with `--over-skipped` ratchets its size bucket from the head epoch's bucket, so
  the published bucket never shrinks.
- `kint pull --full` walks only the epochs below the oldest cached one when nothing above it is missing,
  and backfills every epoch from the head to genesis otherwise, so history no longer misses the diff
  epochs behind a snapshot.
- `kint authorize burn-nonce` refuses a key that is not the owner's; a trailing slash on `KINT_RPC_URL`
  no longer collapses the second opinion; the termination handler no longer pushes inside an in-flight
  Sibyl write.
- The session-key passphrase no longer passes through the security command's argv.
- The export's docstring: Sibyl's `memory_forget` does write `archived_entities`, which the export does
  not carry.

## [0.2.0] - 2026-09-10

Snapshots, key rotation, and the browser-side decrypt path for the app.

### Added

- Snapshot epochs: `kint compact` (and `memory_push(snapshot=true)`) anchors the whole state as
  one epoch carrying header flag `FLAG_SNAPSHOT` (0x02) and the plaintext key `"snapshot": true`.
  A cold start stops at the newest snapshot, so restore cost is bounded by the size of the memory,
  not its history; `kint pull --full` (and `memory_pull(full=true)`) walks past snapshots and, on
  a machine that already stopped at one, backfills the older epochs into the history cache.
- Key rotation: `kint rekey` makes a new data key, re-wraps it under every key supplied in the
  same command (wallet signature, vault passphrase, extra passphrase), anchors one snapshot epoch
  under the new key, and only then rewrites the local wraps, key cache, recovery code and
  enrolment, all under the head lock. Keys that open the vault today and were not supplied are
  named and refused unless `--drop-missing`. The old recovery code stops working with the new
  head epoch.
- `js/` kint-core: a framework-free TypeScript package for the browser app (frozen typed data,
  KEK from signature or passphrase, header and wrap parsing, epoch open, plaintext parse,
  `applyEpoch`, `readEpoch` with the header-versus-plaintext consistency check, canonical leaves
  and merkle proofs, a chain reader with `coldStartEvents`), verified byte for byte against
  vectors generated by the Python code (`scripts/gen_vectors.py`).
- `scripts/e2e_cli_snapshot_anvil.sh`: drives compact, rekey, a cold start and `pull --full`
  through the CLI on anvil.

### Changed

- `kint connect` on an already-enrolled machine consults the chain head header and prefers it
  when the local wraps hold a retired key; an unreadable chain falls back to the local key.
- A snapshot epoch keeps the deletions since the previous epoch in its plaintext so history and
  `at_block` record a row's disappearance; `history` and the verify provenance skip a snapshot's
  re-anchor of an unchanged row.
- A pull whose walk stopped at an epoch that claims to be a snapshot but cannot be applied walks
  the full history instead of restoring nothing; epochs sealed under a retired key are reported
  as closed rather than silently dropped.
- `kint recovery-code` refuses to write a code for a key that was rotated on another machine.

## [0.1.0] - 2026-09-09

First release, built for the Sibyl Labs Hackathon.

### Added

- `kint-server`: Sibyl Memory's MCP server imported untouched (eight tools as shipped) plus
  `memory_status`, `memory_connect`, `memory_pull`, `memory_push`, `memory_verify`,
  `memory_history`; pulls before serving, pushes on quiet, on size, on demand and on exit.
- Wallet-owned memory: one frozen EIP-712 message derives the key-encryption key (HKDF over the
  low-S normalised signature); a random data key per space wrapped under a list of KEKs
  (signature, passphrase); recovery code bound to the vault; size-bucket padding before AES-256-GCM
  with an AAD that binds chain id, owner, space, seq, prev, bucket, rows_root and dek_id.
- Base Account (Coinbase Smart Wallet) owners: passphrase vault key and a loopback authorize page
  where the account sends `setSessionKey` itself.
- EpochAnchor on Base mainnet (`0xa22E03f7a4145Bf4909a83595C90a38E14d79600`, verified):
  per-owner, per-space hash-linked epochs in calldata; session keys with expiry; owner-signed
  authorization with ERC-1271; revocation cancels an unsubmitted authorization.
- Restore replays rows through the SDK's own write methods; export is raw SQL in rowid order;
  every replayed row is re-read and its leaf compared; identical journal events stay distinct.
- `memory_verify`: Sibyl's search and typed verdict, exact stored text re-read and hashed,
  merkle inclusion against the anchored root, refusal naming both block heights, refusal written
  back as a Sibyl entity; an unanchored top hit is never credited. `memory_history`: what a row
  held at every anchored epoch.
- Cap volunteering: kint's own footprint is counted in Sibyl's free-tier cap through the public
  `CapGate(db_size_fn=...)` hook.
- Freshness watermark, a cold start that requires two different RPC operators, fork refusal,
  gap handling that retries from the last applied epoch, incomplete-mirror refusal.
- Epochs split by measured compressed size; a row that cannot fit is refused by name.
- `kint setup` wires Claude Code, Codex, Hermes and OpenClaw to `kint-server`; `kint doctor`,
  `kint status`, `kint history`, `kint recovery-code`.

[0.3.0]: https://github.com/s0nderlabs/kint/releases/tag/v0.3.0
[0.2.0]: https://github.com/s0nderlabs/kint/releases/tag/v0.2.0
[0.1.0]: https://github.com/s0nderlabs/kint/releases/tag/v0.1.0
