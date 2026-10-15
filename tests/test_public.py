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
        run(bot.tick(ctxf.clock.t))
    got = texts(ctxf, OTHER)[before:]
    stop = [i for i, t in enumerate(got) if t.startswith("I stopped watching")]
    assert len(stop) == 1 and stop[0] == len(got) - 1         # the last message, then silence
    assert "does not have this much activity" in got[-1]
    assert "more than 20 payments in a minute" in got[-1] and "Send add" in got[-1]
    assert sum(t.count("block reward") + t.count("Block reward") for t in got) >= 1
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
    run(bot.on_utxos(WATCH, [coin], []))                       # ...and in the end it stays
    for i in range(30):                                        # the owner spending from the address
        run(bot.on_utxos(WATCH, [], [_coin(100 + i, WATCH)]))
    for i in range(30):                                        # change outputs are not rewards
        run(bot.on_utxos(WATCH, [_coin(200 + i, WATCH, coinbase=False)], []))
    ctxf.clock.t += 4
    run(bot.tick(ctxf.clock.t))
    assert bot.people[OTHER].address_list() == [WATCH]
    assert not any("stopped watching" in t for t in texts(ctxf, OTHER))
    assert sum("Block reward" in t for t in texts(ctxf, OTHER)) == 1     # one reward, one message


def test_a_lucky_burst_from_a_home_miner_is_kept(ctxf):
    bot = _mining_with(ctxf, WATCH)
    for i in range(8):                                         # 8 blocks in under a minute
        run(bot.on_utxos(WATCH, [_coin(i + 1, WATCH)], []))
        ctxf.clock.t += 5
    assert bot.people[OTHER].address_list() == [WATCH]


def _out(txid, amount, address, index=0):
    return {"address": address, "txid": txid, "index": index, "amount": amount, "isCoinbase": False, "blockDaaScore": 1}


def _wallet_watching(ctxf, watch):
    bot = host(ctxf, "wallet")
    start(bot, OTHER)
    say(bot, watch, OTHER)
    say(bot, "Other bot", OTHER)
    say(bot, "0", OTHER)
    return bot


def test_another_bots_messages_are_never_reported(ctxf):
    """BOT-001: a wallet bot watching another bot's address must not report that bot's messages."""
    W2 = addr("99" * 32)
    bot = _wallet_watching(ctxf, W2)
    before = len(texts(ctxf, OTHER))
    coin = _out("a" * 64, 50_000_000, W2)
    for i in range(30):                                        # 30 messages from W2: each spends its coin...
        nxt = _out(f"{i + 1:064x}", coin["amount"] - 198_000, W2)
        ctxf.self_sends[nxt["txid"]] = True                    # ...and pays only W2 back (the chain says so)
        ctxf.spenders[f"{coin['txid']}:0"] = nxt["txid"]
        run(bot.on_utxos(W2, [nxt], [coin]))
        ctxf.clock.t += 10
        run(bot.tick(ctxf.clock.t))
        coin = nxt
    assert len(texts(ctxf, OTHER)) == before                   # silence: no loop can start


def test_a_self_send_the_chain_never_shows_is_still_skipped(ctxf):
    ctxf.self_send_default = None                              # the follower never sees it
    W2 = addr("99" * 32)
    bot = _wallet_watching(ctxf, W2)
    before = len(texts(ctxf, OTHER))
    run(bot.on_utxos(W2, [_out("b" * 64, 49_802_000, W2)], [_out("a" * 64, 50_000_000, W2)]))
    ctxf.spenders[f"{'a' * 64}:0"] = "b" * 64
    ctxf.clock.t += 16                                         # past the wait: the 0.01 KAS rule decides
    run(bot.tick(ctxf.clock.t))
    assert len(texts(ctxf, OTHER)) == before


def test_real_payments_are_still_reported(ctxf):
    W2 = addr("99" * 32)
    bot = _wallet_watching(ctxf, W2)
    run(bot.on_utxos(W2, [_out("c" * 64, 300_000_000, W2)], []))       # a payment in
    ctxf.clock.t += 10
    run(bot.tick(ctxf.clock.t))
    assert texts(ctxf, OTHER)[-1].startswith("Other bot received 3 KAS")
    ctxf.self_sends["d" * 64] = False                                    # a payment out, change back
    ctxf.spenders[f"{'c' * 64}:0"] = "d" * 64
    run(bot.on_utxos(W2, [_out("d" * 64, 99_000_000, W2)], [_out("c" * 64, 300_000_000, W2)]))
    ctxf.clock.t += 10
    run(bot.tick(ctxf.clock.t))
    assert texts(ctxf, OTHER)[-1].startswith("Other bot sent 2.01 KAS")


def test_people_who_never_agree_are_forgotten_after_a_day(ctxf):
    bot = host(ctxf)
    say(bot, "hi", OTHER)                                      # never agrees
    start(bot, USER)                                           # agrees
    ctxf.clock.t += 86400 + 3601
    run(bot.tick(ctxf.clock.t))
    assert OTHER not in bot.people and USER in bot.people


def test_full_bot_makes_room_by_forgetting_someone_quiet_for_a_month(ctxf, monkeypatch):
    import kachat.bots.public as public
    monkeypatch.setattr(public, "MAX_PEOPLE", 2)
    bot = host(ctxf)
    start(bot, USER)
    ctxf.clock.t += 40 * 86400
    start(bot, OTHER)
    newcomer = addr("66" * 32)
    start(bot, newcomer)                                       # full: USER has been quiet 40 days
    assert USER not in bot.people and newcomer in bot.people
    assert texts(ctxf, newcomer)[-1].startswith("Thanks! I'm the KaChat")


def test_full_of_active_people_says_so_once_a_day(ctxf, monkeypatch):
    import kachat.bots.public as public
    monkeypatch.setattr(public, "MAX_PEOPLE", 2)
    bot = host(ctxf)
    start(bot, USER)
    start(bot, OTHER)
    newcomer = addr("66" * 32)
    say(bot, "hi", newcomer)
    say(bot, "agree", newcomer)
    say(bot, "agree", newcomer)
    full = [t for t in texts(ctxf, newcomer) if t.startswith("Sorry, I'm full right now")]
    assert len(full) == 1 and not bot.people[newcomer].data.get("agreedNotPrivate")
    assert USER in bot.people and OTHER in bot.people


def test_a_carried_over_owner_is_never_forgotten_for_not_agreeing(ctxf):
    store = FakeStore()
    store.data = {"owner": USER, "stage": "active", "seen": [], "createdAt": 1,
                  "settings": {"address": WATCH, "minRewardKas": 0, "hashrateDropPct": None}}
    bot = host(ctxf, store=store)
    ctxf.clock.t += 5 * 86400
    run(bot.tick(ctxf.clock.t))
    assert USER in bot.people and bot.people[USER].address_list() == [WATCH]


def test_a_persons_file_does_not_grow_with_every_message(ctxf):
    """BOT-005: no hourly limit for public people, so no per-message time list either."""
    bot = host(ctxf)
    start(bot, OTHER)
    for _ in range(50):
        say(bot, "help", OTHER)
    assert "outTimes" not in bot.people[OTHER].data


def test_back_to_back_bot_messages_reported_as_one_change_stay_silent(ctxf):
    """BOT-001 (run 8): W2 sends two chained messages accepted together; the node reports
    removed {u0}, added {u2}. Only the chain follower can tell tx2 is a self-send; the wallet
    bot waits for that verdict instead of reporting 'received'."""
    ctxf.self_send_default = None                              # the follower has not seen tx2 yet
    W2 = addr("99" * 32)
    bot = _wallet_watching(ctxf, W2)
    before = len(texts(ctxf, OTHER))
    u0 = _out("a" * 64, 50_000_000, W2)
    u2 = _out("c" * 64, 49_600_000, W2)
    ctxf.spenders[f"{'a' * 64}:0"] = "b" * 64                  # tx1 spent u0 (tx2 spent tx1's output)
    ctxf.self_sends["b" * 64] = True
    run(bot.on_utxos(W2, [u2], [u0]))
    for _ in range(3):                                         # still unknown: it waits
        ctxf.clock.t += 4
        run(bot.tick(ctxf.clock.t))
    assert len(texts(ctxf, OTHER)) == before
    ctxf.self_sends["c" * 64] = True                           # the follower saw tx2: a self-send
    ctxf.clock.t += 2
    run(bot.tick(ctxf.clock.t))
    assert len(texts(ctxf, OTHER)) == before                   # silence, no loop


def test_daemon_records_every_self_send_it_sees():
    from kachat.chain import ChainTx
    from kachat.daemon import Daemon
    d = Daemon.__new__(Daemon)
    import collections
    d.self_sends = collections.OrderedDict()
    W2 = addr("99" * 32)
    d.note_self_send(ChainTx(txid="t1", payload_hex="", block_time_ms=0, block_hash="",
                             inputs=[("p", 0, W2, 5)], outputs=[(W2, 4)]))
    d.note_self_send(ChainTx(txid="t2", payload_hex="", block_time_ms=0, block_hash="",
                             inputs=[("p", 1, W2, 5)], outputs=[(OTHER, 2), (W2, 2)]))
    assert d.self_sends == {"t1": True, "t2": False}
