"""
Database inspector — shows all tables, columns, and sample rows.

Reads both profiles.db and the active movements.db (per-user or fallback).
Displays 10 random rows from each table with formatted output.

Usage:
    python inspect_db.py
    python inspect_db.py --user 1        # inspect user_1's movements.db
    python inspect_db.py --rows 5        # show 5 rows instead of 10
"""

import argparse
import sqlite3
from pathlib import Path

import config


def inspect_database(db_path: Path, rows: int) -> None:
    """Print all tables, their columns, and sample rows from a database."""
    if not db_path.exists():
        print(f"  Database not found: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    if not tables:
        print("  (no tables)")
        conn.close()
        return

    for table_row in tables:
        table = table_row["name"]

        # Column info
        columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = [c["name"] for c in columns]
        col_types = [c["type"] for c in columns]

        # Row count
        count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]

        print(f"\n  {'─' * 60}")
        print(f"  TABLE: {table}  ({count} rows)")
        print(f"  {'─' * 60}")

        # Column listing
        print(f"  {'Column':<30} {'Type':<15}")
        print(f"  {'─' * 30} {'─' * 15}")
        for name, typ in zip(col_names, col_types):
            print(f"  {name:<30} {typ:<15}")

        # Sample rows
        if count == 0:
            print(f"\n  (empty table)")
            continue

        sample = conn.execute(
            f"SELECT * FROM [{table}] ORDER BY RANDOM() LIMIT ?", (rows,)
        ).fetchall()

        print(f"\n  Sample ({min(count, rows)} of {count} rows):")

        # Calculate column widths
        widths = []
        for i, name in enumerate(col_names):
            max_val = max(
                (len(str(row[i])) for row in sample),
                default=0,
            )
            widths.append(max(len(name), min(max_val, 40)))

        # Header
        header = " | ".join(n.ljust(w) for n, w in zip(col_names, widths))
        print(f"  {header}")
        print(f"  {' | '.join('─' * w for w in widths)}")

        # Data rows
        for row in sample:
            values = []
            for i, w in enumerate(widths):
                val = str(row[i])
                if len(val) > 40:
                    val = val[:37] + "..."
                values.append(val.ljust(w))
            print(f"  {' | '.join(values)}")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Input DNA databases")
    parser.add_argument("--user", type=int, default=None, help="User ID (inspect user's movements.db)")
    parser.add_argument("--rows", type=int, default=10, help="Number of sample rows per table (default: 10)")
    args = parser.parse_args()

    # Determine movements.db path
    if args.user is not None:
        movements_path = config.get_user_db_path(args.user)
    else:
        # Try user_1 first (most common), fallback to headless
        user_1_path = config.get_user_db_path(1)
        movements_path = user_1_path if user_1_path.exists() else config.DB_PATH

    profiles_path = config.DB_DIR / "profiles.db"

    print("=" * 64)
    print(f"  PROFILES DATABASE: {profiles_path}")
    print("=" * 64)
    inspect_database(profiles_path, args.rows)

    print(f"\n\n{'=' * 64}")
    print(f"  MOVEMENTS DATABASE: {movements_path}")
    print("=" * 64)
    inspect_database(movements_path, args.rows)

    print()


if __name__ == "__main__":
    main()
