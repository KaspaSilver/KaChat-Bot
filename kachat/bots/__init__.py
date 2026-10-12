"""Bot types. `make_bot` picks the class for a bots.json entry."""
from .base import Bot, BotContext
from .faq import FaqBot
from .mining import MiningBot
from .price import PriceBot
from .public import PublicHost
from .wallet import WalletBot

BOT_CLASSES = {"mining": MiningBot, "price": PriceBot, "wallet": WalletBot, "faq": FaqBot}


def make_bot(cfg, store, ctx: BotContext, public: bool = True) -> Bot:
    """Every bot is public: anyone can use it, no pairing code. The address-watching and price
    bots get one conversation per person (PublicHost); `public=False` builds the single-owner
    bot itself (the per-person engine the host runs, and its tests)."""
    cls = BOT_CLASSES[cfg.type]
    if public and cls.PAIRS:
        return PublicHost(cls, cfg, store, ctx)
    return cls(cfg, store, ctx)


__all__ = ["Bot", "BotContext", "MiningBot", "PriceBot", "WalletBot", "FaqBot", "PublicHost", "BOT_CLASSES", "make_bot"]
