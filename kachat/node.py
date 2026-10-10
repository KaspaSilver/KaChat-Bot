"""kaspad gRPC access (the `proto/` MessageStream), asyncio flavour.

Every request opens its own short MessageStream on one shared channel and
waits for the matching response type; subscriptions keep their stream open.
The protobuf stubs (`messages_pb2`, `messages_pb2_grpc`) are compiled from
`proto/` at image build time (see the Dockerfile) and imported lazily so the
rest of the package works without them.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable, Optional

log = logging.getLogger("kachat.node")

GRPC_OPTIONS = [
    ("grpc.max_receive_message_length", 256 * 1024 * 1024),
    ("grpc.max_send_message_length", 16 * 1024 * 1024),
    ("grpc.keepalive_time_ms", 30_000),
    ("grpc.keepalive_timeout_ms", 10_000),
]

# RpcDataVerbosityLevel (rpc.proto): NONE=0 LOW=1 HIGH=2 FULL=3. HIGH carries the
# payload, every input's previous outpoint and its spent utxoEntry (script +
# scriptPublicKeyAddress), the tx id and the chain block's hash and timestamp.
VERBOSITY_HIGH = 2


class NodeError(RuntimeError):
    pass


def load_pb():
    import messages_pb2  # noqa: WPS433 (generated at build time)
    import messages_pb2_grpc
    return messages_pb2, messages_pb2_grpc


class GrpcNode:
    def __init__(self, target: str):
        self.target = target
        self._channel = None
        self._stub = None

    def _ensure(self):
        if self._stub is None:
            import grpc
            _, pb_grpc = load_pb()
            self._channel = grpc.aio.insecure_channel(self.target, options=GRPC_OPTIONS)
            self._stub = pb_grpc.RPCStub(self._channel)
        return self._stub

    async def close(self):
        if self._channel is not None:
            await self._channel.close()
        self._channel = None
        self._stub = None

    async def request(self, req_field: str, resp_field: str,
                      fill: Optional[Callable] = None, timeout: float = 60.0):
        import grpc
        pb, _ = load_pb()
        stub = self._ensure()
        req = pb.KaspadRequest()
        sub = getattr(req, req_field)
        sub.SetInParent()
        if fill:
            fill(sub)
        call = stub.MessageStream()
        try:
            await call.write(req)

            async def read():
                while True:
                    resp = await call.read()
                    if resp is grpc.aio.EOF:
                        raise NodeError("node closed the stream")
                    if resp.WhichOneof("payload") == resp_field:
                        return getattr(resp, resp_field)

            msg = await asyncio.wait_for(read(), timeout)
        except grpc.aio.AioRpcError as exc:
            raise NodeError(f"node unreachable at {self.target}: {exc.code().name}") from None
        finally:
            call.cancel()
        if msg.HasField("error") and msg.error.message:
            raise NodeError(msg.error.message)
        return msg

    # ── calls ──────────────────────────────────────────────────────────────

    async def get_sink(self) -> str:
        msg = await self.request("GetSinkRequest", "GetSinkResponse")
        return msg.sink

    async def get_dag_info(self):
        return await self.request("getBlockDagInfoRequest", "getBlockDagInfoResponse")

    async def get_balance(self, address: str) -> int:
        msg = await self.request("getBalanceByAddressRequest", "getBalanceByAddressResponse",
                                 lambda m: setattr(m, "address", address))
        return int(msg.balance)

    async def get_utxos(self, addresses) -> list:
        msg = await self.request("getUtxosByAddressesRequest", "getUtxosByAddressesResponse",
                                 lambda m: m.addresses.extend(list(addresses)))
        return [utxo_entry_dict(e) for e in msg.entries]

    async def get_virtual_chain_v2(self, start_hash: str, min_confirmations: int = 0):
        def fill(m):
            m.startHash = start_hash
            m.dataVerbosityLevel = VERBOSITY_HIGH
            m.minConfirmationCount = int(min_confirmations)
        return await self.request("getVirtualChainFromBlockV2Request",
                                  "getVirtualChainFromBlockV2Response", fill, timeout=120.0)

    async def utxo_notifications(self, addresses) -> AsyncIterator:
        """Yields UtxosChangedNotificationMessage for `addresses` until the stream breaks."""
        import grpc
        pb, _ = load_pb()
        stub = self._ensure()
        req = pb.KaspadRequest()
        req.notifyUtxosChangedRequest.addresses.extend(sorted(addresses))
        call = stub.MessageStream()
        try:
            await call.write(req)
            while True:
                resp = await call.read()
                if resp is grpc.aio.EOF:
                    raise NodeError("node closed the notification stream")
                kind = resp.WhichOneof("payload")
                if kind == "notifyUtxosChangedResponse":
                    r = resp.notifyUtxosChangedResponse
                    if r.HasField("error") and r.error.message:
                        raise NodeError(r.error.message)
                elif kind == "utxosChangedNotification":
                    yield resp.utxosChangedNotification
        except grpc.aio.AioRpcError as exc:
            raise NodeError(f"node unreachable at {self.target}: {exc.code().name}") from None
        finally:
            call.cancel()


def utxo_entry_dict(e) -> dict:
    """RpcUtxosByAddressesEntry -> plain dict."""
    u = e.utxoEntry
    return {
        "address": e.address,
        "txid": e.outpoint.transactionId,
        "index": int(e.outpoint.index),
        "amount": int(u.amount),
        "isCoinbase": bool(u.isCoinbase),
        "blockDaaScore": int(u.blockDaaScore),
    }
