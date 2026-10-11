"""Conversation engine and the three bot types, with sending and the chain mocked."""
from conftest import BOT_KEY, OTHER_KEY, USER_KEY, FakeStore, addr, make_cfg, run

from kachat.address import short_address
from kachat.bots.base import PRIVATE_REPLY

USER = addr(USER_KEY)
OTHER = addr(OTHER_KEY)
WATCH = addr("44" * 32)
WATCH2 = addr("55" * 32)
BOTADDR = addr(BOT_KEY)

_n = [0]


def tx():
    _n[0] += 1
    return f"{_n[0]:064x}"


def say(bot, text, sender=USER):
    run(bot.handle_message(sender, text, tx()))


def texts(ctxf, to=USER):
    return [t for (_, r, t) in ctxf.sent if r == to]


def paired(make_bot, ctxf, bot_type, answers, **kw):
    bot = make_bot(bot_type, **kw)
    say(bot, "hi 482915")
    for a in answers:
        say(bot, a)
    assert bot.stage == "active", texts(ctxf)
    ctxf.sent.clear()
    return bot


# ── pairing and strangers ───────────────────────────────────────────────────

def test_stranger_gets_one_private_reply_per_day(make_bot, ctxf):
    bot = make_bot("mining")
    say(bot, "hello", OTHER)
    say(bot, "hello again", OTHER)
    assert texts(ctxf, OTHER) == [PRIVATE_REPLY]
    ctxf.clock.t += 86400
    say(bot, "next day", OTHER)
    assert texts(ctxf, OTHER) == [PRIVATE_REPLY, PRIVATE_REPLY]
    assert bot.owner is None and bot.stage == "awaiting_pairing"


def test_wrong_code_does_not_pair_and_code_must_be_whole(make_bot, ctxf):
    bot = make_bot("mining")
    say(bot, "1482915")            # code embedded in a longer number
    say(bot, "482916")
    assert bot.owner is None


def test_pairing_then_setup_questions(make_bot, ctxf):
    bot = make_bot("mining")
    say(bot, "my code is 482915")
    assert bot.owner == USER and bot.stage == "setup"
    first = texts(ctxf)[0]
    assert first.startswith("Paired!") and "1/3" in first and "mining address" in first
    say(bot, "kaspa:notanaddress")
    assert "doesn't look right" in texts(ctxf)[-1] and "1/3" in texts(ctxf)[-1]
    say(bot, addr("44" * 32, "testnet-10"))           # wrong network
    assert "kaspatest" in texts(ctxf)[-1]
    say(bot, BOTADDR)                                 # its own wallet: refused
    assert "my own address" in texts(ctxf)[-1]
    say(bot, WATCH)
    assert "2/3" in texts(ctxf)[-1]
    say(bot, "abc")
    assert "2/3" in texts(ctxf)[-1]
    say(bot, "skip")
    assert "3/3" in texts(ctxf)[-1]
    say(bot, "30")
    assert bot.stage == "active"
    assert bot.settings == {"addresses": [WATCH], "minRewardKas": 0, "hashrateDropPct": 30.0}
    assert texts(ctxf)[-1].startswith("All set!")


def test_after_pairing_strangers_are_ignored(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "0", "no"])
    say(bot, "482915", OTHER)
    say(bot, "status", OTHER)
    assert ctxf.sent == [] and bot.owner == USER


def test_commands(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "1.5", "no"])
    say(bot, "help")
    assert "Commands" in texts(ctxf)[-1]
    say(bot, "Status")
    assert texts(ctxf)[-1].startswith("Active.") and "Bot wallet" in texts(ctxf)[-1]
    say(bot, "settings")
    assert "1.5 KAS" in texts(ctxf)[-1]
    say(bot, "pause")
    assert bot.stage == "paused"
    say(bot, "/resume")
    assert bot.stage == "active"
    say(bot, "test")
    assert texts(ctxf)[-1].startswith("Test: Block reward")
    say(bot, "what?")
    assert "help" in texts(ctxf)[-1]
    say(bot, "change")
    assert bot.stage == "setup" and "now:" in texts(ctxf)[-1]
    say(bot, "skip")
    say(bot, "2")
    say(bot, "skip")
    assert bot.stage == "active" and bot.settings["minRewardKas"] == 2.0 and bot.settings["addresses"] == [WATCH]


def test_reset_forgets_settings_and_asks_again(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "1.5", "no"])
    say(bot, "reset")
    assert bot.owner == USER                                  # still paired
    assert bot.stage == "setup" and not bot.settings
    last = texts(ctxf)[-1]
    assert last.startswith("Reset:") and "1/3" in last and "now:" not in last  # the old answers are not offered
    say(bot, "skip")                                          # the address is needed again
    assert "needed" in texts(ctxf)[-1]
    say(bot, WATCH)
    say(bot, "skip")
    say(bot, "skip")
    assert bot.stage == "active" and bot.settings["addresses"] == [WATCH] and bot.settings["minRewardKas"] == 0
    say(bot, "help")
    assert "reset" in texts(ctxf)[-1]


def test_commands_during_setup_reask(make_bot, ctxf):
    bot = make_bot("wallet")
    say(bot, "482915")
    say(bot, "pause")
    assert "finish setup" in texts(ctxf)[-1] and "1/3" in texts(ctxf)[-1]
    say(bot, "help")
    assert "Commands" in texts(ctxf)[-1] and "1/3" in texts(ctxf)[-1]
    say(bot, "skip")                       # required question
    assert "needed" in texts(ctxf)[-1]


def test_one_reply_per_message_and_history(make_bot, ctxf):
    store = FakeStore()
    bot = make_bot("price", store=store)
    say(bot, "482915")
    assert len(ctxf.sent) == 1
    assert [h["dir"] for h in store.history] == ["in", "out"]
    assert store.history[1]["txid"]


def test_rate_limit_caps_spending(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["no", "no", "no", "no"], max_out=5)
    ctxf.clock.t += 3601                     # setup itself used the hour's budget
    for _ in range(10):
        say(bot, "status")
    assert len(ctxf.sent) == 5
    assert "Rate limit" in (bot.error or "")
    run(bot.notify("alert"))
    assert len(ctxf.sent) == 5
    ctxf.clock.t += 3601
    say(bot, "status")
    assert len(ctxf.sent) == 6


def test_rate_limit_counts_everything(make_bot, ctxf):
    bot = make_bot("mining", max_out=3)
    for k in range(6):
        say(bot, "hi", addr(f"{k + 60:02x}" * 32))
    assert len(ctxf.sent) == 3


def test_reset_owner_forgets_everything(make_bot, ctxf):
    store = FakeStore()
    bot = paired(make_bot, ctxf, "mining", [WATCH, "0", "no"], store=store)
    bot.apply_config(make_cfg("mining", reset="n1"))
    assert bot.owner is None and bot.settings == {} and bot.stage == "awaiting_pairing"
    bot.apply_config(make_cfg("mining", reset="n1"))     # same nonce: no second reset
    say(bot, "482915", OTHER)
    assert bot.owner == OTHER
    bot.apply_config(make_cfg("mining", reset="n1"))
    assert bot.owner == OTHER
    bot.apply_config(make_cfg("mining", reset="n2"))
    assert bot.owner is None


def test_state_survives_restart(make_bot, ctxf):
    store = FakeStore()
    paired(make_bot, ctxf, "mining", [WATCH, "0", "no"], store=store)
    seen = list(store.data["seen"])
    again = make_bot("mining", store=store)
    assert again.owner == USER and again.stage == "active" and again.settings["addresses"] == [WATCH]
    run(again.handle_message(USER, "status", seen[-1]))      # duplicate txid: ignored
    assert ctxf.sent == []


def test_disabled_bot_is_silent(make_bot, ctxf):
    bot = make_bot("mining", enabled=False)
    say(bot, "482915")
    assert ctxf.sent == [] and bot.status()["stage"] == "disabled"


def test_send_failure_is_reported_not_raised(make_bot, ctxf):
    bot = make_bot("mining")
    ctxf.fail = True
    say(bot, "482915")
    assert bot.owner == USER and "Could not send" in bot.error


def test_status_contract_shape(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "0", "no"])
    bot.balance = 1_000_000_000
    s = bot.status()
    assert set(s) == {"id", "type", "address", "balanceSompi", "funded", "stage", "owner", "settings",
                      "summary", "lastInAt", "lastOutAt", "updatedAt", "error"}
    assert s["funded"] is True and s["stage"] == "active" and s["owner"] == USER
    assert s["summary"].startswith("Watching kaspa:")
    bot.balance = 10
    assert bot.status()["funded"] is False and bot.status()["summary"].startswith("Fund ")


# ── mining ──────────────────────────────────────────────────────────────────

def _entry(txid, amount, coinbase=True, index=0):
    return {"address": WATCH, "txid": txid, "index": index, "amount": amount, "isCoinbase": coinbase,
            "blockDaaScore": 1}


def test_mining_rewards(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "1", "no"])
    ctxf.hashrate = 2500.0
    run(bot.on_utxos(WATCH, [_entry("a" * 64, 387_000_000)], []))
    msg = texts(ctxf)[-1]
    assert "Block reward: 3.87 KAS" in msg and "Balance: 50 KAS" in msg and "2.50 TH/s" in msg
    run(bot.on_utxos(WATCH, [_entry("a" * 64, 387_000_000)], []))      # same outpoint again
    run(bot.on_utxos(WATCH, [_entry("b" * 64, 50_000_000)], []))       # under minRewardKas
    run(bot.on_utxos(WATCH, [_entry("c" * 64, 900_000_000, coinbase=False)], []))  # not a reward
    assert len(ctxf.sent) == 1
    bot.data["stage"] = "paused"
    run(bot.on_utxos(WATCH, [_entry("d" * 64, 387_000_000)], []))
    assert len(ctxf.sent) == 1


def test_mining_hashrate_drop(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "0", "40"])
    t = ctxf.clock.t
    for i in range(10):
        run(bot.check_hashrate(t + i * 60, 1000.0, 40))
    run(bot.check_hashrate(t + 660, 500.0, 40))
    assert ctxf.sent == []                                 # one low reading is a blip
    run(bot.check_hashrate(t + 720, 500.0, 40))
    assert "Hashrate dropped 50%" in texts(ctxf)[-1]
    run(bot.check_hashrate(t + 780, 400.0, 40))
    assert len(ctxf.sent) == 1
    run(bot.check_hashrate(t + 840, 950.0, 40))
    assert "back" in texts(ctxf)[-1] and len(ctxf.sent) == 2


# ── price ───────────────────────────────────────────────────────────────────

def test_price_setup_and_crossings(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["0.05", "$0.03", "9am", "New York", "10%"])
    assert bot.settings == {"above": 0.05, "below": 0.03, "dailyAt": "09:00", "timezone": "America/New_York",
                            "movePct": 10.0, "currency": "usd"}
    t = ctxf.clock.t
    run(bot.observe(t, 0.040))
    run(bot.observe(t + 60, 0.051))
    assert "above $0.0500" in texts(ctxf)[-1]
    run(bot.observe(t + 120, 0.052))
    run(bot.observe(t + 180, 0.0499))                 # back by less than 1%: not re-armed
    run(bot.observe(t + 240, 0.0501))
    assert len(ctxf.sent) == 1
    run(bot.observe(t + 300, 0.049))                  # 2% back: re-armed
    run(bot.observe(t + 360, 0.0505))
    assert len(ctxf.sent) == 2
    run(bot.observe(t + 420, 0.029))
    assert "below $0.0300" in texts(ctxf)[-1]


def test_price_starting_above_does_not_alert(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["0.05", "no", "no", "no"])
    run(bot.observe(ctxf.clock.t, 0.06))
    run(bot.observe(ctxf.clock.t + 60, 0.061))
    assert ctxf.sent == []


def test_price_move_uses_api_change_until_history(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["no", "no", "no", "10"])
    run(bot.observe(ctxf.clock.t, 0.05, 12.5))
    assert "up 12.5% in 24h" in texts(ctxf)[-1]
    run(bot.observe(ctxf.clock.t + 60, 0.05, 13.0))
    assert len(ctxf.sent) == 1
    run(bot.observe(ctxf.clock.t + 120, 0.05, 2.0))      # calmed down: re-armed
    run(bot.observe(ctxf.clock.t + 180, 0.05, 11.0))
    assert len(ctxf.sent) == 2


def test_price_move_from_own_samples(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["no", "no", "no", "10"])
    t = ctxf.clock.t
    for i in range(0, 24 * 12 + 1):
        run(bot.observe(t + i * 300, 0.040, None))
    assert ctxf.sent == []
    run(bot.observe(t + 24 * 3600 + 400, 0.035, None))
    assert "down 12.5% in 24h" in texts(ctxf)[-1]


def test_price_daily_summary_once(make_bot, ctxf):
    import calendar
    import time as _t
    bot = paired(make_bot, ctxf, "price", ["no", "no", "09:00", "UTC", "no"])
    lt = _t.gmtime(ctxf.clock.t)
    nine = calendar.timegm((lt.tm_year, lt.tm_mon, lt.tm_mday, 9, 0, 0, 0, 0, 0))
    run(bot.observe(nine - 60, 0.04))
    assert ctxf.sent == []
    run(bot.observe(nine + 30, 0.041))
    assert texts(ctxf)[-1].startswith("KAS today: $0.0410")
    run(bot.observe(nine + 90, 0.041))
    assert len(ctxf.sent) == 1


def test_price_tick_polls_once_a_minute(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["0.05", "no", "no", "no"])
    ctxf.price = (0.04, None)
    run(bot.tick(1000.0))
    ctxf.price = (0.06, None)
    run(bot.tick(1030.0))
    assert bot.price == 0.04
    run(bot.tick(1061.0))
    assert bot.price == 0.06 and "above" in texts(ctxf)[-1]


# ── wallet ──────────────────────────────────────────────────────────────────

def _w(txid, amount, index=0, address=WATCH):
    return {"address": address, "txid": txid, "index": index, "amount": amount, "isCoinbase": False,
            "blockDaaScore": 1}


def test_wallet_setup_validates_addresses(make_bot, ctxf):
    bot = make_bot("wallet")
    say(bot, "482915")
    say(bot, f"{WATCH}, kaspa:qqbroken")
    assert "doesn't look right" in texts(ctxf)[-1]
    say(bot, f"{WATCH}, {WATCH2} {WATCH}")
    say(bot, "Savings")                               # two addresses, one nickname: asked again
    assert "2 nicknames" in texts(ctxf)[-1]
    say(bot, "Savings, Mining payouts")
    say(bot, "5")
    assert bot.settings == {"addresses": [WATCH, WATCH2], "nicknames": {WATCH: "Savings", WATCH2: "Mining payouts"}, "minKas": 5.0}
    assert bot.watched_addresses() == {WATCH, WATCH2}


def test_wallet_received_and_sent(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "wallet", [WATCH, "Savings", "1"])
    t = ctxf.clock.t
    ctxf.clock.t = t
    run(bot.on_utxos(WATCH, [_w("a" * 64, 1_250_000_000)], []))
    run(bot.tick(t + 1))
    assert ctxf.sent == []                          # settling
    run(bot.tick(t + 5))
    assert texts(ctxf)[-1].startswith("Savings received 12.5 KAS\nBalance: ") and "a" * 64 not in texts(ctxf)[-1]
    # a send with change: spends a's coin, change comes back in tx b
    ctxf.clock.t = t + 10
    run(bot.on_utxos(WATCH, [_w("b" * 64, 250_000_000, 1)], [_w("a" * 64, 1_250_000_000)]))
    run(bot.tick(t + 20))
    assert texts(ctxf)[-1].startswith("Savings sent 10 KAS\nBalance: ") and "b" * 64 not in texts(ctxf)[-1]
    # a sweep (no change): spender comes from the chain follower
    ctxf.spenders[f"{'b' * 64}:1"] = "c" * 64
    ctxf.clock.t = t + 30
    run(bot.on_utxos(WATCH, [], [_w("b" * 64, 250_000_000, 1)]))
    run(bot.tick(t + 40))
    assert texts(ctxf)[-1].startswith("Savings sent 2.5 KAS") and "c" * 64 not in texts(ctxf)[-1]
    # below minKas
    ctxf.clock.t = t + 50
    run(bot.on_utxos(WATCH, [_w("d" * 64, 50_000_000)], []))
    run(bot.tick(t + 60))
    assert len(ctxf.sent) == 3


def test_wallet_without_a_nickname_uses_the_address(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "wallet", [WATCH, "none", "0"])
    assert bot.settings["nicknames"] == {}
    t = ctxf.clock.t
    run(bot.on_utxos(WATCH, [_w("e" * 64, 100_000_000)], []))
    run(bot.tick(t + 5))
    msg = texts(ctxf)[-1]
    assert msg.startswith("kaspa:") and " received 1 KAS\nBalance: " in msg and len(msg.split("\n")) == 2


def test_mining_without_bridge_skips_hashrate_question(ctxf):
    from kachat.bots import make_bot as mk
    ctx = ctxf.make()
    ctx.fetch_hashrate = None
    bot = mk(make_cfg("mining"), FakeStore(), ctx)
    say(bot, "482915")
    assert "1/2" in texts(ctxf)[-1]
    say(bot, WATCH)
    say(bot, "0")
    assert bot.stage == "active" and bot.settings["hashrateDropPct"] is None


# ── add: watch another address (mining, wallet; up to 10) ───────────────────

def test_wallet_add_with_nickname(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "wallet", [WATCH, "Savings", "0"])
    say(bot, "add")
    assert "Which address should I add?" in texts(ctxf)[-1]
    say(bot, "kaspa:broken")
    assert "doesn't look right" in texts(ctxf)[-1] and bot.data.get("adding")
    say(bot, WATCH2)
    assert "What should I call it?" in texts(ctxf)[-1]
    say(bot, "Mining payouts")
    assert texts(ctxf)[-1] == "Added Mining payouts. Now watching 2 addresses."
    assert bot.settings["addresses"] == [WATCH, WATCH2]
    assert bot.settings["nicknames"] == {WATCH: "Savings", WATCH2: "Mining payouts"}
    assert bot.watched_addresses() == {WATCH, WATCH2}
    assert not bot.data.get("adding")


def test_add_inline_duplicate_self_cancel_and_other_commands(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "wallet", [WATCH, "none", "0"])
    say(bot, f"add {WATCH}")
    assert texts(ctxf)[-1] == "I'm already watching that one." and not bot.data.get("adding")
    say(bot, f"add {BOTADDR}")
    assert "my own address" in texts(ctxf)[-1]
    say(bot, "cancel")
    assert texts(ctxf)[-1].startswith("Cancelled") and bot.settings["addresses"] == [WATCH]
    say(bot, "add")
    say(bot, "status")                        # another command ends the add
    assert texts(ctxf)[-1].startswith("Active.") and not bot.data.get("adding")
    say(bot, f"add {addr('66' * 32, 'testnet-10')}")   # wrong network
    assert "kaspatest" in texts(ctxf)[-1]


def test_add_stops_at_ten(make_bot, ctxf):
    keys = [f"{i:02x}" * 32 for i in range(0x60, 0x6a)]          # 10 addresses
    bot = paired(make_bot, ctxf, "wallet", [" ".join(addr(k) for k in keys[:9]), "none", "0"])
    say(bot, f"add {addr(keys[9])}")
    say(bot, "none")
    assert "Now watching 10 addresses" in texts(ctxf)[-1]
    say(bot, "add")
    assert texts(ctxf)[-1] == "I'm already watching 10 addresses, the most I can."
    say(bot, " ".join(addr(k) for k in keys) + " " + addr("7f" * 32))   # not an add answer
    assert len(bot.settings["addresses"]) == 10


def test_mining_add_and_reward_names_the_address(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "0", "no"])
    say(bot, "add")
    say(bot, WATCH2)                          # no nickname question on mining
    assert texts(ctxf)[-1] == f"Added {short_address(WATCH2)}. Now watching 2 addresses."
    assert bot.watched_addresses() == {WATCH, WATCH2}
    run(bot.on_utxos(WATCH2, [_entry("f" * 64, 387_000_000)], []))
    msg = texts(ctxf)[-1]
    assert msg.startswith(short_address(WATCH2) + "\nBlock reward: 3.87 KAS")
    say(bot, "help")
    assert "add - watch another address" in texts(ctxf)[-1]


def test_price_bot_has_no_add(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["0.05", "no", "no", "no"])
    say(bot, "add")
    assert "doesn't watch addresses" in texts(ctxf)[-1]
    say(bot, "help")
    assert "add -" not in texts(ctxf)[-1]


def test_old_single_address_mining_settings_still_work(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "0", "no"])
    bot.data["settings"] = {"address": WATCH, "minRewardKas": 0, "hashrateDropPct": None}
    assert bot.watched_addresses() == {WATCH}
    say(bot, f"add {WATCH2}")
    assert bot.settings["addresses"] == [WATCH, WATCH2]


# ── the panel's Reset: forget the answers, greet the owner again ────────────

def test_panel_reset_keeps_owner_and_asks_again(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "mining", [WATCH, "1.5", "no"])
    sent_before = len(ctxf.sent)
    bot.apply_config(make_cfg("mining", reset_settings="n1"))
    assert bot.owner == USER and not bot.settings and bot.stage == "setup"
    assert bot.watched_addresses() == set()
    run(bot.send_pending_greeting())
    msg = texts(ctxf)[-1]
    assert len(ctxf.sent) == sent_before + 1
    assert msg.startswith("Hi again!") and "1/3" in msg and "mining address" in msg
    run(bot.send_pending_greeting())                 # only once
    assert len(ctxf.sent) == sent_before + 1
    bot.apply_config(make_cfg("mining", reset_settings="n1"))   # same click again: nothing
    assert bot.stage == "setup" and len(ctxf.sent) == sent_before + 1
    say(bot, WATCH2)
    say(bot, "skip")
    say(bot, "skip")
    assert bot.stage == "active" and bot.settings["addresses"] == [WATCH2]


def test_panel_reset_before_pairing_just_records_it(make_bot, ctxf):
    bot = make_bot("wallet")
    bot.apply_config(make_cfg("wallet", reset_settings="n1"))
    run(bot.send_pending_greeting())
    assert ctxf.sent == [] and bot.stage == "awaiting_pairing"


# ── price: daily summary in AM/PM and the owner's time zone ────────────────

def test_parse_time_am_pm():
    from kachat.bots.price import fmt_time, parse_time
    cases = {"9am": "09:00", "9 AM": "09:00", "9:30 p.m.": "21:30", "12 am": "00:00", "12pm": "12:00",
             "noon": "12:00", "midnight": "00:00", "21:15": "21:15", "8:05 PM": "20:05", "no": None}
    for text, want in cases.items():
        assert parse_time(text) == want, text
    for bad in ("13pm", "0am", "25:00", "9:75", "soon"):
        try:
            parse_time(bad)
        except Exception:
            continue
        raise AssertionError(bad)
    assert fmt_time("21:30") == "9:30 PM" and fmt_time("00:05") == "12:05 AM" and fmt_time("12:00") == "12:00 PM"


def test_parse_timezone():
    from kachat.bots.price import parse_timezone
    assert parse_timezone("EST") == "America/New_York"
    assert parse_timezone("new york") == "America/New_York"
    assert parse_timezone("London") == "Europe/London"
    assert parse_timezone("europe/paris") == "Europe/Paris"
    assert parse_timezone("utc") == "UTC"
    try:
        parse_timezone("Atlantis")
    except Exception:
        return
    raise AssertionError("Atlantis")


def test_timezone_only_asked_with_a_daily_summary(make_bot, ctxf):
    bot = paired(make_bot, ctxf, "price", ["no", "no", "no", "no"])
    assert bot.stage == "active" and bot.settings["timezone"] is None
    assert not any("time zone" in t for t in texts(ctxf))


def test_daily_summary_fires_at_the_owners_local_time(make_bot, ctxf):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    bot = paired(make_bot, ctxf, "price", ["no", "no", "9:00 AM", "New York", "no"])
    assert "9:00 AM (America/New_York)" in bot.describe_settings()
    ny = ZoneInfo("America/New_York")
    nine = datetime(2026, 10, 12, 9, 0, 30, tzinfo=ny).timestamp()     # 13:00 UTC
    run(bot.observe(nine - 3600, 0.04))                                 # 8 AM New York: nothing yet
    assert not any(t.startswith("KAS today") for t in texts(ctxf))
    run(bot.observe(nine, 0.041))
    assert texts(ctxf)[-1].startswith("KAS today")
    run(bot.observe(nine + 60, 0.041))                                  # once a day
    assert sum(t.startswith("KAS today") for t in texts(ctxf)) == 1
