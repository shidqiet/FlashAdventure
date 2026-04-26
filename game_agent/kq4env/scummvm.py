"""ScummVM subprocess management and debug console communication."""

from __future__ import annotations

import os
import re
import select
import subprocess
import time
from pathlib import Path

# Regex matching the ScummVM debug console prompt (e.g. "debug>" or "sci>")
_PROMPT_RE = re.compile(r"^[A-Za-z]\w*>[ ]?", re.MULTILINE)


class ScummVMProcess:
    """Manages a ScummVM subprocess with stdin/stdout debug console access.

    Requires a ScummVM binary built with --enable-text-console so the debugger
    uses stdin/stdout instead of the GUI overlay.
    """

    def __init__(
        self,
        scummvm_path: str | Path,
        game_path: str | Path,
        game_id: str = "kq4sci",
        screenshot_dir: str | Path | None = None,
        save_dir: str | Path | None = None,
    ) -> None:
        self.scummvm_path = Path(scummvm_path).resolve()
        self.game_path = Path(game_path).resolve()
        self.game_id = game_id
        self.screenshot_dir = (
            Path(screenshot_dir) if screenshot_dir else Path("/tmp/kq4_screenshots")
        )
        self.save_dir = Path(save_dir) if save_dir else Path("/tmp/kq4_saves")
        self._proc: subprocess.Popen[bytes] | None = None
        self._in_debugger = False

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    @property
    def in_debugger(self) -> bool:
        return self._in_debugger

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch ScummVM with debug-on-startup and stdin/stdout pipes."""
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.save_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(self.scummvm_path),
            "--auto-detect",
            "--debugflags=OnStartup",
            f"--screenshotpath={self.screenshot_dir}",
            f"--savepath={self.save_dir}",
            "-p",
            str(self.game_path),
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,  # unbuffered
        )

        # Make stdout non-blocking so we can use select
        fd = self._proc.stdout.fileno()
        os.set_blocking(fd, False)

        # Wait for the initial debugger prompt
        self._read_until_prompt(timeout=10.0)
        self._in_debugger = True

    def stop(self) -> None:
        """Kill the ScummVM subprocess."""
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait()
            self._proc = None
        self._in_debugger = False

    # ── Debug console protocol ─────────────────────────────────────────

    def resume_until_event(self, timeout: float = 10.0) -> str:
        """Resume the game with 'se' (step_event) and wait for re-entry.

        The game runs until the next SCI event (key/mouse), then the
        debugger automatically reactivates and we get a prompt back.
        Returns any debugger output printed on re-entry.
        """
        if not self._in_debugger:
            raise RuntimeError("Not in debugger")
        self._write(b"se\n")
        self._in_debugger = False
        # Wait for the debugger to reactivate on the next SCI event
        response = self._read_until_prompt(timeout=timeout)
        if _PROMPT_RE.search(response):
            self._in_debugger = True
        return response

    def resume_until_event_async(self) -> None:
        """Send 'se' to resume the game, but don't wait for re-entry.

        The caller is responsible for generating a SCI event (via pyautogui)
        and then calling wait_for_debugger() to catch the re-entry.
        """
        if not self._in_debugger:
            raise RuntimeError("Not in debugger")
        self._write(b"se\n")
        self._in_debugger = False

    def resume_until_global(self, global_num: int, timeout: float = 30.0) -> str:
        """Resume with 'sg N' (step_global) and wait for re-entry.

        The game runs until global variable N is modified, then the
        debugger reactivates. Useful for waiting until the engine sets
        a specific variable (e.g. room number during init).
        """
        if not self._in_debugger:
            raise RuntimeError("Not in debugger")
        self._write(f"sg {global_num}\n".encode())
        self._in_debugger = False
        response = self._read_until_prompt(timeout=timeout)
        if _PROMPT_RE.search(response):
            self._in_debugger = True
        return response

    def resume_until_callk(self, timeout: float = 5.0) -> str:
        """Resume with 'snk' (step_callk) and wait for re-entry.

        The game runs until the next SCI kernel call, then the debugger
        reactivates. This advances the game by one kernel operation —
        much more granular than 'se' but doesn't require external input.
        Useful for pumping game frames (kGetEvent, kDrawPic, etc. all
        trigger re-entry).
        """
        if not self._in_debugger:
            raise RuntimeError("Not in debugger")
        self._write(b"snk\n")
        self._in_debugger = False
        response = self._read_until_prompt(timeout=timeout)
        if _PROMPT_RE.search(response):
            self._in_debugger = True
        return response

    def resume(self) -> None:
        """Resume the game with 'go' (no automatic re-entry).

        Use this only when you don't need to get back into the debugger
        automatically (e.g. during startup while the user handles the
        intro manually).
        """
        if not self._in_debugger:
            return
        self._write(b"go\n")
        time.sleep(0.1)
        self._in_debugger = False

    def wait_for_debugger(self, timeout: float = 30.0) -> bool:
        """Wait for the debugger prompt to appear on stdout.

        Useful after resume() when an external event (breakpoint, manual
        trigger) will eventually reactivate the debugger.
        Returns True if prompt was detected, False on timeout.
        """
        response = self._read_until_prompt(timeout=timeout)
        if _PROMPT_RE.search(response):
            self._in_debugger = True
            return True
        return False

    def send_command(self, cmd: str, timeout: float = 2.0) -> str:
        """Send a debug command and return the response text (excluding prompt).

        Must be called while in the debugger.
        """
        if not self._in_debugger:
            raise RuntimeError("Not in debugger — call enter_debugger() first")

        self._write(f"{cmd}\n".encode())
        response = self._read_until_prompt(timeout=timeout)

        # Strip the echoed command from the start and the prompt from the end
        lines = response.splitlines()
        if lines and cmd in lines[0]:
            lines = lines[1:]
        # Remove trailing prompt line (e.g. "debug>")
        if lines and _PROMPT_RE.match(lines[-1]):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    # ── Low-level I/O ──────────────────────────────────────────────────

    def _write(self, data: bytes) -> None:
        """Write raw bytes to ScummVM's stdin."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("ScummVM process not running")
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def _read_until_prompt(self, timeout: float = 2.0) -> str:
        """Read stdout until a debug prompt is detected or timeout expires.

        Returns all text read (including the prompt line).
        """
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("ScummVM process not running")

        fd = self._proc.stdout.fileno()
        buf = b""
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            ready, _, _ = select.select([fd], [], [], min(remaining, 0.1))
            if ready:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                buf += chunk

                # Check if we've received a prompt
                text = buf.decode("utf-8", errors="replace")
                if _PROMPT_RE.search(text):
                    return text

        return buf.decode("utf-8", errors="replace")
