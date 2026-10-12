"""Public bots: one bot that anyone in KaChat can use, each person with their own settings.

There are no pairing codes. A PublicHost wraps a bot type (mining, price, wallet) and keeps one
private conversation per person who messages it: an ordinary bot of that type whose owner is
that person, so setup, commands, `add`, `reset` and notifications all work exactly as for a
paired bot, just for everyone at once. They all share the host's wallet (it pays every message).

Spending: each person gets at most `per_person_per_day` messages a day (setup replies and
notifications together), then one note that they are done for today. There is no hourly limit
and no limit question (nobody but the panel owns the wallet). At most MAX_PEOPLE people.

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
from .base import Bot, BotContext

log = logging.getLogger("kachat.bot")

MAX_PEOPLE = 1000
DEFAULT_PER_PERSON = 30          # messages one person may get per day


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

    def __init__(self, cls, cfg, store, ctx: BotContext, per_person_per_day: int = DEFAULT_PER_PERSON):
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
        if len(self.people) >= MAX_PEOPLE:
            return None
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
        if p.owner is None:
            await p._pair(sender, text, txid, ts, intro=f"Hi! I'm the KaChat {self.TITLE}. ")
        else:
            await p.handle_message(sender, text, txid, ts)

    async def send_pending_greeting(self) -> None:
        for p in list(self.people.values()):
            await p.send_pending_greeting()

    async def tick(self, now: float) -> None:
        for p in list(self.people.values()):
            try:
                await p.tick(now)
            except Exception:
                log.exception("[%s] tick for %s failed", self.id, p.owner)

    async def on_utxos(self, address: str, added: list, removed: list) -> None:
        for p in list(self.people.values()):
            if address in p.watched_addresses():
                try:
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
