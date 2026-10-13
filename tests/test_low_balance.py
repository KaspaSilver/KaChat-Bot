"""Below 0.5 KAS every bot tells the people who use it, once, with a signed KaChat payment request."""
import hashlib
from urllib.parse import parse_qs, unquote, urlparse

from conftest import BOT_KEY, OTHER_KEY, USER_KEY, FakeStore, addr, make_cfg, run

from kachat.bots import make_bot as mk
from kachat.crypto import xonly_from_private
from kachat.payreq import payment_request_link, schnorr_verify, signing_digest
from test_engine import say, texts

USER = addr(USER_KEY)
OTHER = addr(OTHER_KEY)
WATCH = addr("44" * 32)
KAS = 100_000_000


def host(ctxf, bot_type="mining", **kw):
    return mk(make_cfg(bot_type, **kw), FakeStore(), ctxf.make())


def start(bot, who):
    say(bot, "hi", who)
    say(bot, "agree", who)


def check_link(text, bot):
    link = text.split("\n")[-1]
    u = urlparse(link)
    assert u.scheme == "https" and u.netloc == "kachat.app" and u.path == "/pay/" + bot.address[len("kaspa:"):]
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q["amount"] == "5" and q["by"] == bot.address[len("kaspa:"):] and "chat" not in q
    digest = signing_digest(bot.address, 5 * KAS, unquote(q["memo"]), False, bot.address)
    assert schnorr_verify(digest, xonly_from_private(bot.priv_hex), bytes.fromhex(q["sig"]))
    return q


def test_mining_bot_tells_its_people_once_with_a_signed_payment_request(ctxf):
    bot = host(ctxf)
    start(bot, USER)
    start(bot, OTHER)
    say(bot, "hi", addr("66" * 32))                       # never agreed: not told
    bot.balance = 2 * KAS
    run(bot.tick(ctxf.clock.t))
    assert not any("balance is low" in t for t in texts(ctxf, USER))
    bot.balance = 49_000_000
    run(bot.tick(ctxf.clock.t + 1))
    for who in (USER, OTHER):
        msg = texts(ctxf, who)[-1]
        assert msg.startswith("My wallet balance is low (0.49 KAS left)") and "If you'd like to contribute" in msg
        q = check_link(msg, bot)
        assert q["memo"] == "Keep the KaChat Mining bot running"
    assert not any("balance is low" in t for t in texts(ctxf, addr("66" * 32)))
    n = len(ctxf.sent)
    run(bot.tick(ctxf.clock.t + 60))                      # still low: not again
    assert len(ctxf.sent) == n
    bot.balance = 3 * KAS                                 # topped up: it may ask next time
    run(bot.tick(ctxf.clock.t + 120))
    bot.balance = 40_000_000
    run(bot.tick(ctxf.clock.t + 180))
    assert len(ctxf.sent) == n + 2


def test_people_gone_for_a_month_are_not_told(ctxf):
    bot = host(ctxf, "price")
    start(bot, USER)
    ctxf.clock.t += 31 * 86400
    start(bot, OTHER)
    bot.balance = 10_000_000
    run(bot.tick(ctxf.clock.t))
    assert "balance is low" in texts(ctxf, OTHER)[-1]
    assert not any("balance is low" in t for t in texts(ctxf, USER))


def test_kaspa_answers_bot_tells_people_who_asked(ctxf):
    bot = host(ctxf, "faq")
    say(bot, "hi", USER)
    say(bot, "agree", USER)
    bot.balance = 30_000_000
    run(bot.tick(ctxf.clock.t))
    msg = texts(ctxf, USER)[-1]
    assert msg.startswith("My wallet balance is low (0.3 KAS left)")
    assert check_link(msg, bot)["memo"] == "Keep the KaChat Kaspa answers bot running"


def test_empty_or_unknown_balance_sends_nothing(ctxf):
    bot = host(ctxf)
    start(bot, USER)
    n = len(ctxf.sent)
    bot.balance = None
    run(bot.tick(ctxf.clock.t))
    bot.balance = 0
    run(bot.tick(ctxf.clock.t))
    assert len(ctxf.sent) == n


def test_link_format_matches_the_app():
    # amounts like the app's amountText, memo escaped to unreserved characters only
    link = payment_request_link(addr(BOT_KEY), 150_000_000, "Keep me & you", "11" * 32)
    assert "/pay/" in link and "amount=1.5&memo=Keep%20me%20%26%20you&by=" in link


def test_bip340_official_vectors():
    from kachat.payreq import schnorr_sign
    assert schnorr_sign(bytes(32), (3).to_bytes(32, "big"), bytes(32)).hex().upper() == (
        "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
        "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0")
    sk = bytes.fromhex("B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF")
    msg = bytes.fromhex("243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89")
    sig = schnorr_sign(msg, sk, (1).to_bytes(32, "big"))
    assert sig.hex().upper() == ("6896BD60EEAE296DB48A229FF71DFE071BDE413E6D43F917DC8DCF8C78DE3341"
                                 "8906D11AC976ABCCB20B091292BFF4EA897EFCB639EA871CFA95F6DE339E4B0A")
    pub = bytes.fromhex("DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659")
    assert schnorr_verify(msg, pub, sig) and not schnorr_verify(msg[::-1], pub, sig)
