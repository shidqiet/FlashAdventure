"""System prompt and per-turn observation formatting for the KQ4 VLM agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kq4env.agent.memory import AgentMemory
    from kq4env.state import GameState

# ── System prompts ────────────────────────────────────────────────────

_SYSTEM_COMMON = """\
You are playing King's Quest IV: The Perils of Rosella, a 1988 Sierra adventure game.
The game uses a text parser and point-and-click interface at 320x200 resolution.

Your goal: maximize your score (max 230) by exploring, collecting items, and solving puzzles.

Available actions:
- GO direction — walk to an adjacent room (north, south, east, west)
- CLICK x y — click at game coordinates (0-319 horizontal, 0-199 vertical)
- TYPE text — type a command into the text parser (e.g. TYPE look, TYPE get ball, TYPE swim)
- KEY keyname — press a key (e.g. KEY escape, KEY return, KEY f5)
- WAIT — do nothing for one turn (useful during cutscenes or when waiting)
- SAVE — save the game (do this before dangerous areas)

Tips:
- Use GO to move between rooms: GO north, GO east, etc.
- Use TYPE for interactions: look, get, open, talk, use, climb, swim, etc.
- Use CLICK to move Rosella within a room or click on specific objects.
- Save before entering caves, crossing bridges, or dangerous areas.
- If you die, the harness will auto-restore. Note what killed you.
- Explore new rooms systematically. Remember which rooms you've visited.
- The SCRATCHPAD is your only memory between turns. Write down your plan and observations."""

SYSTEM_STRUCTURED = (
    _SYSTEM_COMMON
    + """

Respond with a JSON object containing exactly these fields:
{
  "thought": "your reasoning about what you see and what to do next",
  "scratchpad": "notes to carry to the next turn — your plan, observations, what you've tried",
  "action": {
    "type": "go" | "click" | "type" | "key" | "wait" | "save",
    "direction": "north", // only for go (north/south/east/west)
    "x": 160,       // only for click
    "y": 100,       // only for click
    "text": "look", // only for type
    "key": "escape"  // only for key
  }
}"""
)

SYSTEM_FREEFORM = (
    _SYSTEM_COMMON
    + """

Respond in this exact format:
THOUGHT: your reasoning about what you see and what to do next
SCRATCHPAD: notes to carry to the next turn — your plan, observations, what you've tried
ACTION: GO north  (or CLICK 160 100, TYPE look, KEY escape, WAIT, SAVE)"""
)


# ── Quest stage labels ────────────────────────────────────────────────

_QUEST_LABELS = {
    0: "Captured by Lolotte — do her bidding",
    1: "Fetch the unicorn for Lolotte",
    2: "Fetch the magic hen for Lolotte",
    3: "Fetch Pandora's Box for Lolotte",
    99: "Endgame — defeat Lolotte",
}


# ── Observation formatting ────────────────────────────────────────────


def format_observation(state: GameState, memory: AgentMemory) -> str:
    """Build the per-turn observation text from game state and agent memory."""
    parts: list[str] = []

    # Location and score
    parts.append(
        f"Room: {state.room}  Score: {state.score}/230  Position: ({state.ego_x}, {state.ego_y})"
    )

    # Quest stage
    quest_label = _QUEST_LABELS.get(state.quest_stage, f"Stage {state.quest_stage}")
    parts.append(f"Quest: {quest_label}")

    # Time of day
    time_str = "Night" if state.is_night else "Day"
    if state.game_hour or state.game_minutes:
        time_str += f" ({state.game_hour}:{state.game_minutes:02d})"
    parts.append(f"Time: {time_str}")

    # Status warnings
    if state.is_dead:
        parts.append("STATUS: YOU ARE DEAD — harness will auto-restore")
    if state.is_cutscene:
        parts.append("STATUS: Cutscene playing — WAIT until it finishes")
    if state.is_chase:
        chasers = []
        if state.troll_chasing:
            chasers.append("troll")
        if state.henchman_chasing:
            chasers.append("henchman")
        parts.append(f"WARNING: Being chased by {', '.join(chasers)}! Move quickly!")

    # Inventory
    if state.inventory:
        items = [name.replace("_", " ") for name in state.inventory]
        parts.append(f"Inventory: {', '.join(items)}")
    else:
        parts.append("Inventory: empty")

    # Agent memory
    if memory.rooms_visited:
        parts.append(f"Rooms visited: {sorted(memory.rooms_visited)}")
    if memory.scratchpad:
        parts.append(f"\nYour scratchpad from last turn:\n{memory.scratchpad}")
    if memory.death_count > 0:
        parts.append(f"Deaths so far: {memory.death_count}")

    parts.append(f"\nStep {memory.step_count}. What do you do?")

    return "\n".join(parts)
