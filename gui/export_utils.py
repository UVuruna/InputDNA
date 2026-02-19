"""
Data export utilities.

Copies the user's recording database files to a chosen destination.
Each user's data lives in data/db/Username_Surname_YYYY-MM-DD/ —
this module finds all .db files there and copies them.
"""

import logging
import shutil
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def get_user_db_files(username: str, surname: str, date_of_birth: str) -> list[Path]:
    """
    Get all .db files for a user (active + rotated archives).

    Returns empty list if user folder doesn't exist yet.
    """
    user_dir = config.get_user_folder(username, surname, date_of_birth)
    if not user_dir.exists():
        return []
    return sorted(user_dir.glob("*.db"))


def export_database(source: Path, dest_dir: Path) -> tuple[bool, str]:
    """
    Copy a single database file to the destination directory.

    Returns (success, message).
    """
    try:
        dest = dest_dir / source.name
        shutil.copy2(str(source), str(dest))
        return True, f"Exported {source.name} ({source.stat().st_size / 1024 / 1024:.1f} MB)"
    except OSError as e:
        logger.error(f"Export failed for {source}: {e}")
        return False, f"Failed to export {source.name}: {e}"


def export_all_user_data(username: str, surname: str, date_of_birth: str,
                         dest_dir: Path) -> tuple[int, int]:
    """
    Copy all database files for a user to the destination.

    Returns (success_count, total_count).
    """
    files = get_user_db_files(username, surname, date_of_birth)
    if not files:
        return 0, 0

    success = 0
    for f in files:
        ok, msg = export_database(f, dest_dir)
        if ok:
            success += 1
        logger.info(msg)

    return success, len(files)
