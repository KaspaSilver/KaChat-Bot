"""Message discovery.

Primary (node only): follow the virtual selected-parent chain with
GetVirtualChainFromBlockV2 at HIGH verbosity from a persisted checkpoint,
look at every accepted transaction, keep KaChat 1:1 payloads, and name the
sender from input 0's spent output. KaChat messages are self-sends, so the
recipient's address is nowhere in the transaction; only the alias (and, for a
first-contact `dm`, the inbox tag) links it to the bot.

Secondary (optional, KACHAT_INDEXER_URL): poll the chat indexer's
/contextual-messages/by-inbox and /by-sender to fill gaps after downtime.
Everything is deduplicated by txid downstream.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional, Tuple

from .address import address_from_script
from .node import NodeError

log = logging.getLogger("kachat.chain")

CHAT_PREFIXES_HEX = tuple(p.encode().hex() for p in ("kchat:1:comm:", "kchat:1:dm:", "ciph_msg:1:comm:"))


@dataclass
class ChainTx:
    txid: str
    payload_hex: str
    block_time_ms: int
    block_hash: str
    inputs: List[Tuple[str, int, Optional[str], Optional[int]]] = field(default_factory=list)  # (prev txid, index, address, amount)
    outputs: List[Tuple[Optional[str], int]] = field(default_factory=list)                    # (address, amount)

    @property
    def sender(self) -> Optional[str]:
        """Address that owned input 0's spent output, if the tx is a self-send
        (output 0 pays that same address); None otherwise."""
        if not self.inputs or not self.outputs:
            return None
        sender = self.inputs[0][2]
        if not sender or self.outputs[0][0] != sender:
            return None
        return sender


def _script_address(spk, prefix: str) -> Optional[str]:
    try:
        return address_from_script(bytes.fromhex(spk.scriptPublicKey), prefix)
    except ValueError:
        return None


def input_address(inp, prefix: str) -> Tuple[Optional[str], Optional[int]]:
    if not inp.HasField("verboseData") or not inp.verboseData.HasField("utxoEntry"):
        return None, None
    u = inp.verboseData.utxoEntry
    amount = int(u.amount) if u.HasField("amount") else None
    if u.HasField("verboseData") and u.verboseData.HasField("scriptPublicKeyAddress") \
            and u.verboseData.scriptPublicKeyAddress:
        return u.verboseData.scriptPublicKeyAddress, amount
    if u.HasField("scriptPublicKey"):
        return _script_address(u.scriptPublicKey, prefix), amount
    return None, amount


def output_address(out, prefix: str) -> Optional[str]:
    if out.HasField("verboseData") and out.verboseData.HasField("scriptPublicKeyAddress") \
            and out.verboseData.scriptPublicKeyAddress:
        return out.verboseData.scriptPublicKeyAddress
    if out.HasField("scriptPublicKey"):
        return _script_address(out.scriptPublicKey, prefix)
    return None


def chain_tx_from_pb(tx, prefix: str, block_hash: str, block_time_ms: int) -> Optional[ChainTx]:
    """RpcOptionalTransaction -> ChainTx (None without a tx id)."""
    if not tx.HasField("verboseData") or not tx.verboseData.transactionId:
        return None
    ct = ChainTx(
        txid=tx.verboseData.transactionId,
        payload_hex=tx.payload if tx.HasField("payload") else "",
        block_time_ms=block_time_ms,
        block_hash=block_hash,
    )
    for inp in tx.inputs:
        prev_txid, prev_idx = "", 0
        if inp.HasField("previousOutpoint"):
            prev_txid = inp.previousOutpoint.transactionId
            prev_idx = int(inp.previousOutpoint.index)
        addr, amount = input_address(inp, prefix)
        ct.inputs.append((prev_txid, prev_idx, addr, amount))
    for out in tx.outputs:
        ct.outputs.append((output_address(out, prefix), int(out.value) if out.HasField("value") else 0))
    return ct


def is_chat_payload_hex(payload_hex: str) -> bool:
    return bool(payload_hex) and payload_hex.lower().startswith(CHAT_PREFIXES_HEX)


class ChainFollower:
    """Polls GetVirtualChainFromBlockV2 and hands every accepted transaction
    that `want(tx_pb)` selects to `on_tx(ChainTx)`."""

    def __init__(self, node, prefix: str, load_checkpoint: Callable[[], Optional[str]],
                 save_checkpoint: Callable[[str], None],
                 on_tx: Callable[[ChainTx], Awaitable[None]],
                 want: Callable[[object], bool],
                 poll_seconds: float = 1.0, min_confirmations: int = 0,
                 on_status: Optional[Callable[[Optional[str]], None]] = None):
        self.node = node
        self.prefix = prefix
        self.load_checkpoint = load_checkpoint
        self.save_checkpoint = save_checkpoint
        self.on_tx = on_tx
        self.want = want
        self.poll_seconds = poll_seconds
        self.min_confirmations = min_confirmations
        self.on_status = on_status or (lambda err: None)
        # When the follower last saw chain blocks removed (a reorg), unix seconds; 0 = not yet.
        # The mining bot uses it to tell a reward paid again after a reorg from one spent (BOT-013).
        self.last_reorg_at = 0.0

    async def step(self, start: str) -> str:
        """One VSPC round from `start`; returns the new checkpoint."""
        resp = await self.node.get_virtual_chain_v2(start, self.min_confirmations)
        if resp.removedChainBlockHashes:
            # A reorg. Transactions those blocks accepted are normally accepted again
            # by the new chain blocks; handling is idempotent per txid, so nothing to undo.
            log.info("chain reorg: %d chain block(s) removed", len(resp.removedChainBlockHashes))
            self.last_reorg_at = time.time()
        for block in resp.chainBlockAcceptedTransactions:
            hdr = block.chainBlockHeader
            bhash = hdr.hash if hdr.HasField("hash") else ""
            btime = int(hdr.timestamp) if hdr.HasField("timestamp") else int(time.time() * 1000)
            for tx in block.acceptedTransactions:
                if not self.want(tx):
                    continue
                ct = chain_tx_from_pb(tx, self.prefix, bhash, btime)
                if ct is not None:
                    try:
                        await self.on_tx(ct)
                    except Exception:  # one bad tx must never stop the follower
                        log.exception("handling tx %s failed", ct.txid)
        if resp.addedChainBlockHashes:
            return resp.addedChainBlockHashes[-1]
        return start

    async def run(self):
        backoff = 2.0
        while True:
            try:
                start = self.load_checkpoint()
                if not start:
                    start = await self.node.get_sink()
                    self.save_checkpoint(start)
                    log.info("chain follower: first start, from the current sink %s", start)
                while True:
                    try:
                        new = await self.step(start)
                    except NodeError as exc:
                        msg = str(exc).lower()
                        if "not found" in msg or "prun" in msg or "not in" in msg or "cannot find" in msg:
                            log.warning("checkpoint %s unusable (%s); restarting from the sink", start, exc)
                            start = await self.node.get_sink()
                            self.save_checkpoint(start)
                            continue
                        raise
                    if new != start:
                        start = new
                        self.save_checkpoint(start)
                    self.on_status(None)
                    backoff = 2.0
                    await asyncio.sleep(self.poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("chain follower: %s; retrying in %.0fs", exc, backoff)
                self.on_status(str(exc) if isinstance(exc, NodeError) else f"Node error: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)


# ── chat indexer (optional backfill) ─────────────────────────────────────────

class IndexerClient:
    def __init__(self, base_url: str, timeout: float = 10.0, opener=None):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def _get(self, path: str, params: dict):
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "kachat-bot/2"})
        with self._open(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _rows(rows) -> List[dict]:
        out = []
        for r in rows or []:
            if not isinstance(r, dict) or not r.get("tx_id"):
                continue
            try:
                b64 = bytes.fromhex(r.get("message_payload") or "").decode("ascii")
            except (ValueError, UnicodeDecodeError):
                continue
            out.append({"txid": r["tx_id"], "sender": r.get("sender") or "",
                        "block_time": int(r.get("block_time") or 0), "b64": b64})
        return out

    def by_inbox(self, tag: str, block_time_ms: int, limit: int = 100) -> List[dict]:
        return self._rows(self._get("/contextual-messages/by-inbox",
                                    {"tag": tag, "block_time": block_time_ms, "limit": limit}))

    def by_sender(self, sender: str, alias: str, block_time_ms: int, limit: int = 50) -> List[dict]:
        return self._rows(self._get("/contextual-messages/by-sender",
                                    {"address": sender, "alias": alias.encode("ascii").hex(),
                                     "block_time": block_time_ms, "limit": limit}))
