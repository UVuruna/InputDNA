"""
Batched database writer.

Single-threaded writer that consumes records from a thread-safe queue
and writes them in batches to SQLite. Routes each record to the correct
database (mouse, keyboard, or session) based on its _db_target attribute.

All DB writes in the recorder go through this writer — no concurrent
access issues.

Batching: records accumulate until BATCH_SIZE is reached or
FLUSH_INTERVAL seconds have passed, whichever comes first.
Each flush groups records by target DB and commits separately.
"""

import queue
import sqlite3
import threading
import time
import logging
from collections import defaultdict
from pathlib import Path

import config

logger = logging.getLogger(__name__)


class DatabaseWriter:
    """
    Consumes records from a queue and writes them to SQLite in batches.

    Routes records to the correct database based on record._db_target:
    - "mouse"    → mouse.db
    - "keyboard" → keyboard.db
    - "session"  → session.db

    Usage:
        writer = DatabaseWriter(mouse_db, keyboard_db, session_db)
        writer.start()
        writer.put(some_record)   # Thread-safe, called from any thread
        ...
        writer.stop()             # Flushes remaining and closes
    """

    def __init__(self, mouse_db: Path, keyboard_db: Path, session_db: Path,
                 batch_size: int = config.BATCH_SIZE,
                 flush_interval: float = config.FLUSH_INTERVAL_S):
        self._db_paths = {
            "mouse": mouse_db,
            "keyboard": keyboard_db,
            "session": session_db,
        }
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._records_written = 0
        self._flushes = 0

    def start(self):
        """Start the writer thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, name="db-writer", daemon=True)
        self._thread.start()
        logger.info("Database writer started")

    def put(self, record):
        """
        Add a record to the write queue. Thread-safe.

        Record must have a write_to_db(conn) method and a _db_target attribute.
        """
        self._queue.put(record)

    def stop(self):
        """Stop writer, flush remaining records, close connections."""
        logger.info("Database writer stopping...")
        self._running = False
        self._queue.put(None)  # Wake up any blocking get()
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info(
            f"Database writer stopped. "
            f"Total: {self._records_written} records in {self._flushes} flushes"
        )

    @property
    def pending(self) -> int:
        """Number of records waiting to be written."""
        return self._queue.qsize()

    @property
    def total_written(self) -> int:
        """Total records written since start."""
        return self._records_written

    def _run(self):
        """Main writer loop. Runs in dedicated thread."""
        conns = {
            name: sqlite3.connect(str(path))
            for name, path in self._db_paths.items()
        }
        batch: list = []
        last_flush = time.monotonic()

        try:
            while self._running or not self._queue.empty():
                # Short timeout when batch has items (need to respect flush interval).
                # Long timeout when batch is empty (nothing pending — wake up on new record).
                timeout = 0.1 if batch else self.flush_interval
                try:
                    record = self._queue.get(timeout=timeout)
                    if record is None:  # sentinel from stop()
                        break
                    batch.append(record)
                except queue.Empty:
                    pass

                # Check if we should flush
                now = time.monotonic()
                time_to_flush = (now - last_flush) >= self.flush_interval
                batch_full = len(batch) >= self.batch_size

                if batch and (batch_full or time_to_flush):
                    self._flush(conns, batch)
                    batch = []
                    last_flush = time.monotonic()

            # Final flush on shutdown
            if batch:
                self._flush(conns, batch)

        except Exception:
            logger.exception("Database writer error")
        finally:
            for conn in conns.values():
                conn.close()

    def _flush(self, conns: dict[str, sqlite3.Connection], batch: list):
        """Write a batch of records, grouped by target DB, each in its own transaction."""
        try:
            # Group records by target database
            grouped: dict[str, list] = defaultdict(list)
            for record in batch:
                grouped[record._db_target].append(record)

            # Write each group in its own transaction
            for target, records in grouped.items():
                conn = conns[target]
                with conn:  # Auto commit/rollback
                    for record in records:
                        record.write_to_db(conn)

            count = len(batch)
            self._records_written += count
            self._flushes += 1
            logger.debug(f"Flushed {count} records (total: {self._records_written})")
        except Exception:
            logger.exception(f"Failed to flush {len(batch)} records")
