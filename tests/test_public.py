"""Public bots: anyone can use one, no pairing code, each person with their own setup."""
from conftest import BOT_KEY, OTHER_KEY, USER_KEY, FakeStore, addr, make_cfg, run

from kachat.bots import make_bot as mk
from kachat.bots.base import NOT_PRIVATE_NOTICE
from kachat.state import BotStore, read_json
from test_engine import say, texts

USER = addr(USER_KEY)
OTHER = addr(OTHER_KEY)
WATCH = addr("44" * 32)
WATCH2 = addr("55" * 32)


def host(ctxf, bot_type="mining", store=None, **kw):
    return mk(make_cfg(bot_type, **kw), store or FakeStore(), ctxf.make())


def start(bot, who):
    say(bot, "hi", who)
    say(bot, "agree", who)


def _w(txid, amount, address):
    return {"address": address, "txid": txid, "index": 0, "amount": amount, "isCoinbase": False, "blockDaaScore": 1}


def test_anyone_starts_setup_without_a_code_after_agreeing(ctxf):
    bot = host(ctxf)
    say(bot, "hello", OTHER)
    assert texts(ctxf, OTHER) == [NOT_PRIVATE_NOTICE]
    say(bot, "what?", OTHER)                                  # asked again until they agree
    assert texts(ctxf, OTHER)[-1] == NOT_PRIVATE_NOTICE
    assert bot.people[OTHER].stage != "setup"
    say(bot, "I agree", OTHER)
    assert texts(ctxf, OTHER)[-1].startswith("Thanks! I'm the KaChat Mining bot. A few quick questions.")
    assert bot.owner is None and bot.status()["stage"] == "active"


def test_the_notice_says_messages_are_not_private():
    assert "not private" in NOT_PRIVATE_NOTICE and "agree" in NOT_PRIVATE_NOTICE


def test_mining_never_asks_about_the_panels_hashrate(ctxf):
    ctxf.hashrate = 1000.0
    bot = host(ctxf)
    start(bot, OTHER)
    assert "1/2" in texts(ctxf, OTHER)[-1]


def test_two_people_each_get_their_own_setup_and_notifications(ctxf):
    bot = host(ctxf, "wallet")
    for who, watch, name in ((USER, WATCH, "Mine"), (OTHER, WATCH2, "Theirs")):
        start(bot, who)
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
    start(bot, USER)
    for a in ["0.05", "no", "no", "no"]:
        say(bot, a, USER)
    start(bot, OTHER)
    for a in ["0.10", "no", "no", "no"]:
        say(bot, a, OTHER)
    before_user, before_other = len(texts(ctxf, USER)), len(texts(ctxf, OTHER))
    ctxf.price = (0.04, None)
    run(bot.tick(ctxf.clock.t + 120))
    ctxf.price = (0.06, None)
    run(bot.tick(ctxf.clock.t + 240))
    assert len(texts(ctxf, USER)) == before_user + 1 and "0.05" in texts(ctxf, USER)[-1]
    assert len(texts(ctxf, OTHER)) == before_other


def test_no_limit_per_person(ctxf):
    bot = host(ctxf)
    start(bot, OTHER)
    say(bot, "skip", OTHER)                                   # address needed: asked again
    for _ in range(60):
        say(bot, "help", OTHER)
    assert len(texts(ctxf, OTHER)) == 63
    assert not any("limit" in t for t in texts(ctxf, OTHER))
    assert bot.status()["stats"]["perPersonPerDay"] is None


def test_people_and_their_setup_survive_a_restart(ctxf, tmp_path):
    store = BotStore(str(tmp_path), "mining-1")
    bot = host(ctxf, store=store)
    start(bot, OTHER)
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
    assert texts(ctxf, USER)[-1] == NOT_PRIVATE_NOTICE         # asked once, like everyone
    say(bot, "agree", USER)
    assert texts(ctxf, USER)[-1].startswith("Thanks! Carry on where you left off")
    assert p.stage == "active" and p.address_list() == [WATCH]


def test_panel_reset_forgets_everyone(ctxf, tmp_path):
    store = BotStore(str(tmp_path), "mining-1")
    bot = host(ctxf, store=store)
    start(bot, OTHER)
    bot.apply_config(make_cfg("mining", reset_settings="r1"))
    assert bot.people == {} and bot.watched_addresses() == set()
    say(bot, "hi again", OTHER)
    assert texts(ctxf, OTHER)[-1] == NOT_PRIVATE_NOTICE


def test_switched_off_answers_nobody(ctxf):
    bot = host(ctxf, enabled=False)
    say(bot, "hi", OTHER)
    assert texts(ctxf, OTHER) == []


def test_panel_alert_goes_to_a_named_address(ctxf):
    bot = host(ctxf)
    assert run(bot.send_to(USER, "Alert: test"))
    assert texts(ctxf, USER) == ["Alert: test"]


def _coin(i, address, coinbase=True):
    return {"address": address, "txid": f"{i:064x}", "index": 0, "amount": 400_000_000,
            "isCoinbase": coinbase, "blockDaaScore": i}


def _mining_with(ctxf, *watch):
    bot = host(ctxf)
    start(bot, OTHER)
    say(bot, " ".join(watch), OTHER)
    say(bot, "0", OTHER)
    assert bot.people[OTHER].stage == "active"
    return bot


def test_a_pool_address_is_dropped_with_a_message(ctxf):
    POOL = addr("77" * 32)
    bot = _mining_with(ctxf, WATCH, POOL)
    before = len(texts(ctxf, OTHER))
    for i in range(40):                                        # a reward every second: a pool
        run(bot.on_utxos(POOL, [_coin(i + 1, POOL)], []))
        ctxf.clock.t += 1
    got = texts(ctxf, OTHER)[before:]
    assert got[-1].startswith("I stopped watching") and "does not have this much activity" in got[-1]
    assert "more than 20 payments in a minute" in got[-1] and "Send add" in got[-1]
    assert len(got) == 21                                      # 20 rewards, then the message, then silence
    assert bot.people[OTHER].address_list() == [WATCH]
    assert POOL not in bot.watched_addresses() and WATCH in bot.watched_addresses()


def test_last_busy_address_dropped_asks_for_another(ctxf):
    POOL = addr("77" * 32)
    bot = _mining_with(ctxf, POOL)
    for i in range(21):
        run(bot.on_utxos(POOL, [_coin(i + 1, POOL)], []))
    p = bot.people[OTHER]
    assert p.stage == "setup" and "1/2" in texts(ctxf, OTHER)[-1]
    assert bot.watched_addresses() == set()


def test_a_normal_miner_is_not_dropped(ctxf):
    bot = _mining_with(ctxf, WATCH)
    for i in range(12):                                        # a block every 2 minutes for 24 min
        run(bot.on_utxos(WATCH, [_coin(i + 1, WATCH)], []))
        ctxf.clock.t += 120
    assert bot.people[OTHER].address_list() == [WATCH]
    assert not any("stopped watching" in t for t in texts(ctxf, OTHER))


def test_a_busy_wallet_address_is_dropped(ctxf):
    EXCHANGE = addr("88" * 32)
    bot = host(ctxf, "wallet")
    start(bot, OTHER)
    say(bot, EXCHANGE, OTHER)
    say(bot, "Exchange", OTHER)
    say(bot, "0", OTHER)
    for i in range(110):                                       # a payment every 5 s, for 9 minutes
        run(bot.on_utxos(EXCHANGE, [_coin(i + 1, EXCHANGE, coinbase=False)], []))
        ctxf.clock.t += 5
        run(bot.tick(ctxf.clock.t))
    assert any(t.startswith("I stopped watching Exchange") for t in texts(ctxf, OTHER))
    assert bot.watched_addresses() == set()



def test_reorg_churn_and_spends_do_not_count_as_payments(ctxf):
    bot = _mining_with(ctxf, WATCH)
    coin = _coin(1, WATCH)
    for _ in range(30):                                        # the same reward removed and re-added
        run(bot.on_utxos(WATCH, [coin], []))
        run(bot.on_utxos(WATCH, [], [coin]))
    for i in range(30):                                        # the owner spending from the address
        run(bot.on_utxos(WATCH, [], [_coin(100 + i, WATCH)]))
    for i in range(30):                                        # change outputs are not rewards
        run(bot.on_utxos(WATCH, [_coin(200 + i, WATCH, coinbase=False)], []))
    assert bot.people[OTHER].address_list() == [WATCH]
    assert not any("stopped watching" in t for t in texts(ctxf, OTHER))
    assert sum("Block reward" in t for t in texts(ctxf, OTHER)) == 1     # one reward, one message


def test_a_lucky_burst_from_a_home_miner_is_kept(ctxf):
    bot = _mining_with(ctxf, WATCH)
    for i in range(8):                                         # 8 blocks in under a minute
        run(bot.on_utxos(WATCH, [_coin(i + 1, WATCH)], []))
        ctxf.clock.t += 5
    assert bot.people[OTHER].address_list() == [WATCH]
