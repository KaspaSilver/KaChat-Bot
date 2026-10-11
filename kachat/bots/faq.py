"""Kaspa answers bot: fixed, hand-checked answers to common Kaspa questions, for anyone.

Unlike the other bots it is PUBLIC: once its owner has paired and set it up, anyone in
KaChat can message it. The answers live in kachat/faq/kaspa.md (one topic per `##`), and a
question gets the topic whose keys it contains most of. Nothing is generated.

Spending: every reply is a transaction, so each person gets at most `perPersonPerDay`
answers a day (then one "that's all for today" note). Unlike the other bots it has no hourly
limit: anyone may ask, so its wallet is the only cap on how many people it answers. The owner talks to it like any bot (commands) and can ask questions too, without a cap.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .base import Bot, Question, day_key, parse_number

FAQ_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "faq", "kaspa.md")
MISSED_MAX = 20
GREETINGS = ("hi", "hello", "hey", "gm", "yo", "start", "menu", "help", "topics", "topic", "list", "?")


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
        for k in t.keys + [t.title]:
            nk = _norm(k)
            if nk.strip() and nk in q:
                score += len(nk.strip())
        if score > best[0]:
            best = (score, t)
    return best[1]


class FaqBot(Bot):
    TYPE = "faq"
    TITLE = "Kaspa answers bot"
    PUBLIC = True
    HOURLY_LIMIT = False          # anyone may ask; the per-person daily cap is the limit

    def __init__(self, *a, **kw):
        self.topics = load_topics()
        super().__init__(*a, **kw)
        self.data.setdefault("askers", {"day": "", "counts": {}})
        self.data.setdefault("answered", 0)
        self.data.setdefault("missed", [])

    def default_settings(self) -> dict:
        return {"perPersonPerDay": 10}

    def questions(self) -> List[Question]:
        def parse_cap(t: str) -> int:
            return int(parse_number(t, minimum=1, maximum=100, what="a number of answers"))
        return [Question("perPersonPerDay",
                         "How many answers may one person get per day? Every answer costs me a tiny fee.",
                         parse_cap, default=10)]

    def describe_settings(self) -> str:
        return f"Answers per person per day: {self.settings.get('perPersonPerDay', 10)}"

    def summary(self) -> str:
        return f"Answering Kaspa questions for anyone ({self.settings.get('perPersonPerDay', 10)} a day each)"

    def status_extra(self) -> str:
        counts = self._today()["counts"]
        return f"Today: {len(counts)} people asked. Answers so far: {self.data.get('answered', 0)}."

    def sample_notification(self) -> str:
        return self.topics[0].answer if self.topics else "No answers loaded."

    def help_text(self) -> str:
        return (super().help_text() + "\ntopics - what I can answer\nmissed - recent questions I had no answer for"
                "\nAnything else is taken as a Kaspa question.")

    # ── answering ───────────────────────────────────────────────────────────

    def topics_text(self) -> str:
        lines = ["I answer common Kaspa questions. Ask in your own words, or send a number:"]
        lines += [f"{i}. {t.title}" for i, t in enumerate(self.topics, 1)]
        return "\n".join(lines)

    def reply_for(self, text: str) -> Tuple[str, bool]:
        """The reply to one message, and whether it was an answer (False = no match)."""
        t = (text or "").strip()
        bare = t.lower().lstrip("/").rstrip(".!?").strip()
        if bare in GREETINGS or not bare:
            return self.topics_text(), True
        if bare.isdigit():
            n = int(bare)
            if 1 <= n <= len(self.topics):
                return self.topics[n - 1].answer, True
            return f"Pick a number from 1 to {len(self.topics)}, or send topics.", True
        topic = best_topic(self.topics, t)
        if topic:
            return topic.answer, True
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
        counts[sender] = n
        cap = int(self.settings.get("perPersonPerDay", 10))
        if n <= cap:
            await self._reply(sender, text)
        elif n == cap + 1:
            await self.send_to(sender, f"That's all my answers for you today ({cap}). Ask me again tomorrow!")
        self.save()

    async def on_free_text(self, text: str) -> None:
        bare = (text or "").strip().lower().lstrip("/").rstrip(".!?")
        if bare == "missed":
            missed = self.data.get("missed", [])
            await self.say("Recent questions I had no answer for:\n" + "\n".join(f"- {m}" for m in missed[-10:])
                           if missed else "No unanswered questions yet.")
            return
        await self._reply(self.owner, text)
