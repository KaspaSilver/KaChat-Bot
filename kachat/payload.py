"""KaChat 1:1 payloads and message content.

  comm: kchat:1:comm:<alias>:<base64(sealed)>
  dm:   kchat:1:dm:<inboxTag 32 hex>:<alias>:<base64(sealed)>   (first contact)
  read-only legacy: ciph_msg:1:comm:<alias>:<base64(sealed)>

Only `kchat:1:` is ever written.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Optional

COMM_PREFIX = "kchat:1:comm:"
DM_PREFIX = "kchat:1:dm:"
LEGACY_COMM_PREFIX = "ciph_msg:1:comm:"
PREFIXES = (COMM_PREFIX.encode(), DM_PREFIX.encode(), LEGACY_COMM_PREFIX.encode())

_TAG_RE = re.compile(r"^[0-9a-f]{32}$")
_ALIAS_RE = re.compile(r"^[0-9a-f]{1,32}$")

MAX_TEXT_CHARS = 2000


@dataclass(frozen=True)
class ChatPayload:
    kind: str                # "comm" | "dm"
    alias: str
    sealed: bytes
    tag: Optional[str] = None
    legacy: bool = False


def looks_like_chat(raw: bytes) -> bool:
    return raw.startswith(PREFIXES)


def parse_payload(raw) -> Optional[ChatPayload]:
    """Parses payload bytes (or text); None for anything that is not a 1:1 message."""
    if isinstance(raw, (bytes, bytearray)):
        try:
            text = bytes(raw).decode("ascii")
        except UnicodeDecodeError:
            return None
    else:
        text = str(raw)
    kind, tag, legacy = "comm", None, False
    if text.startswith(DM_PREFIX):
        parts = text[len(DM_PREFIX):].split(":", 2)
        if len(parts) != 3:
            return None
        tag, alias, b64 = parts
        if not _TAG_RE.match(tag):
            return None
        kind = "dm"
    elif text.startswith(COMM_PREFIX):
        parts = text[len(COMM_PREFIX):].split(":", 1)
        if len(parts) != 2:
            return None
        alias, b64 = parts
    elif text.startswith(LEGACY_COMM_PREFIX):
        parts = text[len(LEGACY_COMM_PREFIX):].split(":", 1)
        if len(parts) != 2:
            return None
        alias, b64 = parts
        legacy = True
    else:
        return None
    alias = alias.lower()
    if not _ALIAS_RE.match(alias):
        return None
    try:
        sealed = base64.b64decode(b64.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(sealed) < 12 + 33 + 16:
        return None
    return ChatPayload(kind=kind, alias=alias, sealed=sealed, tag=tag, legacy=legacy)


def build_comm(alias: str, sealed: bytes) -> str:
    return f"{COMM_PREFIX}{alias}:{base64.b64encode(sealed).decode('ascii')}"


def build_dm(tag: str, alias: str, sealed: bytes) -> str:
    if not _TAG_RE.match(tag):
        raise ValueError("inbox tag must be 32 lowercase hex characters")
    return f"{DM_PREFIX}{tag}:{alias}:{base64.b64encode(sealed).decode('ascii')}"


# Envelope types a chat app may put inside a message. Only `reply` carries text
# for the bot; the rest (reactions, edits, pools, chess, calls, media) are not
# messages to answer.
def message_text(plaintext: str) -> Optional[str]:
    """The text a person wrote, or None when the plaintext is a non-text envelope."""
    stripped = plaintext.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("type"), str):
            if obj["type"] == "reply":
                t = obj.get("text")
                return t if isinstance(t, str) else None
            return None
    return plaintext


def clean_outgoing(text: str) -> str:
    """Bot text must never look like a JSON envelope, and stays small."""
    t = (text or "").strip()
    if t.startswith("{"):
        t = "​" + t
    if len(t) > MAX_TEXT_CHARS:
        t = t[: MAX_TEXT_CHARS - 1] + "…"
    return t
