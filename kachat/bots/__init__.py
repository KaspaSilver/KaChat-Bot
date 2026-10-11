"""Bot types. `make_bot` picks the class for a bots.json entry."""
from .base import Bot, BotContext
from .faq import FaqBot
from .mining import MiningBot
from .price import PriceBot
from .wallet import WalletBot

BOT_CLASSES = {"mining": MiningBot, "price": PriceBot, "wallet": WalletBot, "faq": FaqBot}


def make_bot(cfg, store, ctx: BotContext) -> Bot:
    return BOT_CLASSES[cfg.type](cfg, store, ctx)


__all__ = ["Bot", "BotContext", "MiningBot", "PriceBot", "WalletBot", "FaqBot", "BOT_CLASSES", "make_bot"]
