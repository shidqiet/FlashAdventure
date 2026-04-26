"""Agent memory: scratchpad and harness-tracked state between turns."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentMemory:
    """Persistent state carried between agent turns.

    The scratchpad is VLM-written text fed back each turn — the agent's
    only memory since we use single-turn (not multi-turn) prompting.
    The other fields are harness-tracked.
    """

    scratchpad: str = ""
    rooms_visited: set[int] = field(default_factory=set)
    death_count: int = 0
    step_count: int = 0

    def update_from_room(self, room: int) -> None:
        """Track a newly observed room."""
        if room > 0:
            self.rooms_visited.add(room)
