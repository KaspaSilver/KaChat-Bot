"""Shared test setup: compile proto/ into a temp dir (so the chain tests use
the real generated messages and their field names), plus fakes for the
node, the SDK backend and the bot context. Nothing here touches a network."""
import asyncio
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_PB_DIR = tempfile.mkdtemp(prefix="kachat-pb-")


def _compile_protos():
    from grpc_tools import protoc
    proto = os.path.join(ROOT, "proto")
    import grpc_tools
    include = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
    rc = protoc.main(["protoc", f"-I{proto}", f"-I{include}", f"--python_out={_PB_DIR}",
                      f"--grpc_python_out={_PB_DIR}",
                      os.path.join(proto, "messages.proto"), os.path.join(proto, "rpc.proto")])
    assert rc == 0, "protoc failed"
    sys.path.insert(0, _PB_DIR)


_compile_protos()

from kachat.address import address_from_xonly  # noqa: E402
from kachat.crypto import xonly_from_private  # noqa: E402

BOT_KEY = "33" * 32
USER_KEY = "11" * 32
OTHER_KEY = "22" * 32
NET = "mainnet"


def addr(key, net=NET):
    return address_from_xonly(xonly_from_private(key), net)


def run(coro):
    return asyncio.run(coro)


class FakeStore:
    """In-memory BotStore."""

    def __init__(self):
        self.data = {}
        self.status = None
        self.history = []
        self.history_path = "/nonexistent/history"

    def load_data(self):
        return dict(self.data)

    def save_data(self, data):
        import json
        self.data = json.loads(json.dumps(data))

    def write_status(self, s):
        self.status = s

    def append_history(self, d, text, txid, ts=None):
        self.history.append({"dir": d, "text": text, "txid": txid})


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeCtxFactory:
    def __init__(self):
        self.sent = []          # (bot id, recipient, text)
        self.fail = False
        self.clock = Clock()
        self.balance = 5_000_000_000
        self.price = None
        self.hashrate = None
        self.spenders = {}

    def make(self, max_out=30):
        from kachat.bots import BotContext

        async def send(bot, recipient, text):
            if self.fail:
                raise RuntimeError("node down")
            self.sent.append((bot.id, recipient, text))
            return f"{len(self.sent):064x}"

        async def get_balance(a):
            return self.balance

        async def fetch_price(cur):
            return self.price

        async def fetch_hashrate():
            return self.hashrate

        return BotContext(network=NET, send=send, get_balance=get_balance, clock=self.clock,
                          fetch_price=fetch_price, fetch_hashrate=fetch_hashrate,
                          spender_of=lambda k: self.spenders.get(k), max_out_per_hour=max_out)


def make_cfg(bot_type="mining", key=BOT_KEY, code="482915", enabled=True, reset=None, bid=None):
    from kachat.state import BotConfig
    return BotConfig(id=bid or f"{bot_type}-1", type=bot_type, enabled=enabled, private_key_hex=key,
                     address=addr(key), pairing_code=code, reset_owner=reset)


@pytest.fixture
def ctxf():
    return FakeCtxFactory()


@pytest.fixture
def make_bot(ctxf):
    from kachat.bots import make_bot as mk

    def _make(bot_type="mining", store=None, max_out=30, **kw):
        return mk(make_cfg(bot_type, **kw), store or FakeStore(), ctxf.make(max_out))
    return _make


class FakeBackend:
    """Stands in for the Kaspa SDK: keeps a UTXO set, 'signs' by recording."""

    def __init__(self, address, amounts=(1_000_000_000,)):
        self.address = address
        self.utxos = [self.entry(f"{i + 1:064x}", 0, a, daa=100) for i, a in enumerate(amounts)]
        self.submitted = []
        self.fail_next = 0

    def entry(self, txid, index, amount, daa=100, coinbase=False):
        return {"address": self.address, "outpoint": {"transactionId": txid, "index": index},
                "utxoEntry": {"amount": amount, "scriptPublicKey": "0000" + "20" + "ab" * 32 + "ac",
                              "blockDaaScore": daa, "isCoinbase": coinbase}}

    async def get_utxos(self, address):
        return [dict(e) for e in self.utxos]

    def build_and_sign(self, entries, address, amount, payload, priv, fee):
        return {"inputs": [e["outpoint"] for e in entries], "in_amounts": [e["utxoEntry"]["amount"] for e in entries],
                "out": (address, amount), "payload": payload, "fee": fee}

    async def submit(self, tx):
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("transaction already spent")
        spent = {(o["transactionId"], o["index"]) for o in tx["inputs"]}
        for s in self.submitted:
            if spent & {(o["transactionId"], o["index"]) for o in s["inputs"]}:
                raise RuntimeError("double spend")
        self.submitted.append(tx)
        return f"{0xabc000 + len(self.submitted):064x}"
