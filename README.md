# FlashAdventure — ScummVM Extension

This fork extends [FlashAdventure](https://github.com/ahnjaewoo/FlashAdventure) with support for **ScummVM text-parser adventure games** (King's Quest IV) using both a simple baseline agent and the COAST multi-agent framework.

> **macOS only (current).** The ScummVM integration uses `osascript` and `screencapture` for window focus/capture — macOS-specific. Linux support would require replacing these with `xdotool` + `scrot`. No new dependencies beyond the original `requirements.txt`.

---

## Setup

```bash
conda create -n flashadventure python=3.11
conda activate flashadventure
pip install -r requirements.txt
```

Start ScummVM and load your game before running any agent.

SSH tunnel to Snellius (for vLLM):
```bash
ssh -L 8000:localhost:8000 <user>@snellius.surf.nl
```

---

## Baseline Agent

Simple loop: screenshot → VLM → action. No memory, no planning.

```bash
cd game_agent/coast
python kq4_agent.py
python kq4_agent.py --base-url http://localhost:8000/v1 --model Qwen/Qwen2-VL-7B-Instruct
```

Logs saved to `runs/kq4_baseline/<timestamp>/`.

---

## COAST Agent (ScummVM)

Multi-agent pipeline: Seeker → Mapper → Solver with clue memory.

```bash
cd game_agent/coast
python scummvm_coast_agent.py --game kq4
python scummvm_coast_agent.py --game kq4 --base-url http://localhost:8000/v1 --model Qwen/Qwen2-VL-7B-Instruct
```

To add a new ScummVM game, add an entry to `game_agent/coast/json/game_prompt.json` with the game name as the key, then pass it via `--game <name>`.

Config: `game_agent/coast/config_scummvm.yaml`

---

## Original FlashAdventure

This repository is a fork of **FlashAdventure** by Jaewoo Ahn et al.

> *FlashAdventure: A Benchmark for GUI Agents Solving Full Story Arcs in Diverse Adventure Games*
> https://arxiv.org/abs/2509.01052 · https://github.com/ahnjaewoo/FlashAdventure
