"""Public bots: anyone can use one, no pairing code, each person with their own setup."""
from conftest import BOT_KEY, OTHER_KEY, USER_KEY, FakeStore, addr, make_cfg, run

from kachat.bots import make_bot as mk
from kachat.state import BotStore, read_json
from test_engine import say, texts

USER = addr(USER_KEY)
OTHER = addr(OTHER_KEY)
WATCH = addr("44" * 32)
WATCH2 = addr("55" * 32)


def host(ctxf, bot_type="mining", store=None, **kw):
    return mk(make_cfg(bot_type, **kw), store or FakeStore(), ctxf.make())


def _w(txid, amount, address):
    return {"address": address, "txid": txid, "index": 0, "amount": amount, "isCoinbase": False, "blockDaaScore": 1}


def test_anyone_starts_setup_without_a_code(ctxf):
    bot = host(ctxf)
    say(bot, "hello", OTHER)
    first = texts(ctxf, OTHER)[0]
    assert first.startswith("Hi! I'm the KaChat Mining bot. A few quick questions.")
    assert "private" not in first.lower()
    assert bot.owner is None and bot.status()["stage"] == "active"


def test_mining_never_asks_about_the_panels_hashrate(ctxf):
    ctxf.hashrate = 1000.0
    bot = host(ctxf)
    say(bot, "hi", OTHER)
    assert "1/2" in texts(ctxf, OTHER)[0]


def test_two_people_each_get_their_own_setup_and_notifications(ctxf):
    bot = host(ctxf, "wallet")
    for who, watch, name in ((USER, WATCH, "Mine"), (OTHER, WATCH2, "Theirs")):
        say(bot, "hi", who)
        say(bot, watch, who)
        say(bot, name, who)
        say(bot, "0", who)
    assert bot.people[USER].settings["addresses"] == [WATCH]
    assert bot.people[OTHER].settings["addresses"] == [WATCH2]
    assert bot.watched_addresses() == {WATCH, WATCH2}
    assert bot.status()["stats"]["people"] == 2 and bot.status()["stats"]["active"] == 2
    t = ctxf.clock.t
    run(bot.on_utxos(WATCH2, [_w("a" * 64, 100_000_000, WATCH2)], []))
    run(bot.tick(t + 10))
    assert texts(ctxf, OTHER)[-1].startswith("Theirs received 1 KAS")
    assert not any("received" in m for m in texts(ctxf, USER))


def test_price_alerts_per_person(ctxf):
    bot = host(ctxf, "price")
    say(bot, "hi", USER)
    for a in ["0.05", "no", "no", "no"]:
        say(bot, a, USER)
    say(bot, "hi", OTHER)
    for a in ["0.10", "no", "no", "no"]:
        say(bot, a, OTHER)
    before_user, before_other = len(texts(ctxf, USER)), len(texts(ctxf, OTHER))
    ctxf.price = (0.04, None)
    run(bot.tick(ctxf.clock.t + 120))
    ctxf.price = (0.06, None)
    run(bot.tick(ctxf.clock.t + 240))
    assert len(texts(ctxf, USER)) == before_user + 1 and "0.05" in texts(ctxf, USER)[-1]
    assert len(texts(ctxf, OTHER)) == before_other


def test_thirty_messages_a_day_each_then_one_note(ctxf):
    bot = host(ctxf)
    for _ in range(40):
        say(bot, "status", OTHER)
    got = texts(ctxf, OTHER)
    assert len(got) == 31 and got[-1].startswith("That's my limit of 30 messages for you today")
    say(bot, "status", USER)                                  # someone else is not affected
    assert len(texts(ctxf, USER)) == 1
    ctxf.clock.t += 86400
    say(bot, "status", OTHER)
    assert len(texts(ctxf, OTHER)) == 32


def test_people_and_their_setup_survive_a_restart(ctxf, tmp_path):
    store = BotStore(str(tmp_path), "mining-1")
    bot = host(ctxf, store=store)
    say(bot, "hi", OTHER)
    say(bot, WATCH, OTHER)
    say(bot, "0", OTHER)
    bot2 = host(ctxf, store=store)
    assert bot2.people[OTHER].address_list() == [WATCH] and bot2.people[OTHER].stage == "active"
    assert bot2.watched_addresses() == {WATCH}
    assert read_json(store.data_path)["people"]


def test_a_paired_owner_keeps_their_setup(ctxf):
    store = FakeStore()
    store.data = {"owner": USER, "stage": "active", "seen": [],
                  "settings": {"address": WATCH, "minRewardKas": 0, "hashrateDropPct": None}}
    bot = host(ctxf, store=store)
    assert bot.owner is None
    p = bot.people[USER]
    assert p.owner == USER and p.stage == "active" and p.address_list() == [WATCH]
    say(bot, "settings", USER)
    assert "Setting up" not in texts(ctxf, USER)[-1] and not texts(ctxf, USER)[-1].startswith("Hi!")


def test_panel_reset_forgets_everyone(ctxf, tmp_path):
    store = BotStore(str(tmp_path), "mining-1")
    bot = host(ctxf, store=store)
    say(bot, "hi", OTHER)
    bot.apply_config(make_cfg("mining", reset_settings="r1"))
    assert bot.people == {} and bot.watched_addresses() == set()
    say(bot, "hi again", OTHER)
    assert texts(ctxf, OTHER)[-1].startswith("Hi! I'm the KaChat")


def test_switched_off_answers_nobody(ctxf):
    bot = host(ctxf, enabled=False)
    say(bot, "hi", OTHER)
    assert texts(ctxf, OTHER) == []


def test_panel_alert_goes_to_a_named_address(ctxf):
    bot = host(ctxf)
    assert run(bot.send_to(USER, "Alert: test"))
    assert texts(ctxf, USER) == ["Alert: test"]
