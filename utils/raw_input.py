"""
Raw Input mouse reader — Windows Raw Input API + QueryPerformanceCounter.

Uses Win32 Raw Input (WM_INPUT) instead of WH_MOUSE_LL for accurate event
timing. WH_MOUSE_LL delivers events via cross-process synchronous SendMessage
with variable scheduling jitter; Raw Input posts WM_INPUT directly to a
dedicated message pump thread, allowing QPC capture with sub-millisecond
accuracy unaffected by cross-process hook delivery overhead.

Architecture:
    - Hidden message-only window (HWND_MESSAGE) created on a background thread.
    - Registered with RIDEV_INPUTSINK — receives events regardless of focus.
    - Message pump runs GetMessage / DispatchMessage in a loop.
    - On WM_INPUT arrival: time.perf_counter_ns() is captured as the FIRST
      operation, before any other work. This gives the earliest possible
      timestamp with ~100ns resolution (QueryPerformanceCounter under the hood).
    - Absolute cursor position is fetched via GetCursorPos() immediately after
      the QPC capture. RAWMOUSE.lLastX/lLastY are relative and used only to
      detect motion, not as coordinates.

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

    cursor_x / cursor_y — absolute screen position from GetCursorPos() captured
                          immediately after the QPC timestamp.
    rel_x / rel_y       — relative movement from RAWMOUSE.lLastX/lLastY. Use
                          only to detect motion (non-zero = cursor moved).
    button_flags        — usButtonFlags bitmask (which buttons changed state).
    button_data         — usButtonData. For wheel events: signed scroll delta
                          in WHEEL_DELTA units (120 per notch); stored as raw
                          unsigned short — callers must sign-extend if needed.
    t_ns                — time.perf_counter_ns() captured as the very first
                          operation in the WM_INPUT handler.
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
            t_ns = time.perf_counter_ns()   # QPC — captured first, before anything else
            self._handle(lparam, t_ns)
            return 0
        if msg == _WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

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

        msg = _MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        _user32.DestroyWindow(hwnd)
        _user32.UnregisterClassW(self._class_name, hinstance)
        self._hwnd = None
        logger.debug(f"RawInputMouseReader '{self._class_name}' stopped")
