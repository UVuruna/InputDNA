# listeners/

Low-level OS event hooks. Each listener runs in its own thread and pushes
raw events to a shared queue for processing.

Listeners are intentionally DUMB — they capture what the OS gives them,
attach a precise timestamp, and push to the queue. No analysis, no filtering.

<a id="folder-structure"></a>

## Folder Structure

```
📁 listeners/
  📝 __listeners.md
  🐍 __init__.py
  🐍 mouse_listener.py
  🐍 keyboard_listener.py
```

<a id="files"></a>

## Files

### `mouse_listener.py` — Mouse Event Capture

Wraps `pynput.mouse.Listener` to capture move, click, and scroll events.
Each event gets a `perf_counter_ns` timestamp and is pushed as a raw
dataclass to the shared event queue.

**Events produced:**

| Event | Trigger | Data |
|-------|---------|------|
| `RawMouseMove` | Cursor moved | x, y, t_ns |
| `RawMouseClick` | Button pressed/released | x, y, button, pressed, t_ns |
| `RawMouseScroll` | Scroll wheel | x, y, dx, dy, t_ns |

Supports pause/resume via the global hotkey (`Ctrl+Alt+R`).

### `keyboard_listener.py` — Keyboard Event Capture

Wraps `pynput.keyboard.Listener` to capture key press/release events.
Extracts scan codes (physical key position) for layout-independent tracking.
Maintains modifier state (`ctrl`, `alt`, `shift`, `win`) internally.

**Events produced:**

| Event | Trigger | Data |
|-------|---------|------|
| `RawKeyPress` | Key pressed down | scan_code, vkey, key_name, t_ns, modifier_state, active_layout |
| `RawKeyRelease` | Key released | scan_code, key_name, t_ns, press_duration_ms |

Calculates key press duration (press→release) and pushes completed
`RawKeyRelease` events with duration attached.

<a id="data-flow"></a>

## Data Flow

```mermaid
flowchart LR
    OS[OS Input Events] --> ML[Mouse Listener]
    OS --> KL[Keyboard Listener]
    ML -- "RawMouse*" --> Q[Event Queue]
    KL -- "RawKey*" --> Q
    Q --> P[Processor Thread]
```

<a id="thread-safety"></a>

## Thread Safety

Both listeners push to the same `queue.Queue` which is thread-safe.
The processor thread is the sole consumer.

| Component | Thread | Role |
|-----------|--------|------|
| `MouseListener` | Thread 1 | Producer |
| `KeyboardListener` | Thread 2 | Producer |
| `EventProcessor` | Thread 3 | Consumer |

<a id="scan-code-extraction"></a>

## Scan Code Extraction

On Windows, pynput's key events contain a `vk` (virtual key code) but
not always a scan code directly. We use `ctypes.windll.user32.MapVirtualKeyW`
to convert vk → scan code when needed.

```mermaid
flowchart LR
    VK[Virtual Key Code] -- "MapVirtualKeyW" --> SC[Scan Code]
    SC -- "PHYSICAL_MAP lookup" --> HF[Hand + Finger]
```

For special keys (extended keys like Right Ctrl, arrows, numpad Enter),
we handle the extended flag to produce correct extended scan codes
(e.g., `0xE01D` for Right Ctrl).

> **Warning:** Virtual key codes are layout-dependent. Scan codes are not.
> Always use scan codes for timing analysis.
