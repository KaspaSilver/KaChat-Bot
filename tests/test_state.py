import json
import os
import time

from conftest import BOT_KEY, addr

from kachat.state import HISTORY_MAX, BotStore, ConfigWatcher, atomic_write_json, parse_config, read_json


def conf(**over):
    b = {"id": "mining-3f9a", "type": "mining", "enabled": True, "privateKeyHex": BOT_KEY,
         "address": addr(BOT_KEY), "pairingCode": "482915"}
    b.update(over)
    return {"version": 1, "bots": [b]}


def test_parse_config_accepts_contract_example():
    bots, problems = parse_config(conf(resetOwner="abc"))
    assert problems == []
    b = bots[0]
    assert (b.id, b.type, b.enabled, b.pairing_code, b.reset_owner) == ("mining-3f9a", "mining", True, "482915", "abc")


def test_parse_config_rejects_bad_entries():
    for bad, word in [({"id": "Bad_ID"}, "id"), ({"type": "chess"}, "type"), ({"privateKeyHex": "12"}, "privateKeyHex"),
                      ({"pairingCode": "12345"}, "pairingCode")]:
        bots, problems = parse_config(conf(**bad))
        assert bots == [] and word in problems[0]
    two = conf()
    two["bots"].append(dict(two["bots"][0]))
    bots, problems = parse_config(two)
    assert len(bots) == 1 and "duplicate" in problems[0]
    assert parse_config({"nope": 1})[0] == []
    bots, _ = parse_config(conf(enabled=False))
    assert bots[0].enabled is False


def test_atomic_write_leaves_no_temp_files(tmp_path):
    p = tmp_path / "bots" / "x.json"
    atomic_write_json(str(p), {"a": 1})
    atomic_write_json(str(p), {"a": 2})
    assert read_json(str(p)) == {"a": 2}
    assert os.listdir(tmp_path / "bots") == ["x.json"]


def test_config_hot_reload(tmp_path):
    path = tmp_path / "bots.json"
    w = ConfigWatcher(str(path))
    bots, problems = w.poll()
    assert bots == [] and "not found" in problems[0]
    assert w.poll() is None
    path.write_text(json.dumps(conf()))
    bots, _ = w.poll()
    assert [b.id for b in bots] == ["mining-3f9a"]
    assert w.poll() is None                                  # unchanged
    time.sleep(0.01)
    path.write_text(json.dumps(conf(enabled=False, resetOwner="n1")))
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
    bots, _ = w.poll()
    assert bots[0].enabled is False and bots[0].reset_owner == "n1"
    path.write_text("{half written")
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 20_000_000))
    assert w.poll() is None                                  # retried next poll, nothing applied


def test_store_files_and_history_trim(tmp_path):
    s = BotStore(str(tmp_path), "price-1")
    s.write_status({"id": "price-1"})
    s.save_data({"owner": None})
    assert read_json(str(tmp_path / "bots" / "price-1.json")) == {"id": "price-1"}
    assert oct(os.stat(tmp_path / "botd" / "price-1.json").st_mode & 0o777) == "0o600"
    for i in range(HISTORY_MAX + 20):
        s.append_history("out" if i % 2 else "in", f"m{i}", None if i % 2 == 0 else "ab", 1000 + i)
    lines = (tmp_path / "bots" / "price-1.history.jsonl").read_text().splitlines()
    assert len(lines) == HISTORY_MAX
    last = json.loads(lines[-1])
    assert last == {"ts": 1000 + HISTORY_MAX + 19, "dir": "out", "text": f"m{HISTORY_MAX + 19}", "txid": "ab"}
    assert json.loads(lines[0])["text"] == "m20"


def test_reset_owner_through_real_store(tmp_path):
    from conftest import FakeCtxFactory, make_cfg
    from kachat.bots import make_bot
    f = FakeCtxFactory()
    store = BotStore(str(tmp_path), "mining-1")
    bot = make_bot(make_cfg("mining"), store, f.make())
    import asyncio
    asyncio.run(bot.handle_message(addr("11" * 32), "482915", "aa" * 32))
    assert os.path.exists(store.history_path)
    bot2 = make_bot(make_cfg("mining", reset="r1"), store, f.make())
    assert bot2.owner is None and not os.path.exists(store.history_path)
    assert read_json(store.data_path)["resetOwnerSeen"] == "r1"
