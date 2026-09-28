"""Tiny SQLite store: per-user login session strings + daily usage counters.

One table, thread-safe access, no ORM. The DB file lives outside Git
(see .gitignore) because stored session strings grant FULL account access.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone

import config

_lock = threading.Lock()
_conn = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    session    TEXT,
    used_date  TEXT,
    used_count INTEGER NOT NULL DEFAULT 0
);
"""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def init() -> None:
    """Create the DB file/table. Call once at startup."""
    global _conn
    parent = os.path.dirname(config.DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _conn.execute(_SCHEMA)
    _conn.commit()


def get_session(user_id: int):
    """Return the stored session string for a user, or None."""
    with _lock:
        row = _conn.execute(
            "SELECT session FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row and row[0] else None


def save_session(user_id: int, session_string: str) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO users (user_id, session) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET session = excluded.session""",
            (user_id, session_string),
        )
        _conn.commit()


def delete_session(user_id: int) -> bool:
    """Remove a stored session. Returns True if the user was logged in."""
    with _lock:
        cur = _conn.execute(
            "UPDATE users SET session = NULL WHERE user_id = ? AND session IS NOT NULL",
            (user_id,),
        )
        _conn.commit()
        return cur.rowcount > 0


def get_usage(user_id: int) -> int:
    """How many links this user processed today (UTC day)."""
    with _lock:
        row = _conn.execute(
            "SELECT used_date, used_count FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row or row[0] != _today():
            return 0
        return row[1]


def increment_usage(user_id: int) -> None:
    today = _today()
    with _lock:
        _conn.execute(
            """INSERT INTO users (user_id, used_date, used_count) VALUES (?, ?, 1)
               ON CONFLICT(user_id) DO UPDATE SET
                   used_count = CASE WHEN used_date = ? THEN used_count + 1 ELSE 1 END,
                   used_date  = ?""",
            (user_id, today, today, today),
        )
        _conn.commit()


def total_users() -> int:
    with _lock:
        return _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def session_count() -> int:
    with _lock:
        return _conn.execute(
            "SELECT COUNT(*) FROM users WHERE session IS NOT NULL"
        ).fetchone()[0]
