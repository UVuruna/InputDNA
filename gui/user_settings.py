"""
Per-user settings persistence.

Stores user-specific configuration overrides in the shared profiles.db.
Each setting is a key-value pair scoped to a user_id. Keys follow the
convention: "category.setting_name" (e.g. "recording.downsample_hz").

Settings in this table override the defaults in config.py when a user
is logged in. On logout, config values reset to defaults.
"""

import sqlite3
from typing import Optional

import config

PROFILES_DB_PATH = config.DB_DIR / "profiles.db"


def _get_conn() -> sqlite3.Connection:
    PROFILES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PROFILES_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id  INTEGER NOT NULL,
            key      TEXT    NOT NULL,
            value    TEXT    NOT NULL,
            PRIMARY KEY (user_id, key)
        )
    """)
    conn.commit()
    return conn


def save_setting(user_id: int, key: str, value: str) -> None:
    """Save a single setting for a user (insert or update)."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) "
            "VALUES (?, ?, ?)",
            (user_id, key, value),
        )
        conn.commit()
    finally:
        conn.close()


def save_settings(user_id: int, settings: dict[str, str]) -> None:
    """Save multiple settings for a user in one transaction."""
    conn = _get_conn()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) "
            "VALUES (?, ?, ?)",
            [(user_id, k, v) for k, v in settings.items()],
        )
        conn.commit()
    finally:
        conn.close()


def load_settings(user_id: int) -> dict[str, str]:
    """Load all settings for a user. Returns empty dict if none saved."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT key, value FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()


def load_setting(user_id: int, key: str) -> Optional[str]:
    """Load a single setting value. Returns None if not set."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def delete_settings(user_id: int) -> None:
    """Delete all settings for a user (reset to defaults)."""
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()
