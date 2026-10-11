"""Kaspa answers bot: fixed answers, public, a daily cap per person."""
import pytest
from conftest import OTHER_KEY, USER_KEY, addr, make_cfg, run

from kachat.bots.faq import best_topic, load_topics
from test_engine import paired, say, texts

USER = addr(USER_KEY)
OTHER = addr(OTHER_KEY)
THIRD = addr("66" * 32)

TOPICS = load_topics()
BY_TITLE = {t.title: t for t in TOPICS}


def test_the_answers_file_loads():
    assert len(TOPICS) >= 40
    assert len({t.title for t in TOPICS}) == len(TOPICS)
    for t in TOPICS:
        assert t.keys, t.title
        assert len(t.answer) <= 600, t.title          # each reply is a transaction: keep it short


@pytest.mark.parametrize("question,title", [
    ("What is Kaspa?", "What is Kaspa"),
    ("what's the max supply of kas", "Max supply"),
    ("When is the next halving?", "Emission and halving"),
    ("how many blocks per second does it do", "Blocks per second"),
    ("Can I stake KAS?", "Staking"),
    ("is there a premine", "Fair launch"),
    ("which wallet should I use", "Wallets"),
    ("someone asked for my seed phrase", "Seed phrase safety"),
    ("What is GHOSTDAG", "GHOSTDAG"),
    ("can I mine with my GPU", "GPU mining"),
    ("Does Kaspa have smart contracts?", "Smart contracts"),
    ("what are KRC-20 tokens", "KRC-20 tokens"),
    ("what ports does a node use", "Node ports"),
    ("Is kaspa a good investment", "Price"),
    ("what is DAGKnight", "DAGKnight"),
    ("what's a sompi", "Sompi"),
])
def test_questions_find_their_topic(question, title):
    assert best_topic(TOPICS, question).title == title


def test_nonsense_finds_nothing():
    assert best_topic(TOPICS, "zzzz qqqq") is None


def test_every_title_finds_itself():
    for t in TOPICS:
        assert best_topic(TOPICS, t.title) is t, t.title


def test_anyone_gets_answers_once_set_up(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "faq", ["skip"])
    say(bot, "what is the max supply?", OTHER)
    assert texts(ctxf, OTHER) == [BY_TITLE["Max supply"].answer]
    say(bot, "hi", OTHER)
    assert texts(ctxf, OTHER)[-1].startswith("I answer common Kaspa questions")
    say(bot, "5", OTHER)
    assert texts(ctxf, OTHER)[-1] == TOPICS[4].answer


def test_strangers_are_turned_away_before_pairing(make_bot, ctxf):
    bot = make_bot("faq")
    say(bot, "what is kaspa", OTHER)
    assert texts(ctxf, OTHER) == ["This bot is private."]


def test_paused_bot_does_not_answer_strangers(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "faq", ["skip"])
    say(bot, "pause")
    say(bot, "what is kaspa", OTHER)
    assert texts(ctxf, OTHER) == []


def test_daily_cap_per_person(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "faq", ["3"])
    for _ in range(6):
        say(bot, "what is kaspa", OTHER)
    got = texts(ctxf, OTHER)
    assert len(got) == 4 and got[-1].startswith("That's all my answers for you today (3)")
    say(bot, "what is kaspa", THIRD)                     # someone else still gets one
    assert len(texts(ctxf, THIRD)) == 1
    ctxf.clock.t += 86400
    say(bot, "what is kaspa", OTHER)
    assert len(texts(ctxf, OTHER)) == 5


def test_owner_asks_too_and_sees_missed_questions(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "faq", ["skip"])
    say(bot, "what is the max supply")
    assert texts(ctxf)[-1] == BY_TITLE["Max supply"].answer
    say(bot, "flibbertigibbet", OTHER)
    say(bot, "missed")
    assert "flibbertigibbet" in texts(ctxf)[-1]
    say(bot, "help")
    assert "topics" in texts(ctxf)[-1]


def test_strangers_hitting_the_hourly_limit_tell_the_owner(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "faq", ["skip"], max_out=5)
    ctxf.clock.t += 3601
    for i in range(7):
        say(bot, "what is kaspa", addr(f"{70 + i:02x}" * 32))
    asks = [t for t in texts(ctxf) if "reached my limit" in t]
    assert len(asks) == 1
    say(bot, "yes")
    assert texts(ctxf)[-1] == "Limit reset. I'll keep sending."
