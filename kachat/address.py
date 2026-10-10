"""Kaspa addresses: the cashaddr-style bech32 codec, validation per network,
and conversion between an address and its scriptPublicKey.

Pure Python, a port of rusty-kaspa `crypto/addresses/src/bech32.rs`, so every
address the bot accepts from a person is checked (prefix + checksum) without
the SDK, and a spent output's script can be turned back into the sender's
address when the node leaves the address field empty.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_REV = {c: i for i, c in enumerate(CHARSET)}

VERSION_PUBKEY = 0x00        # Schnorr P2PK, 32-byte x-only key
VERSION_PUBKEY_ECDSA = 0x01  # ECDSA P2PK, 33-byte compressed key
VERSION_SCRIPT_HASH = 0x08   # P2SH, 32-byte hash

_PAYLOAD_LEN = {VERSION_PUBKEY: 32, VERSION_PUBKEY_ECDSA: 33, VERSION_SCRIPT_HASH: 32}

NETWORK_PREFIX = {
    "mainnet": "kaspa",
    "testnet": "kaspatest",
    "testnet-10": "kaspatest",
    "testnet-11": "kaspatest",
    "simnet": "kaspasim",
    "devnet": "kaspadev",
}


class AddressError(ValueError):
    pass


def prefix_for_network(network: str) -> str:
    net = (network or "mainnet").strip().lower()
    if net in NETWORK_PREFIX:
        return NETWORK_PREFIX[net]
    if net.startswith("testnet"):
        return "kaspatest"
    raise AddressError(f"unknown network {network!r}")


def _polymod(values) -> int:
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07FFFFFFFF) << 5) ^ d
        if c0 & 0x01:
            c ^= 0x98F2BC8E61
        if c0 & 0x02:
            c ^= 0x79B76D99E2
        if c0 & 0x04:
            c ^= 0xF33E5FB3C4
        if c0 & 0x08:
            c ^= 0xAE2EABE2A8
        if c0 & 0x10:
            c ^= 0x1E4F43E470
    return c ^ 1


def _checksum(payload5: list, prefix: str) -> int:
    return _polymod([ord(ch) & 0x1F for ch in prefix] + [0] + list(payload5) + [0] * 8)


def _conv8to5(data: bytes) -> list:
    out = []
    buff = 0
    bits = 0
    for b in data:
        buff = (buff << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append((buff >> bits) & 0x1F)
            buff &= (1 << bits) - 1
    if bits > 0:
        out.append((buff << (5 - bits)) & 0x1F)
    return out


def _conv5to8(data: list) -> bytes:
    out = bytearray()
    buff = 0
    bits = 0
    for c in data:
        buff = (buff << 5) | c
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((buff >> bits) & 0xFF)
            buff &= (1 << bits) - 1
    return bytes(out)


def encode_address(prefix: str, version: int, payload: bytes) -> str:
    five = _conv8to5(bytes([version]) + bytes(payload))
    cs = _checksum(five, prefix)
    five_cs = _conv8to5(cs.to_bytes(8, "big")[3:])
    return prefix + ":" + "".join(CHARSET[i] for i in five + five_cs)


@dataclass(frozen=True)
class DecodedAddress:
    prefix: str
    version: int
    payload: bytes

    @property
    def address(self) -> str:
        return encode_address(self.prefix, self.version, self.payload)


def decode_address(address: str) -> DecodedAddress:
    if not isinstance(address, str):
        raise AddressError("address must be text")
    s = address.strip()
    if s != s.lower() and s != s.upper():
        raise AddressError("mixed-case address")
    s = s.lower()
    if ":" not in s:
        raise AddressError("address has no prefix (kaspa: or kaspatest:)")
    prefix, data = s.split(":", 1)
    if not prefix or len(data) < 8:
        raise AddressError("address is too short")
    try:
        five = [_REV[ch] for ch in data]
    except KeyError as exc:
        raise AddressError(f"invalid character {exc.args[0]!r} in address") from None
    payload5, cs5 = five[:-8], five[-8:]
    cs = int.from_bytes(_conv5to8(cs5).rjust(8, b"\0"), "big")
    if _checksum(payload5, prefix) != cs:
        raise AddressError("address checksum does not match (typo?)")
    raw = _conv5to8(payload5)
    if not raw:
        raise AddressError("empty address payload")
    version, payload = raw[0], raw[1:]
    expected = _PAYLOAD_LEN.get(version)
    if expected is None:
        raise AddressError(f"unknown address version {version}")
    if len(payload) != expected:
        raise AddressError("address payload has the wrong length")
    return DecodedAddress(prefix, version, payload)


def validate_address(address: str, network: str, *, require_pubkey: bool = False) -> str:
    """Returns the normalized (lowercase) address, or raises AddressError with a
    sentence a person can act on."""
    d = decode_address(address)
    want = prefix_for_network(network)
    if d.prefix != want:
        raise AddressError(f"that is a {d.prefix}: address; this bot runs on {want}:")
    if require_pubkey and d.version != VERSION_PUBKEY:
        raise AddressError("only normal (Schnorr) wallet addresses can chat")
    return d.address


def is_valid_address(address: str, network: str, *, require_pubkey: bool = False) -> bool:
    try:
        validate_address(address, network, require_pubkey=require_pubkey)
        return True
    except AddressError:
        return False


def xonly_from_address(address: str) -> bytes:
    d = decode_address(address)
    if d.version != VERSION_PUBKEY:
        raise AddressError("not a Schnorr P2PK address")
    return d.payload


def address_from_xonly(xonly: bytes, network: str) -> str:
    if len(xonly) != 32:
        raise AddressError("x-only key must be 32 bytes")
    return encode_address(prefix_for_network(network), VERSION_PUBKEY, xonly)


def script_for_address(address: str) -> bytes:
    d = decode_address(address)
    if d.version == VERSION_PUBKEY:
        return bytes([0x20]) + d.payload + bytes([0xAC])
    if d.version == VERSION_PUBKEY_ECDSA:
        return bytes([0x21]) + d.payload + bytes([0xAB])
    return bytes([0xAA, 0x20]) + d.payload + bytes([0x87])


def address_from_script(script: bytes, prefix: str) -> Optional[str]:
    """Standard scripts only (P2PK Schnorr/ECDSA, P2SH); None for anything else."""
    s = bytes(script)
    if len(s) == 34 and s[0] == 0x20 and s[-1] == 0xAC:
        return encode_address(prefix, VERSION_PUBKEY, s[1:33])
    if len(s) == 35 and s[0] == 0x21 and s[-1] == 0xAB:
        return encode_address(prefix, VERSION_PUBKEY_ECDSA, s[1:34])
    if len(s) == 35 and s[0] == 0xAA and s[1] == 0x20 and s[-1] == 0x87:
        return encode_address(prefix, VERSION_SCRIPT_HASH, s[2:34])
    return None


def short_address(address: str) -> str:
    """kaspa:qq…abcd, for one-line summaries."""
    if not address or ":" not in address:
        return address or ""
    prefix, data = address.split(":", 1)
    if len(data) <= 10:
        return address
    return f"{prefix}:{data[:2]}…{data[-4:]}"
