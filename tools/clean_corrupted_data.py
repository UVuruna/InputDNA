"""
Clean corruption from already-recorded InputDNA databases (in place).

Two capture bugs polluted data recorded before the 0.4.15x/0.4.16x fixes:

  1. Keyboard auto-repeat — a held key emitted a KeyTransitionRecord
     (from_scan == to_scan) at the OS repeat rate (~30 ms), flooding the
     digraph / flight-time distributions with artificial same-key pairs.

  2. Phantom drag clicks — every drag also emitted a click_details row whose
     press_duration_ms equals the entire drag hold (often seconds), poisoning
     the click-duration signature.

This script removes those artifacts from an existing user's databases. It does
NOT touch anything else. Run once per affected user folder.

Usage (from project root):
    python tools/clean_corrupted_data.py "<path to user folder>"
    python tools/clean_corrupted_data.py "<...>" --dry-run          # report only
    python tools/clean_corrupted_data.py "<...>" --repeat-gap-ms 50 # tune threshold

The user folder is the one containing mouse.db and keyboard.db, e.g.
    data/db/Uros_Vuruna_1990-06-20/

A timestamped backup copy of each modified database is written next to it
before any deletion. Run the app closed (no active recording).
"""

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

# Same-key (from_scan == to_scan) transitions whose gap to the previous
# transition row is below this are treated as OS auto-repeat and deleted.
# Genuine double-letters ("ll", "ee") sit well above this; OS repeat is ~30 ms.
# The first repeat of a hold (after the ~250-500 ms initial repeat delay) is
# intentionally kept — it is indistinguishable from a slow double-letter, so
# this errs toward preserving real data.
DEFAULT_REPEAT_MAX_GAP_MS = 60.0

# A phantom click's press_duration_ms equals its drag's duration by
# construction; require the match to be this tight (ms) so a genuine click that
# merely falls inside a drag's time window (or a cross-reboot perf_counter
# coincidence) is never deleted.
PHANTOM_DURATION_TOLERANCE_MS = 1.0


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _checkpoint_and_backup(db_path: Path) -> Path:
    """Checkpoint the WAL and copy the database to a timestamped backup."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}.pre-clean-{stamp}{db_path.suffix}")
    shutil.copy2(db_path, backup)
    return backup


# ── Keyboard: auto-repeat transitions ─────────────────────────────────────────

def clean_keyboard(db_path: Path, repeat_max_gap_ms: float, dry_run: bool) -> None:
    log(f"=== keyboard.db — {db_path}")
    if not db_path.exists():
        log("  not found, skipping")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) FROM key_transitions").fetchone()[0]
    log(f"  {total:,} transitions total — scanning for auto-repeat runs...")

    # Walk transitions in id order; flag same-key rows whose gap to the previous
    # row is below the repeat threshold (the OS repeat flood).
    rows = conn.execute(
        "SELECT id, from_scan, to_scan, t_ns FROM key_transitions ORDER BY id"
    )
    to_delete: list[int] = []
    prev_t_ns = None
    scanned = 0
    for r in rows:
        if prev_t_ns is not None and r["from_scan"] == r["to_scan"]:
            gap_ms = (r["t_ns"] - prev_t_ns) / 1_000_000
            if 0 <= gap_ms < repeat_max_gap_ms:
                to_delete.append(r["id"])
        prev_t_ns = r["t_ns"]
        scanned += 1
        if scanned % 200_000 == 0:
            log(f"    scanned {scanned:,}/{total:,}")

    pct = (len(to_delete) / total * 100) if total else 0.0
    log(f"  auto-repeat transitions to remove: {len(to_delete):,} ({pct:.1f}%)")

    if dry_run:
        log("  DRY RUN — nothing deleted")
        conn.close()
        return

    if to_delete:
        backup = _checkpoint_and_backup(db_path)
        log(f"  backup: {backup.name}")
        # Reopen after the checkpoint/backup connection was closed.
        conn.close()
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.executemany(
                "DELETE FROM key_transitions WHERE id = ?",
                [(i,) for i in to_delete],
            )
        log(f"  deleted {len(to_delete):,} rows")
    conn.close()


# ── Mouse: phantom drag clicks ────────────────────────────────────────────────

def _phantom_predicate(alias: str) -> str:
    """
    SQL boolean: a click row (referenced as `alias`) is a phantom drag click.

    True when it falls inside a drag's hold window AND its press duration equals
    that drag's duration (how the bug produced it). `?` binds the tolerance ms.
    """
    return (
        f"EXISTS (SELECT 1 FROM drags d "
        f"        WHERE {alias}.t_ns BETWEEN d.start_t_ns AND d.end_t_ns "
        f"          AND ABS({alias}.press_duration_ms "
        f"                  - (d.end_t_ns - d.start_t_ns) / 1000000.0) < ?)"
    )


def clean_mouse(db_path: Path, dry_run: bool) -> None:
    log(f"=== mouse.db — {db_path}")
    if not db_path.exists():
        log("  not found, skipping")
        return

    conn = sqlite3.connect(str(db_path))
    tol = (PHANTOM_DURATION_TOLERANCE_MS,)
    phantom = _phantom_predicate("click_details")

    total = conn.execute("SELECT COUNT(*) FROM click_details").fetchone()[0]
    n_phantom = conn.execute(
        f"SELECT COUNT(*) FROM click_details WHERE {phantom}", tol
    ).fetchone()[0]
    pct = (n_phantom / total * 100) if total else 0.0
    log(f"  {total:,} click_details total — phantom drag clicks: "
        f"{n_phantom:,} ({pct:.1f}%)")

    if dry_run:
        # Sequences whose every detail row is phantom would be emptied.
        cd_phantom = _phantom_predicate("cd")
        n_seq = conn.execute(
            "SELECT COUNT(*) FROM click_sequences cs "
            "WHERE EXISTS (SELECT 1 FROM click_details cd WHERE cd.sequence_id = cs.id) "
            f"  AND NOT EXISTS (SELECT 1 FROM click_details cd "
            f"                  WHERE cd.sequence_id = cs.id AND NOT ({cd_phantom}))",
            tol,
        ).fetchone()[0]
        log(f"  click_sequences that would be emptied: {n_seq:,}")
        log("  DRY RUN — nothing deleted")
        conn.close()
        return

    if n_phantom:
        conn.close()
        backup = _checkpoint_and_backup(db_path)
        log(f"  backup: {backup.name}")
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute(f"DELETE FROM click_details WHERE {phantom}", tol)
            # Remove sequences left with no detail rows.
            cur = conn.execute(
                "DELETE FROM click_sequences "
                "WHERE id NOT IN (SELECT DISTINCT sequence_id FROM click_details)"
            )
            log(f"  deleted {n_phantom:,} phantom clicks, "
                f"{cur.rowcount:,} emptied sequences")
    conn.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Clean auto-repeat and phantom-drag corruption from InputDNA databases.")
    parser.add_argument("folder", help="User data folder containing mouse.db and keyboard.db")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted, change nothing")
    parser.add_argument("--repeat-gap-ms", type=float, default=DEFAULT_REPEAT_MAX_GAP_MS,
                        help=f"Same-key gap below which a transition is auto-repeat (default {DEFAULT_REPEAT_MAX_GAP_MS})")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"ERROR: not a folder: {folder}")
        sys.exit(1)

    log(f"Folder  : {folder}")
    log(f"Mode    : {'DRY RUN' if args.dry_run else 'CLEAN (in place, with backup)'}")
    log("")

    t0 = time.time()
    clean_keyboard(folder / "keyboard.db", args.repeat_gap_ms, args.dry_run)
    log("")
    clean_mouse(folder / "mouse.db", args.dry_run)

    log("")
    log(f"Done in {time.time() - t0:.1f}s")
    if not args.dry_run:
        log("Tip: run 'VACUUM' on the databases to reclaim space if many rows were removed.")


if __name__ == "__main__":
    main()
