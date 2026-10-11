#!/usr/bin/env python3
"""
KaChat Bot v2 daemon: hosts every bot listed in /conf/bots.json.

  python botd.py                         run the daemon (the container's CMD)
  python botd.py --send <botId> "<text>" deliver one message to that bot's owner
  python botd.py --sweep <botId> <toAddress>  send ALL of that bot's funds to toAddress

Environment (set by the Kaspa Quick Start panel):
  NODE_GRPC            kaspad gRPC, e.g. kaspad:16110
  NODE_WRPC            kaspad wRPC (Borsh), e.g. ws://kaspad:17110 (used to sign/submit)
  KASPA_NETWORK        mainnet | testnet-10
  KACHAT_INDEXER_URL   optional chat indexer for backfill after downtime
  BRIDGE_STATS_URL     optional stratum bridge stats (mining bot hashrate)
  BOTS_CONF            default /conf/bots.json
  STATE_DIR            default /state
  BOT_MAX_OUT_PER_HOUR default 50 (messages a bot may send per hour)
  CHAIN_POLL_SECONDS   default 1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys

from kachat.daemon import Daemon, daemon_alive, outbox_send, outbox_sweep, sweep_bot, sweep_result

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("botd")


def env_config() -> dict:
    return {
        "conf_path": os.environ.get("BOTS_CONF", "/conf/bots.json"),
        "state_dir": os.environ.get("STATE_DIR", "/state"),
        "network": os.environ.get("KASPA_NETWORK", "mainnet"),
        "grpc_target": os.environ.get("NODE_GRPC", "kaspad:16110"),
        "wrpc_url": os.environ.get("NODE_WRPC", "ws://kaspad:17110"),
        "indexer_url": os.environ.get("KACHAT_INDEXER_URL", "").strip(),
        "bridge_url": os.environ.get("BRIDGE_STATS_URL", "").strip(),
        "max_out_per_hour": int(os.environ.get("BOT_MAX_OUT_PER_HOUR", "50")),
        "chain_poll": float(os.environ.get("CHAIN_POLL_SECONDS", "1")),
    }


async def send_direct(cfg: dict, bot_id: str, text: str) -> dict:
    """--send when no daemon is running: same bot, same rules, one message."""
    from kachat.bots import BotContext, make_bot
    from kachat.send import KaspaSdkBackend, MessageSender
    from kachat.state import BotStore, parse_config, read_json

    bots, _ = parse_config(read_json(cfg["conf_path"], {}) or {})
    bc = next((b for b in bots if b.id == bot_id), None)
    if bc is None:
        return {"ok": False, "txid": None, "error": f"no bot {bot_id!r} in {cfg['conf_path']}"}
    backend = KaspaSdkBackend(cfg["wrpc_url"], cfg["network"])
    senders = {}

    async def send(bot, recipient, t):
        return await senders[bot.id].send(recipient, t)

    async def no_balance(_):
        return None

    ctx = BotContext(network=cfg["network"], send=send, get_balance=no_balance,
                     max_out_per_hour=cfg["max_out_per_hour"])
    bot = make_bot(bc, BotStore(cfg["state_dir"], bc.id), ctx)
    senders[bot.id] = MessageSender(bot.priv_hex, bot.address, backend)
    try:
        if not bot.enabled:
            return {"ok": False, "txid": None, "error": "bot is disabled"}
        if not bot.owner:
            return {"ok": False, "txid": None, "error": "bot has no owner yet"}
        txid = await bot.say(text)
        bot.store.write_status(bot.status())
        return {"ok": bool(txid), "txid": txid, "error": None if txid else (bot.error or "not sent")}
    finally:
        await backend.reset()


async def sweep_direct(cfg: dict, bot_id: str, to: str) -> dict:
    """--sweep when no daemon is running."""
    from kachat.bots import BotContext, make_bot
    from kachat.send import KaspaSdkBackend, MessageSender
    from kachat.state import BotStore, parse_config, read_json

    bots, _ = parse_config(read_json(cfg["conf_path"], {}) or {})
    bc = next((b for b in bots if b.id == bot_id), None)
    if bc is None:
        return sweep_result(error=f"no bot {bot_id!r} in {cfg['conf_path']}")
    backend = KaspaSdkBackend(cfg["wrpc_url"], cfg["network"])

    async def no_send(*_):
        raise RuntimeError("not sending messages during a sweep")

    async def no_balance(_):
        return None

    bot = make_bot(bc, BotStore(cfg["state_dir"], bc.id),
                   BotContext(network=cfg["network"], send=no_send, get_balance=no_balance))
    try:
        res = await sweep_bot(bot, MessageSender(bot.priv_hex, bot.address, backend), to, cfg["network"])
        bot.store.write_status(bot.status())
        return res
    finally:
        await backend.reset()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KaChat Bot v2 daemon")
    ap.add_argument("--send", nargs=2, metavar=("BOT_ID", "TEXT"), help="send one message to a bot's owner")
    ap.add_argument("--sweep", nargs=2, metavar=("BOT_ID", "TO_ADDRESS"), help="send all of a bot's funds to an address")
    args = ap.parse_args(argv)
    cfg = env_config()

    if args.sweep:
        bot_id, to = args.sweep
        if daemon_alive(cfg["state_dir"]):
            res = outbox_sweep(cfg["state_dir"], bot_id, to)
        else:
            res = asyncio.run(sweep_direct(cfg, bot_id, to))
        print(json.dumps(res))
        return 0 if res.get("ok") else 1

    if args.send:
        bot_id, text = args.send
        if not text.strip():
            print(json.dumps({"ok": False, "txid": None, "error": "empty message"}))
            return 1
        if daemon_alive(cfg["state_dir"]):
            res = outbox_send(cfg["state_dir"], bot_id, text)
        else:
            res = asyncio.run(send_direct(cfg, bot_id, text))
        print(json.dumps(res))
        return 0 if res.get("ok") else 1

    log.info("KaChat Bot v2 on %s; node %s / %s; bots from %s", cfg["network"], cfg["grpc_target"],
             cfg["wrpc_url"], cfg["conf_path"])
    daemon = Daemon(**cfg)

    async def run():
        loop = asyncio.get_running_loop()
        task = asyncio.ensure_future(daemon.run())
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, task.cancel)
            except NotImplementedError:
                pass
        try:
            await task
        except asyncio.CancelledError:
            log.info("stopping")

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
