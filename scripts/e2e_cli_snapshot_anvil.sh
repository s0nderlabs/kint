#!/usr/bin/env bash
# Drive `kint compact`, `kint rekey` and `kint pull --full` through the CLI on anvil.
set -u
export FOUNDRY_DISABLE_NIGHTLY_WARNING=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
KINT="$ROOT/.venv/bin/kint"
WORK="$(mktemp -d)"
PORT=$((20000 + RANDOM % 20000))
anvil --chain-id 8453 --port "$PORT" --silent --block-time 1 >/dev/null 2>&1 &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null; rm -rf "$WORK"' EXIT
export KINT_RPC_URL="http://127.0.0.1:$PORT" KINT_RPC_URL_2="http://localhost:$PORT" KINT_NO_KEYCHAIN=1 KINT_SESSION_PASSPHRASE=e2e
for i in $(seq 1 50); do cast chain-id --rpc-url "$KINT_RPC_URL" >/dev/null 2>&1 && break; sleep 0.2; done
DEPLOYER_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
OWNER_KEY=0x1111111111111111111111111111111111111111111111111111111111111111
OWNER=0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A
cd "$ROOT"
export KINT_CONTRACT=$(KINT_DEPLOYER_KEY=$DEPLOYER_KEY env -u PYTHONPATH "$PY" - <<'PY'
import json, os
from web3 import Web3
from eth_account import Account
w3 = Web3(Web3.HTTPProvider(os.environ["KINT_RPC_URL"]))
art = json.load(open("contracts/out/EpochAnchor.sol/EpochAnchor.json"))
d = Account.from_key(os.environ["KINT_DEPLOYER_KEY"])
tx = {"from": d.address, "data": art["bytecode"]["object"], "nonce": w3.eth.get_transaction_count(d.address), "chainId": 8453, "gas": 2_000_000, "maxFeePerGas": 10**9, "maxPriorityFeePerGas": 1}
h = w3.eth.send_raw_transaction(d.sign_transaction(tx).raw_transaction)
print(w3.eth.wait_for_transaction_receipt(h)["contractAddress"])
PY
)
cast send --rpc-url "$KINT_RPC_URL" --private-key $DEPLOYER_KEY --value 1ether $OWNER >/dev/null
export KINT_HOME="$WORK/A/kint" SIBYL_MEMORY_DB="$WORK/A/sibyl/memory.db" KINT_TENANT=cli-snap
env -u PYTHONPATH "$KINT" canonical-payload --owner $OWNER > "$WORK/payload.json"
cast wallet sign --data --from-file "$WORK/payload.json" --private-key $OWNER_KEY | env -u PYTHONPATH "$KINT" connect --owner $OWNER --signature - || exit 1
SK=$(env -u PYTHONPATH "$KINT" session-key create | head -1 | awk '{print $2}')
cast send --rpc-url "$KINT_RPC_URL" --private-key $DEPLOYER_KEY --value 0.1ether "$SK" >/dev/null
KINT_OWNER_KEY=$OWNER_KEY env -u PYTHONPATH "$KINT" authorize direct --owner $OWNER --days 7 || exit 1
env -u PYTHONPATH "$PY" - <<'PY'
import os, sys
sys.path.insert(0, ".")
from kint import store
from tests.conftest import seed
c = store.open_client(os.environ["SIBYL_MEMORY_DB"], os.environ["KINT_TENANT"]); seed(c)
PY
env -u PYTHONPATH "$KINT" push --confirmations 1 || exit 1
echo "== compact --dry-run"
env -u PYTHONPATH "$KINT" compact --dry-run --confirmations 1 || exit 1
echo "== compact"
env -u PYTHONPATH "$KINT" compact --confirmations 1 || exit 1
echo "== rekey"
cast wallet sign --data --from-file "$WORK/payload.json" --private-key $OWNER_KEY | env -u PYTHONPATH "$KINT" rekey --owner $OWNER --signature - --confirmations 1 || exit 1
env -u PYTHONPATH "$KINT" status
echo "== machine B: cold start stops at the snapshot"
export KINT_HOME="$WORK/B/kint" SIBYL_MEMORY_DB="$WORK/B/sibyl/memory.db"
cast wallet sign --data --from-file "$WORK/payload.json" --private-key $OWNER_KEY | env -u PYTHONPATH "$KINT" connect --owner $OWNER --signature - || exit 1
env -u PYTHONPATH "$KINT" pull || exit 1
env -u PYTHONPATH "$KINT" verify "Friday" || exit 1
echo "== machine C: pull --full"
export KINT_HOME="$WORK/C/kint" SIBYL_MEMORY_DB="$WORK/C/sibyl/memory.db"
cast wallet sign --data --from-file "$WORK/payload.json" --private-key $OWNER_KEY | env -u PYTHONPATH "$KINT" connect --owner $OWNER --signature - || exit 1
env -u PYTHONPATH "$KINT" pull --full || exit 1
env -u PYTHONPATH "$KINT" history entity release-gate --category rules
echo "ALL CLI SNAPSHOT STEPS OK"
