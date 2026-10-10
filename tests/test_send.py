import pytest
from conftest import BOT_KEY, USER_KEY, FakeBackend, addr, run

from kachat.alias import inbox_tag, watch_alias
from kachat.crypto import open_sealed
from kachat.payload import parse_payload
from kachat.send import (InsufficientFunds, MessageSender, SendError, compute_mass, min_fee, select_utxos,
                         tx_byte_size)

BOT = addr(BOT_KEY)
USER = addr(USER_KEY)


def test_fee_formula_matches_ios():
    # 1 input, 1 P2PK output, 300-byte payload:
    size = 2 + 8 + (36 + 8 + 66 + 8) + 8 + (8 + 2 + 8 + 34) + 8 + 20 + 8 + 32 + 8 + 300
    assert tx_byte_size(1, [34], 300) == size
    assert compute_mass(1, [34], 300) == size + 36 * 10 + 1000
    assert min_fee(1, 300) == max(size + 360 + 1000, 2 * size) * 100 + 3
    assert 100_000 < min_fee(1, 300) < 300_000        # ~0.0017 KAS, the spec's ballpark


def _sender(amounts=(1_000_000_000,)):
    be = FakeBackend(BOT, amounts)
    return MessageSender(BOT_KEY, BOT, be), be


def test_send_builds_a_single_self_output_and_a_readable_comm():
    s, be = _sender()
    txid = run(s.send(USER, "Block reward: 1 KAS"))
    tx = be.submitted[0]
    assert txid and len(be.submitted) == 1
    assert tx["out"] == (BOT, 1_000_000_000 - tx["fee"])               # one output, back to the bot
    assert tx["fee"] == min_fee(1, len(tx["payload"]))
    cp = parse_payload(tx["payload"].encode())
    assert cp.kind == "comm"
    # the user's app watches alias(ctx = user's key) for the bot == its watch alias for the bot
    assert cp.alias == watch_alias(USER_KEY, BOT)
    assert open_sealed(cp.sealed, USER_KEY) == "Block reward: 1 KAS"


def test_first_contact_uses_dm_with_recipient_inbox_tag():
    s, be = _sender()
    run(s.send(USER, "hello", first_contact=True))
    cp = parse_payload(be.submitted[0]["payload"].encode())
    assert cp.kind == "dm" and cp.tag == inbox_tag(USER)


def test_back_to_back_sends_chain_instead_of_double_spending():
    s, be = _sender()
    run(s.send(USER, "one"))
    run(s.send(USER, "two"))
    run(s.send(USER, "three"))
    assert len(be.submitted) == 3
    first, second, third = be.submitted
    # 2nd spends the 1st's output 0 (the node has not confirmed anything yet)
    assert second["inputs"] == [{"transactionId": f"{0xabc001:064x}", "index": 0}]
    assert second["in_amounts"] == [first["out"][1]]
    assert third["inputs"][0]["transactionId"] == f"{0xabc002:064x}"


def test_confirmed_chain_link_comes_from_the_node():
    s, be = _sender()
    run(s.send(USER, "one"))
    out = be.submitted[0]["out"][1]
    # node confirmed it: original coin gone, our output present
    be.utxos = [be.entry(f"{0xabc001:064x}", 0, out, daa=200)]
    run(s.send(USER, "two"))
    assert be.submitted[1]["inputs"] == [{"transactionId": f"{0xabc001:064x}", "index": 0}]


def test_retry_after_refused_submit_starts_fresh():
    s, be = _sender()
    run(s.send(USER, "one"))
    be.fail_next = 1
    be.utxos = [be.entry("ff" * 32, 0, 500_000_000)]
    run(s.send(USER, "two"))
    assert be.submitted[-1]["inputs"] == [{"transactionId": "ff" * 32, "index": 0}]
    be.fail_next = 2
    with pytest.raises(SendError):
        run(s.send(USER, "three"))


def test_selection_largest_first_and_never_a_tiny_output():
    be = FakeBackend(BOT, (150_000, 40_000_000, 20_000_000))
    sel = select_utxos(be.utxos, 300)
    assert len(sel.entries) == 1 and sel.total == 40_000_000
    assert sel.output == 40_000_000 - sel.fee
    # a coin that covers the fee but would leave a dust-sized output breaks KIP-9: refused
    be = FakeBackend(BOT, (min_fee(1, 300) + 30_000,))
    with pytest.raises(InsufficientFunds):
        select_utxos(be.utxos, 300)


def test_insufficient_funds_and_coinbase_only():
    be = FakeBackend(BOT, (1000,))
    with pytest.raises(InsufficientFunds):
        select_utxos(be.utxos, 300)
    cb = [be.entry("aa" * 32, 0, 10 ** 10, coinbase=True)]
    with pytest.raises(InsufficientFunds):
        select_utxos(cb, 300)
