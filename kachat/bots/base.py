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
  - after pairing, anyone but the owner is ignored: no reply, no spend, except on a PUBLIC
    bot (the Kaspa answers bot), which answers anyone while active, a few times a day each
"""
from __future__ import annotations

import collections
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
DEFAULT_MAX_OUT_PER_HOUR = 50
REQUIRED = object()

# Bots are public and whoever runs one can read what it receives (its history), so nobody uses a
# bot before agreeing to that. Sent first to everyone, again until they agree.
NOT_PRIVATE_NOTICE = ("Before we start: messages you send to this bot are not private. They are encrypted on "
                      "the way, but whoever runs this bot can read them. Reply agree to continue.")
AGREE_WORDS = ("agree", "i agree", "yes", "y", "ok", "okay", "accept", "i accept", "agreed")


def is_agree(text: str) -> bool:
    return (text or "").strip().lower().strip(".!").strip() in AGREE_WORDS


YES_NO = {"yes": True, "y": True, "yeah": True, "ok": True, "no": False, "n": False, "nope": False}
COMMANDS = ("help", "status", "settings", "change", "reset", "add", "pause", "resume", "test")
MAX_WATCHED = 10                 # addresses one mining or wallet bot may watch
# Too busy to watch: more than `count` new payments within `seconds` and the address is dropped,
# with a message asking for a quieter one. Kaspa makes 864,000 blocks a day (600 a minute), so 100
# rewards in 10 minutes is about 1.7% of every block: a pool's address, never a home miner's. Only
# new payments count, each once (see too_busy).
BUSY_LIMITS = ((60, 20), (600, 100))
BUSY_SEEN_MAX = 5000
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
    fetch_market: Optional[Callable] = None     # async () -> feeds.fetch_market() dict | None
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
            # A reset starts the hourly message budget over, so its greeting always goes out.
            self._clear_rate_limit()
        self.save()

    async def send_pending_greeting(self) -> None:
        """After a panel Reset: the first setup message again, to the owner."""
        if not self.data.get("greetPending") or not self.data.get("owner"):
            return
        q = self.questions()
        intro = f"Hi again! I'm your KaChat {self.TITLE}, and my settings were just reset. "
        if q:
            txid = await self.say(intro + "A few quick questions.\n\n" + self._prompt(0))
        else:
            self._finish_setup()
            txid = await self.say(intro + "All set.")
        # Kept until it really went out (wallet empty, node down, ...): tried again next tick.
        if txid:
            self.data["greetPending"] = False
        self.save()

    def _clear_rate_limit(self) -> None:
        self.data["outTimes"] = []
        self.data["limitAsked"] = False
        self.data["limitQuestion"] = False
        if self.error and self.error.startswith("Rate limit"):
            self.error = None

    def reset_owner(self) -> None:
        self.data.update({"owner": None, "settings": None, "stage": "awaiting_pairing",
                          "setup": None, "privateReplies": {}})
        self._clear_rate_limit()
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

    # A public bot also answers people other than its owner (public_message).
    PUBLIC = False

    # ── low balance: ask the people who use it to chip in ──────────────────
    LOW_BALANCE_SOMPI = 50_000_000         # 0.5 KAS: below this, tell its people (once)
    REARM_BALANCE_SOMPI = 100_000_000      # 1 KAS: back above this, it may ask again later
    CONTRIBUTE_SOMPI = 500_000_000         # the payment request asks for 5 KAS
    LOW_BALANCE_RECIPIENTS = 50            # the most recent people it tells
    LOW_BALANCE_RECENT = 30 * 86400        # people who used it within 30 days

    def low_balance_people(self, now: float) -> List[str]:
        """Who to tell its balance is low: (override) the people who use it, most recent first."""
        return [self.owner] if self.owner else []

    def low_balance_text(self) -> str:
        from ..payreq import payment_request_link
        link = payment_request_link(self.address, self.CONTRIBUTE_SOMPI, f"Keep the KaChat {self.TITLE} running",
                                    self.priv_hex)
        return (f"My wallet balance is low ({fmt_kas(self.balance)} left), and every message I send is paid from it. "
                f"If you'd like to contribute to keep me running, tap here to send KAS:\n{link}")

    async def send_low_balance_notice(self, recipient: str, text: str) -> Optional[str]:
        return await self.send_to(recipient, text)

    async def check_low_balance(self, now: float) -> None:
        """Once each time its balance falls below 0.5 KAS: a message with a KaChat payment request
        link (tap it and Send Kaspa opens, filled in) to the people who use it."""
        state = self.data.setdefault("lowBalance", {"armed": True})
        bal = self.balance
        if bal is None:
            return
        if bal >= self.REARM_BALANCE_SOMPI:
            if not state.get("armed"):
                state["armed"] = True
                self.save()
            return
        if not state.get("armed") or bal >= self.LOW_BALANCE_SOMPI or bal <= 0:
            return
        people = self.low_balance_people(now)[: self.LOW_BALANCE_RECIPIENTS]
        state.update(armed=False, sentAt=int(now), told=len(people))
        self.save()
        if not people:
            return
        log.info("[%s] balance low (%s): telling %d people", self.id, fmt_kas(bal), len(people))
        text = self.low_balance_text()
        for who in people:
            await self.send_low_balance_notice(who, text)
    # The hourly message limit (max_out_per_hour). The Kaspa answers bot turns it off: anyone may
    # ask it, and it caps each person per day instead.
    HOURLY_LIMIT = True
    # False: nobody pairs with it and it has no owner (the Kaspa answers bot). It is live as soon
    # as it runs, and its history logs every conversation, each line naming the other side.
    PAIRS = True
    # Messages one person may get per day (a public bot's people); None = no daily cap.
    daily_cap: Optional[int] = None

    def known_senders(self) -> set:
        """Who may be writing to it outside the inbox (the indexer backfill looks them up)."""
        return {self.owner} if self.owner else set()

    async def public_message(self, sender: str, text: str, now: float) -> None:
        pass

    async def on_free_text(self, text: str) -> None:
        """The owner sent something that is not a command."""
        await self.say("I didn't get that. Send help for the commands.")

    # Address-watching bots (mining, wallet) set ADDRESS_KEY and get the `add` command.
    ADDRESS_KEY: Optional[str] = None
    ASKS_NICKNAME = False

    def address_list(self) -> List[str]:
        return list(self.settings.get(self.ADDRESS_KEY) or []) if self.ADDRESS_KEY else []

    async def tick(self, now: float) -> None:
        pass

    async def on_utxos(self, address: str, added: list, removed: list) -> None:
        pass

    async def too_busy(self, address: str, added: list, removed: list) -> bool:
        """Counts a watched address's activity; when it is far too busy to message about (a mining
        pool, an exchange), stops watching it, tells the person, and returns True."""
        if address not in self.address_list():
            return False
        now = self.ctx.clock()
        # Each new payment once: at 10 blocks a second the node often removes and re-adds the same
        # coin as the chain tip settles, and spends from the address are not payments at all.
        counted = getattr(self, "_busy_counted", None)
        if counted is None:
            counted = self._busy_counted = collections.OrderedDict()
        events = 0
        for e in self.busy_events(added):
            key = f"{e.get('txid')}:{e.get('index')}"
            if key in counted:
                continue
            counted[key] = True
            events += 1
        while len(counted) > BUSY_SEEN_MAX:
            counted.popitem(last=False)
        if not events:
            return False
        longest = max(w for w, _ in BUSY_LIMITS)
        act = self.data.setdefault("activity", {})
        times = [t for t in act.get(address, []) if now - t < longest] + [now] * events
        busy = next(((w, n) for w, n in BUSY_LIMITS if sum(1 for t in times if now - t < w) > n), None)
        if busy is None:
            act[address] = times[-(max(n for _, n in BUSY_LIMITS) + 1):]
            self.data["activity"] = act
            return False
        act.pop(address, None)
        name = (self.settings.get("nicknames") or {}).get(address) or short_address(address)
        log.info("[%s] %s is too busy (%d payments in %d s): no longer watched", self.id, address, len(times), busy[0])
        left = self.remove_watched(address)
        window = "a minute" if busy[0] <= 60 else f"{busy[0] // 60} minutes"
        text = (f"I stopped watching {name}: it gets too much activity (more than {busy[1]} payments in {window}), "
                "far more than I can message you about. Please choose an address that does not have this much activity.")
        if left:
            text += " Send add to watch another."
        else:
            text += "\n\n" + self._prompt(0)
        await self.say(text)
        self.save()
        return True

    def busy_events(self, added: list) -> list:
        """The payments that count toward too_busy: every new coin (a mining bot: rewards only)."""
        return list(added)

    def remove_watched(self, address: str) -> int:
        """Stops watching one address; how many are left. None left: setup starts over."""
        settings = dict(self.settings)
        remaining = [a for a in self.address_list() if a != address]
        settings[self.ADDRESS_KEY] = remaining
        settings.pop("address", None)                    # the mining bot's old single address
        if settings.get("nicknames"):
            settings["nicknames"] = {a: n for a, n in settings["nicknames"].items() if a != address}
        buffered = getattr(self, "_buffer", None)        # a wallet bot's not-yet-sent changes
        if buffered:
            self._buffer = [b for b in buffered if b[1] != address]
        if remaining:
            self.data["settings"] = settings
            self.on_settings_changed()
        else:
            self.data["settings"] = None
            self.on_reset()
            self.on_settings_changed()
            self._start_setup(from_current=False)
        return len(remaining)

    # ── sending ─────────────────────────────────────────────────────────────

    def _out_budget_left(self, now: float) -> int:
        times = [t for t in self.data.get("outTimes", []) if now - t < 3600]
        self.data["outTimes"] = times
        left = self.ctx.max_out_per_hour - len(times)
        # The hour has moved on: the warning and the question are not true any more.
        if left > 0:
            if self.error and self.error.startswith("Rate limit"):
                self.error = None
            self.data["limitAsked"] = False
            self.data["limitQuestion"] = False
        return left

    def limit_text(self) -> str:
        return (f"I've reached my limit of {self.ctx.max_out_per_hour} messages within an hour, so I've stopped sending.\n"
                "Reset the limit and keep sending? Reply yes or no.")

    async def _ask_about_limit(self) -> None:
        """Once per full hour: tell the owner the limit was reached and ask whether to reset it."""
        if not self.owner or self.data.get("limitAsked"):
            return
        self.data["limitAsked"] = True
        if await self.send_to(self.owner, self.limit_text(), force=True):
            self.data["limitQuestion"] = True
        self.save()

    async def _answer_limit(self, cmd: str) -> bool:
        """The owner's yes/no to the limit question; True when it was one."""
        if not self.data.get("limitQuestion") or cmd not in YES_NO:
            return False
        self.data["limitQuestion"] = False
        if YES_NO[cmd]:
            self._clear_rate_limit()
            self.data["limitAsked"] = False
            self.save()
            await self.say("Limit reset. I'll keep sending.")
        else:
            self.save()
            await self.send_to(self.owner, "OK. I'll wait until the hour has passed, then send again.", force=True)
        return True

    async def send_to(self, recipient: str, text: str, force: bool = False) -> Optional[str]:
        """Sends one message if the rate limit allows; returns the txid or None.
        `force` is only for the limit question and its answer (at most two a full hour)."""
        if not self.enabled:
            return None
        now = self.ctx.clock()
        if not force and self.HOURLY_LIMIT and self._out_budget_left(now) <= 0:
            self.error = f"Rate limit: {self.ctx.max_out_per_hour} messages in the last hour; holding back"
            log.warning("[%s] %s", self.id, self.error)
            self.save()
            await self._ask_about_limit()       # always the owner, whoever this was for
            return None
        if not force and self.daily_cap:
            day = day_key(now)
            d = self.data.get("dayOut") or {}
            if d.get("day") != day:
                d = {"day": day, "n": 0, "noted": False}
            self.data["dayOut"] = d
            if d["n"] >= self.daily_cap:
                if not d["noted"]:
                    d["noted"] = True
                    await self.send_to(recipient, f"That's my limit of {self.daily_cap} messages for you today. "
                                                  "I'll pick up again tomorrow.", force=True)
                self.save()
                return None
            d["n"] += 1
        if not force:
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
        elif not self.PAIRS:
            self.store.append_history("out", f"To {short_address(recipient)}: {text}", txid, int(now))
        self.data["lastOutAt"] = int(now)
        if self.error and (self.error.startswith("Could not send") or (not force and self.error.startswith("Rate limit"))):
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
        if not self.PAIRS:
            # No owner, no pairing: everyone is just someone asking.
            if self.stage == "active" and sender != self.address:
                self.data["lastInAt"] = ts
                self.store.append_history("in", f"{short_address(sender)}: {text}", txid, ts)
                await self.public_message(sender, text, now)
            self.save()
            return
        if self.owner is None:
            if re.search(rf"(?<!\d){re.escape(self.cfg.pairing_code)}(?!\d)", text or ""):
                await self._pair(sender, text, txid, ts)
            else:
                await self._private_reply(sender, now)
            self.save()
            return
        if sender != self.owner:
            if self.PUBLIC and self.stage == "active" and sender != self.address:
                await self.public_message(sender, text, now)
            self.save()               # remember the txid, nothing else
            return
        self.data["lastInAt"] = ts
        self.store.append_history("in", text, txid, ts)
        self.save()
        await self._dispatch(text)

    async def _pair(self, sender: str, text: str, txid: str, ts: int, intro: Optional[str] = None) -> None:
        log.info("[%s] paired with %s", self.id, sender)
        self.data["owner"] = sender
        self.data["lastInAt"] = ts
        self.data["privateReplies"] = {}
        self.store.append_history("in", text, txid, ts)
        self._start_setup(from_current=False)
        self.save()
        q = self.questions()
        intro = intro or f"Paired! I'm your KaChat {self.TITLE}. "
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
        if await self._answer_limit(cmd):
            return
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
                await self.on_free_text(text)
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
        self._out_budget_left(self.ctx.clock())       # drops a rate-limit warning that has expired
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
