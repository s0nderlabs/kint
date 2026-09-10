"""Per-machine session key, the cached vault key, and the enrolment record.

Session key: a plain EOA generated on this machine, stored as a V3 scrypt
keystore at ~/.kint/session.key (0600). Its passphrase comes from the macOS
Keychain item `dev.kint-session-key` (created on first use) or, on a server,
from KINT_SESSION_PASSPHRASE. It signs Base transactions to EpochAnchor and
nothing else; it can never decrypt.

Vault cache: the unwrapped DEK for a space, encrypted at rest under a key
derived from the same passphrase, with a TTL (KINT_KEY_TTL: seconds, or
`24h` default, `30d` for unattended machines, `session` for memory only).
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from eth_account import Account

from . import paths

KEYCHAIN_SERVICE = "dev.kint-session-key"
KEYCHAIN_ACCOUNT = "passphrase"
_memory_only_dek: dict[str, tuple[bytes, float]] = {}


class KeyError_(Exception):
    pass


# ---------------------------------------------------------------------------
# Passphrase source (Keychain on macOS, env elsewhere)
# ---------------------------------------------------------------------------

def _keychain_read() -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _keychain_write(value: str) -> bool:
    # `security -i` reads its command from stdin, so the passphrase never
    # appears on a process argv where `ps` could show it. The value is
    # token_urlsafe output ([A-Za-z0-9_-]), so the quoting below is exact.
    line = (f'add-generic-password -s "{KEYCHAIN_SERVICE}" -a "{KEYCHAIN_ACCOUNT}" '
            f'-w "{value}" -U\n')
    try:
        out = subprocess.run(
            ["security", "-i"], input=line,
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def local_passphrase(create: bool = True) -> str:
    """The machine-local secret that protects the session keystore and the vault cache."""
    env = os.environ.get("KINT_SESSION_PASSPHRASE")
    if env:
        return env
    if platform.system() == "Darwin" and os.environ.get("KINT_NO_KEYCHAIN") != "1":
        v = _keychain_read()
        if v:
            return v
        if create:
            v = secrets.token_urlsafe(32)
            if _keychain_write(v):
                return v
    p = paths.kint_home() / "local.secret"
    if p.exists():
        return p.read_text().strip()
    if not create:
        raise KeyError_("no local passphrase: set KINT_SESSION_PASSPHRASE")
    v = secrets.token_urlsafe(32)
    paths.write_private(p, (v + "\n").encode())
    return v


# ---------------------------------------------------------------------------
# Session key
# ---------------------------------------------------------------------------

def session_key_exists() -> bool:
    return paths.session_key_path().exists()


def session_key_address() -> str | None:
    p = paths.session_key_path()
    if not p.exists():
        return None
    try:
        from eth_utils import to_checksum_address
        return to_checksum_address("0x" + json.loads(p.read_text())["address"].lower().removeprefix("0x"))
    except Exception:
        return None


def create_session_key() -> str:
    """Generate a fresh session key; refuse to overwrite an existing one."""
    p = paths.session_key_path()
    if p.exists():
        raise KeyError_(f"session key already exists at {p}; use `kint session-key rotate`")
    acct = Account.create()
    ks = Account.encrypt(acct.key, local_passphrase())
    paths.write_private(p, json.dumps(ks).encode())
    return acct.address


def rotate_session_key() -> str:
    p = paths.session_key_path()
    if p.exists():
        os.replace(p, p.with_suffix(".key.old"))
    return create_session_key()


def load_session_account():
    p = paths.session_key_path()
    if not p.exists():
        raise KeyError_("no session key on this machine; run `kint session-key create`")
    ks = json.loads(p.read_text())
    key = Account.decrypt(ks, local_passphrase(create=False))
    return Account.from_key(key)


# ---------------------------------------------------------------------------
# Vault cache (unwrapped DEK with TTL)
# ---------------------------------------------------------------------------

DEFAULT_TTL_SECONDS = 24 * 3600


def _ttl_seconds() -> float | None:
    raw = (os.environ.get("KINT_KEY_TTL") or "").strip().lower()
    if not raw:
        return float(DEFAULT_TTL_SECONDS)
    if raw == "session":
        return None
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if raw[-1] in mult:
            return float(raw[:-1]) * mult[raw[-1]]
        return float(raw)
    except ValueError:
        return float(DEFAULT_TTL_SECONDS)


def _cache_key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"", info=b"kint-vault-cache-v1").derive(
        local_passphrase().encode("utf-8"))


def cache_dek(space_hex: str, dek: bytes) -> None:
    ttl = _ttl_seconds()
    if ttl is None:
        _memory_only_dek[space_hex] = (dek, float("inf"))
        return
    expires = time.time() + ttl
    nonce = os.urandom(12)
    ct = AESGCM(_cache_key()).encrypt(nonce, dek, space_hex.encode())
    paths.write_private(paths.vault_cache_path(space_hex),
                        json.dumps({"expires": expires, "nonce": nonce.hex(), "ct": ct.hex()}).encode())


def cached_dek(space_hex: str) -> bytes | None:
    if space_hex in _memory_only_dek:
        return _memory_only_dek[space_hex][0]
    p = paths.vault_cache_path(space_hex)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        if time.time() > float(d["expires"]):
            return None
        return AESGCM(_cache_key()).decrypt(bytes.fromhex(d["nonce"]), bytes.fromhex(d["ct"]), space_hex.encode())
    except Exception:
        return None


def forget_dek(space_hex: str) -> None:
    _memory_only_dek.pop(space_hex, None)
    p = paths.vault_cache_path(space_hex)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Enrolment record (local pin state, never payload state)
# ---------------------------------------------------------------------------

ACCOUNT_KIND_EOA = 0
ACCOUNT_KIND_SMART_ACCOUNT = 1   # owner is a smart account address; key from passphrase


@dataclass
class Enrolment:
    owner: str
    tenant_id: str
    space: str                 # hex, no 0x
    account_kind: int
    signer: str                # == owner for EOA; the owner EOA for a smart account (unused this week)
    chain_id: int
    kek_tags: list[str]        # hex tags of the wraps this machine can open
    wrap_kinds: list[int]
    created_at: float
    contract: str | None = None
    created_here: bool = False   # this machine generated the DEK (so the recovery code was issued here)

    def save(self) -> None:
        paths.write_private(paths.enrolment_path(self.space), json.dumps(asdict(self), indent=1).encode())

    @classmethod
    def load(cls, space_hex: str) -> "Enrolment | None":
        p = paths.enrolment_path(space_hex)
        if not p.exists():
            return None
        try:
            return cls(**json.loads(p.read_text()))
        except Exception:
            return None
