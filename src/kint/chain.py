"""EpochAnchor on Base: reads, epoch walking, and the session-key transactions.

Rules that live here:
- Nothing in this module is ever called from inside a Sibyl write transaction.
- The session key signs push / setSessionKeyBySig transactions and nothing else.
- Readers walk epochs backwards from the head through the prevBlock field of
  each Epoch event (one exact-block eth_getLogs per epoch), so no RPC range
  cap is ever hit. Range scans are chunked and only used for discovery.
- Sends go to the keyed endpoint (KINT_RPC_URL, else the Alchemy key in the
  macOS Keychain `dev.api.alchemy`); reads use it too, with the public
  https://mainnet.base.org as the independent second opinion on a cold start.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address
from web3 import Web3
from web3.exceptions import ContractLogicError

CHAIN_ID = 8453
PUBLIC_RPC = "https://mainnet.base.org"
PUBLIC_RPC_2 = "https://base-rpc.publicnode.com"   # a different operator, for the cold-start second opinion
# EpochAnchor on Base mainnet, deployed Sep 9 2026 at block 51,081,696
# (tx 0xf2e03cd1c4e7ca005ee602a6c61ed50861d2238acee217b2c19f8670ba2cc9f6).
DEFAULT_CONTRACT = "0xa22E03f7a4145Bf4909a83595C90a38E14d79600"

ABI_PATH = Path(__file__).with_name("EpochAnchor.abi.json")


def load_abi() -> list[dict[str, Any]]:
    return json.loads(ABI_PATH.read_text())


class ChainError(Exception):
    pass


class StaleHead(ChainError):
    pass


# ---------------------------------------------------------------------------
# RPC selection
# ---------------------------------------------------------------------------

def _keychain_alchemy_key() -> str | None:
    if platform.system() != "Darwin" or os.environ.get("KINT_NO_KEYCHAIN") == "1":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "dev.api.alchemy", "-a", "api-key", "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def primary_rpc_url() -> str:
    url = os.environ.get("KINT_RPC_URL")
    if url:
        return url
    key = _keychain_alchemy_key()
    if key:
        return f"https://base-mainnet.g.alchemy.com/v2/{key}"
    return PUBLIC_RPC


def secondary_rpc_url() -> str:
    """A second, independently operated endpoint. When the primary already fell back to the
    public Base RPC, the second opinion comes from another public operator."""
    url = os.environ.get("KINT_RPC_URL_2")
    if url:
        return url
    return PUBLIC_RPC_2 if primary_rpc_url() == PUBLIC_RPC else PUBLIC_RPC


def redact(url: str) -> str:
    """Never print a keyed URL: keep scheme and host, drop any path, query or userinfo."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url)
    except Exception:
        return "<rpc>"
    host = u.hostname or "<rpc>"
    port = f":{u.port}" if u.port else ""
    tail = "/<redacted>" if (u.path.strip("/") or u.query) else ""
    return f"{u.scheme}://{host}{port}{tail}"


def contract_address() -> str:
    addr = os.environ.get("KINT_CONTRACT") or DEFAULT_CONTRACT
    if not addr:
        raise ChainError("no EpochAnchor address: set KINT_CONTRACT")
    return to_checksum_address(addr)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

@dataclass
class Head:
    digest: bytes
    seq: int
    block_number: int


@dataclass
class EpochEvent:
    owner: str
    space: bytes
    writer: str
    seq: int
    prev: bytes
    digest: bytes
    prev_block: int
    block_number: int
    tx_hash: str


class Anchor:
    def __init__(self, rpc_url: str | None = None, address: str | None = None, timeout: int = 60):
        self.rpc_url = rpc_url or primary_rpc_url()
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": timeout}))
        self.address = to_checksum_address(address or contract_address())
        self.contract = self.w3.eth.contract(address=self.address, abi=load_abi())
        self._epoch_topic = "0x" + keccak(
            text="Epoch(address,bytes32,address,uint64,bytes32,bytes32,uint64)").hex()

    # reads --------------------------------------------------------------
    def chain_id(self) -> int:
        return self.w3.eth.chain_id

    def block_number(self) -> int:
        return self.w3.eth.block_number

    def head(self, owner: str, space: bytes) -> Head:
        digest, seq, bn = self.contract.functions.head(to_checksum_address(owner), space).call()
        return Head(bytes(digest), int(seq), int(bn))

    def can_write(self, owner: str, writer: str) -> bool:
        return bool(self.contract.functions.canWrite(to_checksum_address(owner), to_checksum_address(writer)).call())

    def session_key_expiry(self, owner: str, key: str, block_identifier: Any = "latest") -> int:
        return int(self.contract.functions.sessionKeyExpiry(
            to_checksum_address(owner), to_checksum_address(key)).call(block_identifier=block_identifier))

    def auth_nonce(self, owner: str) -> int:
        return int(self.contract.functions.authNonce(to_checksum_address(owner)).call())

    def domain_separator(self) -> bytes:
        return bytes(self.contract.functions.DOMAIN_SEPARATOR().call())

    def has_code(self, addr: str) -> bool:
        return len(self.w3.eth.get_code(to_checksum_address(addr))) > 0

    def balance(self, addr: str) -> int:
        return self.w3.eth.get_balance(to_checksum_address(addr))

    def _parse_epoch_log(self, log) -> EpochEvent:
        ev = self.contract.events.Epoch().process_log(log)
        a = ev["args"]
        return EpochEvent(
            owner=to_checksum_address(a["owner"]), space=bytes(a["space"]), writer=to_checksum_address(a["writer"]),
            seq=int(a["seq"]), prev=bytes(a["prev"]), digest=bytes(a["digest"]), prev_block=int(a["prevBlock"]),
            block_number=int(ev["blockNumber"]), tx_hash=ev["transactionHash"].hex(),
        )

    def epoch_at_block(self, owner: str, space: bytes, block_number: int) -> list[EpochEvent]:
        """Exact-block query: every Epoch event for (owner, space) in that block."""
        owner_topic = "0x" + bytes(12) .hex() + to_checksum_address(owner)[2:].lower()
        logs = self.w3.eth.get_logs({
            "fromBlock": block_number, "toBlock": block_number, "address": self.address,
            "topics": [self._epoch_topic, owner_topic, "0x" + space.hex()],
        })
        return [self._parse_epoch_log(l) for l in logs]

    def walk_epochs(self, owner: str, space: bytes, *, stop_seq: int = 0, head: Head | None = None,
                    max_epochs: int = 100000, stop_when=None) -> list[EpochEvent]:
        """Head to genesis (or to stop_seq exclusive), newest first, via prevBlock.

        `stop_when(ev) -> bool` is evaluated AFTER the event is appended: True ends the
        walk with that event included (a cold start stops at the newest snapshot epoch).
        """
        head = head or self.head(owner, space)
        out: list[EpochEvent] = []
        if head.seq == 0:
            return out
        block = head.block_number
        want_seq = head.seq
        while block > 0 and want_seq > stop_seq and len(out) < max_epochs:
            evs = [e for e in self.epoch_at_block(owner, space, block) if e.seq == want_seq]
            if not evs:
                raise ChainError(f"no Epoch event for seq {want_seq} at block {block}; the RPC may be pruned or lying")
            e = evs[0]
            out.append(e)
            if stop_when is not None and stop_when(e):
                break
            block = e.prev_block
            want_seq -= 1
        return out

    def scan_epochs(self, owner: str, space: bytes, from_block: int, to_block: int, chunk: int = 2000) -> list[EpochEvent]:
        """Chunked range scan (discovery only). Halves the chunk on RPC range errors."""
        out: list[EpochEvent] = []
        owner_topic = "0x" + bytes(12).hex() + to_checksum_address(owner)[2:].lower()
        start = from_block
        while start <= to_block:
            end = min(start + chunk - 1, to_block)
            try:
                logs = self.w3.eth.get_logs({
                    "fromBlock": start, "toBlock": end, "address": self.address,
                    "topics": [self._epoch_topic, owner_topic, "0x" + space.hex()],
                })
            except Exception as e:  # noqa: BLE001
                if chunk > 50:
                    chunk //= 2
                    continue
                raise ChainError(f"eth_getLogs failed even at chunk {chunk}: {e}") from e
            out.extend(self._parse_epoch_log(l) for l in logs)
            start = end + 1
        return out

    def epoch_ciphertext(self, tx_hash: str) -> tuple[str, bytes, bytes, bytes]:
        """(owner, space, prev, ct) decoded from the push transaction's calldata."""
        tx = self.w3.eth.get_transaction(tx_hash)
        if tx["to"] is None or to_checksum_address(tx["to"]) != self.address:
            raise ChainError(f"tx {tx_hash} is not addressed to EpochAnchor")
        fn, args = self.contract.decode_function_input(tx["input"])
        if fn.fn_name != "push":
            raise ChainError(f"tx {tx_hash} does not call push")
        return to_checksum_address(args["owner"]), bytes(args["space"]), bytes(args["prev"]), bytes(args["ct"])

    def receipt_cost(self, tx_hash: str) -> dict[str, Any]:
        r = self.w3.eth.get_transaction_receipt(tx_hash)
        gas_used = int(r["gasUsed"])
        price = int(r.get("effectiveGasPrice", 0))
        raw_l1 = r.get("l1Fee", 0) or 0
        l1 = int(raw_l1, 16) if isinstance(raw_l1, str) else int(raw_l1)
        return {"gasUsed": gas_used, "effectiveGasPrice": price, "l1Fee": l1,
                "totalWei": gas_used * price + l1, "blockNumber": int(r["blockNumber"]),
                "status": int(r["status"])}

    # writes -------------------------------------------------------------
    def _send(self, account, fn, *, gas_margin: float = 1.2, value: int = 0) -> str:
        nonce = self.w3.eth.get_transaction_count(account.address, "pending")
        base = self.w3.eth.get_block("latest")["baseFeePerGas"]
        try:
            prio = self.w3.eth.max_priority_fee
        except Exception:  # noqa: BLE001
            prio = 1000
        prio = max(int(prio), 1000)
        tx = fn.build_transaction({
            "from": account.address, "nonce": nonce, "chainId": self.chain_id(), "value": value,
            "maxFeePerGas": int(base * 2 + prio), "maxPriorityFeePerGas": prio,
        })
        try:
            est = self.w3.eth.estimate_gas(tx)
        except ContractLogicError as e:
            raise ChainError(f"transaction would revert: {e}") from e
        tx["gas"] = int(est * gas_margin) + 10000
        signed = account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return h.hex() if h.hex().startswith("0x") else "0x" + h.hex()

    def wait(self, tx_hash: str, confirmations: int = 1, timeout: int = 180) -> dict[str, Any]:
        r = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        if int(r["status"]) != 1:
            raise ChainError(f"tx {tx_hash} reverted")
        target = int(r["blockNumber"]) + confirmations - 1
        deadline = time.time() + timeout
        while self.w3.eth.block_number < target:
            if time.time() > deadline:
                raise ChainError("timed out waiting for confirmations")
            time.sleep(1.5)
        return self.receipt_cost(tx_hash)

    def push(self, account, owner: str, space: bytes, prev: bytes, ct: bytes) -> str:
        return self._send(account, self.contract.functions.push(to_checksum_address(owner), space, prev, ct))

    def set_session_key(self, owner_account, key: str, expiry: int) -> str:
        return self._send(owner_account, self.contract.functions.setSessionKey(to_checksum_address(key), expiry))

    def set_session_key_by_sig(self, submitter_account, owner: str, key: str, expiry: int, deadline: int, signature: bytes) -> str:
        return self._send(submitter_account, self.contract.functions.setSessionKeyBySig(
            to_checksum_address(owner), to_checksum_address(key), expiry, deadline, signature))

    def transfer(self, account, to: str, wei: int) -> str:
        nonce = self.w3.eth.get_transaction_count(account.address, "pending")
        base = self.w3.eth.get_block("latest")["baseFeePerGas"]
        prio = max(int(getattr(self.w3.eth, "max_priority_fee", 1000) or 1000), 1000)
        tx = {"to": to_checksum_address(to), "value": wei, "nonce": nonce, "chainId": self.chain_id(),
              "gas": 21000, "maxFeePerGas": int(base * 2 + prio), "maxPriorityFeePerGas": prio}
        signed = account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return h.hex() if h.hex().startswith("0x") else "0x" + h.hex()


# ---------------------------------------------------------------------------
# Session-key authorization typed data. A DIFFERENT EIP-712 domain from the
# vault key on purpose: an authorization signature can never double as a
# derive signature (different domain, different digest), and the contract
# address in this domain pins it to one deployment. This is not a phishing
# defence for the vault signature; that one is defended by the PURPOSE string
# the wallet renders (crypto.PURPOSE) and by never being accepted as a login.
# ---------------------------------------------------------------------------

def authorization_typed_data(contract: str, owner: str, key: str, expiry: int, nonce: int, deadline: int,
                             chain_id: int = CHAIN_ID) -> dict:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"},
            ],
            "SessionKeyAuthorization": [
                {"name": "owner", "type": "address"}, {"name": "key", "type": "address"},
                {"name": "expiry", "type": "uint64"}, {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "SessionKeyAuthorization",
        "domain": {"name": "kint EpochAnchor", "version": "1", "chainId": chain_id,
                   "verifyingContract": to_checksum_address(contract)},
        "message": {"owner": to_checksum_address(owner), "key": to_checksum_address(key),
                    "expiry": expiry, "nonce": nonce, "deadline": deadline},
    }


def authorization_digest(contract: str, owner: str, key: str, expiry: int, nonce: int, deadline: int,
                         chain_id: int = CHAIN_ID) -> bytes:
    s = encode_typed_data(full_message=authorization_typed_data(contract, owner, key, expiry, nonce, deadline, chain_id))
    return keccak(b"\x19" + s.version + s.header + s.body)


def sign_authorization(owner_account, contract: str, key: str, expiry: int, nonce: int, deadline: int,
                       chain_id: int = CHAIN_ID) -> bytes:
    s = encode_typed_data(full_message=authorization_typed_data(
        contract, owner_account.address, key, expiry, nonce, deadline, chain_id))
    return bytes(owner_account.sign_message(s).signature)
