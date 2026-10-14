"""Wallet bot: a message when a watched address receives or sends KAS.

Each address can have a nickname (asked in setup, optional). A message is just the amount
and the address's new balance, by nickname when it has one:

    Savings received 12.5 KAS
    Balance: 1,234.75 KAS


Driven by a UtxosChanged subscription on the watched addresses. A receive is
a new output (its txid is the paying transaction). A send shows up as removed
outputs; the spending transaction is looked up in what the chain follower saw
(`ctx.spender_of`), or is the transaction that paid change back. Changes are
held a few seconds so both halves of one transaction land in one message.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..address import short_address
from .base import MAX_WATCHED, AnswerError, Bot, Question, fmt_kas, parse_address_list, parse_number

SETTLE = 4.0
SELF_SEND_MAX_SOMPI = 1_000_000      # 0.01 KAS: the fee of a self-send, never a real payment
MAX_NICKNAME = 32
NO_NICKNAME = ("none", "no", "nothing", "n/a")


class WalletBot(Bot):
    TYPE = "wallet"
    TITLE = "Wallet bot"
    ADDRESS_KEY = "addresses"
    ASKS_NICKNAME = True

    def __init__(self, *a, **kw):
        self._buffer: List[tuple] = []     # (time, address, added, removed)
        super().__init__(*a, **kw)

    def default_settings(self) -> dict:
        return {"addresses": [], "nicknames": {}, "minKas": 0}

    def questions(self) -> List[Question]:
        net = self.ctx.network

        parse_addrs = parse_address_list(net, not_self=self.address, most=MAX_WATCHED)

        def parse_nicknames(t: str) -> Dict[str, str]:
            addrs = ((self.data.get("setup") or {}).get("draft") or {}).get("addresses") or self.settings.get("addresses") or []
            text = (t or "").strip()
            if text.lower() in NO_NICKNAME:
                return {}
            names = [text] if len(addrs) == 1 else [n.strip() for n in text.split(",")]
            if len(names) != len(addrs):
                raise AnswerError(
                    f"I'm watching {len(addrs)} addresses: send {len(addrs)} nicknames in the same order, "
                    "separated by commas, or none."
                )
            out = {}
            for a, n in zip(addrs, names):
                if len(n) > MAX_NICKNAME:
                    raise AnswerError(f"Keep a nickname to {MAX_NICKNAME} characters or fewer.")
                if n and n.lower() not in NO_NICKNAME:
                    out[a] = n
            return out

        def show_nicknames(v) -> str:
            return ", ".join(v.values()) if v else "none"

        def parse_min(t: str):
            return parse_number(t, minimum=0, what="an amount in KAS, like 0 or 10")

        return [
            Question("addresses", "Which address(es) should I watch? (paste kaspa: addresses, separated by spaces)",
                     parse_addrs, show=lambda v: ", ".join(short_address(a) for a in v) or "none"),
            Question("nicknames", "What should I call it? Send a nickname (like Savings), or none. "
                     "For several addresses, nicknames in the same order separated by commas.",
                     parse_nicknames, {}, show=show_nicknames),
            Question("minKas", "Smallest amount to report, in KAS? (0 = everything)", parse_min, 0,
                     show=lambda v: f"{v:g} KAS"),
        ]

    def name_of(self, address: str) -> str:
        """The address's nickname, or the address shortened."""
        return (self.settings.get("nicknames") or {}).get(address) or short_address(address)

    def describe_settings(self) -> str:
        s = self.settings
        nick = s.get("nicknames") or {}
        addrs = "\n".join(f"{nick[a]}: {a}" if a in nick else a for a in s.get("addresses") or []) or "none"
        return f"Watching:\n{addrs}\nReporting amounts of at least {float(s.get('minKas') or 0):g} KAS"

    def summary(self) -> str:
        n = len(self.settings.get("addresses") or [])
        if not n:
            return "Not set up"
        if n == 1:
            return f"Watching {self.name_of(self.settings['addresses'][0])}"
        return f"Watching {n} addresses"

    def sample_notification(self) -> str:
        a = (self.settings.get("addresses") or ["kaspa:qqexample"])[0]
        return self.event_text(a, 1_250_000_000, "0" * 64, 98_765_000_000)

    def watched_addresses(self) -> set:
        if not self.enabled or self.stage not in ("active", "paused"):
            return set()
        return set(self.settings.get("addresses") or [])

    def event_text(self, address: str, net: int, txid: Optional[str], balance: Optional[int]) -> str:
        # Just the amount and the new balance, by nickname when there is one: no transaction id.
        verb = "received" if net > 0 else "sent"
        return f"{self.name_of(address)} {verb} {fmt_kas(abs(net))}\nBalance: {fmt_kas(balance)}"

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
                if self.is_self_send(txid, net, added, removed):
                    continue
                await self.report(addr, txid, net)

    def is_self_send(self, txid: Optional[str], net: int, added: list, removed: list) -> bool:
        """A transaction that only paid its own address back: a bot's message, a wallet compound.
        Nothing moved anywhere, so it is never reported. Without that, two public wallet bots
        watching each other's address report each other's messages forever (BOT-001). Exact when
        the chain follower has seen the transaction; otherwise a change that both spent from and
        paid back to the address and moved under 0.01 KAS is taken as one."""
        if not txid:
            return False
        known = self.ctx.self_send_of(txid)
        if known is not None:
            return known
        spent_back = any(e.get("txid") == txid for e in added) and bool(removed)
        return spent_back and net < 0 and -net < SELF_SEND_MAX_SOMPI

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
