# Changelog

All notable changes to kint are recorded here. Format based on Keep a Changelog.

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

[0.1.0]: https://github.com/s0nderlabs/kint/releases/tag/v0.1.0
