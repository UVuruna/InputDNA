"""
Extract and clean keyboard data from SQLite for ML training.

Loads keystrokes, key transitions, and shortcuts from keyboard.db.
Computes inter-key delays from consecutive transition timestamps.
Separates data by typing mode (text, numpad, code, shortcut).
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Maximum inter-key delay to consider a valid typing transition (ms).
# Longer gaps indicate a pause between typing sessions, not a transition.
_MAX_TRANSITION_DELAY_MS = 5000.0

# Minimum transitions per scan-code pair to include in digraph stats.
_MIN_PAIR_COUNT = 2


@dataclass
class DigraphEntry:
    """Statistics for a single scan-code pair transition."""
    from_scan: int
    to_scan: int
    delays_ms: np.ndarray   # All observed delays
    mean_ms: float = 0.0
    std_ms: float = 0.0
    median_ms: float = 0.0
    count: int = 0


@dataclass
class KeyHoldEntry:
    """Statistics for a single key's hold duration."""
    scan_code: int
    durations_ms: np.ndarray
    mean_ms: float = 0.0
    std_ms: float = 0.0
    median_ms: float = 0.0
    count: int = 0


@dataclass
class ShortcutEntry:
    """Statistics for a specific shortcut combination."""
    modifier_scans: list[int]
    main_scan: int
    modifier_to_main_ms: np.ndarray
    main_hold_ms: np.ndarray
    total_ms: np.ndarray
    release_order_counts: dict[str, int] = field(default_factory=dict)
    count: int = 0


@dataclass
class KeyboardDataset:
    """Complete keyboard dataset ready for model training."""
    # Digraph tables by typing mode
    text_digraphs: dict[tuple[int, int], DigraphEntry]
    numpad_digraphs: dict[tuple[int, int], DigraphEntry]
    code_digraphs: dict[tuple[int, int], DigraphEntry]
    # Key hold durations (all modes combined)
    key_holds: dict[int, KeyHoldEntry]
    # Shortcut timing profiles
    shortcuts: dict[str, ShortcutEntry]  # key = "mod1,mod2+main" string
    # Summary stats
    total_transitions: int
    total_keystrokes: int
    total_shortcuts: int


def load_keyboard_data(db_path: Path, progress_cb=None) -> KeyboardDataset:
    """
    Load and preprocess all keyboard data from keyboard.db.

    Args:
        db_path: Path to keyboard.db
        progress_cb: Optional callback(percent, message) for progress updates.
    """
    logger.info(f"Loading keyboard data from {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # ── Load key transitions ──────────────────────────────────
    if progress_cb:
        progress_cb(0, "Loading key transitions...")

    cursor = conn.execute(
        "SELECT from_scan, to_scan, typing_mode, t_ns "
        "FROM key_transitions ORDER BY id"
    )
    raw_transitions = cursor.fetchall()
    logger.info(f"  Loaded {len(raw_transitions):,} transitions")

    # ── Compute inter-key delays ──────────────────────────────
    if progress_cb:
        progress_cb(15, "Computing inter-key delays...")

    # Each transition's t_ns is the press timestamp of to_scan.
    # Delay = current t_ns - previous t_ns (when chain is valid).
    text_pairs: dict[tuple[int, int], list[float]] = {}
    numpad_pairs: dict[tuple[int, int], list[float]] = {}
    code_pairs: dict[tuple[int, int], list[float]] = {}

    valid_transitions = 0
    skipped_gap = 0
    skipped_chain = 0

    for i in range(1, len(raw_transitions)):
        prev = raw_transitions[i - 1]
        curr = raw_transitions[i]

        # Chain validation: previous to_scan must match current from_scan
        if prev["to_scan"] != curr["from_scan"]:
            skipped_chain += 1
            continue

        delay_ns = curr["t_ns"] - prev["t_ns"]
        delay_ms = delay_ns / 1_000_000

        # Filter unreasonable delays
        if delay_ms <= 0 or delay_ms > _MAX_TRANSITION_DELAY_MS:
            skipped_gap += 1
            continue

        pair = (curr["from_scan"], curr["to_scan"])
        mode = curr["typing_mode"]

        if mode == "text":
            text_pairs.setdefault(pair, []).append(delay_ms)
        elif mode == "numpad":
            numpad_pairs.setdefault(pair, []).append(delay_ms)
        elif mode == "code":
            code_pairs.setdefault(pair, []).append(delay_ms)
        # "shortcut" transitions are handled separately via shortcuts table

        valid_transitions += 1

    logger.info(
        f"  Valid transitions: {valid_transitions:,} "
        f"(skipped: {skipped_chain} chain breaks, {skipped_gap} too long/negative)"
    )

    # ── Build digraph tables ──────────────────────────────────
    if progress_cb:
        progress_cb(35, "Building digraph tables...")

    text_digraphs = _build_digraph_table(text_pairs)
    numpad_digraphs = _build_digraph_table(numpad_pairs)
    code_digraphs = _build_digraph_table(code_pairs)

    logger.info(
        f"  Digraph pairs — text: {len(text_digraphs)}, "
        f"numpad: {len(numpad_digraphs)}, code: {len(code_digraphs)}"
    )

    # ── Load keystrokes for hold duration ─────────────────────
    if progress_cb:
        progress_cb(50, "Loading keystrokes...")

    cursor = conn.execute(
        "SELECT scan_code, press_duration_ms FROM keystrokes"
    )
    raw_keystrokes = cursor.fetchall()
    logger.info(f"  Loaded {len(raw_keystrokes):,} keystrokes")

    # Group by scan code
    holds_by_scan: dict[int, list[float]] = {}
    for row in raw_keystrokes:
        scan = row["scan_code"]
        dur = row["press_duration_ms"]
        if dur > 0:  # Filter zero-duration (key repeat artifacts)
            holds_by_scan.setdefault(scan, []).append(dur)

    if progress_cb:
        progress_cb(65, "Computing hold statistics...")

    key_holds: dict[int, KeyHoldEntry] = {}
    for scan, durations in holds_by_scan.items():
        if len(durations) < _MIN_PAIR_COUNT:
            continue
        arr = np.array(durations, dtype=np.float64)
        key_holds[scan] = KeyHoldEntry(
            scan_code=scan,
            durations_ms=arr,
            mean_ms=float(np.mean(arr)),
            std_ms=float(np.std(arr)),
            median_ms=float(np.median(arr)),
            count=len(arr),
        )

    logger.info(f"  Key hold entries: {len(key_holds)}")

    # ── Load shortcuts ────────────────────────────────────────
    if progress_cb:
        progress_cb(75, "Loading shortcuts...")

    cursor = conn.execute(
        "SELECT modifier_scans, main_scan, modifier_to_main_ms, "
        "main_hold_ms, total_ms, release_order FROM shortcuts"
    )
    raw_shortcuts = cursor.fetchall()
    logger.info(f"  Loaded {len(raw_shortcuts):,} shortcuts")

    # Group by combo key
    shortcut_groups: dict[str, dict] = {}
    for row in raw_shortcuts:
        mod_scans = json.loads(row["modifier_scans"])
        main_scan = row["main_scan"]
        # Normalize key: sorted modifiers + main
        combo_key = ",".join(str(s) for s in sorted(mod_scans)) + f"+{main_scan}"

        if combo_key not in shortcut_groups:
            shortcut_groups[combo_key] = {
                "modifier_scans": mod_scans,
                "main_scan": main_scan,
                "modifier_to_main": [],
                "main_hold": [],
                "total": [],
                "release_orders": {},
            }
        g = shortcut_groups[combo_key]
        g["modifier_to_main"].append(row["modifier_to_main_ms"])
        g["main_hold"].append(row["main_hold_ms"])
        g["total"].append(row["total_ms"])
        order = row["release_order"]
        g["release_orders"][order] = g["release_orders"].get(order, 0) + 1

    if progress_cb:
        progress_cb(85, "Computing shortcut statistics...")

    shortcuts: dict[str, ShortcutEntry] = {}
    for combo_key, g in shortcut_groups.items():
        if len(g["modifier_to_main"]) < _MIN_PAIR_COUNT:
            continue
        shortcuts[combo_key] = ShortcutEntry(
            modifier_scans=g["modifier_scans"],
            main_scan=g["main_scan"],
            modifier_to_main_ms=np.array(g["modifier_to_main"], dtype=np.float64),
            main_hold_ms=np.array(g["main_hold"], dtype=np.float64),
            total_ms=np.array(g["total"], dtype=np.float64),
            release_order_counts=g["release_orders"],
            count=len(g["modifier_to_main"]),
        )

    logger.info(f"  Shortcut combos: {len(shortcuts)}")

    conn.close()

    if progress_cb:
        progress_cb(100, "Keyboard data loaded.")

    return KeyboardDataset(
        text_digraphs=text_digraphs,
        numpad_digraphs=numpad_digraphs,
        code_digraphs=code_digraphs,
        key_holds=key_holds,
        shortcuts=shortcuts,
        total_transitions=valid_transitions,
        total_keystrokes=len(raw_keystrokes),
        total_shortcuts=len(raw_shortcuts),
    )


def _build_digraph_table(
    pairs: dict[tuple[int, int], list[float]],
) -> dict[tuple[int, int], DigraphEntry]:
    """Convert raw delay lists into DigraphEntry objects with statistics."""
    table: dict[tuple[int, int], DigraphEntry] = {}
    for pair, delays in pairs.items():
        if len(delays) < _MIN_PAIR_COUNT:
            continue
        arr = np.array(delays, dtype=np.float64)
        table[pair] = DigraphEntry(
            from_scan=pair[0],
            to_scan=pair[1],
            delays_ms=arr,
            mean_ms=float(np.mean(arr)),
            std_ms=float(np.std(arr)),
            median_ms=float(np.median(arr)),
            count=len(arr),
        )
    return table
