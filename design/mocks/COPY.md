# kint landing and app: FROZEN COPY (Sep 10 2026)

Every mock uses exactly this copy and exactly these numbers. Nothing here is invented: every
address, hash, block and row is live on Base mainnet under the demo tenant `kint-demo`.
Do not paraphrase the H1, the lede, the three actors or the box. Do not add claims.

## Words that must never appear (Sibyl's vocabulary or forbidden claims)
sync, cross-device, multi-device, shared memory, fleet, sovereign, supercharged,
single source of truth, tamper-proof, immutable, "you don't need Pro", "anchor gate".
Also: no em dash character anywhere, in copy, code or comments.

## Words to use
wallet-owned, self-custodied, outlives the machine, restore, verify, refuse,
built on Sibyl Memory, under Sibyl, their eight tools unmodified, block-height upper bound.

---

## Landing

**Wordmark:** kint (lowercase, always; the dot of the i is the accent square, see BRIEF)
**Nav:** App · GitHub · theme toggle

**Eyebrow:** Built on Sibyl Memory, under it. Live on Base mainnet.

**H1:** Sibyl Memory that outlives the laptop.
(the one emphasised word is "outlives": coloured with the accent, never italic)

**Lede:** Wipe the machine, connect the wallet, and the agent comes back knowing what it knew,
and proves it was not tampered with.

**Primary CTA:** Open the app
**Secondary CTA:** Read the README
**Install line (mono):** uv tool install kint

**Proof strip (live facts, mono; the contract links to its basescan address page, each epoch links to its basescan tx page):**
EpochAnchor 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 · head seq 2 · block 51,081,880 ·
digest 7df5378a8c4fa866 · 15 rows · 4 KB bucket · Base mainnet
Epoch tx hashes (full, for links): epoch 1 0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455 (block 51,081,867), epoch 2 0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729 (block 51,081,880).

**Section eyebrows (in order):** THE THREE ACTORS · THE BEAT · WHAT SIBYL DOES · HONEST LIMITS

### The three actors
1. **The wallet owns.** One frozen message, signed once per machine, derives the key. Nothing
   decrypted ever leaves the machine.
2. **The passphrase or the signature unlocks.** A Base Account owner types a passphrase. An EOA
   owner signs. Either opens the same vault, and a recovery code covers the day both are gone.
3. **kint does the rest.** Every change is packed, padded, encrypted and written to Base as
   calldata under a small contract. On any machine you connect, kint pulls, verifies every
   epoch against the chain, and replays the rows through Sibyl's own write methods.

### The beat (a real terminal transcript; render verbatim, mono, no decoration)
```
$ kint status
tenant kint-demo  space bd2a3b5b8f3fb4c8  store ~/.sibyl-memory/memory.db
owner 0xC635e6Eb223aE14143E23cEEa9440bC773dc87Ec  data key cached
last anchored on this machine: seq 2 block 51081880 rows 15
chain head: seq 2 digest 7df5378a8c4fa866 block 51081880 (in step)

$ kint verify "release rule"
sibyl verdict: ok  hits: 3
  verified   entity rules/release-gate: stored text matches the leaf anchored on Base
  verified   reference runbook-release: stored text matches the leaf anchored on Base
DECISION: PROCEED: verified against rows_root 390336ff71dbcb85 anchored at epoch 2, block 51081880

$ sqlite3 ~/.sibyl-memory/memory.db "update entities set body = replace(body, 'never', 'always') where name = 'release-gate'"
$ kint verify "release rule"
  REFUSED    entity rules/release-gate: stored text does not match the leaf anchored at epoch 2, block 51081880
DECISION: REFUSE: refusal written back as entity kint_refusal/release-gate

$ kint history entity release-gate --category rules
epoch 1 block <= 51081867 leaf f406bb0919d23360: {"rule":"never ship on a Friday; every release needs a green deadlift test and a second reviewer", ...}
epoch 2 block <= 51081880 leaf 4ac605528bbb00e7: {"rule":"never ship on a Friday; every release needs a green deadlift test, a second reviewer, AND a passing kint verify", ...}
```
Caption under the transcript: A row's block height is an upper bound: it existed no later than that block.

### What Sibyl does (the box; this is the judged 40 percent, set it apart)
**Delete the Sibyl Memory layer and what breaks.**
The decision beat reaches the row through Sibyl's memory_search (four FTS5 indexes plus the
shadow fallback) and keys on the typed verdict from verdicts.py. Without Sibyl there is no
ranked candidate and no verdict to key on: the epoch is a decrypted blob with no query surface,
so a fresh session neither refuses nor proceeds. Base holds the ciphertext; Sibyl is what turns
it back into an answerable store. Their eight tools ship unmodified; kint adds six.

### Honest limits (four bullets, verbatim)
- One wallet owns one memory; many machines may write under it, one at a time. Two machines
  writing at once is a fork: kint refuses and tells you.
- Base holds ciphertext, but the row count and the size bucket are public.
- A phished derive signature is a permanent key. The EIP-712 message says so in the one field
  every wallet renders. kint never accepts that signature as a login and never sends it anywhere.
- A cold start stops at the newest snapshot epoch, so restore cost is bounded by the size of the
  memory, not its history.

**Footer:** MIT · Built for the Sibyl Labs Hackathon, September 2026 · s0nderlabs · on Base

---

## App (the memory viewer)

**Top bar:** kint · owner 0xC635…87Ec · tenant kint-demo · head seq 2 · block 51,081,880 ·
lock state (Locked / Unlocked) · theme toggle

### Screen 1: connect and unlock
Fields: Owner address (0xC635e6Eb223aE14143E23cEEa9440bC773dc87Ec), Tenant (kint-demo).
Two unlock paths, side by side or stacked:
- **Sign with the wallet** (EOA owners): "One frozen message. Signing it reveals your memory
  encryption key. Only sign it in a kint page you opened yourself."
- **Type the passphrase** (Base Account owners): a single passphrase field, "Never leaves this page."
Small line under both: Nothing decrypted leaves the browser. Reads never send a transaction.

### Screen 2: the cold start (the film moment)
Progress line (mono): walking epoch 2 of 2 · block 51,081,880 · 15 rows
Then epochs land in order, oldest first:
- epoch 1 · block 51,081,867 · 14 rows · tx 0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455 · opened
- epoch 2 · block 51,081,880 · +2 rows, 1 deleted · tx 0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729 · opened
Finish line: restored 15 rows · rows_root 390336ff71dbcb85 matches the chain · in 1.2 s

### Screen 3: the memory
Tabs (Sibyl's tiers): entities 7 · state 2 · reference 2 · journal 4
Table columns: key · category · status · body · no later than block
Rows (real, from the demo tenant):
| tier | category | key | body (preview) | no later than block |
|---|---|---|---|---|
| entity | rules | release-gate | never ship on a Friday; every release needs a green deadlift test, a second reviewer, AND a passing kint verify | 51,081,880 |
| entity | rules | destructive-commands | never rm -rf a shared path; ask what processes anchor there first | 51,081,867 |
| entity | people | elpabl0 | role founder · tz WIB · prefers short answers, no walls of text | 51,081,867 |
| entity | people | reviewer-a | role second reviewer · reachable attn | 51,081,867 |
| entity | people | reviewer-b | role second reviewer · reachable attn | 51,081,880 |
| entity | projects | kint | Sibyl Memory that outlives the laptop · chain Base · status hackathon build | 51,081,867 |
| entity | facts | deploy-window | Tue to Thu, 09:00 to 17:00 WIB · why: support coverage | 51,081,867 |
| state | | priorities | top: kint submission, sigil audit · updated 2026-09-09 | 51,081,867 |
| state | | session | last_task: wire the harnesses to kint-server | 51,081,867 |
| reference | | runbook-release | # Release runbook · 1. Green tests. 2. Second reviewer signs off. 3. Never on a Friday. 4. Tag, seal, announce. | 51,081,867 |
| reference | | glossary | epoch: one anchored change set. space: keccak of the tenant id. leaf: hash of a stored row. | 51,081,867 |
| journal | | 2026-05-01 09:00 | decision: adopted the Friday release rule after the May 19 incident | 51,081,867 |
| journal | | 2026-08-28 15:30 | refusal: ship the hotfix tonight? why: Friday · next: Monday 09:00 WIB | 51,081,867 |
| journal | | 2026-09-09 18:25 | observation: kura send --wallet is ignored; switch the default wallet first | 51,081,880 |
Deleted in epoch 2 (shown struck through or in a "gone" group): entity projects/sigil, "compliance layer for the agentic economy · status paused", gone at block 51,081,880.
Footer line (mono): verified 15 of 15 rows against block 51,081,880 in 1.2 s · 2 epochs · 4 KB each

### Screen 4: one row's history (drawer or page for rules/release-gate)
Header: rules / release-gate · 2 versions
- **epoch 2 · block <= 51,081,880 · leaf 4ac605528bbb00e7** (current)
  never ship on a Friday; every release needs a green deadlift test, a second reviewer, AND a passing kint verify
  since 2026-09-09 · source: kint hackathon build, supersedes the May rule
- **epoch 1 · block <= 51,081,867 · leaf f406bb0919d23360**
  never ship on a Friday; every release needs a green deadlift test and a second reviewer
  since 2026-05-01 · source: postmortem of the May 19 incident
Show the changed words (the diff) in the accent. Links: tx on basescan, "open the memory at this block".
Caption: existed no later than block N. Never a wall-clock "as of".

### Verdict vocabulary (pills, one word plus a glyph)
verified (green) · refused (red) · closed (an epoch sealed under a retired key, muted) ·
a banner for a refused snapshot: "epoch 3 claims to be a snapshot its plaintext does not back up; the history was read the long way round."

### Empty and error states (one line each, mono)
- wrong passphrase: refused by the key tag before any decrypt
- chain unreadable: two RPC operators disagree on the head; refusing to restore
- fork: another machine wrote epoch 3 first; this machine's 2 unanchored rows are refused
