import pytest

from kachat.address import (AddressError, address_from_script, address_from_xonly, decode_address,
                            encode_address, is_valid_address, script_for_address, validate_address)
from kachat.alias import inbox_tag, send_alias, watch_alias
from kachat.crypto import xonly_from_private
from kachat.send import fits_storage_mass, storage_mass

PRIV_A = "11" * 32
PRIV_B = "22" * 32


# ── protocol-spec vectors (kachat-1to1-protocol.md §3.4/§3.5) ───────────────

def test_spec_alias_vector():
    assert xonly_from_private(PRIV_A).hex() == "4f355bdcb7cc0af728ef3cceb9615d90684bb5b2ca5f859ab0f0b704075871aa"
    assert xonly_from_private(PRIV_B).hex() == "466d7fcae563e5cb09a0d1870bb580344804617879a14949cf22285f1bae3f27"
    a = address_from_xonly(xonly_from_private(PRIV_A), "mainnet")
    b = address_from_xonly(xonly_from_private(PRIV_B), "mainnet")
    # A -> B: A's send alias == B's watch alias
    assert send_alias(PRIV_A, b) == watch_alias(PRIV_B, a) == "9a60f88b055d"
    # B -> A
    assert send_alias(PRIV_B, a) == watch_alias(PRIV_A, b) == "bab2a6ee2b52"


def test_alias_does_not_depend_on_network_prefix():
    a_main = address_from_xonly(xonly_from_private(PRIV_A), "mainnet")
    b_main = address_from_xonly(xonly_from_private(PRIV_B), "mainnet")
    b_test = address_from_xonly(xonly_from_private(PRIV_B), "testnet-10")
    assert send_alias(PRIV_A, b_main) == send_alias(PRIV_A, b_test)
    assert len(watch_alias(PRIV_B, a_main)) == 12


def test_spec_inbox_tag_vectors():
    assert inbox_tag("kaspa:qqexample") == "61e65970af5e912a104fbc5097d3c76c"
    assert inbox_tag("KASPA:QQEXAMPLE ") == "61e65970af5e912a104fbc5097d3c76c"
    assert inbox_tag("kaspatest:qqexample") == "c6eab5d765d44aed76ac5633f5a7692e"


# ── rusty-kaspa address vectors (crypto/addresses/src/lib.rs tests) ─────────

@pytest.mark.parametrize("prefix,version,payload,expected", [
    ("kaspatest", 0, bytes(32), "kaspatest:qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqhqrxplya"),
    ("kaspatest", 1, bytes(33), "kaspatest:qyqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqhe837j2d"),
    ("kaspatest", 1, bytes.fromhex("ba01fc5f4e9d9879599c69a3dafdb835a7255e5f2e934e9322ecd3af190ab0f60e"),
     "kaspatest:qxaqrlzlf6wes72en3568khahq66wf27tuhfxn5nytkd8tcep2c0vrse6gdmpks"),
    ("kaspa", 0, bytes(32), "kaspa:qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkx9awp4e"),
    ("kaspa", 0, bytes.fromhex("5fff3c4da18f45adcdd499e44611e9fff148ba69db3c4ea2ddd955fc46a59522"),
     "kaspa:qp0l70zd5x85ttwd6jv7g3s3a8llzj96d8dncn4zmhv4tlzx5k2jyqh70xmfj"),
])
def test_rusty_kaspa_address_vectors(prefix, version, payload, expected):
    assert encode_address(prefix, version, payload) == expected
    d = decode_address(expected)
    assert (d.prefix, d.version, d.payload) == (prefix, version, payload)


def test_bip340_key_to_address():
    # BIP-340 vector 0: secret key 3 -> x-only F9308A01...
    x = xonly_from_private("00" * 31 + "03")
    assert x.hex() == "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"
    assert address_from_xonly(x, "mainnet").startswith("kaspa:qr")


def test_validation_rejects_bad_checksum_prefix_and_chars():
    good = "kaspa:qp0l70zd5x85ttwd6jv7g3s3a8llzj96d8dncn4zmhv4tlzx5k2jyqh70xmfj"
    assert validate_address(good, "mainnet") == good
    assert validate_address(good.upper(), "mainnet") == good
    with pytest.raises(AddressError):
        validate_address(good[:-1] + "e", "mainnet")              # checksum
    with pytest.raises(AddressError):
        validate_address(good, "testnet-10")                       # wrong network
    with pytest.raises(AddressError):
        validate_address("kaspa:qqqqqqqqqqqqq1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkx9awp4e", "mainnet")
    with pytest.raises(AddressError):
        validate_address("Kaspa:qp0l70zd5x85ttwd6jv7g3s3a8llzj96d8dncn4zmhv4tlzx5k2jyqh70xmfj", "mainnet")
    assert not is_valid_address("kaspa:notanaddress", "mainnet")
    assert not is_valid_address("hello", "mainnet")
    ecdsa = "kaspatest:qxaqrlzlf6wes72en3568khahq66wf27tuhfxn5nytkd8tcep2c0vrse6gdmpks"
    assert is_valid_address(ecdsa, "testnet-10")
    assert not is_valid_address(ecdsa, "testnet-10", require_pubkey=True)


def test_script_round_trip():
    for a in ("kaspa:qp0l70zd5x85ttwd6jv7g3s3a8llzj96d8dncn4zmhv4tlzx5k2jyqh70xmfj",
              "kaspatest:qxaqrlzlf6wes72en3568khahq66wf27tuhfxn5nytkd8tcep2c0vrse6gdmpks",
              encode_address("kaspa", 8, bytes(range(32)))):
        assert address_from_script(script_for_address(a), a.split(":")[0]) == a
    assert address_from_script(b"\x6a\x00", "kaspa") is None


# ── KIP-9 storage mass: the iOS KaChatCoreTests vectors ─────────────────────

def test_storage_mass_matches_ios_vectors():
    kas = 100_000_000
    assert storage_mass([20_000_000], [19_800_000]) == 505
    assert fits_storage_mass([20_000_000], [19_800_000])
    assert storage_mass([1000 * kas], [19_800_000]) == 50_495
    assert not fits_storage_mass([1000 * kas], [1_000_000])
    assert storage_mass([10 * kas] * 3, [10 * kas] * 3) == 0
    assert not fits_storage_mass([20_000_000], [19_800_000, 0])
