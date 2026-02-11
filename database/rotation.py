"""
Database rotation — archive old DB when it exceeds size threshold.

Called once at session start. If the active DB file exceeds
DB_ROTATION_MAX_BYTES, it is renamed with a timestamp suffix
and a fresh DB is created. The old file is VACUUMed in a
background thread to reclaim unused space.
"""

import sqlite3
import logging
import threading
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def check_and_rotate(db_path: Path) -> Path:
    """
    Check if DB file needs rotation. If so, rename the old file
    and return the (now empty) db_path for fresh initialization.

    Returns the path to use for the new session (always db_path).
    """
    if config.DB_ROTATION_MAX_BYTES == 0:
        return db_path

    if not db_path.exists():
        return db_path

    size = db_path.stat().st_size
    if size < config.DB_ROTATION_MAX_BYTES:
        logger.info(
            f"DB size: {size / (1024*1024):.1f} MB "
            f"(threshold: {config.DB_ROTATION_MAX_BYTES / (1024*1024*1024):.1f} GB) — no rotation needed"
        )
        return db_path

    # Rotate: rename old file with timestamp suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived_name = db_path.stem + f"_{timestamp}" + db_path.suffix
    archived_path = db_path.parent / archived_name

    logger.info(
        f"DB rotation: {size / (1024*1024*1024):.2f} GB exceeds threshold. "
        f"Archiving to {archived_name}"
    )

    # Also rename WAL and SHM files if they exist
    for suffix in ("", "-wal", "-shm"):
        src = db_path.parent / (db_path.name + suffix)
        dst = db_path.parent / (archived_name + suffix)
        if src.exists():
            src.rename(dst)

    # VACUUM the archived DB in background thread
    _vacuum_in_background(archived_path)

    return db_path


def _vacuum_in_background(db_path: Path):
    """Run VACUUM on archived DB in a background thread."""
    def _vacuum():
        try:
            logger.info(f"VACUUM started on {db_path.name}")
            conn = sqlite3.connect(str(db_path))
            conn.execute("VACUUM")
            conn.close()
            size_after = db_path.stat().st_size
            logger.info(
                f"VACUUM completed on {db_path.name} "
                f"(size after: {size_after / (1024*1024):.1f} MB)"
            )
        except Exception:
            logger.exception(f"VACUUM failed on {db_path.name}")

    thread = threading.Thread(target=_vacuum, name="db-vacuum", daemon=True)
    thread.start()
