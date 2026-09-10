/* End-to-end check of the app's data layer outside the browser: read the passphrase from STDIN
   (never argv), unlock the demo lane on Base mainnet, walk and open every epoch, and print counts
   only. Nothing secret is ever printed. Run: security find-generic-password -s dev.kint-demo-passphrase -a passphrase -w | bun run scripts/try-open.ts */
import { unlock, loadMemory } from "../lib/kint";

const owner = process.env.KINT_OWNER || "0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3";
const tenant = process.env.KINT_TENANT || "kint-demo";
const method = (process.env.KINT_METHOD as "passphrase" | "recovery") || "passphrase";

const secret = (await Bun.stdin.text()).trim();
if (!secret) { console.error("no secret on stdin"); process.exit(2); }

const t0 = Date.now();
const u = await unlock({ owner, tenant }, method, secret);
console.log(`unlocked with ${method}: head seq ${u.head.seq} at block ${u.head.blockNumber}, dek id ${u.dekId}, ${Date.now() - t0} ms`);
const mem = await loadMemory({ owner, tenant }, u, (m) => console.log("  " + m));
console.log(`epochs ${mem.epochs.length}, rows ${mem.rows.length}, versions ${mem.versions.size}, stoppedAt ${mem.stoppedAt}`);
for (const e of mem.epochs) console.log(`  epoch ${e.seq} block ${e.block} ${e.opened ? `opened, ${e.changed} changed, ${e.deleted} deleted, root ${e.matchesRoot ? "ok" : "DIFFERS"}, ${e.bucket} B` : `NOT OPENED: ${e.note}`}`);
const tiers = new Map<string, number>();
for (const r of mem.rows) tiers.set(String(r.tier), (tiers.get(String(r.tier)) || 0) + 1);
console.log("tiers", Object.fromEntries(tiers));
console.log(`total ${Date.now() - t0} ms`);
