"""Action types and execution for KQ4 gameplay input."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyautogui

if TYPE_CHECKING:
    from kq4env.scummvm import ScummVMProcess

# Disable pyautogui's built-in pause and failsafe for automated use
pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False


# ── Action types ───────────────────────────────────────────────────────


@dataclass
class Click:
    """Click at game coordinates (0-319, 0-199)."""

    x: int
    y: int


@dataclass
class Type:
    """Type text followed by Return (for the SCI text parser)."""

    text: str


@dataclass
class KeyPress:
    """Press a single key (e.g. "return", "escape", "f5", "up")."""

    key: str


@dataclass
class Wait:
    """Wait without sending input."""

    duration_ms: int = 500


@dataclass
class Save:
    """Save game via debug console."""

    slot: int = 0
    description: str = "auto"


@dataclass
class Load:
    """Load game via debug console."""

    slot: int = 0


Action = Click | Type | KeyPress | Wait | Save | Load


# ── Window tracking ───────────────────────────────────────────────────


def _get_scummvm_window_position() -> tuple[int, int, int, int]:
    """Return (x, y, width, height) of the ScummVM window via Quartz.

    Falls back to (0, 0, 320, 200) if detection fails.
    """
    try:
        import Quartz

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID,
        )
        for w in windows:
            name = w.get(Quartz.kCGWindowOwnerName, "")
            if "ScummVM" in name or "scummvm" in name.lower():
                bounds = w.get(Quartz.kCGWindowBounds, {})
                return (
                    int(bounds.get("X", 0)),
                    int(bounds.get("Y", 0)),
                    int(bounds.get("Width", 320)),
                    int(bounds.get("Height", 200)),
                )
    except ImportError:
        pass
    return (0, 0, 320, 200)


def _game_to_screen(game_x: int, game_y: int) -> tuple[int, int]:
    """Convert game coordinates (320x200) to screen coordinates."""
    wx, wy, ww, wh = _get_scummvm_window_position()
    # Scale game coords to window size
    scale_x = ww / 320
    scale_y = wh / 200
    screen_x = int(wx + game_x * scale_x)
    screen_y = int(wy + game_y * scale_y)
    return screen_x, screen_y


def _focus_scummvm(pid: int | None = None) -> None:
    """Bring ScummVM window to front using System Events (works for bare binaries)."""
    import subprocess

    if pid is not None:
        script = (
            f'tell application "System Events" to set frontmost of '
            f'(first process whose unix id is {pid}) to true'
        )
    else:
        script = 'tell application "System Events" to set frontmost of (first process whose name is "scummvm") to true'

    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
    time.sleep(0.3)


# ── Action executor ────────────────────────────────────────────────────


class ActionExecutor:
    """Sends gameplay input to ScummVM via pyautogui.

    The caller (env.py) is responsible for managing the debugger state.
    The executor just sends OS-level input to the running game window.
    """

    def __init__(self, process: ScummVMProcess) -> None:
        self._process = process

    def execute(self, action: Action) -> None:
        """Execute an action by sending OS-level input via pyautogui.

        The game must be running (not paused in debugger) when this is
        called for Click/Type/KeyPress actions.
        """
        pid = self._process.pid
        match action:
            case Click(x, y):
                _focus_scummvm(pid)
                screen_x, screen_y = _game_to_screen(x, y)
                pyautogui.click(screen_x, screen_y)
            case Type(text):
                _focus_scummvm(pid)
                pyautogui.typewrite(text, interval=0.03)
                pyautogui.press("return")
            case KeyPress(key):
                _focus_scummvm(pid)
                pyautogui.press(key)
            case Wait(duration_ms):
                time.sleep(duration_ms / 1000.0)
            case Save() | Load():
                pass  # Handled directly by env.py via debug console
