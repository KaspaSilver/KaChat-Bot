"""`botd.py --sweep`: every spendable coin to the panel's payout address."""
import asyncio
import json
import sys
import types

from conftest import BOT_KEY, USER_KEY, FakeBackend, FakeStore, addr, make_cfg, run

from kachat.bots import make_bot
from kachat.daemon import outbox_sweep, sweep_bot
from kachat.send import MAX_INPUTS, KaspaSdkBackend, MessageSender, min_fee
from kachat.state import read_json

BOT = addr(BOT_KEY)
PAYEE = addr(USER_KEY)
P2PK = 34
KEYS = {"ok", "txid", "txids", "amountSompi", "feeSompi", "error"}


def setup(amounts=(1_000_000_000,), ctxf=None):
    from conftest import FakeCtxFactory
    f = ctxf or FakeCtxFactory()
    bot = make_bot(make_cfg("wallet"), FakeStore(), f.make())
    be = FakeBackend(BOT, amounts)
    return bot, MessageSender(BOT_KEY, BOT, be), be


def test_single_coin_sweep_pays_everything_minus_fee_to_the_payee_only():
    bot, sender, be = setup((987_000_000,))
    res = run(sweep_bot(bot, sender, PAYEE, "mainnet"))
    assert set(res) == KEYS and res["ok"] and res["error"] is None
    tx, = be.submitted
    fee = min_fee(1, 0, P2PK)
    assert tx["out"] == (PAYEE, 987_000_000 - fee)          # the only output; no change
    assert tx["payload"] == "" and tx["fee"] == fee
    assert res["amountSompi"] == 987_000_000 - fee and res["feeSompi"] == fee
    assert res["txids"] == [res["txid"]]
    # no owner needed, not counted against the message limit, recorded in the history
    assert bot.owner is None and bot.data["outTimes"] == []
    h = bot.store.history[-1]
    assert h["dir"] == "out" and h["txid"] == res["txid"]
    assert h["text"].startswith("Sent 9.868") and "(all funds)" in h["text"] and "kaspa:" in h["text"]


def test_many_coins_are_batched_under_the_mass_limit():
    coins = tuple(10_000_000 + i for i in range(200))
    bot, sender, be = setup(coins)
    res = run(sweep_bot(bot, sender, PAYEE, "mainnet"))
    assert res["ok"] and len(res["txids"]) == 3 == len(be.submitted)
    assert [len(t["inputs"]) for t in be.submitted] == [MAX_INPUTS, MAX_INPUTS, 40]
    spent = [(o["transactionId"], o["index"]) for t in be.submitted for o in t["inputs"]]
    assert len(set(spent)) == 200                              # every coin, once
    for t in be.submitted:
        assert t["out"][0] == PAYEE and t["out"][1] == sum(t["in_amounts"]) - t["fee"]
        assert t["fee"] == min_fee(len(t["inputs"]), 0, P2PK)
    assert res["amountSompi"] + res["feeSompi"] == sum(coins)


def test_address_validation():
    bot, sender, be = setup()
    for to, word in [(addr(USER_KEY, "testnet-10"), "kaspatest"),
                     (PAYEE[:-1] + ("q" if PAYEE[-1] != "q" else "p"), "checksum"),
                     ("not-an-address", "prefix"),
                     (BOT, "own address")]:
        res = run(sweep_bot(bot, sender, to, "mainnet"))
        assert not res["ok"] and word in res["error"] and res["txid"] is None
    assert be.submitted == []


def test_empty_and_dust_wallets():
    bot, sender, be = setup(())
    res = run(sweep_bot(bot, sender, PAYEE, "mainnet"))
    assert not res["ok"] and res["error"] == "Nothing to send: the bot's wallet holds 0 KAS"
    bot, sender, be = setup((50_000,))
    res = run(sweep_bot(bot, sender, PAYEE, "mainnet"))
    assert not res["ok"] and "too little to pay the network fee" in res["error"]
    assert be.submitted == []


def test_sweep_includes_the_pending_chain_link_and_drops_chain_state():
    bot, sender, be = setup((1_000_000_000,))
    run(sender.send(PAYEE, "hello"))                    # leaves an unconfirmed output 0
    msg = be.submitted[0]
    res = run(sweep_bot(bot, sender, PAYEE, "mainnet"))
    sweep = be.submitted[1]
    assert res["ok"]
    assert sweep["inputs"] == [{"transactionId": f"{0xabc001:064x}", "index": 0}]
    assert sweep["out"][1] == msg["out"][1] - sweep["fee"]
    assert sender._pending is None
    # the node still lists the original coin; it must not be reused
    import pytest
    from kachat.send import InsufficientFunds
    with pytest.raises(InsufficientFunds):
        run(sender.sweep(PAYEE))


def test_sweep_holds_the_wallet_lock():
    async def go():
        bot, sender, be = setup((1_000_000_000, 2_000_000_000))
        gate = asyncio.Event()
        order = []
        real_submit = be.submit

        async def slow_submit(tx):
            order.append("submit:" + ("sweep" if tx["payload"] == "" else "msg"))
            if tx["payload"] == "":
                await gate.wait()
            return await real_submit(tx)
        be.submit = slow_submit
        sweep = asyncio.ensure_future(sweep_bot(bot, sender, PAYEE, "mainnet"))
        await asyncio.sleep(0.02)
        msg = asyncio.ensure_future(sender.send(PAYEE, "racing"))
        await asyncio.sleep(0.05)
        assert order == ["submit:sweep"] and not msg.done()      # the message waits
        gate.set()
        res = await sweep
        assert res["ok"]
        try:
            await msg
        except Exception as exc:                                 # wallet is empty now
            assert "Nothing" in str(exc) or "not enough" in str(exc) or "no spendable" in str(exc)
        assert order[0] == "submit:sweep"
    asyncio.run(go())


def test_outbox_round_trip(tmp_path):
    from test_chain import make_daemon

    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(None, outbox_sweep, str(tmp_path / "state"), "mining-1", PAYEE, 10)
        for _ in range(60):
            await asyncio.sleep(0.05)
            await d.process_outbox()
            if fut.done():
                break
        res = await fut
        assert set(res) == KEYS and res["ok"] and be.submitted[-1]["out"][0] == PAYEE
        d.write_statuses()
        st = read_json(str(tmp_path / "state" / "bots" / "mining-1.json"))
        assert st["balanceSompi"] == 0 and st["owner"] is None
        hist = (tmp_path / "state" / "bots" / "mining-1.history.jsonl").read_text().splitlines()
        assert json.loads(hist[-1])["text"].endswith("(all funds)")
        bad = loop.run_in_executor(None, outbox_sweep, str(tmp_path / "state"), "nope", PAYEE, 10)
        for _ in range(60):
            await asyncio.sleep(0.05)
            await d.process_outbox()
            if bad.done():
                break
        assert (await bad)["error"] == "no such bot"
        for t in d.workers.values():
            t.cancel()
    asyncio.run(go())


def test_sdk_layer_builds_one_output_and_no_payload(monkeypatch):
    calls = {}
    fake = types.ModuleType("kaspa")
    fake.Address = lambda a: ("Address", a)
    fake.PaymentOutput = lambda a, v: ("Out", a, v)
    fake.PrivateKey = lambda k: ("Key",)

    def create_transaction(entries, outputs, fee, payload, sig_ops):
        calls.update(entries=entries, outputs=outputs, fee=fee, payload=payload, sig_ops=sig_ops)
        return "tx"
    fake.create_transaction = create_transaction
    fake.update_transaction_mass = lambda net, tx: True
    fake.sign_transaction = lambda tx, keys, verify: "signed"
    monkeypatch.setitem(sys.modules, "kaspa", fake)
    be = KaspaSdkBackend("ws://none", "mainnet")
    assert be.build_and_sign([{"e": 1}], PAYEE, 123, "", BOT_KEY, 7) == "signed"
    assert calls["outputs"] == [("Out", ("Address", PAYEE), 123)] and calls["payload"] is None
    be.build_and_sign([{"e": 1}], BOT, 5, "kchat:1:comm:x", BOT_KEY, 7)
    assert calls["payload"] == "kchat:1:comm:x".encode().hex()
