# tools/

One-off scripts for database maintenance and migration. Not part of the recorder runtime.

<a id="folder-structure"></a>

## Folder Structure

```
📁 tools/
  📝 __tools.md
  🐍 migrate_v1_to_v3.py
  🐍 clean_corrupted_data.py
```

<a id="files"></a>

## Files

### `migrate_v1_to_v3.py` — Database Migration (delta_v1 → delta_v3)

Migrates a user's databases from the old schema (`delta_v1`) to the current
schema (`delta_v3`). Run once per user when upgrading from an old installation.

**Source:** `V:/InputDNA/database-old/<username>/`
**Target:** `data/db/<username>/`

**Run from project root:**
```
python tools/migrate_v1_to_v3.py
```

**What changes between delta_v1 and delta_v3:**

| Table | delta_v1 | delta_v3 |
|-------|----------|----------|
| `movements` | Many derived columns (`duration_ms`, `distance_px`, `point_count`, `hour_of_day`, `day_of_week`, `timestamp`, `recording_session_id`) | Only raw fields: `start_t_ns`, `end_t_ns`, coordinates, `end_event` |
| `path_points` | `id` (autoincrement), absolute `t_ns` per point | No `id`, `dt_us` (delta µs), WITHOUT ROWID, composite PK |
| `drag_points` | `id` (autoincrement), absolute `t_ns` per point | No `id`, `dt_us` (delta µs), WITHOUT ROWID, composite PK |
| `click_details` | Many derived columns (`x`, `y`, `delay_since_prev_ms`) | Only `press_duration_ms`, `t_ns`, composite PK WITHOUT ROWID |
| `drags` | Auto-increment `id`, many derived columns | App-generated `id = session_id × 1_000_000 + seq`, raw fields only |
| `keystrokes` | `modifier_state` as JSON string | `modifier_state` as INTEGER bitmask |
| `shortcuts` | Extra derived columns | Only timing profile fields |

**Key migration logic:**

- **`process_points()`** — converts delta_v1 point rows to delta_v3 encoding:
  - `seq=0`: absolute `t_ns` → becomes `movements.start_t_ns`; `dt_us=0`
  - `seq>0`: delta `t_ns` (ns) → `dt_us = t_ns // 1000`
  - x,y values are unchanged (already delta-encoded in delta_v1)
  - Accumulates all delta t_ns to compute `end_t_ns`

- **Drag ID assignment** — old drags had auto-increment IDs (1, 2, 3...). New IDs
  follow `session_id × 1_000_000 + seq_within_session`. Session is determined by
  finding the nearest movement by `start_t_ns` (binary search). Across boot
  epochs (perf_counter reset on restart), inter-epoch t_ns differences always
  exceed intra-epoch differences, so nearest-movement correctly identifies session.

- **`modifier_json_to_bitmask()`** — converts old JSON `{"ctrl": true, "shift": false, ...}`
  to integer bitmask: `bit0=Ctrl, bit1=Alt, bit2=Shift, bit3=Win`.

**Streaming:** path_points (3.5M+ rows) and drag_points (314K+ rows) are streamed
grouped by parent ID — never fully loaded into memory. Batch size: 10,000 rows.

### `clean_corrupted_data.py` — Remove Capture-Bug Artifacts (in place)

Cleans two classes of corruption from databases recorded **before** the
0.4.15x/0.4.16x capture fixes:

1. **Keyboard auto-repeat** — a held key emitted `key_transitions` rows with
   `from_scan == to_scan` at the OS repeat rate (~30 ms), flooding digraph /
   flight-time distributions. Removed by scanning transitions in `id` order and
   deleting same-key rows whose gap to the previous row is below
   `--repeat-gap-ms` (default 60 ms). Genuine double-letters ("ll", "ee") sit
   well above that and are kept; the first repeat of a hold (after the long
   initial repeat delay) is intentionally kept too — the script errs toward
   preserving real data.
2. **Phantom drag clicks** — every drag also wrote a `click_details` row whose
   `press_duration_ms` equals the whole drag. Removed by matching click rows
   that fall inside a drag's `[start_t_ns, end_t_ns]` window **and** whose press
   duration equals that drag's duration (tight tolerance, so a genuine click or
   a cross-reboot `perf_counter` coincidence is never deleted). Sequences left
   with no detail rows are then dropped.

**Run from project root:**
```
python tools/clean_corrupted_data.py "<user folder>"            # clean in place
python tools/clean_corrupted_data.py "<user folder>" --dry-run  # report only
```

The user folder is the one containing `mouse.db` and `keyboard.db`. A
timestamped backup copy of each modified database is written next to it before
any deletion. Run with the app closed (no active recording).

> **Note:** New recordings tag auto-repeat via `key_transitions.is_repeat`; this
> script is only for legacy data recorded before that column existed.

<a id="design-decisions"></a>

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Read-only source connection | `file:...?mode=ro` — prevents any accidental writes to original data |
| Delete and recreate target | Clean slate avoids partial migration artifacts |
| Streaming by parent ID | Path_points are too large to load into memory; ORDER BY parent_id enables group-by-group streaming |
| Nearest-movement session assignment for drags | Drags didn't have `recording_session_id` in old schema; temporal proximity reliably identifies session even across boot epochs |
| VACUUM not called after migration | Caller's responsibility — run `VACUUM` manually after migration to compact the database |
