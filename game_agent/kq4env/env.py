"""Top-level KQ4 environment tying together all components."""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from kq4env.actions import (
    Action,
    ActionExecutor,
    Click,
    KeyPress,
    Load,
    Save,
    Type,
    Wait,
)
from kq4env.config import ROOM, SCRIPT_RUNNING
from kq4env.screenshots import ScreenshotCapture
from kq4env.scummvm import ScummVMProcess
from kq4env.state import GameState, StateExtractor


class KQ4Environment:
    """High-level interface for running KQ4 via ScummVM.

    Debug console re-entry strategy:
    ScummVM's text console debugger only reads stdin while active.
    We use 'se' (step_event) to resume — the game runs until the next
    SCI event (keyboard/mouse), then the debugger reactivates automatically.
    Every action that generates a SCI event (click, keypress, type)
    naturally gives us the debugger back.
    """

    def __init__(
        self,
        scummvm_path: str | Path = "./bin/scummvm-src/scummvm",
        game_path: str | Path = "./games/KQ4",
        game_id: str = "kq4sci",
        screenshot_dir: str | Path | None = None,
        save_dir: str | Path | None = None,
    ) -> None:
        self._process = ScummVMProcess(
            scummvm_path=scummvm_path,
            game_path=game_path,
            game_id=game_id,
            screenshot_dir=screenshot_dir,
            save_dir=save_dir,
        )
        self._state_extractor: StateExtractor | None = None
        self._action_executor: ActionExecutor | None = None
        self._screenshot_capture = ScreenshotCapture(screenshot_dir)

    def start(self, max_room: int = 200) -> GameState:
        """Launch the game and wait until it reaches a gameplay room.

        Strategy: step through room changes with 'sg 11'. The game runs
        normally between transitions, so the user can handle the copy
        protection interactively. We stop when we reach a room in the
        gameplay range (1 < room < max_room).

        KQ4 intro/special rooms are 700+. Gameplay rooms are 1-100ish.
        """
        self._process.start()
        self._state_extractor = StateExtractor(self._process)
        self._action_executor = ActionExecutor(self._process)

        print("[kq4env] Game started. Stepping through startup rooms...")
        print("[kq4env] Complete the copy protection if prompted.")

        seen_intro = False
        while True:
            # Resume until room number changes. Long timeout so the user
            # has time to answer the copy protection prompt.
            self._process.resume_until_global(11, timeout=120.0)
            if not self._process.in_debugger:
                raise TimeoutError("Lost debugger during startup")

            try:
                room = self._state_extractor.read_global(ROOM)
            except ValueError:
                room = 0

            if room >= max_room:
                seen_intro = True

            if 0 < room < max_room:
                print(f"[kq4env] Reached gameplay room {room}")
                break
            elif seen_intro and room == 0:
                # We've been through intro rooms and are back at 0.
                # The game is transitioning to gameplay. Use 'se' to
                # step events until a gameplay room appears.
                print("[kq4env] Post-intro transition, waiting for gameplay room...")
                for _ in range(20):
                    self._process.resume_until_event(timeout=5.0)
                    if not self._process.in_debugger:
                        break
                    try:
                        room = self._state_extractor.read_global(ROOM)
                    except ValueError:
                        room = 0
                    if 0 < room < max_room:
                        print(f"[kq4env] Reached gameplay room {room}")
                        break
                if 0 < room < max_room:
                    break
                print(f"[kq4env] Still in room {room}, continuing with sg 11...")
            else:
                print(f"[kq4env] Room {room} (startup/intro), continuing...")

        # Let the room fully initialize by pumping game cycles via 'snk'.
        # Each 'snk' advances one kernel call; a full frame has many.
        print("[kq4env] Waiting for room to initialize...")
        self._pump_frames(200)

        state = self._state_extractor.poll_state()
        print(
            f"[kq4env] Ready: room={state.room}, score={state.score}, "
            f"ego=({state.ego_x}, {state.ego_y})"
        )
        return state

    def start_from_save(self, slot: int = 0) -> GameState:
        """Launch the game and immediately load a save file.

        Useful when you have a save past the copy protection/intro.
        """
        self._process.start()
        self._state_extractor = StateExtractor(self._process)
        self._action_executor = ActionExecutor(self._process)

        # Wait for engine init first
        self._process.resume_until_global(11, timeout=30.0)
        if not self._process.in_debugger:
            raise TimeoutError("Engine did not initialize")

        # Now restore the save and wait for the room change
        self._process.send_command(f"restore_game {slot}")
        self._process.resume_until_global(11, timeout=15.0)
        if not self._process.in_debugger:
            raise TimeoutError("Debugger did not reactivate after restore")

        return self._state_extractor.poll_state()

    def step(self, action: Action) -> tuple[GameState, Image.Image]:
        """Execute an action and return (new_state, screenshot).

        Flow:
        1. Capture screenshot (game is paused in debugger — current frame)
        2. Resume with 'se' (step_event) — game runs
        3. Send OS-level input via pyautogui (generates SCI event)
        4. Debugger reactivates automatically on that event
        5. Read new state
        """
        if self._action_executor is None or self._state_extractor is None:
            raise RuntimeError("Environment not started")

        if not self._process.in_debugger:
            raise RuntimeError("Not in debugger at start of step()")

        # Capture screenshot while game is paused (current frame)
        screenshot = self._screenshot_capture.capture()

        match action:
            case Save(slot, description):
                self._process.send_command(f'save_game {slot} "{description}"')
                state = self._state_extractor.poll_state()
                return state, screenshot

            case Load(slot):
                self._process.send_command(f"restore_game {slot}")
                self._process.resume_until_event(timeout=10.0)
                if not self._process.in_debugger:
                    raise TimeoutError("Debugger did not reactivate after load")
                state = self._state_extractor.poll_state()
                return state, screenshot

            case Wait(duration_ms):
                # For Wait, we use 'se' multiple times to advance frames
                remaining = duration_ms / 1000.0
                while remaining > 0:
                    self._process.resume_until_event(timeout=max(remaining, 2.0))
                    if not self._process.in_debugger:
                        break
                    remaining -= 0.5  # approximate
                state = self._state_extractor.poll_state()
                return state, screenshot

            case Click() | Type() | KeyPress():
                # Resume game, send input, debugger reactivates on SCI event
                self._process.resume_until_event_async()
                self._action_executor.execute(action)
                if not self._process.wait_for_debugger(timeout=10.0):
                    raise TimeoutError(
                        f"Debugger did not reactivate after {type(action).__name__}"
                    )
                # The debugger broke on the input event. Pump more
                # kernel calls so the game processes the action and renders.
                self._pump_frames(100)
                # Capture the post-action screenshot
                screenshot = self._screenshot_capture.capture()
                state = self._state_extractor.poll_state()
                return state, screenshot

    def get_state(self) -> GameState:
        """Read current game state. Must be in debugger."""
        if self._state_extractor is None:
            raise RuntimeError("Environment not started")
        if not self._process.in_debugger:
            raise RuntimeError("Not in debugger — cannot read state")
        return self._state_extractor.poll_state()

    def get_screenshot(self) -> Image.Image:
        """Capture a screenshot of the current game frame."""
        return self._screenshot_capture.capture()

    def save(self, slot: int = 0, description: str = "auto") -> None:
        """Save game state to a slot via debug console."""
        if not self._process.in_debugger:
            raise RuntimeError("Must be in debugger to save")
        self._process.send_command(f'save_game {slot} "{description}"')

    def load(self, slot: int = 0) -> None:
        """Load game state from a slot via debug console."""
        if not self._process.in_debugger:
            raise RuntimeError("Must be in debugger to load")
        self._process.send_command(f"restore_game {slot}")
        self._process.resume_until_event(timeout=10.0)

    def wait_for_ready(self, timeout: float = 10.0) -> None:
        """Wait until the game is not in a cutscene (global 189 == 0).

        Uses 'se' to advance through cutscene frames.
        """
        if self._state_extractor is None:
            raise RuntimeError("Environment not started")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._process.in_debugger:
                raise RuntimeError("Lost debugger during wait_for_ready")
            val = self._state_extractor.read_global(SCRIPT_RUNNING)
            if val == 0:
                return
            remaining = deadline - time.monotonic()
            self._process.resume_until_event(timeout=min(2.0, remaining))

        raise TimeoutError("Game still in cutscene after timeout")

    def _pump_frames(self, count: int = 50) -> None:
        """Advance the game by stepping through kernel calls with 'snk'.

        Unlike 'se' (which requires real input events), 'snk' breaks on
        the next SCI kernel call (kGetEvent, kDrawPic, etc.) so it
        advances the game without needing external input. We run many
        iterations since each 'snk' only advances one kernel call, and
        a full game frame involves many kernel calls.
        """
        for _ in range(count):
            if not self._process.in_debugger:
                break
            self._process.resume_until_callk(timeout=2.0)

    def close(self) -> None:
        """Shut down the ScummVM process."""
        self._process.stop()
