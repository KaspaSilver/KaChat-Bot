"""Deterministic conversation aliases and the first-contact inbox tag
(iOS `DeterministicAlias.swift`).

  S          = x(my_priv * lift_even(their_x))         (same S on both sides)
  alias(ctx) = hex(HKDF-SHA256(ikm=S, salt=empty, info="chat"||S||ctx, L=6))

The alias of a stream is keyed by the RECIPIENT's x-only key:
  send_alias(peer)  = alias(ctx = peer_x)   what the bot writes on
  watch_alias(peer) = alias(ctx = bot_x)    what the peer writes to the bot on
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .address import xonly_from_address
from .crypto import shared_x, xonly_from_private

ALIAS_LEN = 6


def alias_from_shared(shared: bytes, ctx_x: bytes) -> str:
    info = b"chat" + shared + ctx_x
    out = HKDF(algorithm=hashes.SHA256(), length=ALIAS_LEN, salt=b"", info=info).derive(shared)
    return out.hex()


@lru_cache(maxsize=4096)
def _pair_aliases(priv_hex: str, peer_address: str):
    peer_x = xonly_from_address(peer_address)
    my_x = xonly_from_private(priv_hex)
    s = shared_x(priv_hex, peer_x)
    return alias_from_shared(s, peer_x), alias_from_shared(s, my_x)


def send_alias(priv_hex: str, peer_address: str) -> str:
    """The alias I put on messages to `peer_address` (their `myAlias` for me)."""
    return _pair_aliases(priv_hex, peer_address.strip().lower())[0]


def watch_alias(priv_hex: str, peer_address: str) -> str:
    """The alias `peer_address` puts on messages to me."""
    return _pair_aliases(priv_hex, peer_address.strip().lower())[1]


def inbox_tag(address: str) -> str:
    data = ("kachat-inbox:v1:" + address.strip().lower()).encode("utf-8")
    return hashlib.sha256(data).digest()[:16].hex()
