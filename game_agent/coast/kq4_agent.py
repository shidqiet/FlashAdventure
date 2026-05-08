"""KQ4 baseline agent — screenshot -> VLM -> action.

Start ScummVM separately, then run:
  python kq4_agent.py
  python kq4_agent.py --base-url http://localhost:8000/v1 --model Qwen/Qwen2-VL-7B-Instruct
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

import pyautogui
from openai import OpenAI
from PIL import Image

# ── Config ─────────────────────────────────────────────────────────────

# Snellius: ssh -L 8000:localhost:8000 <user>@snellius.surf.nl
DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "Qwen/Qwen2-VL-7B-Instruct"

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_LOG_DIR = str(PROJECT_ROOT / "runs" / "kq4_baseline")

MODEL_IMG_WIDTH = 720

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

# ── Prompts ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Rosella in King's Quest IV: The Perils of Rosella on ScummVM — a 1988 Sierra text-parser adventure game.

Controls:
- To walk: click on the ground near where you want to go.
- To interact: type a parser command, e.g. "look", "take ball", "open door", "talk to fairy".
- If a text response appears on screen, press return to dismiss it before acting again.
- Do not repeat the same command more than twice if it has no effect.

Reply with ONE JSON object only — not a list, not an array. No explanation."""

ACTION_PROMPT = """Screenshot: {img_w}x{img_h} px. Score bar occupies the top ~{score_bar_h}px — do not click there.

{history}Actions:
  {{"type": "click", "x": <int>, "y": <int>}}   — walk toward a location
  {{"type": "type", "text": "<command>"}}        — parser command, e.g. "look", "take lamp", "open door"
  {{"type": "keypress", "keys": ["return"]}}     — dismiss a game text response
  {{"type": "wait", "duration_ms": 500}}         — wait for animation

Return ONLY the JSON."""

OBSERVE_PROMPT = """You are playing King's Quest IV: The Perils of Rosella — a classic Sierra adventure game.
You just did: {action}

Image 1 is BEFORE the action. Image 2 is AFTER.
What changed between the two screenshots? 1-2 sentences only."""

# ── Screenshot ─────────────────────────────────────────────────────────


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
        print(f"  [!] Quartz error: {e}")
    return None, None


def _screenshot() -> Image.Image:
    wid, _ = _scummvm_window()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    if wid:
        subprocess.run(["screencapture", "-l", str(wid), "-x", path], check=True)
    else:
        print("  [!] ScummVM window not found — capturing full screen")
        subprocess.run(["screencapture", "-x", path], check=True)
    img = Image.open(path)
    new_h = int(img.height * MODEL_IMG_WIDTH / img.width)
    return img.resize((MODEL_IMG_WIDTH, new_h), Image.LANCZOS)


# ── Helpers ────────────────────────────────────────────────────────────


def _encode(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _extract_json(text: str) -> dict | None:
    def _first_dict(val):
        if isinstance(val, dict):
            return val
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    return item
        return None

    text = text.strip()
    try:
        return _first_dict(json.loads(text))
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            return _first_dict(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*?\}", text)
    if m:
        try:
            return _first_dict(json.loads(m.group()))
        except json.JSONDecodeError:
            pass
    return None


# ── Action execution ───────────────────────────────────────────────────


def _focus_scummvm() -> None:
    subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to set frontmost of '
            '(first process whose name contains "scummvm") to true',
        ],
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
        print(f"  [>] click model=({x},{y}) screen=({sx},{sy})")
        pyautogui.click(sx, sy)

    elif t == "type":
        text = action.get("text", "")
        print(f"  [>] type: {text!r}")
        pyautogui.typewrite(text, interval=0.05)
        pyautogui.press("return")

    elif t == "keypress":
        keys = action.get("keys", [])
        key = keys[0] if keys else action.get("key", "")
        if key:
            print(f"  [>] keypress: {key}")
            pyautogui.press(key)

    elif t == "wait":
        ms = action.get("duration_ms", 500)
        print(f"  [>] wait {ms}ms")
        time.sleep(ms / 1000)


# ── Logging ────────────────────────────────────────────────────────────


def _init_log(log_dir: Path, model: str) -> tuple[Path, Path]:
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = log_dir / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        json.dumps({"model": model, "started": ts}, indent=2)
    )
    print(f"[kq4_agent] Logging to: {run_dir}")
    return run_dir, run_dir / "steps.jsonl"


def _log_step(
    log_path: Path, step: int, action: dict | None, raw: str, error: str | None
) -> None:
    with log_path.open("a") as f:
        f.write(
            json.dumps({"step": step, "action": action, "raw": raw, "error": error})
            + "\n"
        )


# ── Observe ────────────────────────────────────────────────────────────

HISTORY_WINDOW = 5


def _observe(
    client: OpenAI, model: str, before: Image.Image, after: Image.Image, action: dict
) -> str:
    prompt = OBSERVE_PROMPT.format(action=json.dumps(action))
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_encode(before)}"
                            },
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_encode(after)}"
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            temperature=0,
            max_tokens=128,
        )
        obs = (resp.choices[0].message.content or "").strip()
        print(f"  [obs] {obs}")
        return obs
    except Exception as e:
        print(f"  [!] observe error: {e}")
        return "(observation failed)"


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["What happened so far:"]
    for i, h in enumerate(history[-HISTORY_WINDOW:], 1):
        lines.append(f"  {i}. did={json.dumps(h['action'])} → {h['observation']}")
    return "\n".join(lines) + "\n\n"


# ── Main loop ──────────────────────────────────────────────────────────


def run(
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    max_steps: int = 100,
    log_dir: str = DEFAULT_LOG_DIR,
    step_delay: float = 1.0,
) -> None:
    client = OpenAI(api_key="dummy", base_url=base_url)
    run_dir, log_path = _init_log(Path(log_dir), model=model)

    print(f"[kq4_agent] model={model}  base_url={base_url}\n")

    history: list[dict] = []

    for step in range(1, max_steps + 1):
        print(f"── Step {step}/{max_steps} " + "─" * 40)

        img = _screenshot()
        img_w, img_h = img.size
        img.save(run_dir / f"step_{step:04d}.png")

        prompt = ACTION_PROMPT.format(
            img_w=img_w,
            img_h=img_h,
            score_bar_h=img_h // 10,
            history=_format_history(history),
        )

        raw, action, error = "", None, None
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{_encode(img)}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    },
                ],
                temperature=0,
                max_tokens=128,
            )
            raw = resp.choices[0].message.content or ""
            print(f"  [<] {raw.strip()}")
            action = _extract_json(raw)
        except Exception as e:
            error = str(e)
            print(f"  [!] API error: {e}")

        if action is None and error is None:
            error = "could not parse JSON"

        print(f"  [*] action={action}  error={error}")
        _log_step(log_path, step, action, raw, error)

        if action:
            _execute(action, img_w, img_h)
            if step_delay > 0:
                time.sleep(step_delay)
            obs_img = _screenshot()
            obs_img.save(run_dir / f"step_{step:04d}_obs.png")
            observation = _observe(client, model, img, obs_img, action)
            history.append({"action": action, "observation": observation})

    print(f"\n[kq4_agent] Done — {max_steps} steps. Log: {run_dir}")


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="KQ4 baseline agent — start ScummVM first"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    parser.add_argument("--step-delay", type=float, default=1.0)
    args = parser.parse_args()

    run(
        model=args.model,
        base_url=args.base_url,
        max_steps=args.max_steps,
        log_dir=args.log_dir,
        step_delay=args.step_delay,
    )
