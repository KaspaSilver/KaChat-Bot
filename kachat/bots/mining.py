"""Mining bot: a message for every block reward paid to a watched address (up to 10; `add`
watches another)
(the v1 watcher's job), plus optional pool-hashrate drop alerts.

Rewards come from a UtxosChanged subscription on the mining address (the
daemon owns the stream): every new coinbase output of at least minRewardKas.
Hashrate is the stratum bridge's per-worker total (BRIDGE_STATS_URL, GH/s).
"""
from __future__ import annotations

from typing import List, Optional

from ..address import short_address
from .base import MAX_WATCHED, Bot, Question, fmt_hashrate, fmt_kas, parse_address_list, parse_number

HASHRATE_POLL = 60.0
# At 10 blocks a second the chain block that pays a mined block's reward is sometimes replaced
# (a short reorg), and the same reward is then paid again in another coinbase: a new txid. So a
# new reward waits REWARD_SETTLE seconds before it is reported (one taken away meanwhile is
# dropped), and one paid again within REPAID_WINDOW of a reported one being taken away, for the
# same amount on the same address, is that same reward and is not reported twice.
REWARD_SETTLE = 3.0
REPAID_WINDOW = 10.0
HASHRATE_WINDOW = 30 * 60      # baseline = average over the last 30 minutes before a drop


class MiningBot(Bot):
    TYPE = "mining"
    TITLE = "Mining bot"
    ADDRESS_KEY = "addresses"

    def __init__(self, *a, **kw):
        self._hr_samples: List[tuple] = []
        self._hr_last_poll = 0.0
        self._hr_low_count = 0
        self._pending: List[tuple] = []     # (time, address, amount, key): rewards not reported yet
        self._orphans: List[tuple] = []     # (time, address, amount): reported rewards taken away
        super().__init__(*a, **kw)

    def default_settings(self) -> dict:
        return {"addresses": [], "minRewardKas": 0, "hashrateDropPct": None}

    def address_list(self) -> List[str]:
        # Settings from before `add` held one "address".
        s = self.settings
        return list(s.get("addresses") or ([s["address"]] if s.get("address") else []))

    def questions(self) -> List[Question]:
        def parse_min(t):
            return parse_number(t, minimum=0, what="an amount in KAS, like 0 or 1.5")

        def parse_drop(t):
            return parse_number(t, minimum=1, maximum=99, allow_none=True, what="a percentage, like 30")

        qs = [
            Question("addresses", "Which mining address should I watch? (paste the kaspa: address; several "
                     "separated by spaces, up to 10)",
                     parse_address_list(self.ctx.network, not_self=self.address, most=MAX_WATCHED),
                     show=lambda v: ", ".join(short_address(a) for a in v) or "none"),
            Question("minRewardKas", "Smallest reward to report, in KAS? (0 = every block)", parse_min, 0,
                     show=lambda v: f"{v:g} KAS"),
            Question("hashrateDropPct", "Alert me when the pool hashrate drops by how many %? (e.g. 30, or no)",
                     parse_drop, None, show=lambda v: "no" if v is None else f"{v:g}%"),
        ]
        # Without the stratum bridge there is no hashrate to watch: don't ask.
        return qs if self.ctx.fetch_hashrate else qs[:2]

    def describe_settings(self) -> str:
        s = self.settings
        drop = s.get("hashrateDropPct")
        return ("Watching " + ("\n".join(self.address_list()) or "none") + "\n"
                f"Reporting rewards of at least {float(s.get('minRewardKas') or 0):g} KAS\n"
                f"Hashrate drop alerts: {'off' if drop is None else f'{drop:g}%'}")

    def summary(self) -> str:
        addrs = self.address_list()
        if not addrs:
            return "Not set up"
        if len(addrs) == 1:
            return f"Watching {short_address(addrs[0])} for blocks"
        return f"Watching {len(addrs)} addresses for blocks"

    def sample_notification(self) -> str:
        return self.reward_text([123456789], 98765432100, None)

    def watched_addresses(self) -> set:
        return set(self.address_list()) if self.enabled and self.stage in ("active", "paused") else set()

    def on_settings_changed(self) -> None:
        self._hr_samples = []
        self._hr_low_count = 0
        self.data["hashrateAlerted"] = False

    def reward_text(self, amounts: List[int], balance: Optional[int], hashrate: Optional[float],
                    address: Optional[str] = None) -> str:
        if len(amounts) == 1:
            head = f"Block reward: {fmt_kas(amounts[0])}"
        else:
            head = f"{len(amounts)} block rewards: {fmt_kas(sum(amounts))}"
        # Watching several: say which one found it.
        if address and len(self.address_list()) > 1:
            head = f"{short_address(address)}\n{head}"
        lines = [head, f"Balance: {fmt_kas(balance)}"]
        if hashrate is not None:
            lines.append(f"Hashrate: {fmt_hashrate(hashrate)}")
        return "\n".join(lines)

    def busy_events(self, added: list) -> list:
        return [e for e in added if e.get("isCoinbase")]     # block rewards, nothing else

    async def on_utxos(self, address: str, added: list, removed: list) -> None:
        s = self.settings
        if address not in self.address_list() or self.stage != "active":
            return
        now = self.ctx.clock()
        self._orphans = [o for o in self._orphans if now - o[0] < REPAID_WINDOW]
        # A reward taken away: dropped if not reported yet, remembered if it was (its re-payment
        # comes back as a new coin of the same amount).
        for e in removed:
            if not e.get("isCoinbase"):
                continue
            key = f"reward:{e['txid']}:{e['index']}"
            before = len(self._pending)
            self._pending = [p for p in self._pending if p[3] != key]
            if len(self._pending) == before and self.seen(key):
                self._orphans.append((now, address, int(e["amount"])))
        min_sompi = int(round(float(s.get("minRewardKas") or 0) * 100_000_000))
        for e in added:
            if not e.get("isCoinbase") or e["amount"] <= 0 or e["amount"] < min_sompi:
                continue
            key = f"reward:{e['txid']}:{e['index']}"
            if self.seen(key) or any(p[3] == key for p in self._pending):
                continue
            match = next((o for o in self._orphans if o[1] == address and o[2] == int(e["amount"])), None)
            if match:
                # The same reward paid again after a reorg: already reported.
                self._orphans.remove(match)
                self.mark_seen(key)
                continue
            self._pending.append((now, address, int(e["amount"]), key))

    async def report_rewards(self, now: float) -> None:
        """Rewards that have settled, one message per address."""
        ready = [p for p in self._pending if now - p[0] >= REWARD_SETTLE]
        if not ready:
            return
        self._pending = [p for p in self._pending if now - p[0] < REWARD_SETTLE]
        by_addr: dict = {}
        watching = set(self.address_list())
        for _, address, amount, key in ready:
            self.mark_seen(key)
            if address in watching:              # not one dropped meanwhile (too busy, removed)
                by_addr.setdefault(address, []).append(amount)
        for address, rewards in by_addr.items():
            balance = await self.ctx.get_balance(address)
            hashrate = await self.ctx.fetch_hashrate() if self.ctx.fetch_hashrate else None
            await self.notify(self.reward_text(rewards, balance, hashrate, address))

    async def tick(self, now: float) -> None:
        await self.report_rewards(now)
        drop = self.settings.get("hashrateDropPct")
        if drop is None or self.stage != "active" or not self.ctx.fetch_hashrate:
            return
        if now - self._hr_last_poll < HASHRATE_POLL:
            return
        self._hr_last_poll = now
        hr = await self.ctx.fetch_hashrate()
        if hr is None:
            return
        await self.check_hashrate(now, hr, float(drop))

    async def check_hashrate(self, now: float, hr: float, drop: float) -> None:
        past = [v for (t, v) in self._hr_samples if now - t <= HASHRATE_WINDOW]
        baseline = sum(past) / len(past) if past else None
        alerted = bool(self.data.get("hashrateAlerted"))
        if baseline and baseline > 0:
            fall = (baseline - hr) / baseline * 100
            if not alerted:
                if fall >= drop:
                    self._hr_low_count += 1
                    if self._hr_low_count >= 2:          # two polls in a row, not a blip
                        self.data["hashrateAlerted"] = True
                        self.data["hashrateBefore"] = baseline
                        self.save()
                        await self.notify(f"Hashrate dropped {fall:.0f}%: {fmt_hashrate(hr)} "
                                          f"(was {fmt_hashrate(baseline)})")
                    return                               # keep low readings out of the baseline
                self._hr_low_count = 0
        if alerted:
            before = float(self.data.get("hashrateBefore") or 0)
            if before and hr >= before * (1 - drop / 200):
                self.data["hashrateAlerted"] = False
                self._hr_low_count = 0
                self.save()
                await self.notify(f"Hashrate is back: {fmt_hashrate(hr)}")
            else:
                return
        self._hr_samples.append((now, hr))
        self._hr_samples = [(t, v) for (t, v) in self._hr_samples if now - t <= HASHRATE_WINDOW]

