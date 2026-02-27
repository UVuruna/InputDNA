"""
Raw Input mouse reader — Windows Raw Input API with MSG.time calibration.

Uses Win32 Raw Input (WM_INPUT) for low-overhead, non-blocking mouse event
capture. Unlike WH_MOUSE_LL (which blocks the entire system input pipeline
until the hook returns), Raw Input posts WM_INPUT messages asynchronously —
the OS never waits for our code.

Timestamp strategy — MSG.time calibration:
    WM_INPUT messages are dispatched by a Python message pump thread that must
    hold the CPython GIL. When other Python threads hold the GIL (default switch
    interval = 5ms), multiple WM_INPUT messages queue up and are dispatched in a
    burst — all receiving nearly identical perf_counter_ns() timestamps despite
    arriving at the hardware level with correct 2ms spacing (500Hz mouse).

    To recover true event timing, we use the MSG.time field: a DWORD millisecond
    timestamp set by the Windows kernel at message POST time (before any
    user-mode GIL contention). On first WM_INPUT, a calibration anchor maps
    MSG.time into the perf_counter_ns domain. All subsequent event timestamps
    are computed as: anchor_pfc + (msg.time - anchor_tick) * 1_000_000.

    timeBeginPeriod(1) is called during the message pump lifetime to ensure
    MSG.time has 1ms resolution (sufficient for 500Hz = 2ms intervals).

Architecture:
    - Hidden message-only window (HWND_MESSAGE) created on a background thread.
    - Registered with RIDEV_INPUTSINK — receives events regardless of focus.
    - Message pump runs GetMessage / DispatchMessage in a loop.
    - Before each DispatchMessage, msg.time is stored for the wndproc callback.
    - Cursor position via GetCursorPos() — always in screen pixels.

Multiple instances can coexist — each creates a unique HWND class name and
receives an independent copy of every WM_INPUT from the OS.
"""

import ctypes
import ctypes.wintypes
import threading
import time
import logging

from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Windows API references ────────────────────────────────────────────────────

_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_winmm    = ctypes.windll.winmm

# ── Constants ─────────────────────────────────────────────────────────────────

_WM_INPUT               = 0x00FF
_WM_DESTROY             = 0x0002
_WM_QUIT                = 0x0012
_HWND_MESSAGE           = ctypes.wintypes.HWND(-3)
_RID_INPUT              = 0x10000003
_RIM_TYPEMOUSE          = 0
_RIDEV_INPUTSINK        = 0x00000100
_HID_USAGE_PAGE_GENERIC = 0x01
_HID_USAGE_GENERIC_MOUSE = 0x02

_MOUSE_MOVE_RELATIVE    = 0x0000
_MOUSE_MOVE_ABSOLUTE    = 0x0001

# usButtonFlags bitmask values
_RI_MOUSE_LEFT_BUTTON_DOWN   = 0x0001
_RI_MOUSE_LEFT_BUTTON_UP     = 0x0002
_RI_MOUSE_RIGHT_BUTTON_DOWN  = 0x0004
_RI_MOUSE_RIGHT_BUTTON_UP    = 0x0008
_RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
_RI_MOUSE_MIDDLE_BUTTON_UP   = 0x0020
_RI_MOUSE_WHEEL              = 0x0400
_RI_MOUSE_HWHEEL             = 0x0800

# ── ctypes structures ─────────────────────────────────────────────────────────

_WNDPROCTYPE = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class _WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize",        ctypes.wintypes.UINT),
        ("style",         ctypes.wintypes.UINT),
        ("lpfnWndProc",   _WNDPROCTYPE),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     ctypes.wintypes.HANDLE),
        ("hIcon",         ctypes.wintypes.HANDLE),
        ("hCursor",       ctypes.wintypes.HANDLE),
        ("hBrush",        ctypes.wintypes.HANDLE),
        ("lpszMenuName",  ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
        ("hIconSm",       ctypes.wintypes.HANDLE),
    ]


class _RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", ctypes.c_ushort),
        ("usUsage",     ctypes.c_ushort),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("hwndTarget",  ctypes.wintypes.HWND),
    ]


class _RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType",  ctypes.wintypes.DWORD),
        ("dwSize",  ctypes.wintypes.DWORD),
        ("hDevice", ctypes.wintypes.HANDLE),
        ("wParam",  ctypes.wintypes.WPARAM),
    ]


class _RAWMOUSE(ctypes.Structure):
    class _ButtonsUnion(ctypes.Union):
        class _ButtonsStruct(ctypes.Structure):
            _fields_ = [
                ("usButtonFlags", ctypes.c_ushort),
                ("usButtonData",  ctypes.c_ushort),
            ]
        _fields_ = [
            ("ulButtons", ctypes.c_ulong),
            ("_st",       _ButtonsStruct),
        ]
    _fields_ = [
        ("usFlags",            ctypes.c_ushort),
        ("_buttons",           _ButtonsUnion),
        ("ulRawButtons",       ctypes.c_ulong),
        ("lLastX",             ctypes.c_long),
        ("lLastY",             ctypes.c_long),
        ("ulExtraInformation", ctypes.c_ulong),
    ]


class _RAWINPUT(ctypes.Structure):
    class _DataUnion(ctypes.Union):
        _fields_ = [("mouse", _RAWMOUSE)]
    _fields_ = [
        ("header", _RAWINPUTHEADER),
        ("data",   _DataUnion),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    ctypes.wintypes.HWND),
        ("message", ctypes.wintypes.UINT),
        ("wParam",  ctypes.wintypes.WPARAM),
        ("lParam",  ctypes.wintypes.LPARAM),
        ("time",    ctypes.wintypes.DWORD),
        ("pt",      ctypes.wintypes.POINT),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# ── Public data ───────────────────────────────────────────────────────────────

@dataclass(slots=True)
class RawMouseEvent:
    """
    A single raw mouse event delivered by WM_INPUT.

    cursor_x / cursor_y — screen pixel position from GetCursorPos(). Always in
                          the coordinate space used by the rest of the system
                          (clicks, screen resolution, UI element positions).
    rel_x / rel_y       — relative movement from RAWMOUSE.lLastX/lLastY for
                          this specific hardware report (raw hardware counts).
    button_flags        — usButtonFlags bitmask (which buttons changed state).
    button_data         — usButtonData. For wheel events: signed scroll delta
                          in WHEEL_DELTA units (120 per notch); stored as raw
                          unsigned short — callers must sign-extend if needed.
    t_ns                — event timestamp in perf_counter_ns domain. Derived
                          from the kernel-level MSG.time (set when Windows posts
                          the WM_INPUT message) converted to nanoseconds via a
                          one-time calibration anchor. Gives correct inter-event
                          spacing (e.g. 2ms at 500Hz) regardless of GIL delays.
    """
    cursor_x:     int
    cursor_y:     int
    rel_x:        int
    rel_y:        int
    button_flags: int
    button_data:  int
    t_ns:         int


# Public button flag constants (re-exported for callers)
BUTTON_LEFT_DOWN   = _RI_MOUSE_LEFT_BUTTON_DOWN
BUTTON_LEFT_UP     = _RI_MOUSE_LEFT_BUTTON_UP
BUTTON_RIGHT_DOWN  = _RI_MOUSE_RIGHT_BUTTON_DOWN
BUTTON_RIGHT_UP    = _RI_MOUSE_RIGHT_BUTTON_UP
BUTTON_MIDDLE_DOWN = _RI_MOUSE_MIDDLE_BUTTON_DOWN
BUTTON_MIDDLE_UP   = _RI_MOUSE_MIDDLE_BUTTON_UP
BUTTON_WHEEL       = _RI_MOUSE_WHEEL
BUTTON_HWHEEL      = _RI_MOUSE_HWHEEL
WHEEL_DELTA        = 120   # Windows standard: one notch = 120 units

# ── Reader ────────────────────────────────────────────────────────────────────

_instance_counter = 0  # ensures unique WNDCLASS names per process lifetime


class RawInputMouseReader:
    """
    Listens for Raw Input mouse events on a hidden message-only window.

    Calls callback(event: RawMouseEvent) synchronously on the reader's
    dedicated message pump thread. Keep the callback fast — queue events,
    do not block.

    Multiple instances coexist within the same process. Each registers its
    own HWND and receives an independent copy of every WM_INPUT event.

    Usage:
        reader = RawInputMouseReader(callback=my_fn)
        reader.start()   # returns once window is created and registered
        ...
        reader.stop()    # posts WM_QUIT, joins thread
    """

    def __init__(self, callback: Callable[[RawMouseEvent], None]):
        global _instance_counter
        _instance_counter += 1
        self._callback    = callback
        self._hwnd: Optional[ctypes.wintypes.HWND] = None
        self._ready       = threading.Event()
        self._error: Optional[Exception] = None
        self._class_name  = f"InputDNA_RawMouse_{_instance_counter}"
        self._thread = threading.Thread(
            target=self._run,
            name=f"raw-input-{_instance_counter}",
            daemon=True,
        )
        # Timestamp calibration — MSG.time (kernel post time) → perf_counter_ns.
        # Established on first WM_INPUT; all subsequent timestamps use MSG.time
        # deltas from this anchor to eliminate GIL-induced burst clustering.
        self._msg_post_time: int = 0
        self._anchor_pfc:  int  = 0
        self._anchor_tick: int  = 0
        self._calibrated:  bool = False
        self._last_t_ns:   int  = 0

    def start(self):
        """Start the reader. Blocks until the window is registered and ready."""
        self._thread.start()
        self._ready.wait()
        if self._error:
            raise self._error

    def stop(self):
        """Signal stop and wait for the thread to exit."""
        if self._hwnd is not None:
            _user32.PostMessageW(self._hwnd, _WM_QUIT, 0, 0)
        self._thread.join(timeout=3.0)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == _WM_INPUT:
            t_ns = self._stamp()
            self._handle(lparam, t_ns)
            return 0
        if msg == _WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _stamp(self) -> int:
        """Convert MSG.time (kernel post time) to perf_counter_ns domain.

        MSG.time is set by the Windows kernel when the WM_INPUT message is
        posted to the queue — before any user-mode GIL contention. On first
        call, establishes a calibration anchor mapping MSG.time (ms) into the
        perf_counter_ns domain. Subsequent calls compute timestamps from
        MSG.time deltas, giving correct inter-event spacing even when the
        message pump dispatches a burst of queued messages.
        """
        pfc_ns = time.perf_counter_ns()
        tick = self._msg_post_time

        if not self._calibrated:
            self._anchor_pfc  = pfc_ns
            self._anchor_tick = tick
            self._calibrated  = True
            self._last_t_ns   = pfc_ns
            logger.debug(
                f"Timestamp calibration: anchor_tick={tick}ms, "
                f"anchor_pfc={pfc_ns}"
            )
            return pfc_ns

        # MSG.time delta → nanoseconds, mapped into perf_counter domain.
        # Unsigned 32-bit wrap (GetTickCount rolls over every ~49 days)
        # is handled by the & 0xFFFFFFFF mask.
        delta_ms = (tick - self._anchor_tick) & 0xFFFFFFFF
        t_ns = self._anchor_pfc + delta_ms * 1_000_000

        # Ensure strict monotonicity (handles same-tick events at ≥1000Hz
        # where MSG.time resolution may equal the polling interval).
        if t_ns <= self._last_t_ns:
            t_ns = self._last_t_ns + 1
        self._last_t_ns = t_ns
        return t_ns

    def _handle(self, lparam, t_ns: int):
        size = ctypes.wintypes.UINT(0)
        _user32.GetRawInputData(
            ctypes.c_void_p(lparam), _RID_INPUT,
            None, ctypes.byref(size),
            ctypes.sizeof(_RAWINPUTHEADER),
        )
        buf = (ctypes.c_byte * size.value)()
        if _user32.GetRawInputData(
            ctypes.c_void_p(lparam), _RID_INPUT,
            buf, ctypes.byref(size),
            ctypes.sizeof(_RAWINPUTHEADER),
        ) != size.value:
            return

        raw = ctypes.cast(buf, ctypes.POINTER(_RAWINPUT)).contents
        if raw.header.dwType != _RIM_TYPEMOUSE:
            return

        m = raw.data.mouse

        # cursor_x / cursor_y must be screen pixels — the coordinate space
        # used by every other part of the system (clicks, screen resolution,
        # UI element positions). GetCursorPos always returns screen pixels
        # after applying pointer speed and acceleration. lLastX/lLastY are
        # raw hardware counts; with mouse acceleration ON they do NOT equal
        # screen pixels and must NOT be used for position tracking.
        pt = _POINT()
        _user32.GetCursorPos(ctypes.byref(pt))

        self._callback(RawMouseEvent(
            cursor_x     = pt.x,
            cursor_y     = pt.y,
            rel_x        = m.lLastX,
            rel_y        = m.lLastY,
            button_flags = m._buttons._st.usButtonFlags,
            button_data  = m._buttons._st.usButtonData,
            t_ns         = t_ns,
        ))

    def _run(self):
        hinstance    = _kernel32.GetModuleHandleW(None)
        wnd_proc_cb  = _WNDPROCTYPE(self._wnd_proc)

        wc = _WNDCLASSEX()
        wc.cbSize        = ctypes.sizeof(_WNDCLASSEX)
        wc.lpfnWndProc   = wnd_proc_cb
        wc.hInstance     = hinstance
        wc.lpszClassName = self._class_name
        _user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = _user32.CreateWindowExW(
            0, self._class_name, "InputDNA_RawMouse",
            0, 0, 0, 0, 0,
            _HWND_MESSAGE, None, hinstance, None,
        )
        if not hwnd:
            err = _kernel32.GetLastError()
            self._error = RuntimeError(
                f"RawInputMouseReader: CreateWindowEx failed (error {err})"
            )
            self._ready.set()
            return

        self._hwnd = hwnd

        rid = _RAWINPUTDEVICE()
        rid.usUsagePage = _HID_USAGE_PAGE_GENERIC
        rid.usUsage     = _HID_USAGE_GENERIC_MOUSE
        rid.dwFlags     = _RIDEV_INPUTSINK
        rid.hwndTarget  = hwnd

        if not _user32.RegisterRawInputDevices(
            ctypes.byref(rid), 1, ctypes.sizeof(_RAWINPUTDEVICE)
        ):
            err = _kernel32.GetLastError()
            self._error = RuntimeError(
                f"RawInputMouseReader: RegisterRawInputDevices failed (error {err})"
            )
            _user32.DestroyWindow(hwnd)
            self._ready.set()
            return

        self._ready.set()
        logger.debug(f"RawInputMouseReader '{self._class_name}' started")

        _winmm.timeBeginPeriod(1)
        try:
            msg = _MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                self._msg_post_time = msg.time
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _winmm.timeEndPeriod(1)
            _user32.DestroyWindow(hwnd)
            _user32.UnregisterClassW(self._class_name, hinstance)
            self._hwnd = None
            logger.debug(f"RawInputMouseReader '{self._class_name}' stopped")
