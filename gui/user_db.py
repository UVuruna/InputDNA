"""
User profile database.

Stores registered user profiles locally in SQLite.
Each profile represents one person whose input patterns
are being recorded and modeled — their personalized robot.
"""

import sqlite3
from typing import Optional, Dict
from dataclasses import dataclass

import config


@dataclass
class UserProfile:
    id: int
    username: str
    surname: str
    date_of_birth: str  # ISO format YYYY-MM-DD
    created_at: str


PROFILES_DB_PATH = config.DB_DIR / "profiles.db"


def _get_conn() -> sqlite3.Connection:
    PROFILES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PROFILES_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            surname TEXT NOT NULL,
            date_of_birth TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def register(username: str, surname: str, dob: str) -> tuple[bool, str]:
    """
    Register a new user profile.
    Returns (success, message).
    """
    if not username.strip() or not surname.strip():
        return False, "Username and surname are required."

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO profiles (username, surname, date_of_birth) VALUES (?, ?, ?)",
            (username.strip(), surname.strip(), dob)
        )
        conn.commit()
        return True, f"Profile '{username}' created successfully."
    except sqlite3.IntegrityError:
        return False, f"Username '{username}' already exists."
    finally:
        conn.close()


def login(username: str) -> Optional[UserProfile]:
    """
    Log in with username. Returns UserProfile or None.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, username, surname, date_of_birth, created_at FROM profiles WHERE username = ?",
        (username.strip(),)
    ).fetchone()
    conn.close()

    if row:
        return UserProfile(id=row[0], username=row[1], surname=row[2],
                           date_of_birth=row[3], created_at=row[4])
    return None


def get_all_users() -> list[str]:
    """Get list of all registered usernames."""
    conn = _get_conn()
    rows = conn.execute("SELECT username FROM profiles ORDER BY username").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_all_profiles() -> list[UserProfile]:
    """Get all registered user profiles."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, username, surname, date_of_birth, created_at "
        "FROM profiles ORDER BY username"
    ).fetchall()
    conn.close()
    return [
        UserProfile(id=r[0], username=r[1], surname=r[2],
                    date_of_birth=r[3], created_at=r[4])
        for r in rows
    ]
