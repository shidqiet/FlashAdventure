"""ScummVM GUI adapter for COAST.

Two public functions used by the COAST pipeline:
  capture_scummvm_screenshot_b64()  — called by Agent.capture_and_encode_image()
  execute_scummvm_action()           — called by execute.py
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import time

import pyautogui
from openai import OpenAI
from PIL import Image

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

MODEL_IMG_WIDTH = 720

# ── Window ─────────────────────────────────────────────────────────────


def _scummvm_window() -> tuple[int | None, dict | None]:
    try:
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
        )
        for w in windows:
            if "scummvm" in (w.get(Quartz.kCGWindowOwnerName, "") or "").lower():
                return w.get(Quartz.kCGWindowNumber), w.get(Quartz.kCGWindowBounds)
    except Exception as e:
        print(f"  [scummvm] Quartz error: {e}")
    return None, None


# ── Screenshot ───────────────────────────────────────────────────────────


def capture_scummvm_screenshot_b64() -> tuple[str, int, int]:
    wid, _ = _scummvm_window()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    if wid:
        subprocess.run(["screencapture", "-l", str(wid), "-x", path], check=True)
    else:
        print("  [scummvm] ScummVM window not found — capturing full screen")
        subprocess.run(["screencapture", "-x", path], check=True)
    img = Image.open(path)
    new_h = int(img.height * MODEL_IMG_WIDTH / img.width)
    img = img.resize((MODEL_IMG_WIDTH, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return b64, MODEL_IMG_WIDTH, new_h


# ── Execute ─────────────────────────────────────────────────────────────


def _focus_scummvm() -> None:
    subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to set frontmost of '
         '(first process whose name contains "scummvm") to true'],
        capture_output=True,
    )


def _execute(action: dict, img_w: int, img_h: int) -> None:
    _focus_scummvm()
    t = action.get("type")

    if t == "click":
        _, bounds = _scummvm_window()
        x, y = action.get("x", 0), action.get("y", 0)
        if bounds:
            sx = int(bounds["X"] + x * bounds["Width"] / img_w)
            sy = int(bounds["Y"] + y * bounds["Height"] / img_h)
        else:
            sx, sy = x, y
        print(f"  [scummvm] click screen=({sx},{sy})")
        pyautogui.click(sx, sy)

    elif t == "type":
        text = action.get("text", "")
        print(f"  [scummvm] type: {text!r}")
        pyautogui.typewrite(text, interval=0.05)
        pyautogui.press("return")

    elif t == "keypress":
        keys = action.get("keys", [])
        key = keys[0] if keys else action.get("key", "")
        if key:
            print(f"  [scummvm] keypress: {key}")
            pyautogui.press(key)


# ── Action extraction ───────────────────────────────────────────────────


def _extract_action(text: str) -> dict | None:
    if "<ACTION>" in text and "</ACTION>" in text:
        try:
            return json.loads(text.split("<ACTION>")[1].split("</ACTION>")[0].strip())
        except Exception:
            pass
    m = re.search(r'\{[^{}]*"type"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None


# ── Logging ─────────────────────────────────────────────────────────────

_LOG_PATH = "scummvm_action_log.jsonl"


def _log_action(action: dict | None, response: str, model: str) -> None:
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "action": action,
        "response": response[:500],
    }
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Main entry point (called by execute.py) ─────────────────────────────

_ACTION_INSTRUCTION = """
After </RESPO>, output ONE action in an <ACTION> block:
  Walk/interact: <ACTION>{{"type": "click", "x": <int>, "y": <int>}}</ACTION>
  Text command:  <ACTION>{{"type": "type", "text": "<parser command>"}}</ACTION>
  Key press:     <ACTION>{{"type": "keypress", "keys": ["<key>"]}}</ACTION>
Screenshot is {img_w}x{img_h} px."""


def execute_scummvm_action(action_prompt: str, encoded_image: str, reasoning_model: str) -> dict:
    # agent.py passes a full-screen mss shot; our coordinate mapping needs the
    # ScummVM window only — take our own Quartz screenshot instead.
    b64, img_w, img_h = capture_scummvm_screenshot_b64()

    prompt = action_prompt.strip() + "\n" + _ACTION_INSTRUCTION.format(img_w=img_w, img_h=img_h)

    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
        base_url=os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1"),
    )
    resp = client.chat.completions.create(
        model=reasoning_model,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        temperature=0,
        max_tokens=1024,
    )
    response = resp.choices[0].message.content or ""
    print(f"  [scummvm] response: {response[:200]}")

    action = _extract_action(response)
    print(f"  [scummvm] action: {action}")
    _log_action(action, response, reasoning_model)

    if action:
        _execute(action, img_w, img_h)

    return {"messages": [response], "action_count": 1 if action else 0}
