"""Deploy EpochAnchor to Base mainnet.

Reads the RPC URL from KINT_RPC_URL and the deployer private key from
KINT_DEPLOYER_KEY. The key is never accepted on the command line and is never
printed. Run it with the project venv:

    env -u PYTHONPATH .venv/bin/python contracts/deploy.py

Build first (forge build) so out/EpochAnchor.sol/EpochAnchor.json exists.
"""

import json
import os
import sys
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

CHAIN_ID = 8453
HERE = Path(__file__).resolve().parent
ARTIFACT = HERE / "out" / "EpochAnchor.sol" / "EpochAnchor.json"
OUT_FILE = HERE / "deployments" / "base-mainnet.json"
GAS_BUFFER = 1.20


def load_artifact():
    if not ARTIFACT.exists():
        sys.exit("missing %s, run: forge build" % ARTIFACT)
    data = json.loads(ARTIFACT.read_text())
    bytecode = data["bytecode"]["object"]
    if not bytecode.startswith("0x"):
        bytecode = "0x" + bytecode
    if len(bytecode) <= 2:
        sys.exit("artifact has empty bytecode")
    return data["abi"], bytecode


def main():
    rpc_url = os.environ.get("KINT_RPC_URL", "").strip()
    if not rpc_url:
        sys.exit("set KINT_RPC_URL")
    key = os.environ.get("KINT_DEPLOYER_KEY", "").strip()
    if not key:
        sys.exit("set KINT_DEPLOYER_KEY (env only, never a flag)")
    if not key.startswith("0x"):
        key = "0x" + key

    abi, bytecode = load_artifact()

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        sys.exit("cannot reach the RPC at KINT_RPC_URL")

    chain_id = w3.eth.chain_id
    if chain_id != CHAIN_ID:
        sys.exit("wrong chain: RPC reports %d, expected %d" % (chain_id, CHAIN_ID))

    account = Account.from_key(key)
    deployer = account.address
    balance = w3.eth.get_balance(deployer)
    print("deployer:", deployer)
    print("balance:", w3.from_wei(balance, "ether"), "ETH")
    if balance == 0:
        sys.exit("deployer has no ETH on Base")

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    ctor = contract.constructor()

    gas_estimate = ctor.estimate_gas({"from": deployer})
    gas_limit = int(gas_estimate * GAS_BUFFER)
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas", 0) or 0
    try:
        priority_fee = w3.eth.max_priority_fee
    except Exception:
        priority_fee = w3.to_wei(0.001, "gwei")
    max_fee = base_fee * 2 + priority_fee

    print("gas estimate:", gas_estimate, "-> limit:", gas_limit)
    print("base fee (wei):", base_fee, "priority (wei):", priority_fee)
    print("max fee (wei):", max_fee)
    print("worst case L2 cost:", w3.from_wei(gas_limit * max_fee, "ether"), "ETH")

    tx = ctor.build_transaction(
        {
            "from": deployer,
            "chainId": CHAIN_ID,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": gas_limit,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
            "type": 2,
        }
    )

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    tx_hex = tx_hash.hex()
    if not tx_hex.startswith("0x"):
        tx_hex = "0x" + tx_hex
    print("tx hash:", tx_hex)
    print("waiting for the receipt ...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

    if receipt["status"] != 1:
        sys.exit("deploy reverted, tx %s" % tx_hash.hex())

    address = receipt["contractAddress"]
    gas_used = receipt["gasUsed"]
    effective_gas_price = receipt.get("effectiveGasPrice")
    l1_fee = receipt.get("l1Fee")
    if l1_fee is None:
        raw = w3.provider.make_request("eth_getTransactionReceipt", [tx_hex])
        raw_receipt = raw.get("result") or {}
        if raw_receipt.get("l1Fee") is not None:
            l1_fee = int(raw_receipt["l1Fee"], 16)

    print("contract address:", address)
    print("block number:", receipt["blockNumber"])
    print("gasUsed:", gas_used)
    print("effectiveGasPrice (wei):", effective_gas_price)
    print("l1Fee (wei):", l1_fee if l1_fee is not None else "not reported")
    l1_fee = int(l1_fee, 16) if isinstance(l1_fee, str) else (l1_fee or 0)
    if effective_gas_price is not None:
        l2_cost = gas_used * effective_gas_price
        total = l2_cost + l1_fee
        print("L2 cost:", w3.from_wei(l2_cost, "ether"), "ETH")
        print("total cost:", w3.from_wei(total, "ether"), "ETH")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(
            {
                "address": address,
                "txHash": tx_hex,
                "blockNumber": receipt["blockNumber"],
                "chainId": CHAIN_ID,
                "deployer": deployer,
                "abi": abi,
            },
            indent=2,
        )
        + "\n"
    )
    print("wrote", OUT_FILE)


if __name__ == "__main__":
    main()
