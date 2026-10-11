"""The conversation engine every bot type shares.

Life of a bot (contract stages):
  awaiting_pairing  nobody owns it; the first sender of the 6-digit pairing code does
  setup             it asks its questions one at a time, validating each answer
  active            it sends notifications; commands work any time
  paused            like active, but no notifications
  disabled          enabled=false in bots.json: no listening, no sending

Spending rules (every reply costs a network fee):
  - one reply per incoming owner message, at most `max_out_per_hour` messages per hour in total
  - before pairing, a stranger gets at most one "This bot is private." per day
    (and all strangers together at most PRIVATE_REPLIES_PER_DAY a day)
  - after pairing, anyone but the owner is ignored: no reply, no spend
"""
from __future__ import annotations

import copy
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from ..address import AddressError, address_from_xonly, short_address, validate_address
from ..alias import inbox_tag
from ..crypto import xonly_from_private

log = logging.getLogger("kachat.bot")

SEEN_MAX = 3000
PRIVATE_REPLY = "This bot is private."
PRIVATE_REPLIES_PER_DAY = 20
DEFAULT_MAX_OUT_PER_HOUR = 30
REQUIRED = object()

COMMANDS = ("help", "status", "settings", "change", "reset", "add", "pause", "resume", "test")
MAX_WATCHED = 10                 # addresses one mining or wallet bot may watch
SKIP_WORDS = ("skip", "default", "keep", "-")


class AnswerError(ValueError):
    """A setup answer that did not validate; the message is shown to the owner."""


@dataclass
class Question:
    key: str
    prompt: str
    parse: Callable[[str], Any]
    default: Any = REQUIRED
    show: Callable[[Any], str] = lambda v: "none" if v is None else str(v)


def fmt_kas(sompi: Optional[int]) -> str:
    if sompi is None:
        return "unknown"
    kas = sompi / 100_000_000
    s = f"{kas:,.8f}".rstrip("0").rstrip(".")
    return f"{s} KAS"


def fmt_hashrate(ghs: Optional[float]) -> str:
    if ghs is None:
        return "unknown"
    th = ghs / 1000.0
    if th >= 1000:
        return f"{th / 1000:.2f} PH/s"
    if th >= 1:
        return f"{th:.2f} TH/s"
    return f"{ghs:.1f} GH/s"


def parse_number(text: str, *, minimum: float = 0.0, maximum: Optional[float] = None,
                 allow_none: bool = False, what: str = "a number") -> Optional[float]:
    t = text.strip().lower().replace(",", ".").lstrip("$").rstrip("%").strip()
    if allow_none and t in ("no", "none", "off", "n", "never"):
        return None
    try:
        v = float(t)
    except ValueError:
        raise AnswerError(f"I need {what}" + (" (or 'no')." if allow_none else "."))
    if v != v or v < minimum or (maximum is not None and v > maximum):
        rng = f"between {minimum:g} and {maximum:g}" if maximum is not None else f"at least {minimum:g}"
        raise AnswerError(f"That should be {rng}.")
    return v


def day_key(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


@dataclass
class BotContext:
    """What a bot needs from the outside world; the daemon fills it, tests fake it."""
    network: str
    send: Callable                          # async (bot, recipient, text) -> txid
    get_balance: Callable                   # async (address) -> sompi | None
    clock: Callable[[], float] = time.time
    fetch_price: Optional[Callable] = None  # async (currency) -> (price, change24h_pct | None)
    fetch_hashrate: Optional[Callable] = None   # async () -> GH/s | None
    spender_of: Callable[[str], Optional[str]] = lambda key: None
    max_out_per_hour: int = DEFAULT_MAX_OUT_PER_HOUR
    on_change: Callable = lambda bot: None  # status changed -> write it


class Bot:
    TYPE = ""
    TITLE = "Bot"

    def __init__(self, cfg, store, ctx: BotContext):
        self.cfg = cfg
        self.store = store
        self.ctx = ctx
        self.priv_hex = cfg.private_key_hex
        self.address = address_from_xonly(xonly_from_private(self.priv_hex), ctx.network)
        self.inbox_tag = inbox_tag(self.address)
        self.data = store.load_data()
        self.data.setdefault("createdAt", int(ctx.clock()))
        self.data.setdefault("stage", "awaiting_pairing")
        self.data.setdefault("owner", None)
        self.data.setdefault("settings", None)
        self.data.setdefault("seen", [])
        self.data.setdefault("outTimes", [])
        self.data.setdefault("privateReplies", {})
        self.data.setdefault("lastInAt", None)
        self.data.setdefault("lastOutAt", None)
        self.balance: Optional[int] = None
        self.error: Optional[str] = None
        self.node_error: Optional[str] = None
        self._seen_list = [str(t) for t in self.data["seen"]][-SEEN_MAX:]
        self._seen = set(self._seen_list)
        self.config_error: Optional[str] = None
        if cfg.address and cfg.address.strip().lower() != self.address:
            self.config_error = f"bots.json address {cfg.address} does not match the key; using {self.address}"
            log.warning("[%s] %s", cfg.id, self.config_error)
        self.apply_config(cfg, initial=True)

    # ── config ──────────────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self.cfg.id

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    @property
    def owner(self) -> Optional[str]:
        return self.data.get("owner")

    @property
    def stage(self) -> str:
        return self.data.get("stage") or "awaiting_pairing"

    @property
    def settings(self) -> dict:
        return self.data.get("settings") or {}

    def apply_config(self, cfg, initial: bool = False) -> None:
        self.cfg = cfg
        if cfg.reset_owner and cfg.reset_owner != self.data.get("resetOwnerSeen"):
            had_owner = self.data.get("owner") is not None or self.data.get("settings") is not None
            self.data["resetOwnerSeen"] = cfg.reset_owner
            if had_owner:
                log.info("[%s] resetOwner changed: forgetting owner, settings and conversation", cfg.id)
            self.reset_owner()
        # The panel's Reset: forget only the answers (wallet, owner and funds stay) and greet the
        # owner with the first setup message again, as on pairing. The message itself is sent from
        # tick (this runs synchronously on a config reload).
        rs = getattr(cfg, "reset_settings", None)
        # A click made while the bot was stopped still applies at its next start.
        if rs and rs != self.data.get("resetSettingsSeen"):
            self.data["resetSettingsSeen"] = rs
            if self.data.get("owner"):
                log.info("[%s] resetSettings changed: forgetting the answers, setup starts over", cfg.id)
                self.data["settings"] = None
                self.data["adding"] = None
                self.on_reset()
                self.on_settings_changed()
                self._start_setup(from_current=False)
                self.data["greetPending"] = True
        self.save()

    async def send_pending_greeting(self) -> None:
        """After a panel Reset: the first setup message again, to the owner."""
        if not self.data.get("greetPending") or not self.data.get("owner"):
            return
        self.data["greetPending"] = False
        self.save()
        q = self.questions()
        intro = f"Hi again! I'm your KaChat {self.TITLE}, and my settings were just reset. "
        if q:
            await self.say(intro + "A few quick questions.\n\n" + self._prompt(0))
        else:
            self._finish_setup()
            self.save()
            await self.say(intro + "All set.")

    def reset_owner(self) -> None:
        self.data.update({"owner": None, "settings": None, "stage": "awaiting_pairing",
                          "setup": None, "privateReplies": {}})
        self.on_reset()
        try:
            import os
            os.remove(self.store.history_path)
        except OSError:
            pass

    def save(self) -> None:
        if len(self._seen_list) > SEEN_MAX:
            self._seen_list = self._seen_list[-SEEN_MAX:]
            self._seen = set(self._seen_list)
        self.data["seen"] = self._seen_list
        self.store.save_data(self.data)
        self.ctx.on_change(self)

    # ── type hooks (override) ───────────────────────────────────────────────

    def questions(self) -> List[Question]:
        return []

    def describe_settings(self) -> str:
        return ""

    def summary(self) -> str:
        return ""

    def sample_notification(self) -> str:
        return "This is a test notification."

    def status_extra(self) -> str:
        return ""

    def on_reset(self) -> None:
        pass

    def on_settings_changed(self) -> None:
        pass

    def watched_addresses(self) -> set:
        return set()

    # Address-watching bots (mining, wallet) set ADDRESS_KEY and get the `add` command.
    ADDRESS_KEY: Optional[str] = None
    ASKS_NICKNAME = False

    def address_list(self) -> List[str]:
        return list(self.settings.get(self.ADDRESS_KEY) or []) if self.ADDRESS_KEY else []

    async def tick(self, now: float) -> None:
        pass

    async def on_utxos(self, address: str, added: list, removed: list) -> None:
        pass

    # ── sending ─────────────────────────────────────────────────────────────

    def _out_budget_left(self, now: float) -> int:
        times = [t for t in self.data.get("outTimes", []) if now - t < 3600]
        self.data["outTimes"] = times
        return self.ctx.max_out_per_hour - len(times)

    async def send_to(self, recipient: str, text: str) -> Optional[str]:
        """Sends one message if the rate limit allows; returns the txid or None."""
        if not self.enabled:
            return None
        now = self.ctx.clock()
        if self._out_budget_left(now) <= 0:
            self.error = f"Rate limit: {self.ctx.max_out_per_hour} messages in the last hour; holding back"
            log.warning("[%s] %s", self.id, self.error)
            self.save()
            return None
        self.data["outTimes"].append(now)
        try:
            txid = await self.ctx.send(self, recipient, text)
        except Exception as exc:
            self.error = f"Could not send: {exc}"
            log.warning("[%s] send failed: %s", self.id, exc)
            self.save()
            return None
        if recipient == self.owner:
            self.store.append_history("out", text, txid, int(now))
        self.data["lastOutAt"] = int(now)
        if self.error and (self.error.startswith("Could not send") or self.error.startswith("Rate limit")):
            self.error = None
        self.save()
        return txid

    async def say(self, text: str) -> Optional[str]:
        if not self.owner:
            return None
        return await self.send_to(self.owner, text)

    async def notify(self, text: str) -> Optional[str]:
        """A notification: only when active (not paused, not in setup)."""
        if self.stage != "active":
            return None
        return await self.say(text)

    # ── incoming ────────────────────────────────────────────────────────────

    def seen(self, txid: str) -> bool:
        return txid in self._seen

    def mark_seen(self, txid: str) -> None:
        if txid not in self._seen:
            self._seen.add(txid)
            self._seen_list.append(txid)

    async def handle_message(self, sender: str, text: str, txid: str, ts: Optional[float] = None) -> None:
        if not self.enabled or txid in self._seen:
            return
        self.mark_seen(txid)
        now = self.ctx.clock()
        ts = int(ts if ts is not None else now)
        sender = sender.strip().lower()
        if self.owner is None:
            if re.search(rf"(?<!\d){re.escape(self.cfg.pairing_code)}(?!\d)", text or ""):
                await self._pair(sender, text, txid, ts)
            else:
                await self._private_reply(sender, now)
            self.save()
            return
        if sender != self.owner:
            self.save()               # remember the txid, nothing else
            return
        self.data["lastInAt"] = ts
        self.store.append_history("in", text, txid, ts)
        self.save()
        await self._dispatch(text)

    async def _pair(self, sender: str, text: str, txid: str, ts: int) -> None:
        log.info("[%s] paired with %s", self.id, sender)
        self.data["owner"] = sender
        self.data["lastInAt"] = ts
        self.data["privateReplies"] = {}
        self.store.append_history("in", text, txid, ts)
        self._start_setup(from_current=False)
        self.save()
        q = self.questions()
        intro = f"Paired! I'm your KaChat {self.TITLE}. "
        if q:
            await self.say(intro + "A few quick questions.\n\n" + self._prompt(0))
        else:
            self._finish_setup()
            await self.say(intro + "All set.")

    async def _private_reply(self, sender: str, now: float) -> None:
        if sender == self.address:
            return
        today = day_key(now)
        replies = {s: d for s, d in self.data.get("privateReplies", {}).items() if d == today}
        self.data["privateReplies"] = replies
        if replies.get(sender) == today or len(replies) >= PRIVATE_REPLIES_PER_DAY:
            return
        replies[sender] = today
        await self.send_to(sender, PRIVATE_REPLY)

    # ── setup ───────────────────────────────────────────────────────────────

    def _start_setup(self, from_current: bool) -> None:
        draft = {}
        for q in self.questions():
            if from_current and q.key in self.settings:
                draft[q.key] = copy.deepcopy(self.settings[q.key])
            elif q.default is not REQUIRED:
                draft[q.key] = copy.deepcopy(q.default)
        self.data["stage"] = "setup"
        self.data["setup"] = {"step": 0, "draft": draft, "editing": from_current}

    def _prompt(self, step: int) -> str:
        qs = self.questions()
        q = qs[step]
        setup = self.data.get("setup") or {}
        draft = setup.get("draft", {})
        hint = ""
        if q.key in draft:
            word = "now" if setup.get("editing") else "default"
            hint = f" ({word}: {q.show(draft[q.key])}; send skip to keep)"
        return f"{step + 1}/{len(qs)}. {q.prompt}{hint}"

    def _finish_setup(self) -> None:
        setup = self.data.get("setup") or {}
        base = self.default_settings()
        base.update(setup.get("draft", {}))
        self.data["settings"] = base
        self.data["stage"] = "active"
        self.data["setup"] = None
        self.on_settings_changed()

    def default_settings(self) -> dict:
        return {}

    async def _answer(self, text: str) -> None:
        setup = self.data.get("setup") or {"step": 0, "draft": {}}
        qs = self.questions()
        step = int(setup.get("step", 0))
        if step >= len(qs):
            self._finish_setup()
            self.save()
            await self.say("All set!\n" + self.describe_settings())
            return
        q = qs[step]
        t = (text or "").strip()
        if t.lower() in SKIP_WORDS:
            if q.key not in setup["draft"]:
                await self.say("This one is needed. " + self._prompt(step))
                return
        else:
            try:
                setup["draft"][q.key] = q.parse(t)
            except AnswerError as exc:
                await self.say(f"{exc} {self._prompt(step)}")
                return
        step += 1
        setup["step"] = step
        self.data["setup"] = setup
        if step >= len(qs):
            self._finish_setup()
            self.save()
            await self.say("All set! " + self.describe_settings() + "\nSend help for commands.")
        else:
            self.save()
            await self.say(self._prompt(step))

    # ── commands ────────────────────────────────────────────────────────────

    def help_text(self) -> str:
        lines = [
            "Commands:",
            "status - what I'm doing",
            "settings - my settings",
            "change - answer the setup questions again",
            "reset - forget my settings and start setup over",
        ]
        if self.ADDRESS_KEY:
            lines.append(f"add - watch another address (up to {MAX_WATCHED})")
        lines += ["pause / resume - stop / restart notifications", "test - send a sample notification", "help - this list"]
        return "\n".join(lines)

    def status_text(self) -> str:
        state = {"active": "Active", "paused": "Paused", "setup": "Setting up"}.get(self.stage, self.stage)
        lines = [f"{state}. {self.summary()}".strip()]
        extra = self.status_extra()
        if extra:
            lines.append(extra)
        lines.append(f"Bot wallet: {fmt_kas(self.balance)}")
        return "\n".join(lines)

    async def _dispatch(self, text: str) -> None:
        cmd = (text or "").strip().lower().lstrip("/").rstrip(".!?")
        in_setup = self.stage == "setup"
        first, _, rest = (text or "").strip().partition(" ")
        # `add` is a short conversation of its own (address, then a nickname on wallet bots).
        if self.data.get("adding"):
            if cmd == "cancel":
                self.data["adding"] = None
                self.save()
                await self.say("Cancelled. Nothing was added.")
                return
            if cmd not in COMMANDS and first.lower().lstrip("/") != "add":
                await self._add_answer(text)
                return
            self.data["adding"] = None           # another command ends it
        if first.lower().lstrip("/") == "add" and not in_setup:
            await self._add_start(rest.strip())
            return
        if cmd not in COMMANDS:
            if in_setup:
                await self._answer(text)
            else:
                await self.say("I didn't get that. Send help for the commands.")
            return
        again = ("\n\n" + self._prompt(int(self.data["setup"]["step"]))) if in_setup else ""
        if cmd == "help":
            await self.say(self.help_text() + again)
        elif cmd == "status":
            await self.say(self.status_text() + again)
        elif cmd == "settings":
            await self.say((self.describe_settings() if self.data.get("settings") else "Not set up yet.") + again)
        elif cmd == "change":
            self._start_setup(from_current=bool(self.data.get("settings")))
            self.save()
            await self.say("Let's update your settings.\n\n" + self._prompt(0))
        elif cmd == "reset":
            # Forget the settings (you stay paired) and ask everything again from the start,
            # with the defaults rather than the old answers. Nothing is watched until set up.
            self.data["settings"] = None
            self.on_reset()
            self.on_settings_changed()
            self._start_setup(from_current=False)
            self.save()
            await self.say("Reset: I've forgotten your settings. Let's set me up again.\n\n" + self._prompt(0))
        elif in_setup:
            await self.say("Let's finish setup first." + again)
        elif cmd == "pause":
            self.data["stage"] = "paused"
            self.save()
            await self.say("Paused. I won't send notifications until you send resume.")
        elif cmd == "resume":
            self.data["stage"] = "active"
            self.save()
            await self.say("Resumed. " + self.summary())
        elif cmd == "test":
            await self.say("Test: " + self.sample_notification())

    # ── add: watch another address ──────────────────────────────────────────

    async def _add_start(self, inline: str) -> None:
        if not self.ADDRESS_KEY:
            await self.say("This bot doesn't watch addresses. Send help for the commands.")
            return
        if len(self.address_list()) >= MAX_WATCHED:
            await self.say(f"I'm already watching {MAX_WATCHED} addresses, the most I can.")
            return
        self.data["adding"] = {"step": "address"}
        self.save()
        if inline:
            await self._add_answer(inline)
        else:
            await self.say("Which address should I add? (paste the kaspa: address, or cancel)")

    async def _add_answer(self, text: str) -> None:
        adding = self.data.get("adding") or {}
        t = (text or "").strip()
        if adding.get("step") == "address":
            try:
                addr = parse_address_answer(self.ctx.network, not_self=self.address)(t)
            except AnswerError as exc:
                await self.say(f"{exc} Paste the kaspa: address to add, or cancel.")
                return
            if addr in self.address_list():
                self.data["adding"] = None
                self.save()
                await self.say("I'm already watching that one.")
                return
            if self.ASKS_NICKNAME:
                self.data["adding"] = {"step": "nickname", "address": addr}
                self.save()
                await self.say("What should I call it? Send a nickname (like Savings), or none.")
                return
            await self._add_finish(addr, None)
            return
        if adding.get("step") == "nickname":
            name = None if t.lower() in ("none", "no", "nothing", "n/a", "skip", "-") else t
            if name and len(name) > 32:
                await self.say("Keep a nickname to 32 characters or fewer. What should I call it?")
                return
            await self._add_finish(adding["address"], name)

    async def _add_finish(self, addr: str, name: Optional[str]) -> None:
        settings = dict(self.settings)
        settings[self.ADDRESS_KEY] = self.address_list() + [addr]
        if name:
            settings["nicknames"] = {**(settings.get("nicknames") or {}), addr: name}
        self.data["settings"] = settings
        self.data["adding"] = None
        self.on_settings_changed()
        self.save()
        n = len(settings[self.ADDRESS_KEY])
        await self.say(f"Added {name or short_address(addr)}. Now watching {n} address{'es' if n != 1 else ''}.")

    # ── status for the panel ────────────────────────────────────────────────

    def funded(self) -> bool:
        from ..send import min_fee
        return self.balance is not None and self.balance >= min_fee(1, 600)

    def panel_summary(self) -> str:
        if not self.enabled:
            return "Disabled"
        if self.balance is not None and not self.funded():
            return f"Fund {short_address(self.address)} to start"
        if self.owner is None:
            return "Waiting for the pairing code in KaChat"
        if self.stage == "setup":
            return "Setting up with its owner in KaChat"
        s = self.summary()
        return ("Paused. " + s) if self.stage == "paused" else s

    def status(self) -> dict:
        err = self.config_error or self.node_error or self.error
        if err is None and self.balance is not None and not self.funded():
            err = "Wallet empty: send a little KAS to the bot address"
        return {
            "id": self.id,
            "type": self.TYPE,
            "address": self.address,
            "balanceSompi": self.balance,
            "funded": self.funded(),
            "stage": self.stage if self.enabled else "disabled",
            "owner": self.owner,
            "settings": self.data.get("settings"),
            "summary": self.panel_summary(),
            "lastInAt": self.data.get("lastInAt"),
            "lastOutAt": self.data.get("lastOutAt"),
            "updatedAt": int(self.ctx.clock()),
            "error": err,
        }


def parse_address_answer(network: str, not_self: Optional[str] = None) -> Callable[[str], str]:
    def parse(text: str) -> str:
        try:
            a = validate_address(text.strip(), network)
        except AddressError as exc:
            raise AnswerError(f"That address doesn't look right: {exc}.")
        if not_self and a == not_self:
            raise AnswerError("That's my own address; please send the address to watch.")
        return a
    return parse


def parse_address_list(network: str, not_self: Optional[str] = None, most: int = MAX_WATCHED) -> Callable[[str], List[str]]:
    """One or more addresses (spaces, commas or semicolons between them), each checked."""
    def parse(text: str) -> List[str]:
        parts = [p for p in (text or "").replace(",", " ").replace(";", " ").split() if p]
        if not parts:
            raise AnswerError("Paste one or more kaspa: addresses.")
        out: List[str] = []
        for p in parts:
            try:
                a = validate_address(p, network)
            except AddressError as exc:
                raise AnswerError(f"{p[:24]}… doesn't look right: {exc}.")
            if not_self and a == not_self:
                raise AnswerError("That's my own address; I can't watch it (every message I send would trigger another).")
            if a not in out:
                out.append(a)
        if len(out) > most:
            raise AnswerError(f"At most {most} addresses, please.")
        return out
    return parse


@dataclass
class Debounce:
    """Small helper: remember when something last ran."""
    every: float
    last: float = field(default=0.0)

    def due(self, now: float) -> bool:
        if now - self.last >= self.every:
            self.last = now
            return True
        return False
