"""The daemon hosting every bot in /conf/bots.json.

One gRPC connection serves all bots: a chain follower (incoming messages and
wallet spends), one UtxosChanged subscription (mining rewards, wallet
activity) and balance lookups. Sending goes through the Kaspa SDK over wRPC,
one message at a time per bot wallet.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import logging
import os
import time
import uuid
from typing import Dict, Optional

from .address import AddressError, prefix_for_network, short_address, validate_address
from .alias import watch_alias
from .bots import Bot, BotContext, make_bot
from .chain import ChainFollower, ChainTx, IndexerClient, is_chat_payload_hex
from .crypto import CryptoError, open_sealed
from .feeds import fetch_bridge_hashrate, fetch_market, fetch_price
from .node import GrpcNode, utxo_entry_dict
from .payload import message_text, parse_payload
from .send import InsufficientFunds, KaspaSdkBackend, MessageSender, SOMPI_PER_KAS
from .state import BotStore, ConfigWatcher, atomic_write_json, read_json

log = logging.getLogger("kachat.daemon")

STATUS_EVERY = 60.0
BALANCE_EVERY = 60.0
CONFIG_POLL = 5.0
INDEXER_EVERY = 300.0
INDEXER_OVERLAP_MS = 15 * 60 * 1000
SPENT_KEEP = 120.0
HEARTBEAT_EVERY = 5.0


class Daemon:
    def __init__(self, *, conf_path: str, state_dir: str, network: str, grpc_target: str, wrpc_url: str,
                 indexer_url: str = "", bridge_url: str = "", max_out_per_hour: int = 50,
                 chain_poll: float = 1.0, node=None, backend=None):
        self.conf_path = conf_path
        self.state_dir = state_dir
        self.network = network
        self.prefix = prefix_for_network(network)
        self.node = node or GrpcNode(grpc_target)
        self.backend = backend or KaspaSdkBackend(wrpc_url, network)
        self.indexer = IndexerClient(indexer_url) if indexer_url else None
        self.bridge_url = bridge_url
        self.max_out_per_hour = max_out_per_hour
        self.chain_poll = chain_poll
        self.watcher = ConfigWatcher(conf_path)
        self.bots: Dict[str, Bot] = {}
        self._price_cache: Dict[str, tuple] = {}
        self.self_sends: "collections.OrderedDict[str, bool]" = collections.OrderedDict()
        self.senders: Dict[str, MessageSender] = {}
        self.queues: Dict[str, asyncio.Queue] = {}
        self.workers: Dict[str, asyncio.Task] = {}
        self.queued: Dict[str, collections.OrderedDict] = {}
        self.dirty: set = set()
        self.node_error: Optional[str] = None
        self.spenders: "collections.OrderedDict[str, str]" = collections.OrderedDict()
        self.wallet_outpoints: Dict[str, Optional[float]] = {}   # outpoint key -> expiry (None = live)
        self._utxo_task: Optional[asyncio.Task] = None
        self._utxo_addrs: frozenset = frozenset()
        self.botd_dir = os.path.join(state_dir, "botd")
        self.outbox_dir = os.path.join(self.botd_dir, "outbox")
        self.checkpoint_path = os.path.join(self.botd_dir, "chain.json")

    # ── context given to bots ───────────────────────────────────────────────

    def _ctx(self) -> BotContext:
        return BotContext(
            network=self.network,
            send=self._send,
            get_balance=self._balance,
            fetch_price=self._price,
            fetch_market=self._market,
            fetch_hashrate=self._hashrate if self.bridge_url else None,
            spender_of=lambda key: self.spenders.get(key),
            self_send_of=lambda txid: self.self_sends.get(txid),
            max_out_per_hour=self.max_out_per_hour,
            on_change=lambda bot: self.dirty.add(bot.id),
        )

    async def _send(self, bot: Bot, recipient: str, text: str, first_contact: bool = False) -> str:
        txid = await self.senders[bot.id].send(recipient, text, first_contact=first_contact)
        owner = self.bots.get(bot.id, bot)          # a public bot's person shares its host's wallet
        asyncio.get_running_loop().call_later(5, lambda: asyncio.ensure_future(self._refresh_balance(owner)))
        return txid

    async def _balance(self, address: str) -> Optional[int]:
        try:
            return await self.node.get_balance(address)
        except Exception as exc:
            log.info("balance of %s unavailable: %s", address, exc)
            return None

    async def _market(self):
        # The Kaspa answers bot's live price and market cap: one fetch a minute serves everyone.
        hit = self._price_cache.get("market")
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        got = await asyncio.to_thread(fetch_market)
        if got:
            self._price_cache["market"] = (time.time(), got)
        return got

    async def _price(self, currency: str):
        # Every person on a public price bot polls; one fetch a minute serves them all.
        hit = self._price_cache.get(currency)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        got = await asyncio.to_thread(fetch_price, currency)
        if got:
            self._price_cache[currency] = (time.time(), got)
        return got

    async def _hashrate(self):
        return await asyncio.to_thread(fetch_bridge_hashrate, self.bridge_url)

    async def _refresh_balance(self, bot: Bot) -> None:
        bal = await self._balance(bot.address)
        if bal is not None:
            bot.balance = bal
            self.dirty.add(bot.id)

    # ── config ──────────────────────────────────────────────────────────────

    def reload_config(self) -> bool:
        res = self.watcher.poll()
        if res is None:
            return False
        cfgs, problems = res
        for p in problems:
            log.warning("bots.json: %s", p)
        wanted = {c.id: c for c in cfgs}
        for bid in list(self.bots):
            if bid not in wanted:
                log.info("[%s] removed from bots.json: stopping", bid)
                self._stop_bot(bid)
        for cfg in cfgs:
            bot = self.bots.get(cfg.id)
            if bot is not None and (bot.cfg.private_key_hex != cfg.private_key_hex or bot.cfg.type != cfg.type):
                self._stop_bot(cfg.id)
                bot = None
            if bot is None:
                self._start_bot(cfg)
            else:
                bot.apply_config(cfg)
            self.dirty.add(cfg.id)
        return True

    def _start_bot(self, cfg) -> None:
        bot = make_bot(cfg, BotStore(self.state_dir, cfg.id), self._ctx())
        self.bots[cfg.id] = bot
        self.senders[cfg.id] = MessageSender(bot.priv_hex, bot.address, self.backend)
        q: asyncio.Queue = asyncio.Queue()
        self.queues[cfg.id] = q
        self.queued[cfg.id] = collections.OrderedDict()
        self.workers[cfg.id] = asyncio.ensure_future(self._worker(bot, q))
        log.info("[%s] %s bot %s (%s)", cfg.id, cfg.type, bot.address, "enabled" if cfg.enabled else "disabled")
        asyncio.ensure_future(self._refresh_balance(bot))

    def _stop_bot(self, bid: str) -> None:
        t = self.workers.pop(bid, None)
        if t:
            t.cancel()
        self.bots.pop(bid, None)
        self.senders.pop(bid, None)
        self.queues.pop(bid, None)
        self.queued.pop(bid, None)

    # ── incoming messages ───────────────────────────────────────────────────

    def enqueue(self, bot: Bot, sender: str, text: str, txid: str, ts: float) -> None:
        q = self.queued[bot.id]
        if txid in q or bot.seen(txid):
            return
        q[txid] = True
        while len(q) > 2000:
            q.popitem(last=False)
        self.queues[bot.id].put_nowait((sender, text, txid, ts))

    async def _worker(self, bot: Bot, q: asyncio.Queue) -> None:
        while True:
            sender, text, txid, ts = await q.get()
            try:
                await bot.handle_message(sender, text, txid, ts)
            except Exception:
                log.exception("[%s] handling %s failed", bot.id, txid)

    def match_message(self, bot: Bot, sender: str, cp) -> Optional[str]:
        """The decrypted text if this payload from `sender` is a message to `bot`."""
        if not bot.enabled or sender == bot.address:
            return None
        if cp.kind == "dm" and cp.tag != bot.inbox_tag:
            return None                       # first contact to someone else
        try:
            wa = watch_alias(bot.priv_hex, sender)
        except (AddressError, CryptoError, ValueError):
            return None                       # not a chat-capable address
        if cp.alias != wa and cp.kind != "dm" and sender != bot.owner:
            return None
        try:
            plain = open_sealed(cp.sealed, bot.priv_hex)
        except CryptoError:
            return None
        return message_text(plain)

    def route_payload(self, sender: str, payload: bytes, txid: str, ts: float) -> None:
        cp = parse_payload(payload)
        if cp is None:
            return
        for bot in list(self.bots.values()):
            if bot.seen(txid) or txid in self.queued.get(bot.id, {}):
                continue
            text = self.match_message(bot, sender, cp)
            if text is not None:
                self.enqueue(bot, sender, text, txid, ts)

    def want_tx(self, tx) -> bool:
        if tx.HasField("payload") and is_chat_payload_hex(tx.payload):
            return True
        if self.wallet_outpoints:
            for inp in tx.inputs:
                po = inp.previousOutpoint
                if f"{po.transactionId}:{po.index}" in self.wallet_outpoints:
                    return True
        return False

    def note_self_send(self, ct: ChainTx) -> None:
        """A tx whose every input and output is one address moved nothing anywhere: a bot's
        message or a wallet compound, which wallet bots never report (BOT-001). Recorded for every
        tx the follower hands over (each chat message, each spend of a watched coin), not only one
        spending a coin already known: a bot's back-to-back messages chain on each other's unseen
        outputs, and the node reports them as one change."""
        addrs = {a for (_, _, a, _) in ct.inputs} | {a for (a, _) in ct.outputs}
        self.self_sends[ct.txid] = len(addrs) == 1 and None not in addrs
        while len(self.self_sends) > 20000:
            self.self_sends.popitem(last=False)

    async def on_chain_tx(self, ct: ChainTx) -> None:
        self.note_self_send(ct)
        if self.wallet_outpoints:
            for (ptx, pidx, _, _) in ct.inputs:
                key = f"{ptx}:{pidx}"
                if key in self.wallet_outpoints:
                    self.spenders[key] = ct.txid
                    while len(self.spenders) > 5000:
                        self.spenders.popitem(last=False)
        if is_chat_payload_hex(ct.payload_hex):
            sender = ct.sender
            if sender:
                self.route_payload(sender, bytes.fromhex(ct.payload_hex), ct.txid, ct.block_time_ms / 1000)

    # ── loops ───────────────────────────────────────────────────────────────

    def _load_checkpoint(self) -> Optional[str]:
        d = read_json(self.checkpoint_path, {}) or {}
        if d.get("network") not in (None, self.network):
            return None
        return d.get("hash")

    def _save_checkpoint(self, h: str) -> None:
        atomic_write_json(self.checkpoint_path, {"hash": h, "network": self.network, "at": int(time.time())})

    def _set_node_error(self, err: Optional[str]) -> None:
        if err != self.node_error:
            self.node_error = err
            for bot in self.bots.values():
                bot.node_error = err
                self.dirty.add(bot.id)

    async def chain_loop(self):
        follower = ChainFollower(self.node, self.prefix, self._load_checkpoint, self._save_checkpoint,
                                 self.on_chain_tx, self.want_tx, poll_seconds=self.chain_poll,
                                 on_status=self._set_node_error)
        await follower.run()

    def watched_union(self) -> frozenset:
        out = set()
        for bot in self.bots.values():
            out |= bot.watched_addresses()
        return frozenset(out)

    def wallet_addresses(self) -> set:
        out = set()
        for bot in self.bots.values():
            if bot.TYPE == "wallet":
                out |= bot.watched_addresses()
        return out

    def _ensure_utxo_subscription(self) -> None:
        addrs = self.watched_union()
        running = self._utxo_task is not None and not self._utxo_task.done()
        if addrs == self._utxo_addrs and (running or not addrs):
            return
        if self._utxo_task is not None:
            self._utxo_task.cancel()
            self._utxo_task = None
        self._utxo_addrs = addrs
        if addrs:
            self._utxo_task = asyncio.ensure_future(self._utxo_loop(addrs))

    async def _utxo_loop(self, addrs: frozenset) -> None:
        backoff = 2.0
        while True:
            try:
                wallet = self.wallet_addresses() & set(addrs)
                if wallet:
                    for e in await self.node.get_utxos(sorted(wallet)):
                        self.wallet_outpoints[f"{e['txid']}:{e['index']}"] = None
                log.info("watching %d address(es) for UTXO changes", len(addrs))
                async for n in self.node.utxo_notifications(addrs):
                    backoff = 2.0
                    await self.on_utxos_changed(n)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("UTXO subscription: %s; retrying in %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def on_utxos_changed(self, n) -> None:
        by_addr: Dict[str, tuple] = {}
        for e in n.added:
            d = utxo_entry_dict(e)
            by_addr.setdefault(d["address"], ([], []))[0].append(d)
        for e in n.removed:
            d = utxo_entry_dict(e)
            by_addr.setdefault(d["address"], ([], []))[1].append(d)
        await self.dispatch_utxos(by_addr)

    async def dispatch_utxos(self, by_addr: Dict[str, tuple]) -> None:
        now = time.time()
        wallet = self.wallet_addresses()
        for addr, (added, removed) in by_addr.items():
            if addr in wallet:
                for d in added:
                    self.wallet_outpoints[f"{d['txid']}:{d['index']}"] = None
                for d in removed:
                    self.wallet_outpoints[f"{d['txid']}:{d['index']}"] = now + SPENT_KEEP
            for bot in list(self.bots.values()):
                if addr in bot.watched_addresses():
                    try:
                        await bot.on_utxos(addr, added, removed)
                    except Exception:
                        log.exception("[%s] UTXO handling failed", bot.id)
        self.wallet_outpoints = {k: v for k, v in self.wallet_outpoints.items() if v is None or v > now}

    async def tick_loop(self):
        last_config = 0.0
        last_status = 0.0
        last_balance = 0.0
        last_beat = 0.0
        while True:
            now = time.time()
            if now - last_config >= CONFIG_POLL:
                last_config = now
                try:
                    self.reload_config()
                except Exception:
                    log.exception("reading bots.json failed")
            for bot in list(self.bots.values()):
                if not bot.enabled:
                    continue
                try:
                    await bot.send_pending_greeting()
                    await bot.tick(now)
                except Exception:
                    log.exception("[%s] tick failed", bot.id)
            self._ensure_utxo_subscription()
            await self.process_outbox()
            if now - last_balance >= BALANCE_EVERY:
                last_balance = now
                for bot in list(self.bots.values()):
                    await self._refresh_balance(bot)
            if now - last_status >= STATUS_EVERY:
                last_status = now
                self.dirty |= set(self.bots)
            self.write_statuses()
            if now - last_beat >= HEARTBEAT_EVERY:
                last_beat = now
                try:
                    atomic_write_json(os.path.join(self.botd_dir, "daemon.json"),
                                      {"pid": os.getpid(), "heartbeat": int(now), "network": self.network})
                except OSError as exc:
                    log.warning("heartbeat: %s", exc)
            await asyncio.sleep(1.0)

    def write_statuses(self) -> None:
        for bid in list(self.dirty):
            bot = self.bots.get(bid)
            self.dirty.discard(bid)
            if bot is None:
                continue
            try:
                bot.store.write_status(bot.status())
            except OSError as exc:
                log.warning("[%s] status write failed: %s", bid, exc)

    async def indexer_loop(self):
        await asyncio.sleep(10)
        while True:
            for bot in list(self.bots.values()):
                if not bot.enabled:
                    continue
                try:
                    await self.backfill(bot)
                except Exception as exc:
                    log.info("[%s] indexer backfill: %s", bot.id, exc)
            await asyncio.sleep(INDEXER_EVERY)

    async def backfill(self, bot: Bot) -> None:
        """Messages the chain follower may have missed (downtime), from the indexer."""
        started_ms = int(time.time() * 1000)
        cursor = int(bot.data.get("indexerCursorMs") or int(bot.data.get("createdAt", time.time())) * 1000)
        senders = set()
        rows = await asyncio.to_thread(self.indexer.by_inbox, bot.inbox_tag, cursor, 100)
        for r in rows:
            if r["sender"]:
                senders.add(r["sender"])
        senders |= bot.known_senders()
        for s in sorted(senders):
            try:
                s = validate_address(s, self.network, require_pubkey=True)
                alias = watch_alias(bot.priv_hex, s)
            except (AddressError, CryptoError, ValueError):
                continue
            since = cursor
            for _ in range(20):
                page = await asyncio.to_thread(self.indexer.by_sender, s, alias, since, 50)
                for r in page:
                    if bot.seen(r["txid"]):
                        continue
                    try:
                        sealed = base64.b64decode(r["b64"].split(":")[-1], validate=True)
                        text = message_text(open_sealed(sealed, bot.priv_hex))
                    except (ValueError, CryptoError):
                        continue
                    if text is not None:
                        self.enqueue(bot, s, text, r["txid"], r["block_time"] / 1000)
                if len(page) < 50 or page[-1]["block_time"] <= since:
                    break
                since = page[-1]["block_time"]
        bot.data["indexerCursorMs"] = max(cursor, started_ms - INDEXER_OVERLAP_MS)
        bot.save()

    async def process_outbox(self) -> None:
        try:
            names = sorted(n for n in os.listdir(self.outbox_dir) if n.endswith(".req.json"))
        except FileNotFoundError:
            return
        for name in names:
            path = os.path.join(self.outbox_dir, name)
            req = read_json(path)
            result_path = path[: -len(".req.json")] + ".result.json"
            try:
                os.remove(path)
            except OSError:
                pass
            if not isinstance(req, dict):
                continue
            bot = self.bots.get(str(req.get("bot")))
            if req.get("kind") == "sweep":
                if time.time() - float(req.get("createdAt") or 0) > SWEEP_WAIT + 30:
                    res = sweep_result(error="request expired")
                elif bot is None:
                    res = sweep_result(error="no such bot")
                else:
                    res = await sweep_bot(bot, self.senders[bot.id], str(req.get("to") or ""), self.network)
                    self.dirty.add(bot.id)
                atomic_write_json(result_path, res)
                continue
            res = {"ok": False, "txid": None, "error": None}
            if time.time() - float(req.get("createdAt") or 0) > 120:
                res["error"] = "request expired"          # its --send already gave up waiting
            elif bot is None:
                res["error"] = "no such bot"
            elif not bot.enabled:
                res["error"] = "bot is disabled"
            elif not bot.owner and not req.get("to"):
                res["error"] = "bot has no owner, and no address to send to"
            else:
                text = str(req.get("text") or "")
                to = str(req.get("to") or "").strip().lower()
                if to:
                    try:
                        to = validate_address(to, self.network, require_pubkey=True)
                    except AddressError as exc:
                        to, res["error"] = None, f"bad address: {exc}"
                # The panel's alerts go to its owner's address, who may never have written to this bot.
                first = bool(to) and to not in bot.known_senders()
                txid = (await bot.send_to(to, text, first_contact=first) if to else None) if req.get("to") else await bot.say(text)
                res.update(ok=bool(txid), txid=txid, error=None if txid else (res["error"] or bot.error or "not sent"))
            atomic_write_json(result_path, res)

    async def run(self):
        os.makedirs(self.botd_dir, exist_ok=True)
        os.makedirs(os.path.join(self.state_dir, "bots"), exist_ok=True)
        self.reload_config()
        tasks = [asyncio.ensure_future(self.chain_loop()), asyncio.ensure_future(self.tick_loop())]
        if self.indexer:
            tasks.append(asyncio.ensure_future(self.indexer_loop()))
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            self.dirty |= set(self.bots)
            self.write_statuses()
            try:
                os.remove(os.path.join(self.botd_dir, "daemon.json"))
            except OSError:
                pass


SWEEP_WAIT = 120.0


def sweep_result(ok=False, txids=(), amount=None, fee=None, error=None) -> dict:
    """The one-line JSON `botd.py --sweep` prints."""
    txids = list(txids)
    return {"ok": bool(ok), "txid": txids[-1] if txids else None, "txids": txids,
            "amountSompi": amount, "feeSompi": fee, "error": error}


async def sweep_bot(bot: Bot, sender: MessageSender, to: str, network: str) -> dict:
    """Sends all of `bot`'s spendable coins to `to` (the panel's payout address).
    No owner needed and outside the hourly message limit; recorded in the history."""
    try:
        to = validate_address(to, network)
    except AddressError as exc:
        return sweep_result(error=f"invalid payout address: {exc}")
    if to == bot.address:
        return sweep_result(error="the payout address is the bot's own address")
    try:
        r = await sender.sweep(to)
    except InsufficientFunds as exc:
        return sweep_result(error=str(exc))
    except Exception as exc:
        log.warning("[%s] sweep failed: %s", bot.id, exc)
        return sweep_result(error=f"sweep failed: {exc}")
    if r.txids:
        kas = f"{r.amount / SOMPI_PER_KAS:,.8f}".rstrip("0").rstrip(".")
        text = f"Sent {kas} KAS to {short_address(to)} (all funds)"
        if len(r.txids) > 1:
            text += f" in {len(r.txids)} transactions"
        bot.store.append_history("out", text, r.txids[-1], int(time.time()))
        bot.data["lastOutAt"] = int(time.time())
        try:
            bot.balance = await sender.spendable()     # excludes the coins just swept
        except Exception:
            bot.balance = None
        bot.save()
    if r.leftover:   # coins too small to pay their own fee stay; not a failure
        log.info("[%s] sweep left %d sompi in coins too small to pay their fee", bot.id, r.leftover)
    return sweep_result(ok=bool(r.txids) and r.error is None, txids=r.txids,
                        amount=r.amount if r.txids else None, fee=r.fee if r.txids else None, error=r.error)


def outbox_sweep(state_dir: str, bot_id: str, to: str, timeout: float = SWEEP_WAIT) -> dict:
    """Hands a sweep to the running daemon (which holds the wallet's send lock)."""
    res = _outbox_request(state_dir, f"sweep-{bot_id}-", {"kind": "sweep", "bot": bot_id, "to": to}, timeout)
    if res is None:
        return sweep_result(error="the daemon did not answer in time")
    return res


def _outbox_request(state_dir: str, prefix: str, body: dict, timeout: float) -> Optional[dict]:
    outbox = os.path.join(state_dir, "botd", "outbox")
    os.makedirs(outbox, exist_ok=True)
    rid = f"{prefix}{int(time.time())}-{uuid.uuid4().hex[:8]}"
    atomic_write_json(os.path.join(outbox, f"{rid}.req.json"), dict(body, createdAt=int(time.time())))
    result_path = os.path.join(outbox, f"{rid}.result.json")
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = read_json(result_path)
        if isinstance(res, dict):
            try:
                os.remove(result_path)
            except OSError:
                pass
            return res
        time.sleep(0.5)
    return None


def outbox_send(state_dir: str, bot_id: str, text: str, timeout: float = 90.0, to: Optional[str] = None) -> dict:
    """Hands a message to the running daemon and waits for the result (to its owner, or `to`)."""
    req = {"bot": bot_id, "text": text}
    if to:
        req["to"] = to
    res = _outbox_request(state_dir, "", req, timeout)
    return res if res is not None else {"ok": False, "txid": None, "error": "the daemon did not answer in time"}


def daemon_alive(state_dir: str, max_age: float = 30.0) -> bool:
    d = read_json(os.path.join(state_dir, "botd", "daemon.json"), {}) or {}
    return time.time() - float(d.get("heartbeat") or 0) < max_age

