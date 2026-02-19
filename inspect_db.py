"""
Database inspector — shows all tables, columns, and sample rows.

Reads profiles.db and all three per-user databases (mouse.db, keyboard.db,
session.db). Displays random sample rows from each table with formatted output.

Usage:
    python inspect_db.py                                    # auto-detect first user
    python inspect_db.py --user "Uros_Vuruna_1990-06-20"   # specific user folder
    python inspect_db.py --rows 5                           # fewer sample rows
    python inspect_db.py --profiles                         # show only profiles.db
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
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name != 'sqlite_sequence' "
        "ORDER BY name"
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


def find_user_folders() -> list[Path]:
    """Find all user folders in the DB directory."""
    if not config.DB_DIR.exists():
        return []
    folders = []
    for item in sorted(config.DB_DIR.iterdir()):
        if item.is_dir() and any(item.glob("*.db")):
            # Skip old user_N folders
            if not item.name.startswith("user_"):
                folders.append(item)
    return folders


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Input DNA databases")
    parser.add_argument("--user", type=str, default=None,
                        help="User folder name (e.g. Uros_Vuruna_1990-06-20)")
    parser.add_argument("--rows", type=int, default=10,
                        help="Number of sample rows per table (default: 10)")
    parser.add_argument("--profiles", action="store_true",
                        help="Show only profiles.db")
    args = parser.parse_args()

    profiles_path = config.DB_DIR / "profiles.db"

    # Always show profiles.db
    print("=" * 64)
    print(f"  PROFILES DATABASE: {profiles_path}")
    print("=" * 64)
    inspect_database(profiles_path, args.rows)

    if args.profiles:
        print()
        return

    # Determine user folder
    if args.user:
        user_folder = config.DB_DIR / args.user
    else:
        # Auto-detect first user folder
        folders = find_user_folders()
        if folders:
            user_folder = folders[0]
        else:
            print("\n  No user folders found.")
            print()
            return

    # Show all three databases
    for db_name, label in [("mouse.db", "MOUSE"), ("keyboard.db", "KEYBOARD"), ("session.db", "SESSION")]:
        db_path = user_folder / db_name
        print(f"\n\n{'=' * 64}")
        print(f"  {label} DATABASE: {db_path}")
        print("=" * 64)
        inspect_database(db_path, args.rows)

    print()


if __name__ == "__main__":
    main()
