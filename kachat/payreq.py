"""KaChat payment request links, signed by the bot, so tapping one in KaChat opens Send Kaspa
with the bot's address and the amount filled in, shown as "from" the bot.

The format is the app's (`PaymentRequest` in KaChat iOS, Services/LinkPreviewService.swift):

    https://kachat.app/pay/<address>?amount=<KAS>&memo=<text>&by=<address>&sig=<hex>

- the address without `kaspa:` on mainnet, with `kaspatest:` on testnet (same for `by`);
- `amount` in KAS, at most 8 decimals; `memo` at most 140 characters, only unreserved
  characters left unescaped;
- `sig`: a BIP340 Schnorr signature by `by`'s key over SHA-256 of the lines
  "kachat-payment-request:v1", address, amount in sompi, memo, "1"/"0" for chat, creator
  (addresses in full, lower case). The app refuses a link whose signature does not check out.

`chat=1` is left out: the payment is a plain payment to the bot's address, and the memo only
tells the payer what it is for.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional
from urllib.parse import quote

HOST = "https://kachat.app"
MEMO_LIMIT = 140

# ── BIP340 Schnorr (the reference algorithm; signing only happens for an occasional link) ────

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % _P == 0:
        return None
    if a == b:
        lam = 3 * a[0] * a[0] * pow(2 * a[1], _P - 2, _P) % _P
    else:
        lam = (b[1] - a[1]) * pow(b[0] - a[0], _P - 2, _P) % _P
    x = (lam * lam - a[0] - b[0]) % _P
    return x, (lam * (a[0] - x) - a[1]) % _P


def _mul(k: int, pt=_G):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def _tagged(tag: str, msg: bytes) -> bytes:
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _b(x: int) -> bytes:
    return x.to_bytes(32, "big")


def schnorr_sign(msg: bytes, seckey: bytes, aux: Optional[bytes] = None) -> bytes:
    d0 = int.from_bytes(seckey, "big")
    if not 0 < d0 < _N:
        raise ValueError("bad private key")
    pub = _mul(d0)
    d = d0 if pub[1] % 2 == 0 else _N - d0
    aux = os.urandom(32) if aux is None else aux
    t = bytes(x ^ y for x, y in zip(_b(d), _tagged("BIP0340/aux", aux)))
    k0 = int.from_bytes(_tagged("BIP0340/nonce", t + _b(pub[0]) + msg), "big") % _N
    if k0 == 0:
        raise ValueError("bad nonce")
    r = _mul(k0)
    k = k0 if r[1] % 2 == 0 else _N - k0
    e = int.from_bytes(_tagged("BIP0340/challenge", _b(r[0]) + _b(pub[0]) + msg), "big") % _N
    return _b(r[0]) + _b((k + e * d) % _N)


def schnorr_verify(msg: bytes, xonly: bytes, sig: bytes) -> bool:
    x = int.from_bytes(xonly, "big")
    if x >= _P or len(sig) != 64:
        return False
    y = pow((pow(x, 3, _P) + 7) % _P, (_P + 1) // 4, _P)
    if (y * y - x ** 3 - 7) % _P:
        return False
    pub = (x, y if y % 2 == 0 else _P - y)
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if r >= _P or s >= _N:
        return False
    e = int.from_bytes(_tagged("BIP0340/challenge", sig[:32] + xonly + msg), "big") % _N
    pt = _add(_mul(s), _mul(_N - e, pub))
    return pt is not None and pt[1] % 2 == 0 and pt[0] == r


# ── the link ─────────────────────────────────────────────────────────────────

def _amount_text(sompi: int) -> str:
    whole, frac = divmod(int(sompi), 100_000_000)
    return str(whole) if not frac else f"{whole}.{frac:08d}".rstrip("0")


def _path(address: str) -> str:
    return address[len("kaspa:"):] if address.startswith("kaspa:") else address


def signing_digest(address: str, sompi: int, memo: str, chat: bool, creator: str) -> bytes:
    text = "\n".join(["kachat-payment-request:v1", address.lower(), str(int(sompi)), memo,
                      "1" if chat else "0", creator.lower()])
    return hashlib.sha256(text.encode("utf-8")).digest()


def payment_request_link(address: str, sompi: int, memo: str, priv_hex: str) -> str:
    """A signed request to pay `sompi` to `address` (the bot's own, whose key is `priv_hex`)."""
    if sompi <= 0:
        raise ValueError("amount must be positive")
    address = address.strip().lower()
    memo = "".join(ch for ch in (memo or "") if ch.isprintable())[:MEMO_LIMIT]
    sig = schnorr_sign(signing_digest(address, sompi, memo, False, address), bytes.fromhex(priv_hex))
    query = f"amount={_amount_text(sompi)}"
    if memo:
        query += "&memo=" + quote(memo, safe="-._~")
    query += f"&by={_path(address)}&sig={sig.hex()}"
    return f"{HOST}/pay/{_path(address)}?{query}"
