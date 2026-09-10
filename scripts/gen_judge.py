#!/usr/bin/env python3
"""Regenerate docs/judge.md's claims table with live file:line pointers. Run from the repo root."""
import re
S = "/Users/alkautsar/Documents/s0nderlabs/Sibyl-Memory/sibyl-memory-client/src/sibyl_memory_client/"


def line(path, pattern):
    try:
        for i, l in enumerate(open(path, encoding="utf-8"), 1):
            if re.search(pattern, l):
                return i
    except FileNotFoundError:
        return "?"
    return "?"


rows = [
 ("Sibyl's server is imported untouched and its eight tools are kept", "src/kint/server.py", line("src/kint/server.py", r"mcp = build_server\(\)"), "then six `@mcp.tool()` additions below it"),
 ("Their tools use the one client kint builds (cap volunteered)", "src/kint/store.py", line("src/kint/store.py", r"def seed_sibyl_server_cache"), "seeds `sibyl_memory_mcp.server._client_cache`"),
 ("Cap volunteering through Sibyl's public hook", "src/kint/store.py", line("src/kint/store.py", r"db_size_fn=volunteered_size_fn"), "`CapGate(db_size_fn = aggregate_db_size + kint footprint)`"),
 ("Decision beat goes through Sibyl's search and its typed verdict", "src/kint/verify.py", line("src/kint/verify.py", r"results = multi_record_search\(client, query"), f"Sibyl `multi_record_search` at multi_record.py:{line(S+"multi_record.py", r"^def multi_record_search")}, the gated call their `memory_search` makes; returns `SearchResults` with `.verdict`"),
 ("No hit or a non-OK verdict refuses", "src/kint/verify.py", line("src/kint/verify.py", r"if results.verdict.code != VerdictCode.OK"), ""),
 ("Exact stored TEXT is re-read by the key the search returned", "src/kint/export.py", line("src/kint/export.py", r"def read_row"), f"Sibyl's `dumps()` is `sort_keys=False` (storage.py:{line(S+'storage.py', r'def dumps')}); nothing is re-serialised"),
 ("Leaf and merkle inclusion proof against the anchored rows_root", "src/kint/canon.py", line("src/kint/canon.py", r"def leaf\("), f"proof at canon.py:{line('src/kint/canon.py', r'def merkle_proof')}, checked in verify.py:{line('src/kint/verify.py', r'chk.proof_ok = verify_proof')}"),
 ("A drifted row is refused naming the anchored block and the head block", "src/kint/verify.py", line("src/kint/verify.py", r'chk.status = "drifted"'), ""),
 ("An unanchored top hit is never credited as verified", "src/kint/verify.py", line("src/kint/verify.py", r'top = next\(c for c in checks if c.status == "verified"\)'), "tests/test_review_fixes.py"),
 ("The refusal is written back as a Sibyl entity", "src/kint/verify.py", line("src/kint/verify.py", r"def write_refusal_entity"), "category `kint_refusal`, status `refused`"),
 ("Temporal read: every anchored version with a block-height upper bound", "src/kint/verify.py", line("src/kint/verify.py", r"def history\("), f"`at_block` at verify.py:{line('src/kint/verify.py', r'def at_block')}"),
 ("Restore replays through the SDK's write methods, not raw SQL", "src/kint/restore.py", line("src/kint/restore.py", r"def write_row"), f"set_entity client.py:{line(S+'client.py', r'    def set_entity')}, set_state :{line(S+'client.py', r'    def set_state')}, write_event :{line(S+'client.py', r'    def write_event')}, set_reference :{line(S+'client.py', r'    def set_reference')}"),
 ("Every replayed row is re-read and its leaf compared, in the pull path", "src/kint/pull.py", line("src/kint/pull.py", r"verify_db_path=db_path, tenant_id=tenant"), f"the check itself at restore.py:{line('src/kint/restore.py', r'if verify_db_path is not None')}"),
 ("Export is raw SQL in rowid order (documented)", "src/kint/export.py", line("src/kint/export.py", r"def export_rows"), "identical journal events keep distinct ordinals"),
 ("Nothing touches the chain inside a Sibyl write transaction", "src/kint/push.py", line("src/kint/push.py", r"rows = export_rows\(db_path, tenant\)"), "push reads the store read-only after the writes returned; the cap gate in store.py is local-only"),
 ("Freshness before anything: watermark, two DIFFERENT RPCs on a cold start", "src/kint/pull.py", line("src/kint/pull.py", r"def _check_freshness"), f"same-endpoint guard at pull.py:{line('src/kint/pull.py', r'if _same_endpoint\(anchor.rpc_url')}"),
 ("Fork refusal over unanchored local changes", "src/kint/pull.py", line("src/kint/pull.py", r"raise Fork\("), ""),
 ("Epoch integrity: keccak(ct) == event digest, prev continuity, AEAD with a binding AAD", "src/kint/pull.py", line("src/kint/pull.py", r"def _open_one"), f"AAD at crypto.py:{line('src/kint/crypto.py', r'def epoch_aad')}"),
 ("A gap stops the pull at the last applied epoch; the next pull retries", "src/kint/pull.py", line("src/kint/pull.py", r"gap_at = ev.seq"), ""),
 ("An incomplete mirror refuses to push and to verify", "src/kint/epoch.py", line("src/kint/epoch.py", r"def complete"), f"push.py:{line('src/kint/push.py', r'if mirror.skipped')}, verify.py:{line('src/kint/verify.py', r'not mirror.complete')}"),
 ("Key derivation: recover must equal the owner, low-S normalise, HKDF over r||s", "src/kint/crypto.py", line("src/kint/crypto.py", r"def derive_kek_from_signature"), "committed vector in tests/test_crypto.py"),
 ("Random DEK wrapped under a list of KEKs; tag-match, never trial-decrypt", "src/kint/crypto.py", line("src/kint/crypto.py", r"def unwrap_dek"), ""),
 ("Pad to a size bucket before encrypting; publish only the bucket", "src/kint/crypto.py", line("src/kint/crypto.py", r"def pad_to_bucket"), f"monotone ratchet at crypto.py:{line('src/kint/crypto.py', r'def next_bucket')}"),
 ("Epochs are split by MEASURED compressed size; an oversize row is refused by name", "src/kint/push.py", line("src/kint/push.py", r"def _chunk"), ""),
 ("Recovery code as the second path to the data key, bound to the vault before it is cached", "src/kint/connect.py", line("src/kint/connect.py", r"def connect_recovery"), f"code format at crypto.py:{line('src/kint/crypto.py', r'def recovery_code')}"),
 ("The derive signature never travels on argv", "src/kint/connect.py", line("src/kint/connect.py", r"def read_secret"), ""),
 ("Keyed RPC URLs are redacted wherever kint prints one", "src/kint/chain.py", line("src/kint/chain.py", r"def redact"), "exception text raised inside web3 can still carry the URL (known gap)"),
 ("Session key can only append; the contract enforces it", "contracts/src/EpochAnchor.sol", line("contracts/src/EpochAnchor.sol", r"function canWrite"), f"push at EpochAnchor.sol:{line('contracts/src/EpochAnchor.sol', r'function push\(')}"),
 ("Revocation cancels an unspent signed authorization (audit fix)", "contracts/src/EpochAnchor.sol", line("contracts/src/EpochAnchor.sol", r"function revokeSessionKey"), "test_RevokeInvalidatesUnspentAuthorization"),
 ("All kint state lives outside the five paths Sibyl's cap walk sizes", "src/kint/paths.py", line("src/kint/paths.py", r"def kint_home"), f"aggregate_db_size at _capcheck.py:{line(S+'_capcheck.py', r'def aggregate_db_size')}"),
]
out = ["# Claims a judge can check in under two minutes", "",
       "Every line number refers to this repository at the tagged release, and to Sibyl Memory at",
       "revision 761bfc6 (client 0.8.1, mcp 0.2.1). Run `pytest -q` and `forge test` to see the tests that pin them.",
       "Regenerate this table with `scripts/gen_judge.py`.", "",
       "| claim | file | line | note |", "|---|---|---|---|"]
for c, f, l, n in rows:
    out.append(f"| {c} | `{f}` | {l} | {n} |")
out += ["", "## What is not built", "",
        "- `kint pull --rebase` (row-level last-writer-wins over a fork). Refuse-and-tell ships; rebase is next.",
        "- A hosted (HTTPS) door for Claude on the web. The owner / session-key split makes it possible without uploading a key; the user hosts.",
        "- The EOA-owned smart account as a key source (Coinbase Smart Wallet with an EOA owner). Measured on a fork, not shipped; Base Account owners use the passphrase path.",
        "- Owner rotation. Losing the owner key ends new writes for that owner once its session keys expire; reads never need it.",
        "- The frontend viewer (`docs/frontend-contract.md` is its contract).",
        "", "## Deletion test", "",
        "Remove the `multi_record_search(...)` call in `src/kint/verify.py` and there is no ranked candidate and no verdict: the decision cannot be made. Remove `sibyl_memory_mcp.build_server()` from `src/kint/server.py` and no harness can read or write memory at all. Remove the four SDK write calls in `src/kint/restore.py` and a restored machine has an encrypted blob and an empty store.",
        "", "## Executed on Base mainnet", "",
        "EpochAnchor `0xa22E03f7a4145Bf4909a83595C90a38E14d79600` (verified on Basescan). Demo epochs: `0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455` (block 51081867), `0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729` (block 51081880), and from a Base Account owner `0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12` (block 51082012).",
        "", "## Harnesses that read this memory through kint-server (Sep 9 2026)", "",
        "Claude Code (`claude -p`), Codex (`codex exec --sandbox danger-full-access`), Hermes (`hermes chat -q`) and OpenClaw (a dedicated agent on a tool-capable model) each recalled the release rule, verified it and reported decision `proceed` at block 51081880. Commands in `docs/agents.md`."]
open("docs/judge.md", "w").write("\n".join(out) + "\n")
print("docs/judge.md regenerated:", len(rows), "claims,", "unresolved:", sum(1 for r in rows if r[2] == "?"))
