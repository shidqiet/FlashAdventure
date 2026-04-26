"""Parse VLM output into Action objects.

Two modes:
- Structured: VLM returns JSON (via vLLM guided_json). Direct parse.
- Freeform: VLM returns THOUGHT/SCRATCHPAD/ACTION text. Regex extraction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from kq4env.actions import Action, Click, KeyPress, Save, Type, Wait


@dataclass
class ParsedResponse:
    """Parsed VLM response with thought, scratchpad update, and action."""

    thought: str
    scratchpad: str
    action: Action


# ── JSON schema for vLLM guided_json ──────────────────────────────────

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "scratchpad": {"type": "string"},
        "action": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["go", "click", "type", "key", "wait", "save"],
                },
                "direction": {
                    "type": "string",
                    "enum": ["north", "south", "east", "west"],
                },
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "text": {"type": "string"},
                "key": {"type": "string"},
            },
            "required": ["type"],
        },
    },
    "required": ["thought", "scratchpad", "action"],
}


# Navigation: map directions to screen-edge clicks
_DIRECTION_CLICKS = {
    "north": Click(160, 5),
    "south": Click(160, 195),
    "east": Click(315, 100),
    "west": Click(5, 100),
    "up": Click(160, 5),
    "down": Click(160, 195),
    "left": Click(5, 100),
    "right": Click(315, 100),
}


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


def _action_from_dict(d: dict) -> Action:
    """Convert an action dict to an Action object."""
    atype = d.get("type", "wait").lower()
    if atype == "go":
        direction = str(d.get("direction", "north")).lower()
        return _DIRECTION_CLICKS.get(direction, Click(160, 5))
    elif atype == "click":
        return Click(
            x=_clamp(int(d.get("x", 160)), 0, 319),
            y=_clamp(int(d.get("y", 100)), 0, 199),
        )
    elif atype == "type":
        return Type(text=str(d.get("text", "look")))
    elif atype == "key":
        return KeyPress(key=str(d.get("key", "return")))
    elif atype == "save":
        return Save()
    else:
        return Wait()


# ── Structured parsing (vLLM guided_json output) ─────────────────────


def parse_structured(text: str) -> ParsedResponse:
    """Parse JSON response from structured generation.

    Falls back to freeform parsing if the response is not valid JSON
    (e.g. endpoint ignores guided_json).
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_freeform(text)
    return ParsedResponse(
        thought=data.get("thought", ""),
        scratchpad=data.get("scratchpad", ""),
        action=_action_from_dict(data.get("action", {})),
    )


# ── Freeform parsing (regex fallback) ────────────────────────────────

_THOUGHT_RE = re.compile(
    r"THOUGHT:\s*(.+?)(?=\nSCRATCHPAD:|\nACTION:|\Z)", re.DOTALL | re.IGNORECASE
)
_SCRATCHPAD_RE = re.compile(
    r"SCRATCHPAD:\s*(.+?)(?=ACTION:|\Z)", re.DOTALL | re.IGNORECASE
)
_ACTION_RE = re.compile(r"ACTION:\s*(.+)", re.IGNORECASE)

_GO_RE = re.compile(r"GO\s+(north|south|east|west|up|down|left|right)", re.IGNORECASE)
_CLICK_RE = re.compile(r"CLICK\s+(\d+)\s+(\d+)", re.IGNORECASE)
_TYPE_RE = re.compile(r"TYPE\s+(.+)", re.IGNORECASE)
_KEY_RE = re.compile(r"KEY\s+(\S+)", re.IGNORECASE)
_SAVE_RE = re.compile(r"SAVE", re.IGNORECASE)


def _parse_action_text(text: str) -> Action:
    """Parse a single action line like 'CLICK 160 100' or 'TYPE look'."""
    text = text.strip()

    m = _GO_RE.search(text)
    if m:
        direction = m.group(1).lower()
        return _DIRECTION_CLICKS.get(direction, Click(160, 5))

    m = _CLICK_RE.search(text)
    if m:
        return Click(
            x=_clamp(int(m.group(1)), 0, 319), y=_clamp(int(m.group(2)), 0, 199)
        )

    m = _TYPE_RE.search(text)
    if m:
        return Type(text=m.group(1).strip())

    m = _KEY_RE.search(text)
    if m:
        return KeyPress(key=m.group(1).strip().lower())

    if _SAVE_RE.search(text):
        return Save()

    # Default fallback
    return Wait()


def parse_freeform(text: str) -> ParsedResponse:
    """Parse freeform THOUGHT/SCRATCHPAD/ACTION response."""
    thought_m = _THOUGHT_RE.search(text)
    scratchpad_m = _SCRATCHPAD_RE.search(text)
    action_m = _ACTION_RE.search(text)

    thought = thought_m.group(1).strip() if thought_m else ""
    scratchpad = scratchpad_m.group(1).strip() if scratchpad_m else ""

    if action_m:
        action = _parse_action_text(action_m.group(1))
    else:
        # Try to find an action anywhere in the text as last resort
        action = _parse_action_text(text.split("\n")[-1])

    return ParsedResponse(thought=thought, scratchpad=scratchpad, action=action)
