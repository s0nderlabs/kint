# Claims a judge can check in under two minutes

Every line number refers to this repository at the tagged release, and to Sibyl Memory at
revision 761bfc6 (client 0.8.1, mcp 0.2.1). Run `pytest -q` and `forge test` to see the tests that pin them.
Regenerate this table with `scripts/gen_judge.py`.

| claim | file | line | note |
|---|---|---|---|
| Sibyl's server is imported untouched and its eight tools are kept | `src/kint/server.py` | 4 | then six `@mcp.tool()` additions below it |
| Their tools use the one client kint builds (cap volunteered) | `src/kint/store.py` | 80 | seeds `sibyl_memory_mcp.server._client_cache` |
| Cap volunteering through Sibyl's public hook | `src/kint/store.py` | 53 | `CapGate(db_size_fn = aggregate_db_size + kint footprint)` |
| Decision beat goes through Sibyl's search and its typed verdict | `src/kint/verify.py` | 178 | Sibyl `multi_record_search` at multi_record.py:444, the gated call their `memory_search` makes; returns `SearchResults` with `.verdict` |
| No hit or a non-OK verdict refuses | `src/kint/verify.py` | 182 |  |
| Exact stored TEXT is re-read by the key the search returned | `src/kint/export.py` | 70 | Sibyl's `dumps()` is `sort_keys=False` (storage.py:97); nothing is re-serialised |
| Leaf and merkle inclusion proof against the anchored rows_root | `src/kint/canon.py` | 77 | proof at canon.py:106, checked in verify.py:161 |
| A drifted row is refused naming the anchored block and the head block | `src/kint/verify.py` | 166 |  |
| An unanchored top hit is never credited as verified | `src/kint/verify.py` | 216 | tests/test_review_fixes.py |
| The refusal is written back as a Sibyl entity | `src/kint/verify.py` | 227 | category `kint_refusal`, status `refused` |
| Temporal read: every anchored version with a block-height upper bound | `src/kint/verify.py` | 108 | `at_block` at verify.py:133 |
| Restore replays through the SDK's write methods, not raw SQL | `src/kint/restore.py` | 35 | set_entity client.py:887, set_state :986, write_event :1019, set_reference :1092 |
| Every replayed row is re-read and its leaf compared, in the pull path | `src/kint/pull.py` | 285 | the check itself at restore.py:78 |
| Export is raw SQL in rowid order (documented) | `src/kint/export.py` | 30 | identical journal events keep distinct ordinals |
| Nothing touches the chain inside a Sibyl write transaction | `src/kint/push.py` | 137 | push reads the store read-only after the writes returned; the cap gate in store.py is local-only |
| Freshness before anything: watermark, two DIFFERENT RPCs on a cold start | `src/kint/pull.py` | 84 | same-endpoint guard at pull.py:90 |
| Fork refusal over unanchored local changes | `src/kint/pull.py` | 170 |  |
| Epoch integrity: keccak(ct) == event digest, prev continuity, AEAD with a binding AAD | `src/kint/pull.py` | 495 | AAD at crypto.py:360 |
| A gap stops the pull at the last applied epoch; the next pull retries | `src/kint/pull.py` | 262 |  |
| An incomplete mirror refuses to push and to verify | `src/kint/epoch.py` | 62 | push.py:132, verify.py:190 |
| Key derivation: recover must equal the owner, low-S normalise, HKDF over r||s | `src/kint/crypto.py` | 207 | committed vector in tests/test_crypto.py |
| Random DEK wrapped under a list of KEKs; tag-match, never trial-decrypt | `src/kint/crypto.py` | 281 |  |
| Pad to a size bucket before encrypting; publish only the bucket | `src/kint/crypto.py` | 334 | monotone ratchet at crypto.py:329 |
| Epochs are split by MEASURED compressed size; an oversize row is refused by name | `src/kint/push.py` | 64 |  |
| Recovery code as the second path to the data key, bound to the vault before it is cached | `src/kint/connect.py` | 260 | code format at crypto.py:296 |
| The derive signature never travels on argv | `src/kint/connect.py` | 68 |  |
| Keyed RPC URLs are redacted wherever kint prints one | `src/kint/chain.py` | 144 | exception text raised inside web3 can still carry the URL (known gap) |
| Session key can only append; the contract enforces it | `contracts/src/EpochAnchor.sol` | 132 | push at EpochAnchor.sol:140 |
| Revocation cancels an unspent signed authorization (audit fix) | `contracts/src/EpochAnchor.sol` | 78 | test_RevokeInvalidatesUnspentAuthorization |
| All kint state lives outside the five paths Sibyl's cap walk sizes | `src/kint/paths.py` | 15 | aggregate_db_size at _capcheck.py:270 |

## What is not built

- `kint pull --rebase` (row-level last-writer-wins over a fork). Refuse-and-tell ships; rebase is next.
- A hosted (HTTPS) door for Claude on the web. The owner / session-key split makes it possible without uploading a key; the user hosts.
- The EOA-owned smart account as a key source (Coinbase Smart Wallet with an EOA owner). Measured on a fork, not shipped; Base Account owners use the passphrase path.
- Owner rotation. Losing the owner key ends new writes for that owner once its session keys expire; reads never need it.
- The frontend viewer (`docs/frontend-contract.md` is its contract).

## Deletion test

Remove the `multi_record_search(...)` call in `src/kint/verify.py` and there is no ranked candidate and no verdict: the decision cannot be made. Remove `sibyl_memory_mcp.build_server()` from `src/kint/server.py` and no harness can read or write memory at all. Remove the four SDK write calls in `src/kint/restore.py` and a restored machine has an encrypted blob and an empty store.

## Executed on Base mainnet

EpochAnchor `0xa22E03f7a4145Bf4909a83595C90a38E14d79600` (verified on Basescan). Demo epochs: `0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455` (block 51081867), `0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729` (block 51081880), and from a Base Account owner `0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12` (block 51082012).

## Harnesses that read this memory through kint-server (Sep 9 2026)

Claude Code (`claude -p`), Codex (`codex exec --sandbox danger-full-access`), Hermes (`hermes chat -q`) and OpenClaw (a dedicated agent on a tool-capable model) each recalled the release rule, verified it and reported decision `proceed` at block 51081880. Commands in `docs/agents.md`.
