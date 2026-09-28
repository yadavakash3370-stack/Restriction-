"""Fail-fast environment configuration.

Every variable the bot needs is read and validated once, at import time.
If something is missing or malformed, we print a clear list and exit —
instead of crashing later with a cryptic TypeError deep inside Pyrogram.

See README.md → Configuration for the full reference.
"""

import os
import sys

_missing = []


def _required(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        _missing.append(f"{name} (required)")
    return val


def _required_int(name: str) -> int:
    val = _required(name)
    if not val:
        return 0  # already reported by _required
    try:
        return int(val)
    except ValueError:
        _missing.append(f"{name} — must be an integer, got {val!r}")
        return 0


def _int_default(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _missing.append(f"{name} — must be an integer, got {raw!r}")
        return default


def _float_default(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _missing.append(f"{name} — must be a number, got {raw!r}")
        return default


def _bool_default(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _id_set(name: str) -> set:
    """Parse a comma-separated list of Telegram user ids, e.g. '123,456'."""
    out = set()
    for part in os.environ.get(name, "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            _missing.append(f"{name} — bad user id {part!r}")
    return out


# === Required ===
API_ID = _required_int("API_ID")            # from my.telegram.org
API_HASH = _required("API_HASH")            # from my.telegram.org
BOT_TOKEN = _required("BOT_TOKEN")          # from @BotFather
SESSION_STRING = _required("SESSION_STRING")  # Pyrogram user session (see scripts/gen_session.py)

# === Optional ===
# Comma-separated user ids. If set, ONLY these users can use the bot.
AUTH_USERS = _id_set("AUTH_USERS")
# User ids that may use /stats. Empty = nobody.
OWNER_ID = _id_set("OWNER_ID")

AUTO_JOIN = _bool_default("AUTO_JOIN", True)  # join public channels only when needed to fetch
MAX_PER_DAY = _int_default("MAX_PER_DAY", 25)      # per-user daily link limit, 0 = unlimited
COOLDOWN_SECONDS = _float_default("COOLDOWN_SECONDS", 5.0)  # gap between two requests
MAX_LINKS_PER_MESSAGE = _int_default("MAX_LINKS_PER_MESSAGE", 10)
PORT = _int_default("PORT", 8080)                  # keep-alive web server port
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")  # SQLite file for sessions + usage

if _missing:
    print("❌ Missing or invalid environment variables:", file=sys.stderr)
    for item in _missing:
        print(f"   - {item}", file=sys.stderr)
    print("\nSee README.md → Configuration for how to set them.", file=sys.stderr)
    sys.exit(1)
