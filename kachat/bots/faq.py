"""Kaspa answers bot: fixed, hand-checked answers to common Kaspa questions, for anyone.

Unlike the other bots it is PUBLIC and has no owner: no pairing code, no setup chat. It is
live as soon as it runs (and is funded), and anyone in KaChat can message it. The answers live
in kachat/faq/kaspa.md (one topic per `##`), and a question gets the topic whose keys it
contains most of. Nothing is generated.

Spending: every reply is a transaction paid from its wallet. There is no limit per person and no
hourly limit, so its wallet balance is the only cap on how much it answers. How it is doing, and the questions it
had no answer for, show in its panel square (status "stats").
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..address import short_address
from .base import NOT_PRIVATE_NOTICE, Bot, Question, day_key, is_agree

FAQ_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "faq", "kaspa.md")
MISSED_MAX = 20
GREETINGS = ("hi", "hello", "hey", "gm", "yo", "start", "menu", "help", "topics", "topic", "list", "?", "test",
             "hiya", "howdy", "sup", "good morning", "good evening", "你好", "您好", "嗨", "哈喽")
SMALL_TALK = ("haha", "hahaha", "lol", "lmao", "funny", "nice", "cool", "great", "wow", "ok", "okay", "k",
              "哈哈", "哈哈哈", "搞笑", "搞笑的", "好的", "不错", "厉害", "😂", "🤣", "😄", "👍")
THANKS = ("thanks", "thank you", "thx", "ty", "cheers", "谢谢", "多谢", "感谢")
SMALL_TALK_REPLY = "Ask me anything about Kaspa, or send topics to see what I know."
THANKS_REPLY = "You're welcome! Ask me anything else about Kaspa."
# Every answer is in English: someone writing in another script is told so (in Chinese too,
# the language people have asked in so far).
ENGLISH_ONLY_REPLY = ("I can only answer in English for now. 我目前只能用英文回答，请用英文提问。"
                      "Send topics to see what I can answer.")


@dataclass
class Topic:
    title: str
    keys: List[str]
    answer: str
    live: Optional[str] = None       # "market": the answer is a template filled with live market data
    fallback: str = ""               # sent instead when live data is unavailable
    ask: List[str] = field(default_factory=list)   # a follow-up question: the titles to choose from


def fmt_usd(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:,.2f} billion"
    if v >= 1e6:
        return f"${v / 1e6:,.2f} million"
    if v >= 1:
        return f"${v:,.2f}"
    return f"${v:.4f}".rstrip("0").rstrip(".") if v >= 0.0001 else f"${v:.8f}"


def fmt_kas_big(v: float) -> str:
    return f"{v / 1e9:,.2f} billion" if v >= 1e9 else f"{v:,.0f}"


def fill_live(template: str, m: dict) -> str:
    """An answer template with {price} {marketcap} {circulating} {max} {fdv} {change}."""
    ch = m.get("change24h")
    change = "" if ch is None else f" ({'+' if ch >= 0 else ''}{ch:.1f}% in 24 h)"
    return template.format(price=fmt_usd(m["price"]), marketcap=fmt_usd(m["marketcap"]),
                           circulating=fmt_kas_big(m["circulating"]), max=fmt_kas_big(m["max"]),
                           fdv=fmt_usd(m["price"] * m["max"]), change=change)


def _norm(text: str) -> str:
    """Lowercase words with punctuation dropped and a plural 's' trimmed, space-padded."""
    words = re.sub(r"[^a-z0-9.]+", " ", (text or "").lower().replace("-", "")).split()
    words = [w.strip(".") for w in words]
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words if w]
    return " " + " ".join(words) + " "


def load_topics(path: str = FAQ_FILE) -> List[Topic]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    topics: List[Topic] = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = block.strip().splitlines()
        title = lines[0].strip()
        keys: List[str] = []
        body: List[str] = []
        live, fallback, ask = None, "", []
        for line in lines[1:]:
            low = line.lower()
            if low.startswith("ask:") and not body:
                ask = [a.strip() for a in line[4:].split("|") if a.strip()]
                continue
            if low.startswith("keys:") and not body:
                keys = [k.strip() for k in line[5:].split(",") if k.strip()]
            elif low.startswith("live:") and not body:
                live = line[5:].strip()
            elif low.startswith("fallback:"):
                fallback = line[9:].strip()
            else:
                body.append(line)
        answer = "\n".join(body).strip()
        if title and answer:
            topics.append(Topic(title, keys, answer, live, fallback, ask))
    return topics


def best_topic(topics: List[Topic], question: str) -> Optional[Topic]:
    q = _norm(question)
    best: Tuple[int, Optional[Topic]] = (0, None)
    for t in topics:
        score = 0
        for nk in {_norm(k) for k in t.keys + [t.title]}:    # a title that repeats a key counts once
            if nk.strip() and nk in q:
                score += len(nk.strip())
        if score > best[0]:
            best = (score, t)
    return best[1]


class FaqBot(Bot):
    TYPE = "faq"
    TITLE = "Kaspa answers bot"
    PUBLIC = True
    HOURLY_LIMIT = False          # anyone may ask, as often as they like: the wallet is the limit
    PAIRS = False                 # public: no owner, live from the start

    def __init__(self, *a, **kw):
        self.topics = load_topics()
        self.by_title = {t.title: t for t in self.topics}
        super().__init__(*a, **kw)
        self.data.setdefault("askers", {"day": "", "counts": {}})
        self.data.setdefault("answered", 0)
        self.data.setdefault("missed", [])
        self._go_live()

    def _go_live(self) -> None:
        self.data.update({"owner": None, "stage": "active", "setup": None, "greetPending": False,
                          "settings": self.data.get("settings") or self.default_settings()})

    def reset_owner(self) -> None:
        super().reset_owner()
        self._go_live()

    def apply_config(self, cfg, initial: bool = False) -> None:
        super().apply_config(cfg, initial)
        # The panel's Reset: start the counts and the missed list over (there are no answers to forget).
        rs = getattr(cfg, "reset_settings", None)
        if rs and rs != self.data.get("faqResetSeen"):
            self.data.update({"faqResetSeen": rs, "askers": {"day": "", "counts": {}}, "answered": 0, "missed": [],
                              "agreed": {}})
        self._go_live()
        self.save()

    def default_settings(self) -> dict:
        return {}

    def questions(self) -> List[Question]:
        return []

    def describe_settings(self) -> str:
        return "No settings: it answers anyone, as often as they ask."

    def summary(self) -> str:
        return "Answering Kaspa questions for anyone"

    def panel_summary(self) -> str:
        if not self.enabled:
            return "Disabled"
        if self.balance is not None and not self.funded():
            return f"Fund {short_address(self.address)} to start"
        return self.summary()

    def status(self) -> dict:
        st = super().status()
        st["stats"] = {
            "answered": int(self.data.get("answered", 0)),
            "peopleToday": len(self._today()["counts"]),
            "missed": list(self.data.get("missed", []))[-10:],
        }
        return st

    # ── answering ───────────────────────────────────────────────────────────

    def topics_text(self) -> str:
        lines = ["I answer common Kaspa questions. Ask in your own words, or send a number:"]
        lines += [f"{i}. {t.title}" for i, t in enumerate(self.topics, 1)]
        return "\n".join(lines)

    def reply_for(self, text: str) -> Tuple[str, bool]:
        """The reply to one message, and whether it was an answer (False = no match)."""
        reply, matched, _ = self._match(text)
        return reply, matched

    def ask_text(self, topic: Topic) -> str:
        lines = [topic.answer] + [f"{i}. {t}" for i, t in enumerate(topic.ask, 1)]
        return "\n".join(lines + ["Reply with a number."])

    def _choice(self, asked: List[str], text: str) -> Optional[Topic]:
        """The option a reply to a follow-up question picks: its number, or words from its title."""
        bare = (text or "").strip().lower().rstrip(".!?")
        options = [self.by_title[t] for t in asked if t in self.by_title]
        if bare.isdigit() and 1 <= int(bare) <= len(options):
            return options[int(bare) - 1]
        return best_topic(options, text) if options else None

    async def answer(self, text: str, who: Optional[str] = None) -> Tuple[str, bool]:
        """reply_for, with live topics (price, market cap) filled in from current market data, and
        follow-up questions (`ask:`): the question goes out, and `who`'s next reply picks an option."""
        pending = self.data.setdefault("asked", {})
        asked = pending.pop(who, None) if who else None
        topic = self._choice(asked, text) if asked else None
        if topic is not None:
            reply, matched = topic.answer, True
        else:
            reply, matched, topic = self._match(text)
        if topic is not None and topic.ask:
            if who:
                pending[who] = topic.ask
                if len(pending) > 1000:
                    pending.pop(next(iter(pending)))
            return self.ask_text(topic), True
        if topic is not None and topic.live == "market":
            m = await self.ctx.fetch_market() if self.ctx.fetch_market else None
            try:
                return (fill_live(topic.answer, m) if m else topic.fallback or topic.answer), True
            except (KeyError, TypeError, ValueError):
                return topic.fallback or topic.answer, True
        return reply, matched

    def _match(self, text: str) -> Tuple[str, bool, Optional[Topic]]:
        t = (text or "").strip()
        bare = t.lower().lstrip("/").strip().rstrip(".!?？！。～~").strip()
        if bare in GREETINGS or not bare:
            return self.topics_text(), True, None
        if bare in THANKS:
            return THANKS_REPLY, True, None
        if bare in SMALL_TALK:
            return SMALL_TALK_REPLY, True, None
        if bare.isdigit():
            n = int(bare)
            if 1 <= n <= len(self.topics):
                return self.topics[n - 1].answer, True, self.topics[n - 1]
            return f"Pick a number from 1 to {len(self.topics)}, or send topics.", True, None
        topic = best_topic(self.topics, t)
        if topic:
            return topic.answer, True, topic
        if not re.search(r"[a-z]", bare):
            return ENGLISH_ONLY_REPLY, False, None       # still listed as missed, so you see what people ask
        # "Hello, test." and the like: a greeting with nothing to answer.
        words = re.sub(r"[^a-z ]+", " ", bare).split()
        if words and (words[0] in GREETINGS or " ".join(words[:2]) in GREETINGS) and len(words) <= 4:
            return self.topics_text(), True, None
        return "I don't have an answer for that one yet. Send topics to see what I can answer.", False, None

    def _today(self) -> dict:
        today = day_key(self.ctx.clock())
        askers = self.data.get("askers") or {}
        if askers.get("day") != today:
            askers = {"day": today, "counts": {}}
            self.data["askers"] = askers
        return askers

    def _note_missed(self, text: str) -> None:
        missed = [m for m in self.data.get("missed", []) if m != text[:120]]
        self.data["missed"] = (missed + [text[:120]])[-MISSED_MAX:]

    async def _reply(self, recipient: str, text: str) -> None:
        reply, matched = await self.answer(text, who=recipient)
        if not matched:
            self._note_missed((text or "").strip())
        if await self.send_to(recipient, reply):
            self.data["answered"] = int(self.data.get("answered", 0)) + 1
        self.save()

    async def public_message(self, sender: str, text: str, now: float) -> None:
        counts = self._today()["counts"]
        n = counts.get(sender, 0) + 1
        counts[sender] = n                      # only for the panel's "people today"
        agreed = self.data.setdefault("agreed", {})
        if sender not in agreed:
            # Nobody gets answers before agreeing that their messages are not private.
            if is_agree(text):
                agreed[sender] = int(now)
                await self.send_to(sender, "Thanks! " + self.topics_text())
            else:
                await self.send_to(sender, NOT_PRIVATE_NOTICE)
        else:
            await self._reply(sender, text)
        self.save()
