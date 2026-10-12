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
from dataclasses import dataclass
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
        for line in lines[1:]:
            if line.lower().startswith("keys:") and not body:
                keys = [k.strip() for k in line[5:].split(",") if k.strip()]
            else:
                body.append(line)
        answer = "\n".join(body).strip()
        if title and answer:
            topics.append(Topic(title, keys, answer))
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
        t = (text or "").strip()
        bare = t.lower().lstrip("/").strip().rstrip(".!?？！。～~").strip()
        if bare in GREETINGS or not bare:
            return self.topics_text(), True
        if bare in THANKS:
            return THANKS_REPLY, True
        if bare in SMALL_TALK:
            return SMALL_TALK_REPLY, True
        if bare.isdigit():
            n = int(bare)
            if 1 <= n <= len(self.topics):
                return self.topics[n - 1].answer, True
            return f"Pick a number from 1 to {len(self.topics)}, or send topics.", True
        topic = best_topic(self.topics, t)
        if topic:
            return topic.answer, True
        if not re.search(r"[a-z]", bare):
            return ENGLISH_ONLY_REPLY, False       # still listed as missed, so you see what people ask
        # "Hello, test." and the like: a greeting with nothing to answer.
        words = re.sub(r"[^a-z ]+", " ", bare).split()
        if words and (words[0] in GREETINGS or " ".join(words[:2]) in GREETINGS) and len(words) <= 4:
            return self.topics_text(), True
        return "I don't have an answer for that one yet. Send topics to see what I can answer.", False

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
        reply, matched = self.reply_for(text)
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
