---
slug: keys
title: Keys and custody
description: The owner wallet, the per-machine session key, the frozen vault message, the data key and its rotation.
group: Concepts
order: 5
source: 'src/kint/crypto.py'
---

# The wallet owns the memory, and each machine only appends to it.

kint splits custody between an owner wallet, which opens the memory and decides who may write, and a session key per machine, which pays for epochs and decrypts nothing.

## Two keys, two jobs

The two keys never do each other's job. This page covers both, the one message the wallet signs, the data key under it, the recovery code, and what a rotation can and cannot do.

| | Owner wallet | Session key |
|---|---|---|
| What it is | Your own EOA (Ledger, MetaMask, Rabby, a foundry keystore) or a Base Account | A plain EOA that `kint session-key create` generates on this machine |
| Where it lives | Wherever you keep it. kint never stores it | `~/.kint/session.key`, a V3 scrypt keystore, mode 0600 |
| What it signs | The vault message (EOA owners, on connect and on rekey) and each session key's authorization | `push` and `setSessionKeyBySig` transactions to EpochAnchor, nothing else |
| Can it read the memory | Yes: its vault signature derives the key-encryption key (a Base Account owner uses a passphrase instead) | No: it holds nothing that decrypts |
| Pays gas | In the `direct`, `page` and `burn-nonce` lanes | Every epoch, and `setSessionKeyBySig` in the `payload` lane |

The split lets the owner key stay cold. A hardware wallet signs twice per machine (the vault message and the authorization) and goes back in the drawer. The hot key sitting next to the agent can append epochs under the owner's name until it expires or is revoked, and that is all it can do. It cannot rewrite an anchored epoch (the contract keeps only the head digest, and every `push` must name it as `prev`), and it cannot read a byte. What it appends can be any bytes, including an epoch no key opens; [Epochs on Base](/docs/epochs#an-epoch-nobody-can-open) covers how kint gets past one.

EpochAnchor has no owner rotation. If you lose the owner key, new writes end once its session keys expire. The recovery code or a passphrase wrap still opens the memory on a new machine without it.

## The session key

```sh
kint session-key create    # "created: 0x..." (an existing key is reported as "exists: 0x..." and left alone)
kint session-key show      # JSON: address, path, exists, and from the chain balance, authorized, expiry
kint session-key rotate    # moves session.key to session.key.old, then creates a new key
```

`show` asks the chain about the owner from `--owner`, or the owner this machine is connected to. `rotate` does not touch the chain. The new address needs its own authorization and a little ETH, and the old one stays authorized until its expiry unless you revoke it. `kint doctor` reports the session key as ok only when its balance is at least 0.00002 ETH and it is authorized.

You never type the keystore passphrase. kint reads it from the first of these that exists:

1. `KINT_SESSION_PASSPHRASE`, for servers and anything without a Keychain.
2. On macOS, the Keychain item with service `dev.kint-session-key` and account `passphrase`, created with a random value on first use. `KINT_NO_KEYCHAIN=1` skips it.
3. `~/.kint/local.secret` (mode 0600), created with a random value on first use.

If none exists when the key is loaded, kint stops with `no local passphrase: set KINT_SESSION_PASSPHRASE`. The same secret also encrypts the [vault key cache](/docs/keys#the-vault-key-cache).

## Authorize a machine

EpochAnchor accepts a `push` when `canWrite(owner, writer)` is true: the writer is the owner, or `sessionKeyExpiry[owner][writer] > block.timestamp`. `kint authorize` sets that expiry for this machine's session key in one of four lanes. Every lane takes `--owner` (by default, the connected owner) and needs this machine's session key to exist. `direct`, `page` and `payload` compute `expiry = now + days * 86400` from `--days`, which defaults to 30; `submit` sends the expiry that `payload` printed.

| lane | who signs | who sends and pays | contract call |
|---|---|---|---|
| `direct` | the owner key in `KINT_OWNER_KEY` | the owner | `setSessionKey(key, expiry)` |
| `page` | a Base Account, in your browser | the account | `setSessionKey(key, expiry)` |
| `payload`, then `submit` | the owner, offline, over EIP-712 | the session key | `setSessionKeyBySig(owner, key, expiry, deadline, signature)` |
| `burn-nonce` | the owner key in `KINT_OWNER_KEY` | the owner | `setSessionKey(key, current expiry)` |

**direct.** `KINT_OWNER_KEY=0x... kint authorize direct` reads the owner key from the environment, never argv. It refuses a key that is not the owner (`KINT_OWNER_KEY is 0x..., not the owner 0x...`) and prints the transaction, its cost and its block.

**page.** This lane is for Base Account (Coinbase Smart Wallet) owners. kint serves one page on `127.0.0.1` at a random port, with a 32-byte token in the path, and prints the URL. The page connects the account, refuses if it is not the expected owner, and sends `setSessionKey(key, expiry)` from the account. For an account that has never sent a transaction, that same transaction also deploys it. kint then polls `canWrite(owner, key)` every 3 seconds, up to 120 times. The page server binds loopback only, checks `Origin` and `Sec-Fetch-Site` on the result it receives, exits after one result, and gives up after 900 seconds. No derive signature, passphrase or key ever crosses the page.

A signature lane cannot do this job: a counterfactual account has no code, so `setSessionKeyBySig` cannot run its ERC-1271 check. It falls through to `ecrecover` and rejects the signature. After that first transaction the account has code, and ERC-1271 works.

**payload and submit.** In this lane a hardware wallet signs offline, and the session key submits and pays.

```sh
kint authorize payload > kint-auth.json
cast wallet sign --data --from-file kint-auth.json --ledger | kint authorize submit --deadline <D> --expiry <E> --signature -
```

`payload` writes the `SessionKeyAuthorization` typed data to stdout, with `nonce = authNonce(owner)` read from the chain and `deadline = now + 300`. On stderr it prints the nonce, deadline and expiry, plus the exact `submit` line to run. `submit` reads the signature from stdin (`-` is also the default). The signature works once: the nonce increments on success. The contract rejects it once the deadline has passed (`AuthorizationExpired`), so submit within five minutes of `payload`. It also rejects an EOA signature with `s` in the upper half of the curve order (`BadSignature`). Its domain is `kint EpochAnchor`, version `1`, chain 8453, with EpochAnchor as `verifyingContract`. That is a different domain from the vault message, so an authorization signature can never double as a derive signature.

**burn-nonce.** This lane re-sets the session key's current expiry from the owner. That consumes `authNonce`, so any signed but unsubmitted authorization dies. It prints `nonce consumed: authNonce(0x...) is now N`. Like `direct`, it refuses a key that is not the owner (`KINT_OWNER_KEY is 0x..., not the owner 0x...`).

### Expiry and revocation

Expiry is a unix timestamp stored per owner and key, and 0 means revoked. A key expires on its own. After that, push refuses with `session key 0x... is not authorized for owner 0x...: authorize it (kint authorize) and fund it` (exit 5). Run any lane again to extend it.

kint has no revoke command. The owner calls `revokeSessionKey(key)` on EpochAnchor. That sets the expiry to 0 in the same block and consumes `authNonce`, so a signed authorization the revoked machine still holds cannot re-arm it. An EOA owner with Foundry:

```sh
cast send 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 "revokeSessionKey(address)" 0xSESSION_KEY --ledger --rpc-url "$KINT_RPC_URL"
```

A smart-account owner sends the same call from the account. Revoking stops writes, not reads: that machine keeps its cached data key until the cache expires, and any recovery file on it is the data key itself. For a compromised machine, revoke its key, then run [`kint rekey`](/docs/keys#rotate-the-data-key) from a machine you trust. If a leaked key already appended an epoch that does not open, run `kint pull` on that machine first (it records the epoch it cannot apply), then `kint rekey --over-skipped`: the new snapshot chains on the chain head, past that epoch. If the bad epoch's header parses and rekey refuses its wraps, run `kint compact --over-skipped` first, then `kint rekey`.

## The vault message

An EOA owner signs one frozen EIP-712 message, and that signature is the vault key. `kint canonical-payload --owner 0x...` prints it as `cast wallet sign --data --from-file` reads it: byte-stable, one line, no whitespace between tokens. Here it is indented, for the owner in the committed test vectors:

```json
{
  "types": {
    "EIP712Domain": [
      {"name": "name", "type": "string"},
      {"name": "version", "type": "string"},
      {"name": "chainId", "type": "uint256"}
    ],
    "KintVault": [
      {"name": "owner", "type": "address"},
      {"name": "purpose", "type": "string"}
    ]
  },
  "primaryType": "KintVault",
  "domain": {"name": "kint", "version": "1", "chainId": 8453},
  "message": {
    "owner": "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A",
    "purpose": "kint-memory-v1: signing this reveals your memory encryption key. Only sign it in a kint terminal or page you opened yourself."
  }
}
```

For that owner the digest is `39fec015d21465d81dd5611129982b7a310e070a126f41dfdd8c87cc04a31517`. The signature reaches kint through a pipe, never argv:

```sh
kint canonical-payload --owner 0xYOU > kint-canonical.json
cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0xYOU --signature -
```

`--signature-file PATH` also works, and kint deletes the file after reading it. `memory_connect` never accepts the signature.

**Why `purpose` is a warning.** The domain has no `verifyingContract` and no `salt`, so nothing in it ties the message to one page or one deployment. A phishing page could ask for the same signature. The defence is what the signer reads, and `purpose` is the field every wallet renders. So that field says what signing does and where it is safe. The other half of the defence is that kint never accepts this signature as a login and never sends it anywhere. The wallet must sign deterministically (RFC 6979), so the same wallet produces the same 65 bytes on every machine. A Base Account cannot do that (passkey signatures are not deterministic), which is why Base Account owners use the passphrase path.

> **Warning.** A phished derive signature is permanent. It reaches back over every epoch already on Base, it cannot be revoked, and it covers every tenant of that wallet, because the message names no space. Sign it only in a kint terminal or page you opened yourself. With a salt passphrase (`--passphrase-prompt`), the signature alone opens nothing.

## From signature to key

These are the steps for the signature path (wrap kind `0x01`), in order:

1. The signature must be exactly 65 bytes, with `v` as 27/28 or 0/1, and `r` and `s` in range.
2. kint recovers the signer over the vault digest, and it must be the owner. Otherwise kint stops with `derive signature recovers to 0x..., expected 0x...; refusing to derive a key from it`. This check never sits behind a try/except: it is the only thing between a wrong signature and a silently different key.
3. Low-S normalise: if `s > n/2`, then `s = n - s`. A malleated twin of the same signature derives the same key.
4. `ikm = r || s`, 64 bytes. `v` never enters.
5. `info = "kint-kek-v1" || owner (20 bytes) || space (32 bytes)`, 63 bytes, where `space = keccak256("kint-space-v1" || tenant id)`.
6. `KEK = HKDF-SHA256(ikm, salt, info)`, 32 bytes. The salt is empty unless you add a salt passphrase.

Because `info` carries the owner and the space, one signature gives each tenant its own KEK.

**A salt passphrase as a second factor.** `kint connect --passphrase-prompt` (or `--passphrase-stdin` together with `--signature-file`) sets `salt = scrypt(passphrase, owner20, N = 2^17, r = 8, p = 1, 32 bytes)`. `--passphrase-stdin` and `--signature -` cannot share stdin, and kint says so. A header does not say whether a signature wrap is salted: flag `0x01` is defined, but no kint writer sets it. The CLI does not guess: pass the salt flag every time you connect or rekey with a salted signature. The browser contract (`docs/frontend-contract.md`) has a reader derive the unsalted key first and ask for the salt only when no wrap carries that key's tag.

**The passphrase path** (wrap kind `0x02`, `kint connect --smart-account`) needs no wallet. `ikm = scrypt(passphrase, salt = owner20, N = 2^17, r = 8, p = 1, 32 bytes)`, then `KEK = HKDF-SHA256(ikm, salt = "", info)` with the same 63-byte `info`. The passphrase is encoded as UTF-8 with no Unicode normalisation, in Python and in `js/` alike. `--passphrase-stdin` strips leading and trailing whitespace and the prompt does not, so do not start or end a passphrase with a space: the two would derive different keys. kint refuses an empty passphrase. It prompts `vault passphrase: `, or reads stdin with `--passphrase-stdin`. `memory_connect(passphrase=...)` accepts it too, but anything typed into an agent chat lands in the transcript, so use the terminal.

| test vector (owner above, throwaway key `0x11...11`, tenant `demo`, unsalted) | hex |
|---|---|
| space | `fd83319f25a64bb2952805bd9bf32719080d37c6a83b6a51db74e409eb42bff6` |
| KEK, signature path | `c69d894607fac5813904d32c44c4603835b746a529ada52fae1834ac28cc418f` |
| kek_tag | `9710b041b39054fa3ad68ee22c8f2e79` |

## One data key, many wraps

A KEK never encrypts memory. Each space has one random 32-byte data key (DEK), wrapped under a list of KEKs:

```text
wrap        = kind(1) | kek_tag(16) | wrap_nonce(12) | wrapped_dek(48)
wrapped_dek = AES-256-GCM(KEK, wrap_nonce, DEK, aad = "kint-wrap-v1" || kind || kek_tag)
kek_tag     = HMAC-SHA256(KEK, "kint-kek-check-v1")[:16]
dek_id      = HMAC-SHA256(DEK, "kint-dek-id-v1")[:8]
```

Every epoch header carries the whole list and the `dek_id`. A client finds its wrap by comparing `kek_tag`, and never tries each wrap in turn. AES-GCM is not key-committing, so the tag match is what proves the key is the right one. Unwrapping refuses a mismatch before AES runs (`kek_tag mismatch: this key does not open this wrap`). The kinds are a frozen enum, extended only at the end: `0x01` wallet signature, `0x02` passphrase, `0x03` reserved for WebAuthn PRF, `0x04` reserved for an EOA-owned smart account.

`kint connect` gets the DEK from the first of these that works:

1. The wraps on this machine (`~/.kint/wraps-<space16>.json`), while they hold the current key.
2. The header of the newest readable epoch on Base: the head, unless its bytes do not parse as a kint header, in which case kint walks back through `prevBlock` (at most 32 epochs) to the newest one that does. kint fetches that epoch's ciphertext, checks its keccak256 against the `Epoch` event digest, and finds its wrap by tag. Whenever the chain can be read, the header decides, so local wraps left over from before a rotation give way.
3. A fresh vault, when the chain has no epochs for this owner and space and this machine has no wraps for it: a new DEK, one wrap and a new recovery code.

With `KINT_OFFLINE=1`, kint does not ask the chain, so on a machine with no wraps it starts a fresh vault instead of opening the one on Base. If the chain cannot be read and a local wrap matches, connect uses the local key. The command prints the owner, `data key from local wraps | chain head header | fresh vault | recovery code`, and the first 8 hex characters of the kek_tag. It never prints the signature, the KEK or the DEK. Connecting with the wrong key fails on the tag: `this key (tag ...) does not open the vault anchored under 0x...: the wraps in the head epoch carry different tags. Wrong wallet, wrong passphrase, or wrong tenant.`

An EOA owner can add a second key with `kint connect --add-passphrase`, which prompts `extra passphrase wrap (empty to skip): `. It adds a kind `0x02` wrap, derived exactly like the passphrase path, so it opens the same DEK without the wallet. Every epoch pushed after that carries it.

## The recovery code

The recovery code is the data key itself: base32 of `DEK || sha256(DEK)[:2]`, padding stripped, in hyphenated groups of four. That makes 55 characters in 14 groups, the last group three characters long. Decoding ignores case, hyphens and spaces, and the 2-byte checksum catches a typo (`recovery code checksum failed (typo?)`).

kint writes it to `~/.kint/RECOVERY-<space16>.txt`, mode 0600, at three moments: when connect creates a fresh vault, on `kint recovery-code`, and on `kint rekey`.

```text
kint recovery code for owner 0x..., space <space hex>
Keep this somewhere that is not this machine. It opens the vault without the wallet.

XXXX-XXXX-XXXX-...
```

Copy it off the machine. The machine that created the vault refuses to push while that file is missing or empty. `kint recovery-code` rewrites it from the cached data key. It refuses if the cached key is not the one the head epoch was sealed with, which happens when the key was rotated on another machine.

To use it, run `kint connect --owner 0x... --recovery-code-stdin`. The checksum only proves the code was typed correctly, so before caching anything, kint binds the code to this vault: its `dek_id` must equal the head header's (`this recovery code does not belong to the vault anchored under this owner`). When the chain cannot be read, kint checks against the cached data key or the newest cached epoch header instead. With nothing to check against, it refuses: a recovery code cannot start a vault. Connecting with a code adds no wrap. The machine takes the wraps from the head header, so it can push. `memory_connect(recovery_code=...)` accepts it too, but anything typed into an agent chat lands in the transcript, so use the terminal.

## The vault key cache

After a connect, the unwrapped DEK is cached, so the agent is not blocked on you again for a while. The cache is `~/.kint/vault-<space16>.aes`: AES-256-GCM under `HKDF-SHA256(local secret, info = "kint-vault-cache-v1")`, with the space id in hex as AAD. The local secret is the one that protects the session keystore.

| `KINT_KEY_TTL` | how long the cached key lasts |
|---|---|
| unset, empty or unparseable | 24 hours |
| a number | that many seconds |
| a number with `s`, `m`, `h` or `d` | e.g. `30d` for an unattended machine |
| `session` | memory only, in the process that connected; never written to disk |

While kint-server runs, every successful pull and push (the startup pull, `memory_pull`, `memory_push`, the watcher's and the exit hook's) caches the key again with a fresh deadline, so a server in use does not lapse. The key still lapses on a machine that goes longer than the TTL without one of those: an idle server, or a machine used only from the CLI, whose commands never renew it.

An expired key loses nothing. Push refuses with exit 3 (`KEY_EXPIRED` from `memory_push`) and says so: nothing was dropped, and the changes stay in the store until the next push. kint-server starts without pulling, its watcher waits, and `memory_verify` and `memory_history` keep working. Run `kint connect` again, or set `KINT_KEY_TTL=30d` on a machine that stays up.

## Rotate the data key

`kint rekey` replaces the DEK and keeps the keys that open it. It is CLI only. No MCP tool rotates the key, because the secrets that open a vault are typed in a terminal, never in an agent chat. In order:

1. It refuses unless this machine is connected to the vault.
2. It takes the head lock for the space.
3. It reads the newest readable epoch's header from Base (skipped with `KINT_OFFLINE=1`): the head, or, past a head that does not parse as a kint header, the newest epoch within 32 that does, logging `connect: the head epoch N at block B is not a readable kint epoch (...)` and `connect: using epoch N at block B, the newest readable one`. Those wraps are the keys a new machine sees, so they decide what must be carried over. Local wraps count only when the chain has no epochs.
4. It derives a KEK from every key you supplied. Each must open a current wrap: rekey re-wraps keys that work today and cannot add a new one.
5. It unwraps the current DEK and checks its `dek_id` against that header's.
6. It lists the current wraps you did not supply, and refuses by name unless you pass `--drop-missing`.
7. It generates a new random DEK and wraps it under each supplied key, keeping each wrap's kind.
8. It anchors one snapshot epoch under the new DEK, with the same checks a push makes (recovery file, head in step, session key authorized). A machine behind the chain must run `kint pull` first, and the whole state must fit in one epoch. With `--over-skipped`, on a machine whose last pull stopped at an epoch it could not apply, the snapshot chains on the chain head instead ([Epochs on Base](/docs/epochs#an-epoch-nobody-can-open)).
9. Only then, still holding the lock, it rewrites the local wraps, the key cache, the recovery file and the enrolment. If the push fails, nothing on this machine has changed.

```sh
cast wallet sign --data --from-file kint-canonical.json --ledger | kint rekey --signature -
cast wallet sign --data --from-file kint-canonical.json --ledger | kint rekey --signature - --add-passphrase
kint rekey --smart-account          # a Base Account owner: prompts for the vault passphrase
```

| flag | meaning |
|---|---|
| `--owner` | defaults to the connected owner |
| `--signature -`, `--signature-file PATH` | the wallet signature, from stdin or from a file that is deleted after reading |
| `--passphrase-prompt` | the salt passphrase of a salted signature |
| `--passphrase-stdin` | one passphrase from stdin: the salt when a signature is given, otherwise the vault passphrase |
| `--smart-account` | carry the vault passphrase wrap (prompted). Combine with `--signature` to carry both |
| `--add-passphrase` | also carry the extra passphrase wrap (prompted) |
| `--drop-missing` | rotate without the wraps you did not supply |
| `--over-skipped` | rotate even though the last pull stopped at an epoch this machine could not apply: the new snapshot chains on the chain head |
| `--confirmations N` | confirmations to wait for, default 2 |

It prints the old and new `dek_id`, the snapshot epoch and its transaction, how many keys were carried over and which were dropped, the path of the new recovery file, then `the old recovery code no longer opens this vault; copy the new one somewhere that is not this machine`. Exit codes: 2 for a refusal, 3 when there is no session key or no local secret to unlock it, 4 when the chain moved, 5 when the push failed.

Afterwards, other machines holding a carried-over key run `kint connect` again, and the head header hands them the new DEK. A machine whose local wraps hold a dropped key is told `the data key of this vault was rotated and this key (tag ...) was not carried over: it opens the epochs sealed before the rotation and nothing after it`. On a machine with no local wraps, a dropped key gets the ordinary wrong-key refusal. connect refuses the old recovery code, because its `dek_id` no longer matches the head. A machine holding only the new key restores from the rotation's snapshot. It reports older epochs as closed (`sealed under a data key this machine does not hold (rotated)`). `kint pull --full` walks back past the rotation, but it reports each earlier epoch as closed and opens none of them.

**What a rotation cannot undo.** Every epoch before the rotation stays on Base, sealed under the old DEK, which is what the old recovery code encodes and what every old wrap opens. Anyone who held one of those can read everything up to the rotation, permanently. A rotation protects what comes next. Because rekey re-wraps under the same KEKs, a leaked key you carry over opens the new DEK too. To shut a key out, leave it out and pass `--drop-missing`. A leaked wallet signature cannot be changed (same wallet, same message, same key), so leaving its wrap out means that wallet opens nothing sealed after the rotation.

## Files on this machine

These are the key files. `KINT_HOME` also holds the mirror, the epoch cache, the watermark, the head lock and the log.

```text
~/.kint/                      KINT_HOME, mode 0700
├── session.key               the session key, V3 scrypt keystore
├── session.key.old           the previous key, after kint session-key rotate
├── local.secret              keystore and cache secret, when there is no env var or Keychain
├── enrol-<space16>.json      owner, tenant, account kind, the kek tags of the current wraps
├── wraps-<space16>.json      the current wraps of the data key
├── vault-<space16>.aes       the cached data key, encrypted, with its expiry
└── RECOVERY-<space16>.txt    the recovery code
```

`<space16>` is the first 16 hex characters of the space id. kint writes each of these files at mode 0600 through an atomic replace; `session.key.old` is the previous keystore, renamed.

Read [Epochs on Base](/docs/epochs) next.

Source: [`src/kint/crypto.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/crypto.py), [`src/kint/keys.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/keys.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py), [`src/kint/page.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/page.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`contracts/src/EpochAnchor.sol`](https://github.com/s0nderlabs/kint/blob/main/contracts/src/EpochAnchor.sol), [`docs/frontend-contract.md`](https://github.com/s0nderlabs/kint/blob/main/docs/frontend-contract.md).
