# Replay Engine - MouseMux Integration

## Overview

The Replay Engine executes ML-generated human-like inputs through MouseMux's WebSocket API. It translates predicted movements and keystrokes into precise MouseMux commands with accurate timing.

This is the final piece that connects:
```
ML Models → Replay Engine → MouseMux → Chrome Windows → Betting Sites
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      ROBIN WORKER                           │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │  Worker Logic   │───►│ HumanSimulator  │                │
│  │                 │    │   (ML Models)   │                │
│  │ "Click bet btn" │    │                 │                │
│  └─────────────────┘    └────────┬────────┘                │
│                                  │                          │
│                     Path + Timing + Click params            │
│                                  │                          │
│                                  ▼                          │
│                    ┌─────────────────────────┐              │
│                    │     REPLAY ENGINE       │              │
│                    │                         │              │
│                    │  - Command Queue        │              │
│                    │  - Precision Timer      │              │
│                    │  - MouseMux Protocol    │              │
│                    └────────────┬────────────┘              │
│                                 │                           │
└─────────────────────────────────┼───────────────────────────┘
                                  │
                      WebSocket (ws://localhost:41001)
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                        MOUSEMUX                             │
│                                                             │
│    Virtual User (hwid_ms=0x3000, hwid_kb=0x3001)           │
│                          │                                  │
│                          ▼                                  │
│              Claimed Chrome Window (Bet365)                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. MouseMuxClient

WebSocket connection handler for a single virtual user.

```python
class MouseMuxClient:
    """Low-level MouseMux WebSocket client."""

    def __init__(self, url="ws://localhost:41001"):
        self.url = url
        self.ws = None
        self.hwid_ms = None  # Mouse hardware ID
        self.hwid_kb = None  # Keyboard hardware ID
        self.connected = False

    async def connect(self):
        """Establish WebSocket connection and login."""
        self.ws = await websockets.connect(self.url)
        await self._login()
        await self._create_user()
        self.connected = True

    async def _login(self):
        """Send login request."""
        await self.ws.send(json.dumps({
            "type": "client.login.request.A2M",
            "appName": "Robin",
            "appVersion": "1.0",
            "sdkVersion": "2.2.35"
        }))
        # Wait for server.info.notify.M2A
        await self._wait_for_message("server.info.notify.M2A")

    async def _create_user(self):
        """Request HWIDs and create virtual user."""
        # Request HWIDs
        await self.ws.send(json.dumps({
            "type": "user.hwid.request.A2M"
        }))
        response = await self._wait_for_message("user.hwid.request.A2M")
        self.hwid_ms = response["hwid_ms"]
        self.hwid_kb = response["hwid_kb"]

        # Create user
        await self.ws.send(json.dumps({
            "type": "user.create.request.A2M",
            "hwid_ms": self.hwid_ms,
            "hwid_kb": self.hwid_kb
        }))

    # ─────────────────────────────────────────────────────────
    # LOW-LEVEL COMMANDS (immediate execution)
    # ─────────────────────────────────────────────────────────

    async def move_to(self, x: int, y: int):
        """Move mouse to absolute screen position."""
        await self.ws.send(json.dumps({
            "type": "pointer.motion.request.A2M",
            "hwid": self.hwid_ms,
            "x": x,
            "y": y
        }))

    async def mouse_down(self, button: str = "left"):
        """Press mouse button."""
        button_code = {
            "left": 0x01,
            "right": 0x04,
            "middle": 0x10
        }[button]
        await self.ws.send(json.dumps({
            "type": "pointer.button.request.A2M",
            "hwid": self.hwid_ms,
            "button": button_code
        }))

    async def mouse_up(self, button: str = "left"):
        """Release mouse button."""
        button_code = {
            "left": 0x02,
            "right": 0x08,
            "middle": 0x20
        }[button]
        await self.ws.send(json.dumps({
            "type": "pointer.button.request.A2M",
            "hwid": self.hwid_ms,
            "button": button_code
        }))

    async def scroll(self, delta: int, horizontal: bool = False):
        """Mouse wheel scroll."""
        msg = {
            "type": "pointer.wheel.request.A2M",
            "hwid": self.hwid_ms,
            "delta": delta
        }
        if horizontal:
            msg["horizontal"] = True
        await self.ws.send(json.dumps(msg))

    async def key_down(self, vkey: int):
        """Press keyboard key."""
        await self.ws.send(json.dumps({
            "type": "keyboard.key.request.A2M",
            "hwid": self.hwid_kb,
            "vkey": vkey,
            "message": 0x100,  # WM_KEYDOWN
            "scan": vkey,
            "flags": 0
        }))

    async def key_up(self, vkey: int):
        """Release keyboard key."""
        await self.ws.send(json.dumps({
            "type": "keyboard.key.request.A2M",
            "hwid": self.hwid_kb,
            "vkey": vkey,
            "message": 0x101,  # WM_KEYUP
            "scan": vkey,
            "flags": 0
        }))

    async def dispose(self):
        """Clean up virtual user and disconnect."""
        if self.hwid_ms:
            await self.ws.send(json.dumps({
                "type": "user.dispose.request.A2M",
                "hwid_ms": self.hwid_ms,
                "hwid_kb": self.hwid_kb
            }))
        await self.ws.close()
        self.connected = False
```

---

### 2. ReplayEngine

High-level executor that takes ML-generated sequences and executes them with precise timing.

```python
class ReplayEngine:
    """Executes human-like input sequences via MouseMux."""

    def __init__(self, mmx_client: MouseMuxClient):
        self.mmx = mmx_client
        self.current_pos = (0, 0)

    # ─────────────────────────────────────────────────────────
    # MOUSE OPERATIONS
    # ─────────────────────────────────────────────────────────

    async def execute_movement(self, path_points: List[PathPoint]):
        """
        Execute a complete mouse movement.

        path_points: List of PathPoint(x, y, timestamp_ms)
        """
        if not path_points:
            return

        start_time = time.perf_counter()

        for i, point in enumerate(path_points):
            # Calculate when this point should be executed
            target_time = start_time + (point.timestamp_ms / 1000)

            # Wait until target time
            now = time.perf_counter()
            if target_time > now:
                await asyncio.sleep(target_time - now)

            # Execute move
            await self.mmx.move_to(point.x, point.y)
            self.current_pos = (point.x, point.y)

    async def execute_click(self, click_params: ClickParams):
        """
        Execute a click with human-like timing.

        click_params:
            - pre_pause_ms: Hover time before click
            - hold_duration_ms: How long to hold button
            - post_pause_ms: Pause after release
            - recoil: Optional (dx, dy) micro-movement after click
        """
        # Pre-click pause (with jitter if specified)
        if click_params.pre_pause_ms > 0:
            if click_params.jitter_points:
                await self._execute_jitter(
                    click_params.pre_pause_ms,
                    click_params.jitter_points
                )
            else:
                await asyncio.sleep(click_params.pre_pause_ms / 1000)

        # Mouse down
        await self.mmx.mouse_down(click_params.button)

        # Hold duration
        await asyncio.sleep(click_params.hold_duration_ms / 1000)

        # Mouse up
        await self.mmx.mouse_up(click_params.button)

        # Post-click recoil
        if click_params.recoil:
            await asyncio.sleep(0.01)  # Tiny delay
            new_x = self.current_pos[0] + click_params.recoil[0]
            new_y = self.current_pos[1] + click_params.recoil[1]
            await self.mmx.move_to(new_x, new_y)
            self.current_pos = (new_x, new_y)

        # Post-click pause
        if click_params.post_pause_ms > 0:
            await asyncio.sleep(click_params.post_pause_ms / 1000)

    async def _execute_jitter(self, duration_ms: int, jitter_points: List):
        """Execute micro-jitter movements during hover."""
        start_time = time.perf_counter()
        base_x, base_y = self.current_pos

        for point in jitter_points:
            target_time = start_time + (point.timestamp_ms / 1000)
            if target_time > time.perf_counter():
                await asyncio.sleep(target_time - time.perf_counter())

            jitter_x = base_x + point.dx
            jitter_y = base_y + point.dy
            await self.mmx.move_to(jitter_x, jitter_y)

    async def execute_scroll(self, scroll_params: ScrollParams):
        """Execute mouse wheel scroll."""
        for _ in range(scroll_params.ticks):
            await self.mmx.scroll(
                scroll_params.delta_per_tick,
                scroll_params.horizontal
            )
            if scroll_params.delay_between_ms:
                await asyncio.sleep(scroll_params.delay_between_ms / 1000)

    async def execute_drag(self, drag_path: List[PathPoint]):
        """Execute click-drag-release operation."""
        if not drag_path:
            return

        # Move to start
        await self.mmx.move_to(drag_path[0].x, drag_path[0].y)

        # Mouse down
        await self.mmx.mouse_down("left")

        # Execute drag path (skip first point, already there)
        await self.execute_movement(drag_path[1:])

        # Mouse up
        await self.mmx.mouse_up("left")

    # ─────────────────────────────────────────────────────────
    # KEYBOARD OPERATIONS
    # ─────────────────────────────────────────────────────────

    async def execute_typing(self, key_events: List[KeyEvent]):
        """
        Execute a sequence of keyboard events.

        key_events: List of KeyEvent objects:
            - KeyDown(vkey)
            - KeyUp(vkey)
            - Wait(ms)
        """
        for event in key_events:
            if isinstance(event, KeyDown):
                await self.mmx.key_down(event.vkey)
            elif isinstance(event, KeyUp):
                await self.mmx.key_up(event.vkey)
            elif isinstance(event, Wait):
                await asyncio.sleep(event.ms / 1000)

    async def execute_shortcut(self, shortcut_events: List[KeyEvent]):
        """Execute a keyboard shortcut sequence."""
        # Same as typing, shortcuts are just KeyEvent sequences
        await self.execute_typing(shortcut_events)

    # ─────────────────────────────────────────────────────────
    # HIGH-LEVEL OPERATIONS
    # ─────────────────────────────────────────────────────────

    async def move_and_click(
        self,
        target_x: int,
        target_y: int,
        simulator: HumanSimulator
    ):
        """
        Complete human-like move-and-click operation.

        Uses ML models to generate realistic path and timing.
        """
        # Generate movement path
        path = simulator.generate_mouse_movement(
            start=self.current_pos,
            end=(target_x, target_y)
        )

        # Execute movement
        await self.execute_movement(path)

        # Generate click parameters
        click = simulator.generate_click()

        # Execute click
        await self.execute_click(click)

    async def type_text(self, text: str, simulator: HumanSimulator):
        """
        Type text with human-like timing.

        Uses ML models for realistic inter-key delays.
        """
        events = simulator.generate_typing(text)
        await self.execute_typing(events)

    async def press_shortcut(self, shortcut: str, simulator: HumanSimulator):
        """
        Execute keyboard shortcut with human-like timing.

        shortcut: e.g., "ctrl+c", "ctrl+shift+v"
        """
        events = simulator.generate_shortcut(shortcut)
        await self.execute_typing(events)
```

---

### 3. Precision Timer

Critical for realistic timing. Standard `asyncio.sleep()` has ~1-15ms variance on Windows.

```python
class PrecisionTimer:
    """High-precision timing for input simulation."""

    @staticmethod
    async def sleep_precise(seconds: float):
        """
        More precise sleep using spin-wait for final milliseconds.

        For delays > 10ms: use asyncio.sleep for most, spin-wait final 2ms
        For delays < 10ms: pure spin-wait
        """
        if seconds <= 0:
            return

        target = time.perf_counter() + seconds

        if seconds > 0.010:  # > 10ms
            # Sleep for most of the duration
            await asyncio.sleep(seconds - 0.002)

        # Spin-wait for remaining time (high precision)
        while time.perf_counter() < target:
            pass

    @staticmethod
    def sleep_precise_sync(seconds: float):
        """Synchronous version for non-async contexts."""
        if seconds <= 0:
            return

        target = time.perf_counter() + seconds

        if seconds > 0.010:
            time.sleep(seconds - 0.002)

        while time.perf_counter() < target:
            pass
```

---

## Data Types

```python
from dataclasses import dataclass
from typing import List, Optional, Tuple

@dataclass
class PathPoint:
    """Single point in a mouse movement path."""
    x: int
    y: int
    timestamp_ms: int  # Milliseconds from movement start

@dataclass
class JitterPoint:
    """Micro-movement during hover."""
    dx: int  # Offset from base position
    dy: int
    timestamp_ms: int

@dataclass
class ClickParams:
    """Parameters for executing a click."""
    button: str = "left"  # left, right, middle
    pre_pause_ms: int = 0
    hold_duration_ms: int = 80
    post_pause_ms: int = 0
    recoil: Optional[Tuple[int, int]] = None  # (dx, dy)
    jitter_points: Optional[List[JitterPoint]] = None

@dataclass
class ScrollParams:
    """Parameters for scroll operation."""
    ticks: int = 1
    delta_per_tick: int = 120  # Standard wheel delta
    delay_between_ms: int = 50
    horizontal: bool = False

@dataclass
class KeyDown:
    """Key press event."""
    vkey: int

@dataclass
class KeyUp:
    """Key release event."""
    vkey: int

@dataclass
class Wait:
    """Delay event."""
    ms: int

# Union type for key events
KeyEvent = KeyDown | KeyUp | Wait
```

---

## Virtual Key Code Helpers

```python
class VKeys:
    """Windows Virtual Key codes."""

    # Letters
    A, B, C, D, E, F, G, H, I, J = 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A
    K, L, M, N, O, P, Q, R, S, T = 0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53, 0x54
    U, V, W, X, Y, Z = 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A

    # Numbers (main keyboard)
    N0, N1, N2, N3, N4 = 0x30, 0x31, 0x32, 0x33, 0x34
    N5, N6, N7, N8, N9 = 0x35, 0x36, 0x37, 0x38, 0x39

    # Numpad
    NUMPAD0, NUMPAD1, NUMPAD2, NUMPAD3, NUMPAD4 = 0x60, 0x61, 0x62, 0x63, 0x64
    NUMPAD5, NUMPAD6, NUMPAD7, NUMPAD8, NUMPAD9 = 0x65, 0x66, 0x67, 0x68, 0x69

    # Modifiers
    SHIFT = 0x10
    CTRL = 0x11
    ALT = 0x12
    LSHIFT, RSHIFT = 0xA0, 0xA1
    LCTRL, RCTRL = 0xA2, 0xA3
    LALT, RALT = 0xA4, 0xA5

    # Special
    ENTER = 0x0D
    TAB = 0x09
    SPACE = 0x20
    BACKSPACE = 0x08
    DELETE = 0x2E
    ESCAPE = 0x1B

    # Navigation
    LEFT, UP, RIGHT, DOWN = 0x25, 0x26, 0x27, 0x28
    HOME, END = 0x24, 0x23
    PAGEUP, PAGEDOWN = 0x21, 0x22

    # Punctuation
    PERIOD = 0xBE      # .
    COMMA = 0xBC       # ,
    SEMICOLON = 0xBA   # ;
    SLASH = 0xBF       # /
    BACKSLASH = 0xDC   # \
    MINUS = 0xBD       # -
    EQUALS = 0xBB      # =

    @staticmethod
    def from_char(char: str) -> int:
        """Convert character to virtual key code."""
        c = char.upper()
        if 'A' <= c <= 'Z':
            return ord(c)
        if '0' <= c <= '9':
            return ord(c)
        special = {
            ' ': VKeys.SPACE,
            '\n': VKeys.ENTER,
            '\t': VKeys.TAB,
            '.': VKeys.PERIOD,
            ',': VKeys.COMMA,
            ';': VKeys.SEMICOLON,
            '/': VKeys.SLASH,
            '-': VKeys.MINUS,
            '=': VKeys.EQUALS,
        }
        return special.get(char, 0)

    @staticmethod
    def needs_shift(char: str) -> bool:
        """Check if character requires Shift key."""
        return char.isupper() or char in '!@#$%^&*()_+{}|:"<>?'
```

---

## Integration with Robin Worker

```python
class BookieWorker:
    """Single bookie worker with human-like input simulation."""

    def __init__(self, worker_id: int, config: BookieConfig):
        self.worker_id = worker_id
        self.config = config

        # MouseMux client
        self.mmx = MouseMuxClient()

        # Replay engine
        self.replay = None  # Initialized after connect

        # ML models
        self.simulator = HumanSimulator('models/')

    async def start(self):
        """Initialize worker."""
        # Connect to MouseMux
        await self.mmx.connect()

        # Create replay engine
        self.replay = ReplayEngine(self.mmx)

        # Launch Chrome if needed
        await self._launch_chrome()

        # Claim Chrome window
        await self._claim_window()

    async def _launch_chrome(self):
        """Launch MouseMux Chrome instance."""
        chrome_path = (
            r"C:\Program Files (x86)\The MouseMux Company\MouseMux V2"
            r"\store\apps\native\2.2.49\native-chrome\chrome.exe"
        )
        subprocess.Popen([
            chrome_path,
            "--enable-features=MouseMuxIntegration",
            f"--user-data-dir=profiles/worker{self.worker_id}",
            self.config.url
        ])
        await asyncio.sleep(3)  # Wait for Chrome to start

    async def _claim_window(self):
        """Claim Chrome window by clicking on it."""
        window_pos = self.config.window_position
        await self.replay.move_and_click(
            window_pos.center_x,
            window_pos.center_y,
            self.simulator
        )

    # ─────────────────────────────────────────────────────────
    # BETTING OPERATIONS
    # ─────────────────────────────────────────────────────────

    async def click_bet_button(self, button_x: int, button_y: int):
        """Click on bet button with human-like movement."""
        await self.replay.move_and_click(
            button_x,
            button_y,
            self.simulator
        )

    async def enter_bet_amount(self, amount: str):
        """Type bet amount with human-like timing."""
        await self.replay.type_text(amount, self.simulator)

    async def submit_bet(self):
        """Press Enter to submit bet."""
        events = self.simulator.generate_shortcut("enter")
        await self.replay.execute_typing(events)

    async def place_bet(self, button_pos: Tuple[int, int], amount: str):
        """Complete bet placement workflow."""
        # 1. Click bet button
        await self.click_bet_button(*button_pos)

        # 2. Small pause (looking at input field)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # 3. Type amount
        await self.enter_bet_amount(amount)

        # 4. Small pause before submit
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # 5. Submit
        await self.submit_bet()

    async def stop(self):
        """Clean up worker."""
        await self.mmx.dispose()
```

---

## Parallel Execution (Multiple Workers)

```python
class RobinController:
    """Manages multiple bookie workers."""

    def __init__(self):
        self.workers: Dict[int, BookieWorker] = {}
        self.simulator = HumanSimulator('models/')  # Shared models

    async def start_workers(self, configs: List[BookieConfig]):
        """Start all workers in parallel."""
        tasks = []
        for i, config in enumerate(configs):
            worker = BookieWorker(i, config)
            worker.simulator = self.simulator  # Share models
            self.workers[i] = worker
            tasks.append(worker.start())

        await asyncio.gather(*tasks)

    async def parallel_action(self, action_func, *args):
        """Execute action on all workers in parallel."""
        tasks = [
            action_func(worker, *args)
            for worker in self.workers.values()
        ]
        await asyncio.gather(*tasks)

    async def place_bets_parallel(self, bets: Dict[int, BetInfo]):
        """Place bets on multiple bookies simultaneously."""
        tasks = []
        for worker_id, bet_info in bets.items():
            worker = self.workers[worker_id]
            tasks.append(
                worker.place_bet(bet_info.button_pos, bet_info.amount)
            )
        await asyncio.gather(*tasks)
```

---

## Error Handling

```python
class ReplayEngine:
    # ... existing methods ...

    async def execute_movement_safe(self, path_points: List[PathPoint]):
        """Execute movement with error handling and recovery."""
        try:
            await self.execute_movement(path_points)
        except websockets.ConnectionClosed:
            # Reconnect and retry
            await self.mmx.connect()
            await self.execute_movement(path_points)
        except Exception as e:
            logger.error(f"Movement failed: {e}")
            # Fallback: direct teleport to end position
            if path_points:
                end = path_points[-1]
                await self.mmx.move_to(end.x, end.y)

    async def keepalive_loop(self):
        """Handle MouseMux ping/pong keepalive."""
        while self.mmx.connected:
            try:
                msg = await asyncio.wait_for(
                    self.mmx.ws.recv(),
                    timeout=30
                )
                data = json.loads(msg)
                if data.get("type") == "server.ping.notify.M2A":
                    await self.mmx.ws.send(json.dumps({
                        "type": "client.pong.request.A2M"
                    }))
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                break
```

---

## Performance Considerations

### Timing Accuracy

| Method | Typical Accuracy | Use For |
|--------|------------------|---------|
| `asyncio.sleep()` | ±1-15ms | Delays > 50ms |
| `PrecisionTimer.sleep_precise()` | ±0.5ms | Critical timing |
| Spin-wait | ±0.01ms | Sub-millisecond |

### WebSocket Latency

- Localhost connection: < 1ms
- Batch commands when possible
- Don't await response for every move (fire-and-forget)

### Memory Usage

- Path points: ~24 bytes each
- Typical movement: 50-100 points = 1.2-2.4 KB
- 16 workers × 100 movements/min = ~4 MB/min (easily manageable)

---

## Polling Rate Considerations

### Important: Polling Rate, NOT FPS

Mice report coordinates at their **polling rate**, not "FPS". This is input device terminology:

| Polling Rate | Interval | Mouse Type |
|--------------|----------|------------|
| 125 Hz | ~8ms | Basic USB, office mouse |
| 250 Hz | ~4ms | Budget gaming |
| 500 Hz | ~2ms | Gaming mouse |
| 1000 Hz | ~1ms | Pro gaming |

### Website Detection

Websites CAN infer polling rate from timestamp gaps:
```javascript
// If gaps are consistently ~8ms → 125Hz mouse detected
// If gaps are consistently ~1ms → 1000Hz mouse detected
```

### Our Approach: Match Recorded Polling Rate

During recording phase, we measure the user's actual polling rate:
```python
def detect_polling_rate(recorded_movements):
    intervals = []
    for movement in recorded_movements:
        for i in range(1, len(movement.path_points)):
            delta = movement.path_points[i].timestamp_ms - movement.path_points[i-1].timestamp_ms
            intervals.append(delta)
    
    avg_interval = statistics.mean(intervals)
    interval_stddev = statistics.stdev(intervals)
    polling_rate = 1000 / avg_interval
    
    return {
        'polling_rate_hz': polling_rate,      # e.g., 125
        'avg_interval_ms': avg_interval,       # e.g., 8.0
        'interval_stddev_ms': interval_stddev  # e.g., 0.4
    }
```

### Replay Timing

When replaying, we use the recorded polling characteristics:
```python
class ReplayEngine:
    def __init__(self, polling_config):
        self.avg_interval = polling_config['avg_interval_ms']
        self.interval_stddev = polling_config['interval_stddev_ms']
    
    def get_next_interval(self):
        # Add realistic variation (NOT perfect intervals!)
        return random.gauss(self.avg_interval, self.interval_stddev)
```

### Critical: Timing Variation

Real mice are NOT perfectly consistent:
```
Bot (bad):    8.00ms, 8.00ms, 8.00ms, 8.00ms, 8.00ms
Human (good): 7.8ms, 8.3ms, 7.9ms, 8.1ms, 8.4ms, 7.7ms
```

The ML model captures YOUR actual timing variation from recordings.

---

## File Structure

```
robin/
├── input/
│   ├── mousemux_client.py     # Low-level MouseMux WebSocket
│   ├── replay_engine.py       # High-level execution
│   ├── precision_timer.py     # Timing utilities
│   ├── vkeys.py               # Virtual key codes
│   └── types.py               # Data classes
├── models/
│   └── ...                    # ML models (from previous doc)
├── workers/
│   ├── bookie_worker.py       # Single worker implementation
│   └── controller.py          # Multi-worker orchestration
└── simulator/
    └── human_simulator.py     # ML inference API
```

---

## MVP Checklist

### Phase 1: Basic Execution
- [ ] MouseMuxClient with connect/dispose
- [ ] Basic move_to, mouse_down/up, key_down/up
- [ ] Simple ReplayEngine.execute_movement()
- [ ] Test with hardcoded path

### Phase 2: Timing Precision
- [ ] PrecisionTimer implementation
- [ ] Path execution with accurate timing
- [ ] Click with hold duration

### Phase 3: Full Integration
- [ ] HumanSimulator integration
- [ ] Complete move_and_click()
- [ ] Typing with digraph timing
- [ ] Shortcut execution

### Phase 4: Production
- [ ] Error handling and recovery
- [ ] Keepalive handling
- [ ] Parallel worker support
- [ ] Performance optimization
