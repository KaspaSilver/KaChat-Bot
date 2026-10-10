import base64
import json

from kachat.crypto import open_sealed, seal, xonly_from_private
from kachat.payload import build_comm, build_dm, clean_outgoing, looks_like_chat, message_text, parse_payload

USER = "11" * 32
SEALED = seal("hi", xonly_from_private(USER))
B64 = base64.b64encode(SEALED).decode()
TAG = "61e65970af5e912a104fbc5097d3c76c"


def test_build_and_parse_comm():
    p = build_comm("9a60f88b055d", SEALED)
    assert p == f"kchat:1:comm:9a60f88b055d:{B64}"
    cp = parse_payload(p.encode())
    assert (cp.kind, cp.alias, cp.tag, cp.legacy) == ("comm", "9a60f88b055d", None, False)
    assert open_sealed(cp.sealed, USER) == "hi"
    assert looks_like_chat(p.encode())


def test_build_and_parse_dm():
    p = build_dm(TAG, "9a60f88b055d", SEALED)
    assert p.startswith(f"kchat:1:dm:{TAG}:9a60f88b055d:")
    cp = parse_payload(p.encode())
    assert (cp.kind, cp.alias, cp.tag) == ("dm", "9a60f88b055d", TAG)
    assert cp.sealed == SEALED


def test_parse_legacy_and_rejects():
    cp = parse_payload(f"ciph_msg:1:comm:abcdef012345:{B64}".encode())
    assert cp.legacy and cp.alias == "abcdef012345"
    assert parse_payload(b"kchat:1:bcast:general:hello") is None
    assert parse_payload(b"kchat:1:handshake:\x00\x01") is None
    assert parse_payload(f"kchat:1:dm:{TAG.upper()}:abc:{B64}".encode()) is None   # uppercase tag
    assert parse_payload(f"kchat:1:dm:{TAG}:{B64}".encode()) is None                # missing alias
    assert parse_payload(b"kchat:1:comm:abc:!!notbase64") is None
    assert parse_payload(b"kchat:1:comm:abc:" + base64.b64encode(b"short")) is None
    assert parse_payload(b"\xff\xfe") is None
    assert parse_payload(b"kchat:1:comm:zz:" + B64.encode()) is None


def test_message_text_envelopes():
    assert message_text("status") == "status"
    assert message_text(json.dumps({"type": "reply", "replyToId": "x", "text": "pause"})) == "pause"
    assert message_text(json.dumps({"type": "reaction", "targetTxId": "x", "emoji": "x"})) is None
    assert message_text(json.dumps({"type": "edit", "targetTxId": "x", "text": "y"})) is None
    assert message_text('{"no": "type"}') == '{"no": "type"}'
    assert message_text("{not json") == "{not json"


def test_clean_outgoing():
    assert not clean_outgoing('{"type":"x"}').startswith("{")
    assert len(clean_outgoing("x" * 5000)) == 2000
