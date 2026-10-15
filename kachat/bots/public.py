"""Public bots: one bot that anyone in KaChat can use, each person with their own settings.

There are no pairing codes. A PublicHost wraps a bot type (mining, price, wallet) and keeps one
private conversation per person who messages it: an ordinary bot of that type whose owner is
that person, so setup, commands, `add`, `reset` and notifications all work exactly as for a
paired bot, just for everyone at once. They all share the host's wallet (it pays every message).

Nobody is set up before agreeing that their messages are not private (the panel owner can read
them): the first reply to anyone is NOT_PRIVATE_NOTICE, repeated until they answer agree. A
person carried over from a paired bot is asked too, then continues where they were.

Spending: there is no limit per person and no hourly limit (and so no limit question): every
message is paid from the bot's wallet, and its balance is the only cap.

People (BOT-004): at most MAX_PEOPLE who have agreed. Someone who messaged but never agreed is
forgotten after a day (and at most MAX_PENDING wait to agree at once). When a newcomer agrees
with the bot full, the person quiet longest (nothing from them for IDLE_EVICT) makes room; if
nobody is that quiet, the newcomer is told it is full, at most once a day. Someone who is set up
is never forgotten to make room (BOT-012): only people who agreed but never finished setup.
(`per_person_per_day` can still set a daily cap per person; the daemon passes none.)

The pool hashrate (the panel's own stratum bridge) is the owner's, not a stranger's, so public
mining bots never ask about or report it.

State: the host's own file keeps who has talked to it ({"people": {key: address}}); each
person's conversation is its own file next to it (botd/<id>/<key>.json).
"""
from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import shutil
from typing import Dict, Optional

from ..address import short_address
from ..state import atomic_write_json, read_json
from .base import NOT_PRIVATE_NOTICE, Bot, BotContext, is_agree

log = logging.getLogger("kachat.bot")

MAX_PEOPLE = 5000                 # people who agreed
MAX_PENDING = 2000                # people who messaged but have not agreed yet
PENDING_FORGET = 86400            # a day: someone who never agreed is forgotten
IDLE_EVICT = 30 * 86400           # quiet this long, a person may make room for a newcomer
FULL_TEXT = ("Sorry, I'm full right now: I'm already looking after as many people as I can. "
             "Please try again later.")
DEFAULT_PER_PERSON = None        # messages one person may get per day (None = no limit)


def person_key(address: str) -> str:
    return hashlib.sha256(address.encode()).hexdigest()[:20]


class PersonStore:
    """One person's conversation: its own data file; its history goes to the host's, named."""

    def __init__(self, host: "PublicHost", sender: str):
        self.host = host
        self.sender = sender
        self.key = person_key(sender)
        self.history_path = os.devnull + ".none"         # reset_owner deletes this: nothing to delete
        base = getattr(host.store, "data_path", None)
        self.data_path = os.path.join(os.path.splitext(base)[0], f"{self.key}.json") if base else None

    def load_data(self) -> dict:
        if self.data_path:
            d = read_json(self.data_path, {})
            return d if isinstance(d, dict) else {}
        return dict(self.host.memory.get(self.key, {}))

    def save_data(self, data: dict) -> None:
        if self.data_path:
            atomic_write_json(self.data_path, data, mode=0o600)
        else:
            self.host.memory[self.key] = dict(data)

    def write_status(self, status: dict) -> None:
        pass

    def append_history(self, direction: str, text: str, txid, ts=None) -> None:
        who = short_address(self.sender)
        self.host.store.append_history(direction, (f"{who}: " if direction == "in" else f"To {who}: ") + text, txid, ts)


class PublicHost(Bot):
    PAIRS = False

    def __init__(self, cls, cfg, store, ctx: BotContext, per_person_per_day: Optional[int] = DEFAULT_PER_PERSON):
        self.cls = cls
        self.TYPE = cls.TYPE
        self.TITLE = cls.TITLE
        self.per_person = per_person_per_day
        self.people: Dict[str, Bot] = {}
        self.memory: Dict[str, dict] = {}          # person data when the store has no files (tests)
        self._balance: Optional[int] = None
        self._loading = True
        super().__init__(cfg, store, ctx)
        legacy = self.data.get("owner")
        self.data.setdefault("people", {})
        for addr in list(self.data["people"].values()):
            self._person(addr)
        if legacy:
            self._adopt_legacy(legacy)
        self._go_live()
        self._loading = False
        self.save()

    # ── the wallet's balance is everyone's ──────────────────────────────────

    @property
    def balance(self) -> Optional[int]:
        return self._balance

    @balance.setter
    def balance(self, value: Optional[int]) -> None:
        self._balance = value
        for p in getattr(self, "people", {}).values():
            p.balance = value

    # ── people ──────────────────────────────────────────────────────────────

    def _person_cfg(self):
        return dataclasses.replace(self.cfg, reset_owner=None, reset_settings=None)

    def _person(self, sender: str, create: bool = True) -> Optional[Bot]:
        p = self.people.get(sender)
        if p is not None or not create:
            return p
        if sum(1 for q in self.people.values() if not q.data.get("agreedNotPrivate")) >= MAX_PENDING:
            return None                  # too many waiting to agree: nothing new until they age out
        ctx = dataclasses.replace(self.ctx, fetch_hashrate=None)
        p = self.cls(self._person_cfg(), PersonStore(self, sender), ctx)
        p.HOURLY_LIMIT = False
        p.daily_cap = self.per_person
        p.balance = self._balance
        self.people[sender] = p
        self.data["people"][person_key(sender)] = sender
        return p

    def _adopt_legacy(self, owner: str) -> None:
        """A bot paired before bots were public: its owner keeps their setup as a person."""
        keep = {k: v for k, v in self.data.items() if k not in ("seen", "people", "outTimes", "privateReplies")}
        p = self._person(owner)
        if p is None:
            return
        if p.owner is None:
            p.data.update(keep)
            p.data["owner"] = owner
            p.on_settings_changed()
            p.save()
        for k in ("owner", "settings", "setup", "adding", "greetPending"):
            self.data.pop(k, None)
        log.info("[%s] the paired owner %s carries on as one of its people", self.id, owner)

    def _go_live(self) -> None:
        self.data.update({"owner": None, "stage": "active", "setup": None, "greetPending": False})

    def known_senders(self) -> set:
        return set(self.people)

    def watched_addresses(self) -> set:
        out = set()
        for p in self.people.values():
            if p.stage in ("active", "paused"):
                out |= p.watched_addresses()
        return out

    # ── config ──────────────────────────────────────────────────────────────

    def apply_config(self, cfg, initial: bool = False) -> None:
        self.cfg = cfg
        # The panel's Reset (and New owner): everyone's setup is forgotten; each starts over the
        # next time they message. The wallet stays.
        for nonce_key, value in (("resetSettingsSeen", cfg.reset_settings), ("resetOwnerSeen", cfg.reset_owner)):
            if value and value != self.data.get(nonce_key):
                self.data[nonce_key] = value
                if not initial or self.data.get("people"):
                    self._forget_everyone()
        for p in self.people.values():
            p.cfg = self._person_cfg()
        if not self._loading:
            self.save()

    def _forget_everyone(self) -> None:
        log.info("[%s] reset: forgetting everyone's setup", self.cfg.id)
        self.people = {}
        self.memory = {}
        self.data["people"] = {}
        for k in ("owner", "settings", "setup", "adding"):
            self.data.pop(k, None)
        base = getattr(self.store, "data_path", None)
        if base:
            shutil.rmtree(os.path.splitext(base)[0], ignore_errors=True)

    def reset_owner(self) -> None:
        self._forget_everyone()

    def _forget(self, sender: str) -> None:
        """One person gone: their conversation, settings and file."""
        p = self.people.pop(sender, None)
        key = person_key(sender)
        self.data["people"].pop(key, None)
        self.memory.pop(key, None)
        path = getattr(p.store, "data_path", None) if p else None
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    def _agreed_count(self) -> int:
        return sum(1 for p in self.people.values() if p.data.get("agreedNotPrivate"))

    def _last_heard(self, p: Bot) -> int:
        return int(max(p.data.get("lastInAt") or 0, p.data.get("agreedNotPrivate") or 0, p.data.get("createdAt") or 0))

    def _make_room(self, now: float) -> bool:
        """Room for one more agreed person: under the cap, or the quietest idle one forgotten."""
        if self._agreed_count() < MAX_PEOPLE:
            return True
        # Never someone who is set up (BOT-012): subscribers only receive notifications, so they
        # always look quiet. Only people who agreed but never finished setup can make room.
        idle = [(self._last_heard(p), who) for who, p in self.people.items()
                if p.data.get("agreedNotPrivate") and p.stage != "active" and not p.data.get("settings")
                and now - self._last_heard(p) >= IDLE_EVICT]
        if not idle:
            return False
        _, who = min(idle)
        log.info("[%s] full: %s (quiet longest) makes room for a newcomer", self.id, who)
        self._forget(who)
        return True

    def _forget_pending(self, now: float) -> None:
        """People who messaged but never agreed, once a day has passed."""
        # Someone with a setup (carried over from a paired bot) is never forgotten for this.
        stale = [who for who, p in self.people.items()
                 if not p.data.get("agreedNotPrivate") and p.owner is None
                 and now - (p.data.get("createdAt") or now) >= PENDING_FORGET]
        for who in stale:
            self._forget(who)
        if stale:
            self.save()

    # ── messages ────────────────────────────────────────────────────────────

    async def handle_message(self, sender: str, text: str, txid: str, ts: Optional[float] = None) -> None:
        if not self.enabled or txid in self._seen:
            return
        self.mark_seen(txid)
        now = self.ctx.clock()
        ts = int(ts if ts is not None else now)
        sender = sender.strip().lower()
        if sender == self.address:
            return
        p = self._person(sender)
        self.data["lastInAt"] = ts
        self.save()
        if p is None:
            return
        if not p.data.get("agreedNotPrivate"):
            await self._agreement(p, sender, text, txid, ts)
        elif p.owner is None:
            await p._pair(sender, text, txid, ts, intro=f"Hi! I'm the KaChat {self.TITLE}. ")
        else:
            await p.handle_message(sender, text, txid, ts)

    async def _agreement(self, p: Bot, sender: str, text: str, txid: str, ts: int) -> None:
        """Before anything else: the person agrees that their messages are not private."""
        p.mark_seen(txid)
        if not is_agree(text):
            p.store.append_history("in", text, txid, ts)
            sent = await p.send_to(sender, NOT_PRIVATE_NOTICE)
            if sent and p.owner != sender:
                p.store.append_history("out", NOT_PRIVATE_NOTICE, sent, ts)
            p.save()
            return
        if not self._make_room(self.ctx.clock()):
            # Full of active people: say so (once a day each) rather than go quiet.
            day = int(self.ctx.clock() // 86400)
            if p.data.get("fullNoticeDay") != day:
                p.data["fullNoticeDay"] = day
                await p.send_to(sender, FULL_TEXT)
            p.save()
            return
        p.data["agreedNotPrivate"] = int(ts)
        p.save()
        self.save()
        if p.owner is None:
            await p._pair(sender, text, txid, ts, intro=f"Thanks! I'm the KaChat {self.TITLE}. ")
        else:
            p.store.append_history("in", text, txid, ts)
            await p.say("Thanks! Carry on where you left off. Send help for the commands.")

    async def send_pending_greeting(self) -> None:
        for p in list(self.people.values()):
            await p.send_pending_greeting()

    def low_balance_people(self, now: float) -> list:
        recent = [p for p in self.people.values()
                  if p.owner and p.data.get("agreedNotPrivate") and now - (p.data.get("lastInAt") or 0) < self.LOW_BALANCE_RECENT]
        recent.sort(key=lambda p: p.data.get("lastInAt") or 0, reverse=True)
        return [p.owner for p in recent]

    async def send_low_balance_notice(self, recipient: str, text: str):
        p = self.people.get(recipient)
        return await (p.send_to(recipient, text) if p else self.send_to(recipient, text))

    async def tick(self, now: float) -> None:
        try:
            await self.check_low_balance(now)
        except Exception:
            log.exception("[%s] low-balance notice failed", self.id)
        if now - getattr(self, "_pending_swept", 0) >= 3600:
            self._pending_swept = now
            self._forget_pending(now)
        for p in list(self.people.values()):
            try:
                await p.tick(now)
            except Exception:
                log.exception("[%s] tick for %s failed", self.id, p.owner)

    async def on_utxos(self, address: str, added: list, removed: list) -> None:
        for p in list(self.people.values()):
            if address in p.watched_addresses():
                try:
                    if await p.too_busy(address, added, removed):
                        continue                 # a pool or exchange: dropped, they were told
                    await p.on_utxos(address, added, removed)
                except Exception:
                    log.exception("[%s] UTXO handling for %s failed", self.id, p.owner)

    # ── status for the panel ────────────────────────────────────────────────

    def summary(self) -> str:
        n = sum(1 for p in self.people.values() if p.stage == "active")
        return f"Public: {n} {'person' if n == 1 else 'people'} set up"

    def panel_summary(self) -> str:
        if not self.enabled:
            return "Disabled"
        if self.balance is not None and not self.funded():
            return f"Fund {short_address(self.address)} to start"
        return self.summary()

    def status(self) -> dict:
        st = super().status()
        errors = [p.error for p in self.people.values() if p.error and p.error.startswith("Could not send")]
        if st.get("error") is None and errors:
            st["error"] = errors[-1]
        st["stats"] = {
            "people": len(self.people),
            "active": sum(1 for p in self.people.values() if p.stage == "active"),
            "perPersonPerDay": self.per_person,
        }
        return st
