"""Price bot: KAS price alerts.

- crossing `above` / `below`: once per crossing, re-armed after the price moves
  back by 1% (so a price hovering at the line does not spam)
- a daily summary at `dailyAt` (HH:MM, container time zone)
- a move of at least `movePct` within 24 h (own samples; the API's 24 h change
  until the bot has a day of history), once per direction until it calms down

The price is polled every 60 s (api.kaspa.org, CoinGecko as fallback).
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

from .base import AnswerError, Bot, Question, day_key, parse_number

POLL = 60.0
SAMPLE_EVERY = 300.0          # persisted samples, 5 min apart, 25 h kept
DAY = 24 * 3600
REARM = 0.01
DAILY_WINDOW = 3 * 3600       # a missed daily summary is not sent more than 3 h late


def fmt_price(p: Optional[float], currency: str = "usd") -> str:
    if p is None:
        return "unknown"
    sym = {"usd": "$", "eur": "€", "gbp": "£"}.get(currency, "")
    digits = 4 if p < 1 else 2
    s = f"{p:,.{digits}f}"
    return f"{sym}{s}" if sym else f"{s} {currency.upper()}"


def parse_time(t: str) -> Optional[str]:
    t = t.strip().lower()
    if t in ("no", "none", "off", "n", "never"):
        return None
    m = re.match(r"^(\d{1,2})(?::|\.|h)?(\d{2})?\s*(am|pm)?$", t)
    if not m:
        raise AnswerError("I need a time like 09:00 (or no).")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        raise AnswerError("I need a time like 09:00 (or no).")
    return f"{h:02d}:{mi:02d}"


class PriceBot(Bot):
    TYPE = "price"
    TITLE = "Price bot"

    def __init__(self, *a, **kw):
        self._last_poll = 0.0
        self.price: Optional[float] = None
        self.api_change: Optional[float] = None
        super().__init__(*a, **kw)

    def default_settings(self) -> dict:
        return {"above": None, "below": None, "dailyAt": None, "movePct": None, "currency": "usd"}

    @property
    def currency(self) -> str:
        return (self.settings.get("currency") or "usd").lower()

    def questions(self) -> List[Question]:
        cur = self.currency

        def money(t):
            return parse_number(t, minimum=0.000001, allow_none=True, what="a price like 0.05")

        def pct(t):
            return parse_number(t, minimum=1, maximum=100, allow_none=True, what="a percentage, like 10")

        show_p = lambda v: "no" if v is None else fmt_price(v, cur)  # noqa: E731
        return [
            Question("above", "Alert me when KAS goes above which price? (e.g. 0.05, or no)", money, None, show_p),
            Question("below", "Alert me when KAS falls below which price? (e.g. 0.03, or no)", money, None, show_p),
            Question("dailyAt", "Daily price summary at what time? (e.g. 09:00, or no)", parse_time, None,
                     show=lambda v: "no" if v is None else v),
            Question("movePct", "Alert me on a move of how many % within 24 h? (e.g. 10, or no)", pct, None,
                     show=lambda v: "no" if v is None else f"{v:g}%"),
        ]

    def describe_settings(self) -> str:
        s, c = self.settings, self.currency
        def opt(v, f):
            return "off" if v is None else f(v)
        return (f"Above: {opt(s.get('above'), lambda v: fmt_price(v, c))}\n"
                f"Below: {opt(s.get('below'), lambda v: fmt_price(v, c))}\n"
                f"Daily summary: {opt(s.get('dailyAt'), str)}\n"
                f"24h move alert: {opt(s.get('movePct'), lambda v: f'{v:g}%')}")

    def summary(self) -> str:
        parts = [f"KAS {fmt_price(self.price, self.currency)}" if self.price is not None else "Watching the KAS price"]
        s = self.settings
        if s.get("above") is not None:
            parts.append(f"alert above {fmt_price(s['above'], self.currency)}")
        if s.get("below") is not None:
            parts.append(f"below {fmt_price(s['below'], self.currency)}")
        return ", ".join(parts)

    def sample_notification(self) -> str:
        p = self.price if self.price is not None else 0.05
        return f"KAS is above {fmt_price(p * 0.99, self.currency)}: now {fmt_price(p, self.currency)}"

    def status_extra(self) -> str:
        ch = self.change_24h(self.ctx.clock())
        if self.price is None:
            return ""
        return f"KAS {fmt_price(self.price, self.currency)}" + (f" ({ch:+.1f}% 24h)" if ch is not None else "")

    def on_settings_changed(self) -> None:
        self.data["armed"] = {}
        self.data["moveArmed"] = {"up": True, "down": True}

    def on_reset(self) -> None:
        self.data["armed"] = {}

    # ── price history ───────────────────────────────────────────────────────

    def samples(self) -> list:
        return self.data.setdefault("samples", [])

    def record(self, now: float, price: float) -> None:
        s = self.samples()
        if not s or now - s[-1][0] >= SAMPLE_EVERY:
            s.append([int(now), price])
        cutoff = now - DAY - 3600
        self.data["samples"] = [x for x in s if x[0] >= cutoff]

    def change_24h(self, now: float) -> Optional[float]:
        if self.price is None:
            return None
        old = [x for x in self.samples() if x[0] <= now - DAY + SAMPLE_EVERY]
        if old and now - self.samples()[0][0] >= DAY - SAMPLE_EVERY:
            ref = old[-1][1]
            return (self.price - ref) / ref * 100 if ref else None
        return self.api_change

    def range_24h(self, now: float):
        vals = [x[1] for x in self.samples() if x[0] >= now - DAY]
        if self.price is not None:
            vals.append(self.price)
        return (min(vals), max(vals)) if vals else (None, None)

    # ── loop ────────────────────────────────────────────────────────────────

    async def tick(self, now: float) -> None:
        if self.stage not in ("active", "paused") or not self.ctx.fetch_price:
            return
        if now - self._last_poll < POLL:
            return
        self._last_poll = now
        got = await self.ctx.fetch_price(self.currency)
        if not got:
            return
        price, change = got
        await self.observe(now, float(price), change)

    async def observe(self, now: float, price: float, api_change: Optional[float] = None) -> None:
        self.price = price
        self.api_change = api_change
        self.record(now, price)
        s = self.settings
        armed = self.data.setdefault("armed", {})
        msgs = []

        above = s.get("above")
        if above is not None:
            if "above" not in armed:
                armed["above"] = price < above
            elif armed["above"] and price >= above:
                armed["above"] = False
                msgs.append(f"KAS is above {fmt_price(above, self.currency)}: now {fmt_price(price, self.currency)}")
            elif not armed["above"] and price <= above * (1 - REARM):
                armed["above"] = True

        below = s.get("below")
        if below is not None:
            if "below" not in armed:
                armed["below"] = price > below
            elif armed["below"] and price <= below:
                armed["below"] = False
                msgs.append(f"KAS is below {fmt_price(below, self.currency)}: now {fmt_price(price, self.currency)}")
            elif not armed["below"] and price >= below * (1 + REARM):
                armed["below"] = True

        move = s.get("movePct")
        if move is not None:
            ch = self.change_24h(now)
            ma = self.data.setdefault("moveArmed", {"up": True, "down": True})
            if ch is not None:
                if ch >= move and ma.get("up", True):
                    ma["up"] = False
                    msgs.append(f"KAS is up {ch:.1f}% in 24h: {fmt_price(price, self.currency)}")
                elif ch <= -move and ma.get("down", True):
                    ma["down"] = False
                    msgs.append(f"KAS is down {abs(ch):.1f}% in 24h: {fmt_price(price, self.currency)}")
                if ch < move / 2:
                    ma["up"] = True
                if ch > -move / 2:
                    ma["down"] = True

        daily = s.get("dailyAt")
        if daily:
            lt = time.localtime(now)
            h, m = (int(x) for x in daily.split(":"))
            target = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
            today = day_key(now)
            if target <= now < target + DAILY_WINDOW and self.data.get("lastDaily") != today:
                self.data["lastDaily"] = today
                msgs.append(self.daily_text(now))

        self.save()
        if msgs:
            await self.notify("\n".join(msgs))

    def daily_text(self, now: float) -> str:
        ch = self.change_24h(now)
        lo, hi = self.range_24h(now)
        line = f"KAS today: {fmt_price(self.price, self.currency)}"
        if ch is not None:
            line += f" ({ch:+.1f}% 24h)"
        if lo is not None and hi is not None and hi > lo:
            line += f"\n24h range: {fmt_price(lo, self.currency)} - {fmt_price(hi, self.currency)}"
        return line
