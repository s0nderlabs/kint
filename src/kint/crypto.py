"""The frozen cryptography of kint. Change nothing here without a format bump.

One key on every machine, zero key transport:

    owner signs ONE frozen EIP-712 message  ->  65-byte signature (a SECRET)
    ikm = r || s (low-S normalised)          ->  HKDF-SHA256  ->  KEK (32 bytes)
    random DEK per space, wrapped under a LIST of KEKs (signature, passphrase, ...)
    every epoch: gzip -> pad to a size bucket -> AES-256-GCM under the DEK

The derive signature is a secret, never a credential: never accept it as
authentication, never send it anywhere. A phished derive signature is
permanent, retroactive over all public calldata, unrevocable and covers every
space of that wallet.

Committed test vectors live in tests/test_crypto.py and carry their inputs.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import os
import struct
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from eth_abi import encode as abi_encode
from eth_account.messages import encode_typed_data
from eth_keys import keys
from eth_utils import keccak, to_checksum_address

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------

CHAIN_ID = 8453
# The one string every wallet renders. It has to warn, because this signature IS the key.
PURPOSE = ("kint-memory-v1: signing this reveals your memory encryption key. "
           "Only sign it in a kint terminal or page you opened yourself.")
DOMAIN = {"name": "kint", "version": "1", "chainId": CHAIN_ID}
TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
    ],
    "KintVault": [
        {"name": "owner", "type": "address"},
        {"name": "purpose", "type": "string"},
    ],
}
PRIMARY_TYPE = "KintVault"

SPACE_PREFIX = b"kint-space-v1"
KEK_INFO_PREFIX = b"kint-kek-v1"
KEK_CHECK = b"kint-kek-check-v1"
DEK_ID_INFO = b"kint-dek-id-v1"
WRAP_AAD_PREFIX = b"kint-wrap-v1"
LEAF_PREFIX = b"kint-leaf-v1"

SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 512 * 1024 * 1024

SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
SECP256K1_HALF_N = SECP256K1_N // 2

# Wrap kinds (the enum is frozen; add at the end only).
KEK_KIND_SIGNATURE = 0x01
KEK_KIND_PASSPHRASE = 0x02
KEK_KIND_PRF = 0x03            # reserved: WebAuthn PRF
KEK_KIND_SMART_ACCOUNT = 0x04  # reserved: EOA-owned smart account inner signature

# Header flags
FLAG_SIGNATURE_WRAP_PASSPHRASE_SALTED = 0x01
FLAG_SNAPSHOT = 0x02  # this epoch carries the FULL row set; a cold start may stop here

ENVELOPE_VERSION = 1

# Padded-payload size buckets (bytes). Monotone per space: once a space has
# published bucket b, later epochs publish at least b (see next_bucket).
BUCKETS = (4096, 8192, 16384, 32768, 65536, 98304)

WRAP_LEN = 1 + 16 + 12 + 48          # kind | kek_tag | wrap_nonce | wrapped_dek
HEADER_FIXED_LEN = 1 + 1 + 12 + 32 + 8 + 4 + 1  # version|flags|nonce|rows_root|dek_id|bucket|n_wraps
GCM_TAG_LEN = 16


class KintCryptoError(Exception):
    pass


# ---------------------------------------------------------------------------
# Typed data and digest
# ---------------------------------------------------------------------------

def typed_data(owner: str) -> dict:
    """The frozen EIP-712 payload for `owner` (checksummed)."""
    return {
        "types": TYPES,
        "primaryType": PRIMARY_TYPE,
        "domain": DOMAIN,
        "message": {"owner": to_checksum_address(owner), "purpose": PURPOSE},
    }


def canonical_payload_json(owner: str) -> str:
    """What `cast wallet sign --data --from-file` reads. Byte-stable."""
    return json.dumps(typed_data(owner), separators=(",", ":"), sort_keys=False) + "\n"


def vault_digest(owner: str) -> bytes:
    """keccak256(0x19 0x01 || domainSeparator || hashStruct(KintVault))."""
    signable = encode_typed_data(full_message=typed_data(owner))
    return keccak(b"\x19" + signable.version + signable.header + signable.body)


# ---------------------------------------------------------------------------
# Signature handling
# ---------------------------------------------------------------------------

def parse_signature(sig: bytes) -> tuple[int, int, int]:
    """Return (r, s, v01) from a 65-byte signature. v is normalised to 0/1."""
    if len(sig) != 65:
        raise KintCryptoError(f"signature must be 65 bytes, got {len(sig)}")
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:64], "big")
    v = sig[64]
    if v in (27, 28):
        v -= 27
    if v not in (0, 1):
        raise KintCryptoError(f"signature v must be 27/28 or 0/1, got {sig[64]}")
    if not (0 < r < SECP256K1_N and 0 < s < SECP256K1_N):
        raise KintCryptoError("signature r or s out of range")
    return r, s, v


def recover_address(digest: bytes, sig: bytes) -> str:
    """Checksummed address that produced `sig` over `digest`. Raises on garbage."""
    r, s, v = parse_signature(sig)
    pub = keys.Signature(vrs=(v, r, s)).recover_public_key_from_msg_hash(digest)
    return pub.to_checksum_address()


def normalise_low_s(sig: bytes) -> tuple[bytes, int, int]:
    """Return (sig_low_s, r, s_low). A malleated twin derives the same KEK."""
    r, s, v = parse_signature(sig)
    if s > SECP256K1_HALF_N:
        s = SECP256K1_N - s
        v ^= 1
    out = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v + 27])
    return out, r, s


def hex_signature(sig_text: str) -> bytes:
    t = sig_text.strip()
    if t.startswith("0x") or t.startswith("0X"):
        t = t[2:]
    try:
        raw = bytes.fromhex(t)
    except ValueError as e:
        raise KintCryptoError("signature is not hex") from e
    return raw


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def space_id(tenant_id: str) -> bytes:
    """32-byte space id: keccak256("kint-space-v1" || tenant_id)."""
    return keccak(SPACE_PREFIX + tenant_id.encode("utf-8"))


def kek_info(owner: str, space: bytes) -> bytes:
    owner20 = bytes.fromhex(to_checksum_address(owner)[2:])
    info = KEK_INFO_PREFIX + owner20 + space
    assert len(info) == 63, len(info)
    return info


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


def passphrase_stretch(passphrase: str, owner: str) -> bytes:
    """scrypt(passphrase, salt = owner20, n = 2**17, r = 8, p = 1) -> 32 bytes."""
    if not passphrase:
        raise KintCryptoError("empty passphrase")
    owner20 = bytes.fromhex(to_checksum_address(owner)[2:])
    return hashlib.scrypt(
        passphrase.encode("utf-8"), salt=owner20,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=32,
    )


def kek_tag(kek: bytes) -> bytes:
    return hmac.new(kek, KEK_CHECK, hashlib.sha256).digest()[:16]


def derive_kek_from_signature(
    sig: bytes, owner: str, space: bytes, *, passphrase: str | None = None,
    digest: bytes | None = None, signer: str | None = None,
) -> tuple[bytes, bytes]:
    """KEK from the owner's derive signature. Returns (kek, kek_tag).

    Hard checks, never behind try/except: the signature must recover to the
    expected signer over the expected digest (the only thing between us and a
    silently different key), r and s in range, then low-S normalise.
    `signer` defaults to `owner` (plain EOA). For an EOA-owned smart account,
    `owner` is the account and `signer` is the EOA whose 65 bytes are the ikm
    (kind 0x04, reserved, not shipped this week).
    """
    digest = digest if digest is not None else vault_digest(owner)
    expected = to_checksum_address(signer or owner)
    if len(sig) != 65:
        raise KintCryptoError(f"derive signature must be 65 bytes, got {len(sig)}")
    recovered = recover_address(digest, sig)
    if recovered != expected:
        raise KintCryptoError(
            f"derive signature recovers to {recovered}, expected {expected}; "
            "refusing to derive a key from it"
        )
    _, r, s = normalise_low_s(sig)
    ikm = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    salt = passphrase_stretch(passphrase, owner) if passphrase else b""
    kek = _hkdf(ikm, salt, kek_info(owner, space))
    return kek, kek_tag(kek)


def derive_kek_from_passphrase(passphrase: str, owner: str, space: bytes) -> tuple[bytes, bytes]:
    """Kind 0x02: KEK = HKDF(scrypt(passphrase, owner20), salt = "", info). No wallet needed."""
    ikm = passphrase_stretch(passphrase, owner)
    kek = _hkdf(ikm, b"", kek_info(owner, space))
    return kek, kek_tag(kek)


# ---------------------------------------------------------------------------
# DEK, wraps, recovery code
# ---------------------------------------------------------------------------

def new_dek() -> bytes:
    return os.urandom(32)


def dek_id(dek: bytes) -> bytes:
    return hmac.new(dek, DEK_ID_INFO, hashlib.sha256).digest()[:8]


@dataclass(frozen=True)
class Wrap:
    kind: int
    tag: bytes        # 16
    nonce: bytes      # 12
    wrapped: bytes    # 48

    def to_bytes(self) -> bytes:
        assert len(self.tag) == 16 and len(self.nonce) == 12 and len(self.wrapped) == 48
        return bytes([self.kind]) + self.tag + self.nonce + self.wrapped

    @classmethod
    def from_bytes(cls, b: bytes) -> "Wrap":
        if len(b) != WRAP_LEN:
            raise KintCryptoError("bad wrap length")
        return cls(kind=b[0], tag=b[1:17], nonce=b[17:29], wrapped=b[29:77])


def wrap_dek(dek: bytes, kek: bytes, kind: int) -> Wrap:
    tag = kek_tag(kek)
    nonce = os.urandom(12)
    ct = AESGCM(kek).encrypt(nonce, dek, WRAP_AAD_PREFIX + bytes([kind]) + tag)
    return Wrap(kind=kind, tag=tag, nonce=nonce, wrapped=ct)


def unwrap_dek(wrap: Wrap, kek: bytes) -> bytes:
    """Tag-match first (GCM is not key-committing): never trial-decrypt."""
    if kek_tag(kek) != wrap.tag:
        raise KintCryptoError("kek_tag mismatch: this key does not open this wrap")
    return AESGCM(kek).decrypt(wrap.nonce, wrap.wrapped, WRAP_AAD_PREFIX + bytes([wrap.kind]) + wrap.tag)


def find_wrap(wraps: list[Wrap], kek: bytes) -> Wrap | None:
    tag = kek_tag(kek)
    for w in wraps:
        if w.tag == tag:
            return w
    return None


def recovery_code(dek: bytes) -> str:
    """base32 of DEK || sha256(DEK)[:2], grouped by four. Human-typeable."""
    check = hashlib.sha256(dek).digest()[:2]
    raw = base64.b32encode(dek + check).decode("ascii").rstrip("=")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def decode_recovery_code(code: str) -> bytes:
    raw = code.strip().replace("-", "").replace(" ", "").upper()
    pad = "=" * (-len(raw) % 8)
    try:
        data = base64.b32decode(raw + pad)
    except Exception as e:
        raise KintCryptoError("recovery code is not valid base32") from e
    if len(data) != 34:
        raise KintCryptoError("recovery code has the wrong length")
    dek, check = data[:32], data[32:]
    if hashlib.sha256(dek).digest()[:2] != check:
        raise KintCryptoError("recovery code checksum failed (typo?)")
    return dek


# ---------------------------------------------------------------------------
# Padding and buckets
# ---------------------------------------------------------------------------

def bucket_for(length: int) -> int:
    for b in BUCKETS:
        if length <= b:
            return b
    raise KintCryptoError(f"payload of {length} bytes exceeds the largest bucket {BUCKETS[-1]}; split the epoch")


def next_bucket(length: int, previous_bucket: int) -> int:
    """Monotone ratchet per space: never publish a smaller bucket than before."""
    return max(bucket_for(length), previous_bucket)


def pad_to_bucket(compressed: bytes, bucket: int) -> bytes:
    body = struct.pack(">I", len(compressed)) + compressed
    if len(body) > bucket:
        raise KintCryptoError("compressed payload larger than bucket")
    return body + b"\x00" * (bucket - len(body))


def unpad(padded: bytes) -> bytes:
    (n,) = struct.unpack(">I", padded[:4])
    if 4 + n > len(padded):
        raise KintCryptoError("padded payload declares a length beyond its size")
    return padded[4:4 + n]


def compress(plaintext: bytes) -> bytes:
    return gzip.compress(plaintext, compresslevel=9, mtime=0)


def decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def epoch_aad(owner: str, space: bytes, seq: int, prev: bytes, bucket: int, rows_root: bytes, dek_id_: bytes) -> bytes:
    """keccak256(abi.encode(chainId, owner, space, seq, prev, lenBucket, rows_root, dek_id))."""
    return keccak(abi_encode(
        ["uint256", "address", "bytes32", "uint64", "bytes32", "uint32", "bytes32", "bytes8"],
        [CHAIN_ID, to_checksum_address(owner), space, seq, prev, bucket, rows_root, dek_id_],
    ))


@dataclass
class Header:
    version: int
    flags: int
    nonce: bytes
    rows_root: bytes
    dek_id: bytes
    bucket: int
    wraps: list[Wrap] = field(default_factory=list)

    def to_bytes(self) -> bytes:
        out = bytes([self.version, self.flags]) + self.nonce + self.rows_root + self.dek_id
        out += struct.pack(">I", self.bucket) + bytes([len(self.wraps)])
        for w in self.wraps:
            out += w.to_bytes()
        return out

    @classmethod
    def parse(cls, blob: bytes) -> tuple["Header", int]:
        if len(blob) < HEADER_FIXED_LEN:
            raise KintCryptoError("blob shorter than a header")
        version, flags = blob[0], blob[1]
        if version != ENVELOPE_VERSION:
            raise KintCryptoError(f"unsupported envelope version {version}")
        nonce = blob[2:14]
        rows_root = blob[14:46]
        dek_id_ = blob[46:54]
        (bucket,) = struct.unpack(">I", blob[54:58])
        n = blob[58]
        off = HEADER_FIXED_LEN
        wraps = []
        for _ in range(n):
            wraps.append(Wrap.from_bytes(blob[off:off + WRAP_LEN]))
            off += WRAP_LEN
        return cls(version, flags, nonce, rows_root, dek_id_, bucket, wraps), off


def seal_epoch(
    plaintext: bytes, *, dek: bytes, wraps: list[Wrap], owner: str, space: bytes,
    seq: int, prev: bytes, rows_root: bytes, previous_bucket: int = 0, flags: int = 0,
) -> bytes:
    """gzip -> pad to bucket -> AES-256-GCM(DEK) with the epoch AAD. Returns header || ciphertext."""
    compressed = compress(plaintext)
    bucket = next_bucket(len(compressed) + 4, previous_bucket)
    padded = pad_to_bucket(compressed, bucket)
    nonce = os.urandom(12)
    did = dek_id(dek)
    header = Header(ENVELOPE_VERSION, flags, nonce, rows_root, did, bucket, list(wraps))
    aad = epoch_aad(owner, space, seq, prev, bucket, rows_root, did)
    ct = AESGCM(dek).encrypt(nonce, padded, aad)
    assert len(ct) == bucket + GCM_TAG_LEN
    return header.to_bytes() + ct


def open_epoch(blob: bytes, *, dek: bytes, owner: str, space: bytes, seq: int, prev: bytes) -> tuple[Header, bytes]:
    """Inverse of seal_epoch. Every epoch decrypts with the DEK from its OWN header
    (the caller unwraps it with find_wrap / unwrap_dek first)."""
    header, off = Header.parse(blob)
    ct = blob[off:]
    if len(ct) != header.bucket + GCM_TAG_LEN:
        raise KintCryptoError(
            f"ciphertext length {len(ct)} does not match bucket {header.bucket} + tag"
        )
    if dek_id(dek) != header.dek_id:
        raise KintCryptoError("dek_id mismatch: wrong data key for this epoch")
    aad = epoch_aad(owner, space, seq, prev, header.bucket, header.rows_root, header.dek_id)
    padded = AESGCM(dek).decrypt(header.nonce, ct, aad)
    return header, decompress(unpad(padded))


def peek_header(blob: bytes) -> Header:
    return Header.parse(blob)[0]
