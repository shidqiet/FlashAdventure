"""Per-step JSONL + screenshot logging for VLM agent runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from kq4env.agent.parser import ParsedResponse
    from kq4env.state import GameState


class RunLogger:
    """Log each agent step to JSONL and save screenshots.

    Directory layout:
        <log_dir>/
            steps.jsonl          — one JSON object per step
            screenshots/         — step_NNNN.png
            summary.json         — final stats (written at end)
    """

    def __init__(self, log_dir: str | Path) -> None:
        self.log_dir = Path(log_dir)
        self.screenshot_dir = self.log_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self.log_dir / "steps.jsonl"
        self._start_time = time.monotonic()

    def log_step(
        self,
        step: int,
        state: GameState,
        screenshot: Image.Image,
        parsed: ParsedResponse,
        vlm_duration: float,
    ) -> None:
        """Save screenshot and append step data to JSONL."""
        # Save screenshot
        png_path = self.screenshot_dir / f"step_{step:04d}.png"
        screenshot.save(png_path)

        # Build step record
        record = {
            "step": step,
            "room": state.room,
            "score": state.score,
            "ego_x": state.ego_x,
            "ego_y": state.ego_y,
            "is_dead": state.is_dead,
            "inventory": state.inventory,
            "thought": parsed.thought,
            "scratchpad": parsed.scratchpad,
            "action": _action_to_dict(parsed.action),
            "vlm_duration_s": round(vlm_duration, 2),
            "screenshot": str(png_path.name),
        }

        with open(self._jsonl_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def write_summary(
        self,
        total_steps: int,
        final_score: int,
        rooms_visited: set[int],
        death_count: int,
    ) -> None:
        """Write final run summary to summary.json."""
        elapsed = time.monotonic() - self._start_time
        summary = {
            "total_steps": total_steps,
            "final_score": final_score,
            "max_score": 230,
            "rooms_visited": sorted(rooms_visited),
            "num_rooms_visited": len(rooms_visited),
            "death_count": death_count,
            "elapsed_seconds": round(elapsed, 1),
        }
        summary_path = self.log_dir / "summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)


def _action_to_dict(action) -> dict:
    """Convert an Action dataclass to a JSON-serializable dict."""
    from kq4env.actions import Click, KeyPress, Save, Type, Wait

    match action:
        case Click(x, y):
            return {"type": "click", "x": x, "y": y}
        case Type(text):
            return {"type": "type", "text": text}
        case KeyPress(key):
            return {"type": "key", "key": key}
        case Wait(duration_ms):
            return {"type": "wait", "duration_ms": duration_ms}
        case Save(slot, description):
            return {"type": "save", "slot": slot, "description": description}
        case _:
            return {"type": "unknown"}
