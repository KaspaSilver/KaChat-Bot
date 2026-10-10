"""Sending a KaChat message: a self-send whose payload is the sealed text.

Shape (iOS `buildContextualMessageTx` / `selectUtxosForContextualMessage`):
  inputs  the bot's own coins (prefer the pending output of its previous message,
          so back-to-back sends chain instead of double-spending one coin)
  outputs exactly ONE, back to the bot: total input - fee. Never a change output,
          so never a tiny output that breaks the KIP-9 storage-mass budget.
  fee     iOS minimum standard fee: 100 sompi * max(computeMass, 2 * txBytes) + 3.

Signing and submitting go through the Kaspa Python SDK (the same one v1 used).
The SDK sits behind `KaspaSdkBackend` so tests run with a fake backend.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from . import alias as alias_mod
from .address import script_for_address, xonly_from_address
from .crypto import seal
from .payload import build_comm, build_dm, clean_outgoing

log = logging.getLogger("kachat.send")

SOMPI_PER_KAS = 100_000_000
FEE_PER_GRAM = 100
FEE_BUFFER = 3
SIG_SCRIPT_LEN = 66            # Schnorr: push(65) + 64-byte sig + sighash type
P2PK_SCRIPT_LEN = 34
MAX_STANDARD_MASS = 100_000
STORAGE_MASS_C = 10 ** 12
MAX_INPUTS = 80
PENDING_TTL = 600              # forget an unconfirmed chain link after 10 minutes


def _loop_lock(owner, attr: str) -> asyncio.Lock:
    """An asyncio.Lock bound to the running loop (Python < 3.10 binds locks at creation)."""
    loop = asyncio.get_running_loop()
    held = getattr(owner, attr, None)
    if held is None or held[0] is not loop:
        held = (loop, asyncio.Lock())
        setattr(owner, attr, held)
    return held[1]


class SendError(RuntimeError):
    pass


class InsufficientFunds(SendError):
    pass


def tx_byte_size(n_inputs: int, out_script_lens: List[int], payload_len: int) -> int:
    size = 2 + 8 + n_inputs * (32 + 4 + 8 + SIG_SCRIPT_LEN + 8) + 8
    for sl in out_script_lens:
        size += 8 + 2 + 8 + sl
    return size + 8 + 20 + 8 + 32 + 8 + payload_len


def compute_mass(n_inputs: int, out_script_lens: List[int], payload_len: int) -> int:
    spk = sum((2 + sl) * 10 for sl in out_script_lens)
    return tx_byte_size(n_inputs, out_script_lens, payload_len) + spk + n_inputs * 1000


def min_fee(n_inputs: int, payload_len: int, out_script_len: int = P2PK_SCRIPT_LEN) -> int:
    lens = [out_script_len]
    fee_mass = max(compute_mass(n_inputs, lens, payload_len), 2 * tx_byte_size(n_inputs, lens, payload_len))
    return fee_mass * FEE_PER_GRAM + FEE_BUFFER


def storage_mass(inputs: List[int], outputs: List[int]) -> int:
    """KIP-9 storage mass (iOS `KasiaTransactionBuilder.storageMass`)."""
    c = STORAGE_MASS_C
    harmonic_outs = sum(c // max(a, 1) for a in outputs)
    if len(outputs) == 1 or len(inputs) == 1 or (len(outputs) == 2 and len(inputs) == 2):
        harmonic_ins = sum(c // max(a, 1) for a in inputs)
        return max(harmonic_outs - harmonic_ins, 0)
    mean_ins = max(sum(inputs) // max(len(inputs), 1), 1)
    return max(harmonic_outs - len(inputs) * (c // mean_ins), 0)


def fits_storage_mass(inputs: List[int], outputs: List[int]) -> bool:
    return all(o > 0 for o in outputs) and storage_mass(inputs, outputs) <= MAX_STANDARD_MASS


@dataclass
class Selection:
    entries: List[dict]
    total: int
    fee: int

    @property
    def output(self) -> int:
        return self.total - self.fee


def _amount(e: dict) -> int:
    return int(e["utxoEntry"]["amount"])


def _outpoint_key(e: dict) -> str:
    op = e["outpoint"]
    return f"{op['transactionId']}:{int(op['index'])}"


def select_utxos(entries: List[dict], payload_len: int) -> Selection:
    """iOS order: a single pending chain link if it can pay, else largest first."""
    spendable = [e for e in entries if not e["utxoEntry"].get("isCoinbase")]
    if not spendable:
        raise InsufficientFunds("the bot wallet has no spendable coins")
    fee1 = min_fee(1, payload_len)
    pending = sorted((e for e in spendable if int(e["utxoEntry"].get("blockDaaScore") or 0) == 0),
                     key=_amount, reverse=True)
    for e in pending:
        a = _amount(e)
        if a > fee1 and fits_storage_mass([a], [a - fee1]):
            return Selection([e], a, fee1)
    ordered = sorted(spendable, key=lambda e: (_amount(e), int(e["utxoEntry"].get("blockDaaScore") or 0) == 0),
                     reverse=True)
    selected: List[dict] = []
    total = 0
    for e in ordered[:MAX_INPUTS]:
        selected.append(e)
        total += _amount(e)
        fee = min_fee(len(selected), payload_len)
        if total <= fee:
            continue
        if fits_storage_mass([_amount(x) for x in selected], [total - fee]):
            return Selection(list(selected), total, fee)
    raise InsufficientFunds("not enough KAS in the bot wallet for the network fee")


def build_payload(priv_hex: str, recipient: str, text: str, *, first_contact: bool = False) -> str:
    """The payload text for `text` sent from the bot (`priv_hex`) to `recipient`."""
    sealed = seal(clean_outgoing(text), xonly_from_address(recipient))
    a = alias_mod.send_alias(priv_hex, recipient)
    if first_contact:
        return build_dm(alias_mod.inbox_tag(recipient), a, sealed)
    return build_comm(a, sealed)


class KaspaSdkBackend:
    """UTXO lookup, signing and submission through the Kaspa Python SDK (wRPC)."""

    def __init__(self, url: str, network: str):
        self.url = url
        self.network = network
        self._rpc = None

    async def _client(self):
        async with _loop_lock(self, "_lock"):
            if self._rpc is None:
                from kaspa import RpcClient
                rpc = RpcClient(url=self.url)
                await rpc.connect()
                self._rpc = rpc
            return self._rpc

    async def reset(self):
        rpc, self._rpc = self._rpc, None
        if rpc is not None:
            try:
                await rpc.disconnect()
            except Exception:
                pass

    async def get_utxos(self, address: str) -> List[dict]:
        try:
            resp = await (await self._client()).get_utxos_by_addresses({"addresses": [address]})
        except Exception:
            await self.reset()
            raise
        return list(resp.get("entries", []))

    def build_and_sign(self, entries: List[dict], address: str, amount: int, payload: str, priv_hex: str, fee: int):
        from kaspa import Address, PaymentOutput, PrivateKey, create_transaction, sign_transaction
        tx = create_transaction(entries, [PaymentOutput(Address(address), int(amount))], int(fee), payload.encode().hex(), 1)
        try:
            from kaspa import update_transaction_mass
            if not update_transaction_mass(self.network, tx):
                raise SendError("message transaction is over the standard mass limit")
        except ImportError:
            pass
        return sign_transaction(tx, [PrivateKey(priv_hex)], True)

    async def submit(self, tx) -> str:
        try:
            resp = await (await self._client()).submit_transaction({"transaction": tx, "allowOrphan": False})
        except Exception:
            await self.reset()
            raise
        txid = resp.get("transactionId") if isinstance(resp, dict) else None
        return str(txid or tx.id)


class MessageSender:
    """One per bot wallet. Sends one message at a time and chains its coins."""

    def __init__(self, priv_hex: str, address: str, backend, clock=time.time):
        self.priv_hex = priv_hex
        self.address = address
        self.backend = backend
        self.clock = clock
        self._pending: Optional[dict] = None          # our last output, maybe unconfirmed
        self._pending_at = 0.0
        self._spent: dict = {}                        # outpoint key -> time we spent it
        self._script_hex = "0000" + script_for_address(address).hex()

    def _merge(self, node_entries: List[dict]) -> List[dict]:
        now = self.clock()
        self._spent = {k: t for k, t in self._spent.items() if now - t < PENDING_TTL}
        out = [e for e in node_entries if _outpoint_key(e) not in self._spent]
        if self._pending is not None:
            key = _outpoint_key(self._pending)
            if any(_outpoint_key(e) == key for e in node_entries) or now - self._pending_at > PENDING_TTL:
                self._pending = None                  # confirmed (node has it) or stale
            elif key not in self._spent:
                out.append(self._pending)
        return out

    def _forget_chain(self):
        self._pending = None
        self._spent.clear()

    async def spendable(self) -> int:
        entries = self._merge(await self.backend.get_utxos(self.address))
        return sum(_amount(e) for e in entries if not e["utxoEntry"].get("isCoinbase"))

    async def send(self, recipient: str, text: str, *, first_contact: bool = False) -> str:
        payload = build_payload(self.priv_hex, recipient, text, first_contact=first_contact)
        async with _loop_lock(self, "_send_lock"):
            last_exc: Optional[Exception] = None
            for attempt in (1, 2):
                node_entries = await self.backend.get_utxos(self.address)
                sel = select_utxos(self._merge(node_entries), len(payload))
                tx = self.backend.build_and_sign(sel.entries, self.address, sel.output, payload, self.priv_hex, sel.fee)
                try:
                    txid = await self.backend.submit(tx)
                except Exception as exc:              # double spend, orphan, node hiccup
                    last_exc = exc
                    log.warning("submit failed (attempt %d): %s", attempt, exc)
                    self._forget_chain()
                    continue
                now = self.clock()
                spk = next((e["utxoEntry"].get("scriptPublicKey") for e in node_entries
                            if isinstance(e["utxoEntry"].get("scriptPublicKey"), str)), self._script_hex)
                for e in sel.entries:
                    self._spent[_outpoint_key(e)] = now
                self._pending = {
                    "address": self.address,
                    "outpoint": {"transactionId": txid, "index": 0},
                    "utxoEntry": {
                        "amount": sel.output,
                        "scriptPublicKey": spk,
                        "blockDaaScore": 0,
                        "isCoinbase": False,
                    },
                }
                self._pending_at = now
                log.info("sent message %s (fee %d sompi, %d input(s))", txid, sel.fee, len(sel.entries))
                return txid
            raise SendError(f"the node refused the message: {last_exc}")
