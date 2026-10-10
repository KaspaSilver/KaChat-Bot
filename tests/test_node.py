"""GrpcNode against an in-process gRPC server speaking the real proto/ MessageStream."""
import asyncio

import grpc
import messages_pb2 as pb
import messages_pb2_grpc as pb_grpc
import pytest

from kachat.node import GrpcNode, NodeError, VERBOSITY_HIGH


class FakeKaspad(pb_grpc.RPCServicer):
    async def MessageStream(self, request_iterator, context):
        async for req in request_iterator:
            kind = req.WhichOneof("payload")
            resp = pb.KaspadResponse(id=req.id)
            if kind == "GetSinkRequest":
                resp.GetSinkResponse.sink = "ab" * 32
            elif kind == "getVirtualChainFromBlockV2Request":
                r = req.getVirtualChainFromBlockV2Request
                v = resp.getVirtualChainFromBlockV2Response
                if r.startHash == "00" * 32:
                    v.error.message = "cannot find header 00..."
                else:
                    assert r.dataVerbosityLevel == VERBOSITY_HIGH
                    v.addedChainBlockHashes.append("cd" * 32)
            elif kind == "getBalanceByAddressRequest":
                resp.getBalanceByAddressResponse.balance = 123 if req.getBalanceByAddressRequest.address else 0
            elif kind == "getUtxosByAddressesRequest":
                e = resp.getUtxosByAddressesResponse.entries.add()
                e.address = req.getUtxosByAddressesRequest.addresses[0]
                e.outpoint.transactionId = "ef" * 32
                e.outpoint.index = 1
                e.utxoEntry.amount = 5
                e.utxoEntry.isCoinbase = True
            elif kind == "notifyUtxosChangedRequest":
                resp.notifyUtxosChangedResponse.SetInParent()
                yield resp
                n = pb.KaspadResponse()
                a = n.utxosChangedNotification.added.add()
                a.address = req.notifyUtxosChangedRequest.addresses[0]
                a.outpoint.transactionId = "12" * 32
                a.utxoEntry.amount = 7
                yield n
                await asyncio.sleep(10)
                continue
            yield resp


@pytest.fixture
def server_port():
    holder = {}

    async def start():
        server = grpc.aio.server()
        pb_grpc.add_RPCServicer_to_server(FakeKaspad(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        holder["server"] = server
        return port
    return holder, start


def test_requests_and_subscription(server_port):
    holder, start = server_port

    async def go():
        port = await start()
        node = GrpcNode(f"127.0.0.1:{port}")
        try:
            assert await node.get_sink() == "ab" * 32
            r = await node.get_virtual_chain_v2("11" * 32)
            assert list(r.addedChainBlockHashes) == ["cd" * 32]
            with pytest.raises(NodeError, match="cannot find"):
                await node.get_virtual_chain_v2("00" * 32)
            assert await node.get_balance("kaspa:x") == 123
            utxos = await node.get_utxos(["kaspa:y"])
            assert utxos == [{"address": "kaspa:y", "txid": "ef" * 32, "index": 1, "amount": 5,
                              "isCoinbase": True, "blockDaaScore": 0}]
            async for n in node.utxo_notifications({"kaspa:z"}):
                assert n.added[0].address == "kaspa:z" and n.added[0].utxoEntry.amount == 7
                break
        finally:
            await node.close()
            await holder["server"].stop(None)
    asyncio.run(go())


def test_unreachable_node_raises_node_error():
    async def go():
        node = GrpcNode("127.0.0.1:1")
        with pytest.raises(NodeError):
            await node.request("GetSinkRequest", "GetSinkResponse", timeout=5)
        await node.close()
    asyncio.run(go())
