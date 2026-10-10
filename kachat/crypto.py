"""KaChat message cryptography (iOS `KaChatCipher.swift`, byte for byte).

seal:  ephemeral secp256k1 key e, E = compressed(e*G)
       S = x(e * lift_even(recipient_x)); K = HKDF-SHA256(S, salt=empty, info=empty, 32)
       sealed = nonce(12) || E(33) || ChaCha20-Poly1305(K).seal(nonce, utf8(text))
open:  S = x(d * E), same HKDF, open.

`kachat_encrypt` keeps the exact signature and layout of the v1 bot's
watcher.py function so anything built on it keeps working.
"""
from __future__ import annotations

import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    SECP256K1,
    EllipticCurvePublicKey,
    EllipticCurvePublicNumbers,
    derive_private_key,
    generate_private_key,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

NONCE_LEN = 12
EPH_LEN = 33
TAG_LEN = 16


class CryptoError(ValueError):
    pass


def _hkdf(ikm: bytes, length: int, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=b"", info=info).derive(ikm)


def lift_even(x: bytes) -> EllipticCurvePublicKey:
    """The point with x-coordinate `x` and even y (BIP-340 / Kaspa x-only keys)."""
    if len(x) != 32:
        raise CryptoError("x-only key must be 32 bytes")
    xi = int.from_bytes(x, "big")
    if xi >= _P:
        raise CryptoError("x-only key out of range")
    y_sq = (pow(xi, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if (y * y) % _P != y_sq:
        raise CryptoError("x-only key is not on the curve")
    if y % 2:
        y = _P - y
    return EllipticCurvePublicNumbers(x=xi, y=y, curve=SECP256K1()).public_key()


def private_key(priv_hex: str):
    if not isinstance(priv_hex, str) or len(priv_hex) != 64:
        raise CryptoError("private key must be 64 hex characters")
    d = int(priv_hex, 16)
    if not 0 < d < _N:
        raise CryptoError("private key out of range")
    return derive_private_key(d, SECP256K1())


def xonly_from_private(priv_hex: str) -> bytes:
    nums = private_key(priv_hex).public_key().public_numbers()
    return nums.x.to_bytes(32, "big")


def shared_x(priv_hex: str, their_x: bytes) -> bytes:
    """x(d * lift_even(their_x)); the same on both sides of a chat."""
    return private_key(priv_hex).exchange(ECDH(), lift_even(their_x))


def seal(plaintext: str, recipient_x: bytes) -> bytes:
    recv = lift_even(recipient_x)
    eph = generate_private_key(SECP256K1())
    eph_pub = eph.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    key = _hkdf(eph.exchange(ECDH(), recv), 32, b"")
    nonce = secrets.token_bytes(NONCE_LEN)
    return nonce + eph_pub + ChaCha20Poly1305(key).encrypt(nonce, plaintext.encode("utf-8"), None)


def kachat_encrypt(plaintext: str, receiver_x_hex: str) -> bytes:
    """v1 watcher.py API: recipient x-only key as 64 hex characters."""
    return seal(plaintext, bytes.fromhex(receiver_x_hex))


def open_sealed(sealed: bytes, priv_hex: str) -> str:
    """Decrypts a sealed message for the holder of `priv_hex`; raises CryptoError."""
    if len(sealed) < NONCE_LEN + EPH_LEN + TAG_LEN:
        raise CryptoError("sealed message too short")
    nonce = sealed[:NONCE_LEN]
    eph = sealed[NONCE_LEN:NONCE_LEN + EPH_LEN]
    if eph[0] not in (0x02, 0x03):
        raise CryptoError("unsupported ephemeral key form")
    try:
        pub = EllipticCurvePublicKey.from_encoded_point(SECP256K1(), eph)
        key = _hkdf(private_key(priv_hex).exchange(ECDH(), pub), 32, b"")
        plain = ChaCha20Poly1305(key).decrypt(nonce, sealed[NONCE_LEN + EPH_LEN:], None)
        return plain.decode("utf-8")
    except CryptoError:
        raise
    except Exception as exc:  # InvalidTag, bad point, bad UTF-8
        raise CryptoError(f"cannot decrypt: {type(exc).__name__}") from None


def kachat_decrypt(sealed: bytes, priv_hex: str) -> str:
    return open_sealed(sealed, priv_hex)
