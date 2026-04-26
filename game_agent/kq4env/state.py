"""Game state extraction from ScummVM debug console."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kq4env import config

if TYPE_CHECKING:
    from kq4env.scummvm import ScummVMProcess

# Regex for parsing `vv g N` output: "global var 15 == 0000:002a"
# SCI format is segment:offset in hex — the offset is the integer value.
_GLOBAL_RE = re.compile(r"global var\s+(\d+)\s*==\s*([0-9a-fA-F]+):([0-9a-fA-F]+)")
# Regex for parsing `send ?obj prop` output: "Message completed. Value returned: 0000:00a0"
_PROP_RE = re.compile(r"([0-9a-fA-F]{4}):([0-9a-fA-F]{4})")


@dataclass
class GameState:
    """Snapshot of KQ4 game state at a single tick."""

    score: int = 0
    room: int = 0
    prev_room: int = 0
    ego_x: int = 0
    ego_y: int = 0
    quest_stage: int = 0
    is_night: bool = False
    is_dead: bool = False
    is_cutscene: bool = False
    is_chase: bool = False
    troll_chasing: bool = False
    henchman_chasing: bool = False
    inventory: list[str] = field(default_factory=list)
    game_hour: int = 0
    game_minutes: int = 0
    raw_globals: dict[int, int] = field(default_factory=dict)


class StateExtractor:
    """Reads game state from the ScummVM debug console."""

    def __init__(self, process: ScummVMProcess) -> None:
        self._process = process
        self._ego_ref: tuple[int, int] | None = (
            None  # Cached ego object ref (seg, offset)
        )

    def read_global(self, var_num: int) -> int:
        """Read a single global variable. Returns its integer value.

        The SCI debug console outputs globals as "global var N == SSSS:OOOO"
        where SSSS:OOOO is a hex segment:offset. For integer values, the
        segment is 0 and the offset is the value.
        """
        response = self._process.send_command(f"vv g {var_num}")
        m = _GLOBAL_RE.search(response)
        if m:
            # offset part is the integer value
            return int(m.group(3), 16)
        raise ValueError(f"Failed to parse global {var_num} from: {response!r}")

    def read_globals(self, var_nums: list[int]) -> dict[int, int]:
        """Read multiple globals, one at a time. Returns {var_num: value}."""
        result = {}
        for n in var_nums:
            result[n] = self.read_global(n)
        return result

    def read_ego_position(self) -> tuple[int, int]:
        """Read ego's x, y position via object property queries."""
        x_resp = self._process.send_command("send ?ego x")
        y_resp = self._process.send_command("send ?ego y")

        x_match = _PROP_RE.search(x_resp)
        y_match = _PROP_RE.search(y_resp)

        x = int(x_match.group(2), 16) if x_match else 0
        y = int(y_match.group(2), 16) if y_match else 0
        return x, y

    def _get_ego_ref(self) -> tuple[int, int]:
        """Get the ego object reference from global 0 (cached after first call).

        Returns (segment, offset) tuple for comparison with object properties.
        """
        if self._ego_ref is None:
            response = self._process.send_command("vv g 0")
            m = _GLOBAL_RE.search(response)
            if m:
                self._ego_ref = (int(m.group(2), 16), int(m.group(3), 16))
            else:
                raise ValueError(f"Failed to parse ego ref from global 0: {response!r}")
        return self._ego_ref

    def read_inventory(self) -> list[str]:
        """Check which inventory items are owned by ego.

        Queries `send ?ItemName owner` for each known item and checks if
        the owner matches the ego object reference.
        """
        ego_ref = self._get_ego_ref()
        carried = []

        for item_name in config.INVENTORY_ITEMS:
            response = self._process.send_command(f"send ?{item_name} owner")
            m = _PROP_RE.search(response)
            if m:
                owner_ref = (int(m.group(1), 16), int(m.group(2), 16))
                if owner_ref == ego_ref:
                    carried.append(item_name)

        return carried

    def poll_state(self) -> GameState:
        """Read all tracked globals, ego position, and inventory. Returns a GameState."""
        if not self._process.in_debugger:
            raise RuntimeError("Must be in debugger to poll state")

        raw = self.read_globals(config.POLL_GLOBALS)
        ego_x, ego_y = self.read_ego_position()
        inventory = self.read_inventory()

        return GameState(
            score=raw.get(config.SCORE, 0),
            room=raw.get(config.ROOM, 0),
            prev_room=raw.get(config.PREV_ROOM, 0),
            ego_x=ego_x,
            ego_y=ego_y,
            quest_stage=raw.get(config.ACT, 0),
            is_night=bool(raw.get(config.NIGHT, 0)),
            is_dead=bool(raw.get(config.DEATH, 0)),
            is_cutscene=bool(raw.get(config.SCRIPT_RUNNING, 0)),
            is_chase=bool(
                raw.get(config.TROLL_CHASING, 0) or raw.get(config.HENCHMAN_CHASING, 0)
            ),
            troll_chasing=bool(raw.get(config.TROLL_CHASING, 0)),
            henchman_chasing=bool(raw.get(config.HENCHMAN_CHASING, 0)),
            inventory=inventory,
            game_hour=raw.get(config.GAME_HOUR, 0),
            game_minutes=raw.get(config.GAME_MINUTES, 0),
            raw_globals=raw,
        )
