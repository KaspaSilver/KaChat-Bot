"""Outside data: the KAS price and the stratum bridge's hashrate. Blocking
urllib calls; the daemon runs them in a thread."""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Optional, Tuple

log = logging.getLogger("kachat.feeds")

KASPA_API_PRICE = "https://api.kaspa.org/info/price"
KASPA_API_MARKETCAP = "https://api.kaspa.org/info/marketcap"
KASPA_API_SUPPLY = "https://api.kaspa.org/info/coinsupply"
COINGECKO_MARKET = ("https://api.coingecko.com/api/v3/simple/price?ids=kaspa&vs_currencies=usd"
                    "&include_market_cap=true&include_24hr_change=true")
COINGECKO_PRICE = "https://api.coingecko.com/api/v3/simple/price?ids=kaspa&vs_currencies={cur}&include_24hr_change=true"


def _get_json(url: str, timeout: float = 10.0, opener=None):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "kachat-bot/2"})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_price(currency: str = "usd", opener=None) -> Optional[Tuple[float, Optional[float]]]:
    """(price, 24h change % or None). api.kaspa.org answers {"price": 0.0408} in USD;
    CoinGecko answers {"kaspa": {"usd": 0.0408, "usd_24h_change": -1.45}}."""
    cur = (currency or "usd").lower()
    if cur == "usd":
        try:
            data = _get_json(KASPA_API_PRICE, opener=opener)
            p = float(data["price"])
            if p > 0:
                return p, None
        except Exception as exc:
            log.info("api.kaspa.org price failed (%s); trying CoinGecko", exc)
    try:
        data = _get_json(COINGECKO_PRICE.format(cur=cur), opener=opener)
        k = data["kaspa"]
        p = float(k[cur])
        ch = k.get(f"{cur}_24h_change")
        return (p, float(ch) if ch is not None else None) if p > 0 else None
    except Exception as exc:
        log.warning("price unavailable: %s", exc)
        return None


def fetch_market(opener=None) -> Optional[dict]:
    """Live market data in USD: {"price", "marketcap", "circulating", "max", "change24h"} (KAS amounts
    in KAS, change in % or None). api.kaspa.org first (price, market cap, coin supply in sompi);
    CoinGecko for the 24 h change, and for everything when api.kaspa.org is down."""
    out: dict = {}
    try:
        out["price"] = float(_get_json(KASPA_API_PRICE, opener=opener)["price"])
        out["marketcap"] = float(_get_json(KASPA_API_MARKETCAP, opener=opener)["marketcap"])
        sup = _get_json(KASPA_API_SUPPLY, opener=opener)
        out["circulating"] = int(sup["circulatingSupply"]) / 1e8
        out["max"] = int(sup["maxSupply"]) / 1e8
    except Exception as exc:
        log.info("api.kaspa.org market data failed (%s); trying CoinGecko", exc)
        out = {}
    try:
        k = _get_json(COINGECKO_MARKET, opener=opener)["kaspa"]
        ch = k.get("usd_24h_change")
        out["change24h"] = float(ch) if ch is not None else None
        if "price" not in out:
            out["price"] = float(k["usd"])
            out["marketcap"] = float(k["usd_market_cap"])
            out["circulating"] = out["marketcap"] / out["price"] if out["price"] else None
            out["max"] = 28_704_026_601.0
    except Exception as exc:
        log.info("CoinGecko market data failed: %s", exc)
        out.setdefault("change24h", None)
    return out if out.get("price") else None


def fetch_bridge_hashrate(url: str, opener=None) -> Optional[float]:
    """Total of the bridge's per-worker hashrates, GH/s; None if unreachable."""
    if not url:
        return None
    try:
        data = _get_json(url, timeout=5.0, opener=opener)
        workers = data.get("workers") or []
        return sum(float(w.get("hashrate") or 0) for w in workers)
    except Exception as exc:
        log.info("bridge stats unavailable: %s", exc)
        return None
