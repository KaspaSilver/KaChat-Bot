"""Discovery through the real generated protobuf messages (field names checked
against proto/), and the daemon end to end with a fake node and SDK backend."""
import asyncio
import json
import os
import time

import rpc_pb2
from conftest import BOT_KEY, OTHER_KEY, USER_KEY, FakeBackend, addr

from kachat.address import script_for_address, short_address
from kachat.bots.base import NOT_PRIVATE_NOTICE
from kachat.alias import send_alias, watch_alias
from kachat.chain import ChainFollower, chain_tx_from_pb, is_chat_payload_hex
from kachat.crypto import open_sealed
from kachat.daemon import Daemon, outbox_send
from kachat.payload import parse_payload
from kachat.send import build_payload
from kachat.state import read_json

BOT = addr(BOT_KEY)
USER = addr(USER_KEY)
OTHER = addr(OTHER_KEY)
_n = [0]


def make_tx(payload: str, sender: str, out_addr: str = None, address_field=True, prev=None):
    _n[0] += 1
    tx = rpc_pb2.RpcOptionalTransaction()
    tx.verboseData.transactionId = f"{0x7000 + _n[0]:064x}"
    tx.payload = payload.encode().hex()
    inp = tx.inputs.add()
    inp.previousOutpoint.transactionId = (prev or ("ee" * 32, 0))[0]
    inp.previousOutpoint.index = (prev or ("ee" * 32, 0))[1]
    u = inp.verboseData.utxoEntry
    u.amount = 100_000_000
    u.scriptPublicKey.version = 0
    u.scriptPublicKey.scriptPublicKey = script_for_address(sender).hex()
    if address_field:
        u.verboseData.scriptPublicKeyAddress = sender
    out = tx.outputs.add()
    out.value = 99_800_000
    out.scriptPublicKey.scriptPublicKey = script_for_address(out_addr or sender).hex()
    if address_field:
        out.verboseData.scriptPublicKeyAddress = out_addr or sender
    return tx


def vspc(txs, start="00" * 32, n_blocks=1, removed=()):
    r = rpc_pb2.GetVirtualChainFromBlockV2ResponseMessage()
    r.removedChainBlockHashes.extend(removed)
    for i in range(n_blocks):
        r.addedChainBlockHashes.append(f"{0xb000 + _n[0] * 10 + i:064x}")
    blk = r.chainBlockAcceptedTransactions.add()
    blk.chainBlockHeader.hash = r.addedChainBlockHashes[-1]
    blk.chainBlockHeader.timestamp = 1_800_000_000_000
    for t in txs:
        blk.acceptedTransactions.add().CopyFrom(t)
    return r


class FakeNode:
    def __init__(self):
        self.responses = []
        self.calls = []
        self.balance = 2_000_000_000

    async def get_sink(self):
        return "aa" * 32

    async def get_virtual_chain_v2(self, start, minconf=0):
        self.calls.append(start)
        return self.responses.pop(0) if self.responses else rpc_pb2.GetVirtualChainFromBlockV2ResponseMessage()

    async def get_balance(self, address):
        return self.balance

    async def get_utxos(self, addresses):
        return []


def user_msg(text, first=False, key=USER_KEY, to=BOT):
    return build_payload(key, to, text, first_contact=first)


# ── pure parsing ────────────────────────────────────────────────────────────

def test_sender_from_address_field_and_from_script():
    for field in (True, False):
        ct = chain_tx_from_pb(make_tx(user_msg("x"), USER, address_field=field), "kaspa", "bb", 1)
        assert ct.sender == USER and ct.outputs[0] == (USER, 99_800_000)
        assert is_chat_payload_hex(ct.payload_hex)


def test_sender_requires_self_send_shape():
    ct = chain_tx_from_pb(make_tx(user_msg("x"), USER, out_addr=OTHER), "kaspa", "bb", 1)
    assert ct.sender is None
    tx = make_tx(user_msg("x"), USER)
    tx.ClearField("verboseData")
    assert chain_tx_from_pb(tx, "kaspa", "bb", 1) is None


def test_follower_checkpoints_and_filters():
    node = FakeNode()
    seen, saved = [], []
    chat = make_tx(user_msg("hi"), USER)
    noise = make_tx("kchat:1:bcast:general:hello", USER)
    node.responses = [vspc([chat, noise], removed=["dd" * 32])]

    async def on_tx(ct):
        seen.append(ct.txid)

    f = ChainFollower(node, "kaspa", lambda: None, saved.append, on_tx,
                      want=lambda tx: is_chat_payload_hex(tx.payload))
    new = asyncio.run(f.step("aa" * 32))
    assert seen == [chat.verboseData.transactionId]
    assert new != "aa" * 32
    assert asyncio.run(f.step(new)) == new           # nothing new: checkpoint kept


# ── the daemon end to end ───────────────────────────────────────────────────

def write_conf(tmp_path, **over):
    b = {"id": "mining-1", "type": "mining", "enabled": True, "privateKeyHex": BOT_KEY,
         "address": BOT, "pairingCode": "482915"}
    b.update(over)
    p = tmp_path / "bots.json"
    p.write_text(json.dumps({"version": 1, "bots": [b]}))
    return str(p)


def make_daemon(tmp_path, **kw):
    node = FakeNode()
    be = FakeBackend(BOT, (5_000_000_000,))
    d = Daemon(conf_path=write_conf(tmp_path, **kw), state_dir=str(tmp_path / "state"), network="mainnet",
               grpc_target="none", wrpc_url="none", node=node, backend=be)
    return d, node, be


def replies(be, key=USER_KEY):
    out = []
    for tx in be.submitted:
        cp = parse_payload(tx["payload"].encode())
        assert cp.kind == "comm"
        out.append((cp.alias, open_sealed(cp.sealed, key)))
    return out


async def _settle():
    for _ in range(20):
        await asyncio.sleep(0.01)


def test_daemon_pairs_over_chain_and_replies_on_users_alias(tmp_path):
    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        bot = d.bots["mining-1"]
        f = ChainFollower(node, "kaspa", lambda: None, lambda h: None, d.on_chain_tx, d.want_tx)
        # a stranger's chat with someone else, a spoofed send, then the user's first contact (dm)
        node.responses = [vspc([
            make_tx(user_msg("482915", key=OTHER_KEY, to=USER), OTHER),
            make_tx(user_msg("482915", first=True, key=OTHER_KEY), OTHER, out_addr=USER),
            make_tx(user_msg("hello 482915", first=True), USER),
        ])]
        await f.step("aa" * 32)
        await _settle()
        alias, text = replies(be)[-1]
        assert alias == watch_alias(USER_KEY, BOT) == send_alias(BOT_KEY, USER)
        assert text == NOT_PRIVATE_NOTICE                                  # public: no pairing, agree first
        # later messages are plain comm on the user's send alias
        node.responses = [vspc([make_tx(user_msg("agree"), USER)])]
        await f.step("ab" * 32)
        await _settle()
        assert bot.owner is None and bot.people[USER].owner == USER
        assert replies(be)[-1][1].startswith("Thanks! I'm the KaChat Mining bot")
        node.responses = [vspc([make_tx(user_msg(addr("44" * 32)), USER)])]
        await f.step("bb" * 32)
        await _settle()
        assert "2/2" in replies(be)[-1][1]
        d.write_statuses()
        st = read_json(str(tmp_path / "state" / "bots" / "mining-1.json"))
        assert st["owner"] is None and st["stage"] == "active" and st["address"] == BOT
        assert st["stats"]["people"] >= 1
        hist = [json.loads(h) for h in (tmp_path / "state" / "bots" / "mining-1.history.jsonl").read_text().splitlines()]
        mine = [h for h in hist if short_address(USER) in h["text"]]
        assert [h["dir"] for h in mine] == ["in", "out", "in", "out", "in", "out"]
        # the person's conversation is its own file next to the bot's
        assert os.listdir(tmp_path / "state" / "botd" / "mining-1")
        for t in d.workers.values():
            t.cancel()
    asyncio.run(go())


def test_daemon_dedupes_reaccepted_tx(tmp_path):
    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        tx = make_tx(user_msg("482915", first=True), USER)
        f = ChainFollower(node, "kaspa", lambda: None, lambda h: None, d.on_chain_tx, d.want_tx)
        node.responses = [vspc([tx]), vspc([tx], removed=["cc" * 32])]
        await f.step("aa" * 32)
        await f.step("bb" * 32)
        await _settle()
        assert len(be.submitted) == 1
        for t in d.workers.values():
            t.cancel()
    asyncio.run(go())


def test_indexer_backfill_fills_gaps(tmp_path):
    class FakeIndexer:
        def __init__(self, rows):
            self.rows = rows

        def inbox_page(self, tag, block_time, limit):
            assert tag == d.bots["mining-1"].inbox_tag
            return [{"txid": "f1" * 32, "sender": USER, "block_time": 1, "b64": ""}], 1, 1

        def by_sender(self, sender, alias, block_time, limit):
            assert alias == watch_alias(BOT_KEY, sender)
            return self.rows if sender == USER else []

    def row(txid, text, first=False):
        p = user_msg(text, first=first)
        return {"txid": txid, "sender": USER, "block_time": 1_800_000_000_000,
                "b64": p.split(":")[-1]}

    async def go():
        nonlocal d
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        d.indexer = FakeIndexer([row("f1" * 32, "482915", True), row("f0" * 32, "agree"), row("f2" * 32, "kaspa:bad")])
        await d.backfill(d.bots["mining-1"])
        await _settle()
        assert d.bots["mining-1"].people[USER].owner == USER
        assert len(be.submitted) == 3 and "doesn't look right" in replies(be)[-1][1]
        await d.backfill(d.bots["mining-1"])          # same rows: nothing new
        await _settle()
        assert len(be.submitted) == 3
        assert d.bots["mining-1"].data["indexerCursorMs"] > 0
        for t in d.workers.values():
            t.cancel()
    d = None
    asyncio.run(go())


def test_outbox_and_utxo_dispatch(tmp_path):
    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        bot = d.bots["mining-1"]
        p = bot._person(USER)
        p.data.update(owner=USER, stage="active",
                      settings={"address": addr("44" * 32), "minRewardKas": 0, "hashrateDropPct": None})
        # --send through the outbox: no owner any more, so the panel names the address
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(None, lambda: outbox_send(str(tmp_path / "state"), "mining-1", "Alert: test", 10, to=USER))
        for _ in range(50):
            await asyncio.sleep(0.05)
            await d.process_outbox()
            if fut.done():
                break
        res = await fut
        assert res["ok"] and res["txid"]
        assert replies(be)[-1][1] == "Alert: test"
        # a coinbase reward on the watched address
        await d.dispatch_utxos({addr("44" * 32): ([{"address": addr("44" * 32), "txid": "c0" * 32, "index": 0,
                                                     "amount": 400_000_000, "isCoinbase": True,
                                                     "blockDaaScore": 5}], [])})
        await bot.tick(time.time() + 4)                     # rewards are reported once settled
        assert replies(be)[-1][1].startswith("Block reward: 4 KAS")
        assert os.listdir(tmp_path / "state" / "botd" / "outbox") == []
        for t in d.workers.values():
            t.cancel()
    asyncio.run(go())


def test_disabled_and_removed_bots(tmp_path):
    async def go():
        d, node, be = make_daemon(tmp_path, enabled=False)
        d.reload_config()
        tx = make_tx(user_msg("482915", first=True), USER)
        await d.on_chain_tx(chain_tx_from_pb(tx, "kaspa", "bb", 1))
        await _settle()
        assert be.submitted == [] and d.bots["mining-1"].status()["stage"] == "disabled"
        (tmp_path / "bots.json").write_text(json.dumps({"version": 1, "bots": []}))
        os.utime(tmp_path / "bots.json", ns=(1, 2_000_000_000_000_000_000))
        d.reload_config()
        assert d.bots == {}
    asyncio.run(go())



def test_panel_alert_to_someone_who_never_wrote_is_a_first_contact(tmp_path):
    """BOT-006: an untagged message from an unknown sender never shows in KaChat; the alert must be a dm."""
    from kachat.alias import inbox_tag

    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(None, lambda: outbox_send(str(tmp_path / "state"), "mining-1", "Alert: low", 10, to=USER))
        for _ in range(50):
            await asyncio.sleep(0.05)
            await d.process_outbox()
            if fut.done():
                break
        assert (await fut)["ok"]
        cp = parse_payload(be.submitted[-1]["payload"].encode())
        assert cp.kind == "dm" and cp.tag == inbox_tag(USER)
        assert open_sealed(cp.sealed, USER_KEY) == "Alert: low"
        for t in d.workers.values():
            t.cancel()
    asyncio.run(go())


def test_an_outbox_request_is_never_acted_on_twice(tmp_path):
    """BOT-009: a request whose file cannot be removed (left by another user) is not sent again."""
    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        outbox = tmp_path / "state" / "botd" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        req = outbox / "x1.req.json"
        req.write_text(json.dumps({"bot": "mining-1", "text": "Alert", "to": USER, "createdAt": time.time()}))
        real_remove = os.remove
        os.remove = lambda p: (_ for _ in ()).throw(PermissionError("root-owned"))   # cannot remove it
        try:
            await d.process_outbox()
            await d.process_outbox()
            await d.process_outbox()
        finally:
            os.remove = real_remove
        assert len(be.submitted) == 1                          # sent once, not three times
        for t in d.workers.values():
            t.cancel()
    asyncio.run(go())


def test_backfill_reads_every_first_contact_page(tmp_path):
    """BOT-011: more than 100 first contacts since the cursor are all found."""
    senders = [addr(f"{0x40 + i:02x}" * 32) for i in range(150)]

    class FakeIndexer:
        def __init__(self):
            self.inbox_calls = []
            self.asked = set()

        def inbox_page(self, tag, block_time, limit):
            self.inbox_calls.append(block_time)
            rows = [{"txid": f"{i:064x}", "sender": s, "block_time": 1000 + i, "b64": ""}
                    for i, s in enumerate(senders) if 1000 + i >= block_time][:limit]
            return rows, len(rows), rows[-1]["block_time"] if rows else block_time

        def by_sender(self, sender, alias, block_time, limit):
            self.asked.add(sender)
            return []

    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        bot = d.bots["mining-1"]
        bot.data["indexerCursorMs"] = 1
        d.indexer = FakeIndexer()
        await d.backfill(bot)
        assert len(d.indexer.inbox_calls) == 2                       # 100, then the last 50
        assert set(senders) <= d.indexer.asked
        for t in d.workers.values():
            t.cancel()
    asyncio.run(go())


class _RawInbox:
    """The indexer's by-inbox route over raw rows (block_time inclusive, at most `limit`), for a
    real IndexerClient: rows it can't read still fill the page, as on the live indexer."""

    def __init__(self, raw):
        self.raw = sorted(raw, key=lambda r: r["block_time"])
        self.calls = []

    def __call__(self, req, timeout=None):
        import io, json, urllib.parse
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        if "by-inbox" not in req.full_url:
            body = []
        else:
            since, limit = int(q["block_time"]), int(q["limit"])
            self.calls.append((since, limit))
            body = [r for r in self.raw if r["block_time"] >= since][:limit]

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Resp(json.dumps(body).encode())


def _raw_row(i, sender, block_time, payload="kchat:1:dm:x:AAAA"):
    return {"tx_id": f"{i:064x}", "sender": sender, "block_time": block_time,
            "message_payload": payload.encode("latin-1").hex()}


def _asked_senders(tmp_path, raw):
    from kachat.chain import IndexerClient
    asked = set()
    opener = _RawInbox(raw)
    client = IndexerClient("http://indexer", opener=opener)
    client.by_sender = lambda sender, alias, block_time, limit: asked.add(sender) or []

    async def go():
        d, node, be = make_daemon(tmp_path)
        d.reload_config()
        bot = d.bots["mining-1"]
        bot.data["indexerCursorMs"] = 1
        d.indexer = client
        await d.backfill(bot)
        for t in d.workers.values():
            t.cancel()
        return bot.data["indexerCursorMs"]
    return asked, opener.calls, asyncio.run(go())


def test_backfill_pages_past_unreadable_rows(tmp_path):
    """BOT-011 (run 9): a row with a non-text payload in a full page doesn't end the paging."""
    senders = [addr(f"{0x40 + i:02x}" * 32) for i in range(150)]
    raw = [_raw_row(i, s, 1000 + i) for i, s in enumerate(senders)]
    raw[10] = _raw_row(10, senders[10], 1010, "kchat:1:dm:x:\xff\xfe")      # junk inside page one
    asked, calls, _ = _asked_senders(tmp_path, raw)
    assert len(calls) == 2
    assert set(senders) - {senders[10]} <= asked


def test_backfill_reads_a_crowded_block_time(tmp_path):
    """BOT-011 (run 9): more than a page of first contacts at one block time are all read."""
    senders = [addr(f"{i + 0x4000:04x}" * 16) for i in range(180)]
    raw = [_raw_row(i, s, 5000) for i, s in enumerate(senders[:150])]
    raw += [_raw_row(200 + i, s, 6000 + i) for i, s in enumerate(senders[150:])]
    asked, calls, _ = _asked_senders(tmp_path, raw)
    assert calls[:2] == [(1, 100), (5000, 100)] and calls[2] == (5000, 500)
    assert set(senders) <= asked


def test_backfill_cursor_stays_when_not_done(tmp_path):
    """BOT-011 (run 9): when the run stops before a short page, the cursor only moves to the last
    block time read, never to now."""
    import kachat.daemon as daemon
    senders = [addr(f"{0x40 + i:02x}" * 32) for i in range(150)]
    raw = [_raw_row(i, s, 1000 + i) for i, s in enumerate(senders)]
    old = daemon.INBOX_PAGES
    daemon.INBOX_PAGES = 1
    try:
        _, calls, cursor = _asked_senders(tmp_path, raw)
    finally:
        daemon.INBOX_PAGES = old
    assert calls == [(1, 100)] and cursor == 1099

