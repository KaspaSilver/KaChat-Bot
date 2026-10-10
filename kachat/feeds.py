"""Outside data: the KAS price and the stratum bridge's hashrate. Blocking
urllib calls; the daemon runs them in a thread."""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Optional, Tuple

log = logging.getLogger("kachat.feeds")

KASPA_API_PRICE = "https://api.kaspa.org/info/price"
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
