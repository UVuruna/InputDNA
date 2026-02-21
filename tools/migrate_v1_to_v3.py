"""
Migrate InputDNA databases from delta_v1 (old schema) to delta_v3 (new schema).

Source: V:/InputDNA/database-old/Uros_Vuruna_1990-06-20/
Target: (project root)/data/db/Uros_Vuruna_1990-06-20/

Run from the project root:
    python tools/migrate_v1_to_v3.py

delta_v1 path_point encoding (confirmed from data inspection):
  seq=0 : absolute x, y, t_ns (perf_counter_ns at point time)
  seq>0 : delta x, delta y, delta t_ns (nanoseconds since previous point)

delta_v3 path_point encoding:
  seq=0 : absolute x, y; dt_us=0 (timing anchored by movements.start_t_ns)
  seq>0 : delta x, delta y; dt_us = delta_t_ns // 1000
"""

import bisect
import json
import sqlite3
import sys
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

SRC_DIR = Path("V:/InputDNA/database-old/Uros_Vuruna_1990-06-20")
DST_DIR = Path(__file__).parent.parent / "data" / "db" / "Uros_Vuruna_1990-06-20"
BATCH = 10_000  # rows per INSERT batch

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def modifier_json_to_bitmask(value) -> int:
    """Convert {"ctrl": bool, "alt": bool, "shift": bool, "win": bool} → int bitmask.
    Encoding: bit0=Ctrl, bit1=Alt, bit2=Shift, bit3=Win.
    If value is already an int, return as-is.
    """
    if isinstance(value, int):
        return value
    try:
        d = json.loads(value)
        return (
            (bool(d.get("ctrl"))  << 0) |
            (bool(d.get("alt"))   << 1) |
            (bool(d.get("shift")) << 2) |
            (bool(d.get("win"))   << 3)
        )
    except Exception:
        return 0


def process_points(rows: list[tuple]) -> tuple[int, int, list[tuple]]:
    """
    Process path_points or drag_points rows from delta_v1 source.

    Input rows: list of (seq, x, y, t_ns) sorted by seq.
      seq=0 : absolute (x, y, t_ns)
      seq>0 : delta (Δx, Δy, Δt_ns)

    Returns:
      start_t_ns  — absolute perf_counter_ns of first point
      end_t_ns    — absolute perf_counter_ns of last point
      encoded     — list of (seq, x, y, dt_us) for delta_v3 INSERT
                    x,y unchanged (already delta-encoded), dt_us computed from t_ns
    """
    if not rows:
        return 0, 0, []

    start_t_ns = rows[0][3]  # seq=0 t_ns is absolute

    encoded = [(0, rows[0][1], rows[0][2], 0)]  # seq=0: dt_us=0

    cumulative_t_ns = start_t_ns
    for seq, x, y, t_ns in rows[1:]:
        dt_us = t_ns // 1000  # t_ns is already delta nanoseconds
        encoded.append((seq, x, y, dt_us))
        cumulative_t_ns += t_ns

    end_t_ns = cumulative_t_ns
    return start_t_ns, end_t_ns, encoded


def flush(dst: sqlite3.Connection, sql: str, batch: list) -> None:
    if batch:
        dst.executemany(sql, batch)
        dst.commit()
        batch.clear()


# ── Mouse DB ──────────────────────────────────────────────────────────────────

def migrate_mouse(src_path: Path, dst_path: Path) -> None:
    log("=== mouse.db ===")

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    dst_path.unlink(missing_ok=True)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from database.schema import init_mouse_db
    dst = init_mouse_db(dst_path)

    # ── movements + path_points ───────────────────────────────────────────────
    # Load all movements indexed by id.
    movements = {
        row["id"]: row
        for row in src.execute("SELECT * FROM movements ORDER BY id")
    }
    total_mov = len(movements)
    log(f"  {total_mov:,} movements, streaming path_points...")

    # Stream path_points grouped by movement_id (ordered, so they arrive in groups).
    batch_mov = []
    batch_pts = []
    movements_processed = set()

    cur = src.execute(
        "SELECT movement_id, seq, x, y, t_ns FROM path_points ORDER BY movement_id, seq"
    )

    current_mid = None
    current_pts = []

    def flush_movement(mid: int, pts: list[tuple]) -> None:
        mov = movements[mid]
        start_t_ns, end_t_ns, encoded = process_points(pts)
        batch_mov.append((
            mid,
            mov["start_x"], mov["start_y"],
            mov["end_x"],   mov["end_y"],
            mov["end_event"],
            start_t_ns, end_t_ns,
        ))
        for seq, x, y, dt_us in encoded:
            batch_pts.append((mid, seq, x, y, dt_us))
        movements_processed.add(mid)

    for movement_id, seq, x, y, t_ns in cur:
        if movement_id != current_mid:
            if current_mid is not None:
                flush_movement(current_mid, current_pts)
                if len(batch_mov) >= BATCH:
                    flush(dst,
                          "INSERT INTO movements (id,start_x,start_y,end_x,end_y,end_event,start_t_ns,end_t_ns) VALUES (?,?,?,?,?,?,?,?)",
                          batch_mov)
                    flush(dst,
                          "INSERT INTO path_points (movement_id,seq,x,y,dt_us) VALUES (?,?,?,?,?)",
                          batch_pts)
                    log(f"    {len(movements_processed):,}/{total_mov:,} movements")
            current_mid = movement_id
            current_pts = [(seq, x, y, t_ns)]
        else:
            current_pts.append((seq, x, y, t_ns))

    if current_mid is not None:
        flush_movement(current_mid, current_pts)

    # Movements without any path_points (use t_ns=0 as fallback).
    for mid, mov in movements.items():
        if mid not in movements_processed:
            batch_mov.append((
                mid,
                mov["start_x"], mov["start_y"],
                mov["end_x"],   mov["end_y"],
                mov["end_event"],
                0, 0,
            ))

    flush(dst,
          "INSERT INTO movements (id,start_x,start_y,end_x,end_y,end_event,start_t_ns,end_t_ns) VALUES (?,?,?,?,?,?,?,?)",
          batch_mov)
    flush(dst,
          "INSERT INTO path_points (movement_id,seq,x,y,dt_us) VALUES (?,?,?,?,?)",
          batch_pts)
    log(f"    {total_mov:,}/{total_mov:,} movements done")

    # ── click_sequences ───────────────────────────────────────────────────────
    log("  Migrating click_sequences...")
    batch = [
        (row["id"], row["movement_id"], row["button"])
        for row in src.execute("SELECT id, movement_id, button FROM click_sequences")
    ]
    n = len(batch)
    flush(dst, "INSERT INTO click_sequences (id,movement_id,button) VALUES (?,?,?)", batch)
    log(f"    {n} sequences done")

    # ── click_details ─────────────────────────────────────────────────────────
    log("  Migrating click_details...")
    batch = [
        (row["sequence_id"], row["seq"], row["press_duration_ms"], row["t_ns"])
        for row in src.execute(
            "SELECT sequence_id, seq, press_duration_ms, t_ns FROM click_details ORDER BY sequence_id, seq"
        )
    ]
    n = len(batch)
    flush(dst,
          "INSERT INTO click_details (sequence_id,seq,press_duration_ms,t_ns) VALUES (?,?,?,?)",
          batch)
    log(f"    {n} click details done")

    # ── drags + drag_points ───────────────────────────────────────────────────
    drags = {
        row["id"]: row
        for row in src.execute("SELECT * FROM drags ORDER BY id")
    }
    total_drags = len(drags)
    log(f"  {total_drags:,} drags, streaming drag_points...")

    # Build sorted lookup: (movement_start_t_ns, session_id) for session assignment.
    # For each drag we find the nearest movement by start_t_ns — within the same
    # perf_counter boot epoch the difference is always smaller than cross-epoch gaps.
    mov_times = sorted(
        (row[0], row[1])
        for row in src.execute("""
            SELECT pp.t_ns, m.recording_session_id
            FROM path_points pp
            JOIN movements m ON m.id = pp.movement_id
            WHERE pp.seq = 0
        """)
    )

    def find_session(start_t_ns: int) -> int:
        pos = bisect.bisect_left(mov_times, (start_t_ns, 0))
        candidates = []
        if pos < len(mov_times):
            candidates.append(mov_times[pos])
        if pos > 0:
            candidates.append(mov_times[pos - 1])
        return min(candidates, key=lambda c: abs(c[0] - start_t_ns))[1]

    drag_seq_per_session: dict[int, int] = {}

    batch_drags = []
    batch_dpts = []
    drags_processed = set()

    cur = src.execute(
        "SELECT drag_id, seq, x, y, t_ns FROM drag_points ORDER BY drag_id, seq"
    )

    current_did = None
    current_dpts = []

    def flush_drag(did: int, pts: list[tuple]) -> None:
        drag = drags[did]
        start_t_ns, end_t_ns, encoded = process_points(pts)
        session_id = find_session(start_t_ns)
        drag_seq_per_session[session_id] = drag_seq_per_session.get(session_id, 0) + 1
        new_id = session_id * 1_000_000 + drag_seq_per_session[session_id]
        batch_drags.append((
            new_id,
            drag["button"],
            drag["start_x"], drag["start_y"],
            start_t_ns, end_t_ns,
        ))
        for seq, x, y, dt_us in encoded:
            batch_dpts.append((new_id, seq, x, y, dt_us))
        drags_processed.add(did)

    for drag_id, seq, x, y, t_ns in cur:
        if drag_id != current_did:
            if current_did is not None:
                flush_drag(current_did, current_dpts)
                if len(batch_drags) >= BATCH:
                    flush(dst,
                          "INSERT INTO drags (id,button,start_x,start_y,start_t_ns,end_t_ns) VALUES (?,?,?,?,?,?)",
                          batch_drags)
                    flush(dst,
                          "INSERT INTO drag_points (drag_id,seq,x,y,dt_us) VALUES (?,?,?,?,?)",
                          batch_dpts)
                    log(f"    {len(drags_processed):,}/{total_drags:,} drags")
            current_did = drag_id
            current_dpts = [(seq, x, y, t_ns)]
        else:
            current_dpts.append((seq, x, y, t_ns))

    if current_did is not None:
        flush_drag(current_did, current_dpts)

    # Fallback: drags without any drag_points (assign to session 1).
    for did, drag in drags.items():
        if did not in drags_processed:
            drag_seq_per_session[1] = drag_seq_per_session.get(1, 0) + 1
            new_id = 1 * 1_000_000 + drag_seq_per_session[1]
            batch_drags.append((new_id, drag["button"], drag["start_x"], drag["start_y"], 0, 0))

    flush(dst,
          "INSERT INTO drags (id,button,start_x,start_y,start_t_ns,end_t_ns) VALUES (?,?,?,?,?,?)",
          batch_drags)
    flush(dst,
          "INSERT INTO drag_points (drag_id,seq,x,y,dt_us) VALUES (?,?,?,?,?)",
          batch_dpts)
    log(f"    {total_drags:,}/{total_drags:,} drags done")

    # ── scrolls ───────────────────────────────────────────────────────────────
    log("  Migrating scrolls...")
    batch = [
        (row["id"], row["movement_id"], row["delta"], row["x"], row["y"], row["t_ns"])
        for row in src.execute("SELECT id, movement_id, delta, x, y, t_ns FROM scrolls")
    ]
    n = len(batch)
    flush(dst, "INSERT INTO scrolls (id,movement_id,delta,x,y,t_ns) VALUES (?,?,?,?,?,?)", batch)
    log(f"    {n} scrolls done")

    src.close()
    dst.close()
    log("mouse.db done!")


# ── Keyboard DB ───────────────────────────────────────────────────────────────

def migrate_keyboard(src_path: Path, dst_path: Path) -> None:
    log("=== keyboard.db ===")

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    dst_path.unlink(missing_ok=True)

    from database.schema import init_keyboard_db
    dst = init_keyboard_db(dst_path)

    # ── keystrokes ────────────────────────────────────────────────────────────
    log("  Migrating keystrokes...")
    batch = [
        (
            row["scan_code"],
            row["press_duration_ms"],
            modifier_json_to_bitmask(row["modifier_state"]),
            row["t_ns"],
        )
        for row in src.execute(
            "SELECT scan_code, press_duration_ms, modifier_state, t_ns FROM keystrokes ORDER BY id"
        )
    ]
    n = len(batch)
    flush(dst,
          "INSERT INTO keystrokes (scan_code,press_duration_ms,modifier_state,t_ns) VALUES (?,?,?,?)",
          batch)
    log(f"    {n:,} keystrokes done")

    # ── key_transitions ───────────────────────────────────────────────────────
    log("  Migrating key_transitions...")
    batch = [
        (row["from_scan"], row["to_scan"], row["typing_mode"], row["t_ns"])
        for row in src.execute(
            "SELECT from_scan, to_scan, typing_mode, t_ns FROM key_transitions ORDER BY id"
        )
    ]
    n = len(batch)
    flush(dst,
          "INSERT INTO key_transitions (from_scan,to_scan,typing_mode,t_ns) VALUES (?,?,?,?)",
          batch)
    log(f"    {n:,} transitions done")

    # ── shortcuts ─────────────────────────────────────────────────────────────
    log("  Migrating shortcuts...")
    batch = [
        (
            row["modifier_scans"], row["main_scan"],
            row["modifier_to_main_ms"], row["main_hold_ms"],
            row["overlap_ms"], row["total_ms"],
            row["release_order"], row["t_ns"],
        )
        for row in src.execute(
            "SELECT modifier_scans, main_scan, modifier_to_main_ms, main_hold_ms, "
            "overlap_ms, total_ms, release_order, t_ns FROM shortcuts ORDER BY id"
        )
    ]
    n = len(batch)
    flush(dst,
          "INSERT INTO shortcuts (modifier_scans,main_scan,modifier_to_main_ms,main_hold_ms,overlap_ms,total_ms,release_order,t_ns) VALUES (?,?,?,?,?,?,?,?)",
          batch)
    log(f"    {n:,} shortcuts done")

    src.close()
    dst.close()
    log("keyboard.db done!")


# ── Session DB ────────────────────────────────────────────────────────────────

def migrate_session(src_path: Path, dst_path: Path) -> None:
    log("=== session.db ===")

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    dst_path.unlink(missing_ok=True)

    from database.schema import init_session_db
    dst = init_session_db(dst_path)

    # ── recording_sessions ────────────────────────────────────────────────────
    log("  Migrating recording_sessions...")
    batch = [
        (
            row["id"], row["started_at"], row["ended_at"],
            row["total_movements"], row["total_clicks"], row["total_keystrokes"],
            row["perf_counter_start_ns"],
        )
        for row in src.execute(
            "SELECT id, started_at, ended_at, total_movements, total_clicks, "
            "total_keystrokes, perf_counter_start_ns FROM recording_sessions"
        )
    ]
    n = len(batch)
    flush(dst,
          "INSERT INTO recording_sessions (id,started_at,ended_at,total_movements,total_clicks,total_keystrokes,perf_counter_start_ns) VALUES (?,?,?,?,?,?,?)",
          batch)
    log(f"    {n} sessions done")

    # ── system_events ─────────────────────────────────────────────────────────
    log("  Migrating system_events...")
    batch = [
        (row["id"], row["key"], row["value"], row["t_ns"], row["timestamp"])
        for row in src.execute("SELECT id, key, value, t_ns, timestamp FROM system_events")
    ]
    n = len(batch)
    flush(dst,
          "INSERT INTO system_events (id,key,value,t_ns,timestamp) VALUES (?,?,?,?,?)",
          batch)
    log(f"    {n} system events done")

    src.close()
    dst.close()
    log("session.db done!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not SRC_DIR.exists():
        print(f"ERROR: Source directory not found: {SRC_DIR}")
        sys.exit(1)

    log(f"Source : {SRC_DIR}")
    log(f"Target : {DST_DIR}")
    log("")

    t0 = time.time()

    migrate_mouse(   SRC_DIR / "mouse.db",    DST_DIR / "mouse.db")
    log("")
    migrate_keyboard(SRC_DIR / "keyboard.db", DST_DIR / "keyboard.db")
    log("")
    migrate_session( SRC_DIR / "session.db",  DST_DIR / "session.db")

    elapsed = time.time() - t0
    log(f"\nMigration complete in {elapsed:.1f}s")
    log(f"Output: {DST_DIR}")


if __name__ == "__main__":
    main()
