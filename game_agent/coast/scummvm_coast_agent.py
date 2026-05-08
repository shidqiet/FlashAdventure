"""ScummVM COAST agent — generalized for any ScummVM game.

Start ScummVM separately, then run:
  python scummvm_coast_agent.py --game kq4
  python scummvm_coast_agent.py --game kq4 --base-url http://localhost:8000/v1 --model Qwen/Qwen2-VL-7B-Instruct
"""

import argparse
import json
import os

from agent import MapperBot, SeekerBot, SolverBot
from tools import load_config


def load_mapping(memory_path: str) -> list:
    path = os.path.join(memory_path, "mapping_memory.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def main(config_path: str = "config_scummvm.yaml", game_name: str = None) -> None:
    config = load_config(config_path)
    game_name = game_name or config.get("game_name", "kq4")
    max_actions = config.get("max_action_count", 50)
    MAX_ITER = 10
    total_actions = 0
    total_seeker = 0
    total_solver = 0
    iteration = 0

    print(f"\n[scummvm_coast] Starting — game={game_name}  model={config.get('reasoning_model')}  base_url={os.environ.get('OPENAI_BASE_URL')}")

    while iteration < MAX_ITER:
        iteration += 1
        print(f"\n[Iteration {iteration}] total actions: {total_actions}/{max_actions}")

        # 1. Seeker
        seeker = SeekerBot(config_path=config_path, game_name=game_name)
        seeker_actions = seeker.run()
        total_seeker += seeker_actions
        total_actions += seeker_actions
        print(f"[Seeker] {seeker_actions} actions. Cumulative: {total_actions}/{max_actions}")

        if total_actions >= max_actions:
            print("[scummvm_coast] Action limit reached.")
            break

        # 2. Mapper
        mapper = MapperBot(config_path=config_path, game_name=game_name)
        mapper.run()

        # 3. Check mappings
        mappings = load_mapping(mapper.memory_path)
        if not mappings:
            print("[Mapper] No mappings — retrying seeker.")
            continue

        failed = [m for m in mappings if isinstance(m, dict) and not m.get("success", False)]
        if not failed:
            print("[scummvm_coast] All mappings successful.")
            break

        print(f"[Solver] {len(failed)} failed mapping(s)...")

        # 4. Solver
        for idx, mapping in enumerate(failed):
            print(f"  [{idx + 1}/{len(failed)}] clue={mapping.get('clue', {})}")
            solver = SolverBot(config_path=config_path, game_name=game_name)
            solver.get_mapping([mapping])
            solver_actions = solver.run()
            total_solver += solver_actions
            total_actions += solver_actions

            if total_actions >= max_actions:
                print("[scummvm_coast] Action limit reached.")
                break

        if total_actions >= max_actions:
            break

        remaining = [m for m in load_mapping(mapper.memory_path) if isinstance(m, dict) and not m.get("success", False)]
        if not remaining:
            print("[scummvm_coast] All mappings resolved.")
            break

    print(f"\n[scummvm_coast] Done — seeker={total_seeker}  solver={total_solver}  total={total_actions}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ScummVM COAST agent — start ScummVM first")
    parser.add_argument("--config", default="config_scummvm.yaml")
    parser.add_argument("--game", default=None, help="Game name (must match game_prompt.json key)")
    parser.add_argument("--base-url", default=None, help="vLLM base URL")
    parser.add_argument("--model", default=None, help="Model name override")
    args = parser.parse_args()

    config = load_config(args.config)

    base_url = args.base_url or config.get("scummvm_base_url", "http://localhost:8000/v1")
    api_key  = config.get("scummvm_api_key", "dummy")
    model    = args.model or config.get("reasoning_model", "Qwen/Qwen2-VL-7B-Instruct")

    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_KEY"]  = api_key

    if args.model:
        config["reasoning_model"] = model
        import yaml, tempfile, atexit
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, dir=".", prefix="_scummvm_tmp_")
        yaml.dump(config, tmp)
        tmp.close()
        atexit.register(os.unlink, tmp.name)
        args.config = tmp.name

    main(config_path=args.config, game_name=args.game)
