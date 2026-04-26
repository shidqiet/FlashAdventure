"""Screenshot capture from ScummVM window."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image


def _find_scummvm_window_id() -> int | None:
    """Find the ScummVM window ID via Quartz CGWindowList.

    Returns the CGWindowID (int) or None if not found.
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
                return int(w.get(Quartz.kCGWindowNumber, 0))
    except ImportError:
        pass
    return None


class ScreenshotCapture:
    """Captures screenshots of the ScummVM window."""

    def __init__(self, screenshot_dir: str | Path | None = None) -> None:
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else None

    def capture(self) -> Image.Image:
        """Capture the ScummVM window and return as a PIL Image.

        Uses macOS `screencapture -l <window_id>` for window-specific capture.
        Falls back to full screen capture if window ID can't be found.
        """
        window_id = _find_scummvm_window_id()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        for attempt in range(3):
            try:
                if window_id:
                    # Capture specific window (no shadow, silent)
                    subprocess.run(
                        ["screencapture", "-l", str(window_id), "-x", "-o", tmp_path],
                        capture_output=True,
                        timeout=5,
                    )
                else:
                    # Fallback: capture entire screen
                    subprocess.run(
                        ["screencapture", "-x", tmp_path],
                        capture_output=True,
                        timeout=5,
                    )

                img = Image.open(tmp_path).copy()
                return img
            except Exception:
                if attempt < 2:
                    time.sleep(0.3)
                else:
                    raise
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        raise RuntimeError("Screenshot capture failed after retries")
