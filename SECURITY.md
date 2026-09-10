# Security

kint holds the key to someone's memory, so a flaw in it is a flaw in their custody. If you find
one, please report it privately.

## Reporting

Open a private advisory at
[github.com/s0nderlabs/kint/security/advisories/new](https://github.com/s0nderlabs/kint/security/advisories/new).
Include the version (`kint --help` prints it in the package metadata; the tag is in
`pyproject.toml`), what an attacker needs, what they gain, and a way to reproduce it. Do not open a
public issue for anything that can expose a vault key, a session key or memory contents.

## Scope

- `src/kint/` (key derivation, the envelope, push, pull, restore, verify, the MCP server, the CLI
  and the loopback authorize page).
- `contracts/src/EpochAnchor.sol`, deployed on Base mainnet at
  `0xa22E03f7a4145Bf4909a83595C90a38E14d79600`. It has no admin and no upgrade path, so a fix is a
  new deployment and a new chain of epochs.
- `js/` (`@s0nderlabs/kint-core`, the browser decrypt path).

Sibyl Memory itself is out of scope here; report issues in it to
[Sibyl Labs](https://github.com/Sibyl-Labs/Sibyl-Memory).

## What kint already treats as a limit

These are documented properties, not vulnerabilities: a phished derive signature is a permanent
key; epochs sealed before a `kint rekey` stay readable to whoever held the old key; the row count
and the size bucket of every epoch are public; reading the ciphertext back needs a node that keeps
its transaction index. The full threat model, with who can do what, is the
[Limits and threat model](docs/site/16-limits.md) chapter.
