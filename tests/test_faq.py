"""Kaspa answers bot: fixed answers, public, a daily cap per person."""
import pytest
from conftest import OTHER_KEY, USER_KEY, addr, make_cfg

from kachat.bots.base import NOT_PRIVATE_NOTICE
from kachat.bots.faq import best_topic, load_topics
from test_engine import say, texts

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


def live(make_bot, ctxf, **kw):
    bot = make_bot("faq", **kw)
    ctxf.sent.clear()
    return bot


def agreed(bot, ctxf, *who):
    for w in who:
        say(bot, "agree", w)
    ctxf.sent.clear()
    bot.data["askers"] = {"day": "", "counts": {}}       # the agreeing does not count here


def test_answers_only_after_agreeing_messages_are_not_private(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    say(bot, "what is the max supply?", OTHER)
    assert texts(ctxf, OTHER) == [NOT_PRIVATE_NOTICE]
    say(bot, "agree", OTHER)
    assert texts(ctxf, OTHER)[-1].startswith("Thanks! I answer common Kaspa questions")
    say(bot, "what is the max supply?", OTHER)
    assert texts(ctxf, OTHER)[-1] == BY_TITLE["Max supply"].answer


def test_live_from_the_start_with_no_owner(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    assert bot.stage == "active" and bot.owner is None
    st = bot.status()
    assert st["stage"] == "active" and st["stats"] == {"answered": 0, "peopleToday": 0, "missed": []}
    assert "Waiting" not in st["summary"] and "pairing" not in st["summary"].lower()


def test_anyone_gets_answers(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    agreed(bot, ctxf, OTHER)
    say(bot, "what is the max supply?", OTHER)
    assert texts(ctxf, OTHER) == [BY_TITLE["Max supply"].answer]
    say(bot, "hi", OTHER)
    assert texts(ctxf, OTHER)[-1].startswith("I answer common Kaspa questions")
    say(bot, "5", OTHER)
    assert texts(ctxf, OTHER)[-1] == TOPICS[4].answer
    assert bot.status()["stats"]["answered"] == 3


def test_the_pairing_code_is_just_a_question(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    say(bot, "482915", USER)
    assert bot.owner is None and bot.stage == "active"
    assert texts(ctxf, USER) == [NOT_PRIVATE_NOTICE]


def test_switched_off_answers_nobody(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    bot.apply_config(make_cfg("faq", enabled=False))
    say(bot, "what is kaspa", OTHER)
    assert texts(ctxf, OTHER) == []


def test_no_limit_per_person(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    agreed(bot, ctxf, OTHER)
    for _ in range(60):
        say(bot, "what is kaspa", OTHER)
    got = texts(ctxf, OTHER)
    assert len(got) == 60 and all(t == BY_TITLE["What is Kaspa"].answer for t in got)


def test_people_today_still_counted_for_the_panel(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    say(bot, "hi", OTHER)
    say(bot, "hi", THIRD)
    assert bot.status()["stats"]["peopleToday"] == 2


def test_missed_questions_and_history_show_in_the_panel(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    agreed(bot, ctxf, OTHER)
    bot.store.history.clear()
    say(bot, "flibbertigibbet", OTHER)
    assert bot.status()["stats"]["missed"] == ["flibbertigibbet"]
    lines = [(h["dir"], h["text"]) for h in bot.store.history]
    assert lines[0][0] == "in" and lines[0][1].endswith(": flibbertigibbet")
    assert lines[1][0] == "out" and lines[1][1].startswith("To ")


def test_panel_reset_starts_the_counts_over_and_new_owner_changes_nothing(make_bot, ctxf):
    bot = live(make_bot, ctxf)
    say(bot, "zzz", OTHER)
    bot.apply_config(make_cfg("faq", reset_settings="r1"))
    assert bot.status()["stats"] == {"answered": 0, "peopleToday": 0, "missed": []}
    bot.apply_config(make_cfg("faq", reset="o1"))
    assert bot.stage == "active" and bot.owner is None


def test_no_hourly_limit_for_many_people(make_bot, ctxf):
    bot = live(make_bot, ctxf, max_out=5)
    for i in range(20):
        say(bot, "what is kaspa", addr(f"{70 + i:02x}" * 32))
    assert len(ctxf.sent) == 20
    assert bot.status()["error"] is None


@pytest.mark.parametrize("question,title", [
    ("Whats the current block reward", "Current reward and circulating supply"),
    ("what is the block reward right now?", "Current reward and circulating supply"),
    ("Economically what's its purpose?", "What Kaspa is for"),
    ("what is kaspa for", "What Kaspa is for"),
])
def test_questions_people_asked(question, title):
    assert best_topic(TOPICS, question).title == title


@pytest.mark.parametrize("text,start", [
    ("Hello, test.", "I answer common Kaspa questions"),
    ("你好", "I answer common Kaspa questions"),
    ("哈哈", "Ask me anything about Kaspa"),
    ("搞笑的", "Ask me anything about Kaspa"),
    ("thanks!", "You're welcome!"),
    ("你能用中文吗？", "I can only answer in English"),
])
def test_greetings_small_talk_and_other_languages(make_bot, ctxf, text, start):
    bot = live(make_bot, ctxf)
    reply, _ = bot.reply_for(text)
    assert reply.startswith(start)


@pytest.mark.parametrize("question,title", [
    ("what is the finality depth", "Finality"),
    ("can a transaction be reversed after 12 hours", "Finality"),
    ("how many blocks per day", "Blocks per day"),
    ("what is the bitcoin scaling problem", "The Bitcoin scaling problem"),
    ("what are red blocks", "Blue and red blocks"),
    ("what is blue score", "Blue score and blue work"),
    ("what is the k parameter", "The k parameter"),
    ("what is the virtual block", "Virtual block"),
    ("what is toccata", "Toccata hard fork"),
    ("why is the fee so high for tiny amounts", "Storage mass (KIP-9)"),
    ("what is KIP-9", "Storage mass (KIP-9)"),
    ("how big is a block", "Block mass limit"),
    ("what are covenants", "Covenants"),
    ("what does KIP-10 do", "KIP-10"),
    ("what is KIP-21", "KIP-21"),
    ("what is SilverScript", "SilverScript"),
    ("does kaspa support multisig", "Kaspa Script and opcodes"),
    ("how long does it take a new node to sync", "How a new node syncs"),
    ("what is in a block header", "Inside a block"),
    ("can miners fake a timestamp", "Block timestamps"),
    ("where can I learn more", "Learn more"),
    ("how much history does a node keep", "Pruning"),
])
def test_learn_kaspa_topics(question, title):
    assert best_topic(TOPICS, question).title == title


def test_learn_kaspa_answers_cite_their_article():
    assert BY_TITLE["Finality"].answer.endswith("Source: https://kaspa.com/learn-kaspa/post/finality-depth")
    cited = [t for t in TOPICS if "\nSource: https://kaspa.com/learn-kaspa" in t.answer]
    assert len(cited) == 26
