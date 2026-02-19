"""
Global settings persistence.

Stores application-wide settings in the shared profiles.db.
These are NOT per-user — they apply regardless of who is logged in.

Examples: data storage location, start with Windows.
"""

import sqlite3
from typing import Optional

import config

PROFILES_DB_PATH = config.DB_DIR / "profiles.db"


def _get_conn() -> sqlite3.Connection:
    PROFILES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PROFILES_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS global_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_global(key: str, value: str) -> None:
    """Save a single global setting (insert or update)."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def save_globals(settings: dict[str, str]) -> None:
    """Save multiple global settings in one transaction."""
    conn = _get_conn()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)",
            list(settings.items()),
        )
        conn.commit()
    finally:
        conn.close()


def load_globals() -> dict[str, str]:
    """Load all global settings. Returns empty dict if none saved."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM global_settings").fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()


def load_global(key: str) -> Optional[str]:
    """Load a single global setting value. Returns None if not set."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = ?", (key,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()
