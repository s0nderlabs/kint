"""Committed vectors (every vector carries its inputs) and round trips for kint.crypto."""

import os

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from kint import crypto

# Throwaway key, never used for anything real.
VEC_KEY = b"\x11" * 32
VEC_OWNER = "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
VEC_DIGEST = "39fec015d21465d81dd5611129982b7a310e070a126f41dfdd8c87cc04a31517"
VEC_SPACE_DEMO = "fd83319f25a64bb2952805bd9bf32719080d37c6a83b6a51db74e409eb42bff6"
VEC_KEK = "c69d894607fac5813904d32c44c4603835b746a529ada52fae1834ac28cc418f"
VEC_TAG = "9710b041b39054fa3ad68ee22c8f2e79"


def _sign(owner_key: bytes, owner: str) -> bytes:
    acct = Account.from_key(owner_key)
    signable = encode_typed_data(full_message=crypto.typed_data(owner))
    return bytes(acct.sign_message(signable).signature)


def test_vector_owner_digest_space_kek_tag():
    acct = Account.from_key(VEC_KEY)
    assert acct.address == VEC_OWNER
    assert crypto.vault_digest(VEC_OWNER).hex() == VEC_DIGEST
    assert crypto.space_id("demo").hex() == VEC_SPACE_DEMO
    sig = _sign(VEC_KEY, VEC_OWNER)
    assert len(sig) == 65
    # deterministic across calls (RFC 6979)
    assert sig == _sign(VEC_KEY, VEC_OWNER)
    kek, tag = crypto.derive_kek_from_signature(sig, VEC_OWNER, crypto.space_id("demo"))
    assert kek.hex() == VEC_KEK
    assert tag.hex() == VEC_TAG


def test_canonical_payload_is_byte_stable():
    a = crypto.canonical_payload_json(VEC_OWNER)
    b = crypto.canonical_payload_json(VEC_OWNER.lower())
    assert a == b
    assert '"primaryType":"KintVault"' in a
    assert '"chainId":8453' in a
    assert "verifyingContract" not in a


def test_malleated_twin_derives_same_kek():
    sig = _sign(VEC_KEY, VEC_OWNER)
    r, s, v = crypto.parse_signature(sig)
    twin_s = crypto.SECP256K1_N - s
    twin = r.to_bytes(32, "big") + twin_s.to_bytes(32, "big") + bytes([(v ^ 1) + 27])
    space = crypto.space_id("demo")
    assert crypto.recover_address(crypto.vault_digest(VEC_OWNER), twin) == VEC_OWNER
    k1, _ = crypto.derive_kek_from_signature(sig, VEC_OWNER, space)
    k2, _ = crypto.derive_kek_from_signature(twin, VEC_OWNER, space)
    assert k1 == k2


def test_wrong_signer_is_refused_not_derived():
    other = Account.from_key(b"\x22" * 32)
    sig = _sign(b"\x22" * 32, VEC_OWNER)  # other key signs the owner's payload
    assert crypto.recover_address(crypto.vault_digest(VEC_OWNER), sig) == other.address
    with pytest.raises(crypto.KintCryptoError):
        crypto.derive_kek_from_signature(sig, VEC_OWNER, crypto.space_id("demo"))
    with pytest.raises(crypto.KintCryptoError):
        crypto.derive_kek_from_signature(sig[:64], VEC_OWNER, crypto.space_id("demo"))


def test_kek_differs_per_space_and_owner():
    sig = _sign(VEC_KEY, VEC_OWNER)
    k_demo, _ = crypto.derive_kek_from_signature(sig, VEC_OWNER, crypto.space_id("demo"))
    k_other, _ = crypto.derive_kek_from_signature(sig, VEC_OWNER, crypto.space_id("other"))
    assert k_demo != k_other


@pytest.mark.slow
def test_passphrase_kek_and_salted_signature_kek():
    sig = _sign(VEC_KEY, VEC_OWNER)
    space = crypto.space_id("demo")
    k_plain, t_plain = crypto.derive_kek_from_signature(sig, VEC_OWNER, space)
    k_salted, t_salted = crypto.derive_kek_from_signature(sig, VEC_OWNER, space, passphrase="correct horse")
    k_pass, t_pass = crypto.derive_kek_from_passphrase("correct horse", VEC_OWNER, space)
    assert len({k_plain, k_salted, k_pass}) == 3
    assert len({t_plain, t_salted, t_pass}) == 3
    # stable
    assert crypto.derive_kek_from_passphrase("correct horse", VEC_OWNER, space)[0] == k_pass
    assert crypto.derive_kek_from_passphrase("correct horsf", VEC_OWNER, space)[0] != k_pass


def test_wrap_unwrap_and_tag_ladder():
    dek = crypto.new_dek()
    kek_a = os.urandom(32)
    kek_b = os.urandom(32)
    wa = crypto.wrap_dek(dek, kek_a, crypto.KEK_KIND_SIGNATURE)
    wb = crypto.wrap_dek(dek, kek_b, crypto.KEK_KIND_PASSPHRASE)
    assert len(wa.to_bytes()) == crypto.WRAP_LEN
    assert crypto.Wrap.from_bytes(wa.to_bytes()) == wa
    wraps = [wa, wb]
    assert crypto.find_wrap(wraps, kek_b) is wb
    assert crypto.unwrap_dek(wb, kek_b) == dek
    assert crypto.unwrap_dek(wa, kek_a) == dek
    with pytest.raises(crypto.KintCryptoError):
        crypto.unwrap_dek(wa, kek_b)  # tag mismatch, never trial-decrypted
    assert crypto.find_wrap(wraps, os.urandom(32)) is None


def test_recovery_code_round_trip_and_checksum():
    dek = crypto.new_dek()
    code = crypto.recovery_code(dek)
    assert crypto.decode_recovery_code(code) == dek
    assert crypto.decode_recovery_code(code.lower().replace("-", " ")) == dek
    bad = list(code)
    bad[0] = "B" if bad[0] != "B" else "C"
    with pytest.raises(crypto.KintCryptoError):
        crypto.decode_recovery_code("".join(bad))


def test_buckets_and_padding():
    assert crypto.bucket_for(1) == 4096
    assert crypto.bucket_for(4096) == 4096
    assert crypto.bucket_for(4097) == 8192
    assert crypto.next_bucket(100, 32768) == 32768
    with pytest.raises(crypto.KintCryptoError):
        crypto.bucket_for(98305)
    data = os.urandom(1000)
    padded = crypto.pad_to_bucket(data, 4096)
    assert len(padded) == 4096
    assert crypto.unpad(padded) == data


def test_envelope_round_trip_and_aad_binding():
    dek = crypto.new_dek()
    kek = os.urandom(32)
    wraps = [crypto.wrap_dek(dek, kek, crypto.KEK_KIND_SIGNATURE)]
    space = crypto.space_id("demo")
    rows_root = os.urandom(32)
    prev = bytes(32)
    plaintext = b'{"rows":[' + b'{"k":"v"},' * 300 + b'{"k":"v"}]}'
    blob = crypto.seal_epoch(plaintext, dek=dek, wraps=wraps, owner=VEC_OWNER, space=space,
                             seq=1, prev=prev, rows_root=rows_root)
    header = crypto.peek_header(blob)
    assert header.bucket == 4096
    assert header.rows_root == rows_root
    assert header.dek_id == crypto.dek_id(dek)
    assert len(blob) == crypto.HEADER_FIXED_LEN + crypto.WRAP_LEN + 4096 + crypto.GCM_TAG_LEN
    # unwrap through the header, then open
    w = crypto.find_wrap(header.wraps, kek)
    assert w is not None
    dek2 = crypto.unwrap_dek(w, kek)
    h2, pt = crypto.open_epoch(blob, dek=dek2, owner=VEC_OWNER, space=space, seq=1, prev=prev)
    assert pt == plaintext
    # any change in the AAD inputs refuses
    for kwargs in ({"seq": 2}, {"prev": os.urandom(32)}, {"space": crypto.space_id("x")},
                   {"owner": "0x0000000000000000000000000000000000000001"}):
        args = dict(dek=dek2, owner=VEC_OWNER, space=space, seq=1, prev=prev)
        args.update(kwargs)
        with pytest.raises(Exception):
            crypto.open_epoch(blob, **args)
    # a flipped ciphertext byte refuses
    tampered = bytearray(blob)
    tampered[-1] ^= 0x01
    with pytest.raises(Exception):
        crypto.open_epoch(bytes(tampered), dek=dek2, owner=VEC_OWNER, space=space, seq=1, prev=prev)
    # a tampered header field refuses (rows_root is in the AAD)
    tampered = bytearray(blob)
    tampered[14] ^= 0x01
    with pytest.raises(Exception):
        crypto.open_epoch(bytes(tampered), dek=dek2, owner=VEC_OWNER, space=space, seq=1, prev=prev)
    # wrong DEK refuses by dek_id before any decrypt
    with pytest.raises(crypto.KintCryptoError):
        crypto.open_epoch(blob, dek=crypto.new_dek(), owner=VEC_OWNER, space=space, seq=1, prev=prev)


def test_bucket_ratchet_is_monotone():
    dek = crypto.new_dek()
    wraps = [crypto.wrap_dek(dek, os.urandom(32), crypto.KEK_KIND_SIGNATURE)]
    space = crypto.space_id("demo")
    blob = crypto.seal_epoch(b"tiny", dek=dek, wraps=wraps, owner=VEC_OWNER, space=space,
                             seq=1, prev=bytes(32), rows_root=bytes(32), previous_bucket=16384)
    assert crypto.peek_header(blob).bucket == 16384
