"""The files shared with the Kaspa Quick Start panel, and the bot's own state.

  /conf/bots.json                 panel -> bot (read only here; hot-reloaded on mtime change)
  /state/bots/<id>.json           bot -> panel status (contract shape, atomic writes)
  /state/bots/<id>.history.jsonl  one line per message in/out, last 500 kept
  /state/botd/<id>.json           the bot's own working state (not part of the contract)
  /state/botd/chain.json          chain-follower checkpoint
  /state/botd/outbox/             `botd.py --send` requests handed to a running daemon
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

log = logging.getLogger("kachat.state")

BOT_ID_RE = re.compile(r"^[a-z0-9-]{1,32}$")
KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")
CODE_RE = re.compile(r"^[0-9]{6}$")
BOT_TYPES = ("mining", "price", "wallet", "faq")
HISTORY_MAX = 500


def atomic_write_json(path: str, obj, mode: int = 0o644) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return default


@dataclass(frozen=True)
class BotConfig:
    id: str
    type: str
    enabled: bool
    private_key_hex: str
    address: str
    pairing_code: str
    reset_owner: Optional[str]
    reset_settings: Optional[str] = None


def parse_config(obj) -> Tuple[List[BotConfig], List[str]]:
    """Valid bots and one problem sentence per rejected entry."""
    bots: List[BotConfig] = []
    problems: List[str] = []
    seen = set()
    entries = obj.get("bots") if isinstance(obj, dict) else None
    if not isinstance(entries, list):
        return [], ["bots.json has no \"bots\" list"]
    for i, b in enumerate(entries):
        if not isinstance(b, dict):
            problems.append(f"bots[{i}] is not an object")
            continue
        bid = b.get("id")
        if not isinstance(bid, str) or not BOT_ID_RE.match(bid):
            problems.append(f"bots[{i}]: bad id {bid!r}")
            continue
        if bid in seen:
            problems.append(f"{bid}: duplicate id")
            continue
        btype = b.get("type")
        if btype not in BOT_TYPES:
            problems.append(f"{bid}: unknown type {btype!r}")
            continue
        key = b.get("privateKeyHex")
        if not isinstance(key, str) or not KEY_RE.match(key):
            problems.append(f"{bid}: privateKeyHex must be 64 hex characters")
            continue
        code = str(b.get("pairingCode") or "")
        if not CODE_RE.match(code):
            problems.append(f"{bid}: pairingCode must be 6 digits")
            continue
        reset = b.get("resetOwner")
        reset_settings = b.get("resetSettings")
        seen.add(bid)
        bots.append(BotConfig(
            id=bid, type=btype, enabled=b.get("enabled", True) is not False,
            private_key_hex=key.lower(), address=str(b.get("address") or ""),
            pairing_code=code, reset_owner=str(reset) if reset not in (None, "") else None,
            reset_settings=str(reset_settings) if reset_settings not in (None, "") else None,
        ))
    return bots, problems


class ConfigWatcher:
    """Re-reads bots.json when its mtime (or size) changes."""

    def __init__(self, path: str):
        self.path = path
        self._sig = ()                # never read yet

    def poll(self) -> Optional[Tuple[List[BotConfig], List[str]]]:
        try:
            st = os.stat(self.path)
            sig = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            sig = None
        if sig == self._sig:
            return None
        self._sig = sig
        if sig is None:
            return [], [f"{self.path} not found"]
        obj = read_json(self.path)
        if obj is None:
            self._sig = ()            # half-written file: try again next poll
            return None
        return parse_config(obj)


class BotStore:
    def __init__(self, state_dir: str, bot_id: str):
        self.status_path = os.path.join(state_dir, "bots", f"{bot_id}.json")
        self.history_path = os.path.join(state_dir, "bots", f"{bot_id}.history.jsonl")
        self.data_path = os.path.join(state_dir, "botd", f"{bot_id}.json")

    def load_data(self) -> dict:
        d = read_json(self.data_path, {})
        return d if isinstance(d, dict) else {}

    def save_data(self, data: dict) -> None:
        atomic_write_json(self.data_path, data, mode=0o600)

    def write_status(self, status: dict) -> None:
        atomic_write_json(self.status_path, status)

    def append_history(self, direction: str, text: str, txid: Optional[str], ts: Optional[int] = None) -> None:
        line = json.dumps({"ts": int(ts if ts is not None else time.time()), "dir": direction,
                           "text": text[:2000], "txid": txid}, ensure_ascii=False)
        try:
            os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
            lines = []
            try:
                with open(self.history_path, "r", encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except FileNotFoundError:
                pass
            lines.append(line)
            lines = lines[-HISTORY_MAX:]
            d = os.path.dirname(self.history_path)
            fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.history_path)
        except OSError as exc:
            log.warning("could not write history: %s", exc)
