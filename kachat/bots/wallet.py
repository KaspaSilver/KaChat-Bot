"""Wallet bot: a message when a watched address receives or sends KAS.

Driven by a UtxosChanged subscription on the watched addresses. A receive is
a new output (its txid is the paying transaction). A send shows up as removed
outputs; the spending transaction is looked up in what the chain follower saw
(`ctx.spender_of`), or is the transaction that paid change back. Changes are
held a few seconds so both halves of one transaction land in one message.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..address import AddressError, short_address, validate_address
from .base import AnswerError, Bot, Question, fmt_kas, parse_number

SETTLE = 4.0
MAX_ADDRESSES = 10


class WalletBot(Bot):
    TYPE = "wallet"
    TITLE = "Wallet bot"

    def __init__(self, *a, **kw):
        self._buffer: List[tuple] = []     # (time, address, added, removed)
        super().__init__(*a, **kw)

    def default_settings(self) -> dict:
        return {"addresses": [], "minKas": 0}

    def questions(self) -> List[Question]:
        net = self.ctx.network

        def parse_addrs(t: str) -> List[str]:
            parts = [p for p in t.replace(",", " ").replace(";", " ").split() if p]
            if not parts:
                raise AnswerError("Paste one or more kaspa: addresses.")
            if len(parts) > MAX_ADDRESSES:
                raise AnswerError(f"At most {MAX_ADDRESSES} addresses, please.")
            out = []
            for p in parts:
                try:
                    a = validate_address(p, net)
                except AddressError as exc:
                    raise AnswerError(f"{p[:24]}… doesn't look right: {exc}.")
                if a == self.address:
                    raise AnswerError("That's my own address; I can't watch it (every message I send would trigger another).")
                if a not in out:
                    out.append(a)
            return out

        def parse_min(t: str):
            return parse_number(t, minimum=0, what="an amount in KAS, like 0 or 10")

        return [
            Question("addresses", "Which address(es) should I watch? (paste kaspa: addresses, separated by spaces)",
                     parse_addrs, show=lambda v: ", ".join(short_address(a) for a in v) or "none"),
            Question("minKas", "Smallest amount to report, in KAS? (0 = everything)", parse_min, 0,
                     show=lambda v: f"{v:g} KAS"),
        ]

    def describe_settings(self) -> str:
        s = self.settings
        addrs = "\n".join(s.get("addresses") or []) or "none"
        return f"Watching:\n{addrs}\nReporting amounts of at least {float(s.get('minKas') or 0):g} KAS"

    def summary(self) -> str:
        n = len(self.settings.get("addresses") or [])
        if not n:
            return "Not set up"
        if n == 1:
            return f"Watching {short_address(self.settings['addresses'][0])}"
        return f"Watching {n} addresses"

    def sample_notification(self) -> str:
        a = (self.settings.get("addresses") or ["kaspa:qqexample"])[0]
        return self.event_text(a, 1_250_000_000, "0" * 64, 98_765_000_000)

    def watched_addresses(self) -> set:
        if not self.enabled or self.stage not in ("active", "paused"):
            return set()
        return set(self.settings.get("addresses") or [])

    def event_text(self, address: str, net: int, txid: Optional[str], balance: Optional[int]) -> str:
        verb = "Received" if net > 0 else "Sent"
        lines = [f"{verb} {fmt_kas(abs(net))} {'on' if net > 0 else 'from'} {short_address(address)}",
                 f"Balance: {fmt_kas(balance)}"]
        lines.append(f"tx: {txid}" if txid else "tx: unknown")
        return "\n".join(lines)

    async def on_utxos(self, address: str, added: list, removed: list) -> None:
        if address in self.watched_addresses():
            self._buffer.append((self.ctx.clock(), address, list(added), list(removed)))

    async def tick(self, now: float) -> None:
        ready = [b for b in self._buffer if now - b[0] >= SETTLE]
        if not ready:
            return
        self._buffer = [b for b in self._buffer if now - b[0] < SETTLE]
        by_addr: Dict[str, tuple] = {}
        for _, addr, added, removed in ready:
            a, r = by_addr.setdefault(addr, ([], []))
            a.extend(added)
            r.extend(removed)
        for addr, (added, removed) in by_addr.items():
            for txid, net in self.net_by_tx(added, removed):
                await self.report(addr, txid, net)

    def net_by_tx(self, added: list, removed: list) -> List[tuple]:
        """[(txid or None, net sompi)] for one address, in a stable order."""
        net: Dict[Optional[str], int] = {}
        order: List[Optional[str]] = []

        def bump(k, v):
            if k not in net:
                net[k] = 0
                order.append(k)
            net[k] += v

        for e in added:
            bump(e["txid"], int(e["amount"]))
        unknown = 0
        for e in removed:
            spender = self.ctx.spender_of(f"{e['txid']}:{e['index']}")
            if spender:
                bump(spender, -int(e["amount"]))
            else:
                unknown -= int(e["amount"])
        if unknown:
            candidates = [k for k in order if k is not None]
            # Change coming back from the spending tx is the usual case: one tx did both.
            bump(candidates[0] if len(candidates) == 1 else None, unknown)
        return [(k, net[k]) for k in order if net[k] != 0]

    async def report(self, address: str, txid: Optional[str], net: int) -> None:
        key = f"wallet:{address}:{txid}:{net}"
        if txid and self.seen(key):
            return
        if txid:
            self.mark_seen(key)
        min_sompi = int(round(float(self.settings.get("minKas") or 0) * 100_000_000))
        if abs(net) < max(min_sompi, 1):
            self.save()
            return
        balance = await self.ctx.get_balance(address)
        await self.notify(self.event_text(address, net, txid, balance))
