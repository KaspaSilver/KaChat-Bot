import secrets

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH, SECP256K1, EllipticCurvePublicNumbers, generate_private_key)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kachat.crypto import (CryptoError, kachat_decrypt, kachat_encrypt, open_sealed, seal,
                           shared_x, xonly_from_private)

USER = "11" * 32
BOT = "33" * 32


def v1_watcher_encrypt(plaintext: str, receiver_x_hex: str) -> bytes:
    """Verbatim copy of the v1 watcher.py `kachat_encrypt` (the shipped layout)."""
    p = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
    x = int(receiver_x_hex, 16)
    y_sq = (pow(x, 3, p) + 7) % p
    y = pow(y_sq, (p + 1) // 4, p)
    if y % 2 != 0:
        y = p - y
    recv_pub = EllipticCurvePublicNumbers(x=x, y=y, curve=SECP256K1()).public_key()
    eph_priv = generate_private_key(SECP256K1())
    eph_pub_b = eph_priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    shared = eph_priv.exchange(ECDH(), recv_pub)
    x_coord = shared[1:33] if len(shared) == 33 else shared[:32]
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"", info=b"").derive(x_coord)
    nonce = secrets.token_bytes(12)
    return nonce + eph_pub_b + ChaCha20Poly1305(key).encrypt(nonce, plaintext.encode("utf-8"), None)


def test_round_trip_and_layout():
    x = xonly_from_private(USER)
    sealed = seal("hello ⛏ block", x)
    assert sealed[12] in (2, 3)
    assert len(sealed) == 12 + 33 + len("hello ⛏ block".encode()) + 16
    assert open_sealed(sealed, USER) == "hello ⛏ block"


def test_v1_layout_is_compatible_both_ways():
    x_hex = xonly_from_private(USER).hex()
    assert open_sealed(v1_watcher_encrypt("from v1", x_hex), USER) == "from v1"
    assert kachat_decrypt(kachat_encrypt("from v2", x_hex), USER) == "from v2"


def test_fresh_nonce_and_ephemeral_key():
    x = xonly_from_private(USER)
    a, b = seal("same", x), seal("same", x)
    assert a[:12] != b[:12] and a[12:45] != b[12:45]


def test_wrong_key_and_tamper_fail():
    sealed = seal("secret", xonly_from_private(USER))
    with pytest.raises(CryptoError):
        open_sealed(sealed, BOT)
    bad = bytearray(sealed)
    bad[50] ^= 1
    with pytest.raises(CryptoError):
        open_sealed(bytes(bad), USER)
    with pytest.raises(CryptoError):
        open_sealed(sealed[:40], USER)


def test_odd_y_private_key_still_decrypts():
    # Only x of the shared point matters, so a key whose public point has odd y
    # (the address carries x only, peers lift it with even y) decrypts fine.
    from kachat.crypto import private_key
    odd = 0
    for _ in range(40):
        k = secrets.token_hex(32)
        odd += private_key(k).public_key().public_numbers().y % 2
        assert open_sealed(seal("x", xonly_from_private(k)), k) == "x"
    assert odd > 0


def test_ecdh_symmetric():
    assert shared_x(USER, xonly_from_private(BOT)) == shared_x(BOT, xonly_from_private(USER))
