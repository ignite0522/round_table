#!/usr/bin/env python3
"""Deterministic multi-island state manager for FunSearch candidates.

Vendored into this project so Merlin does not depend on external skill files.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(run_dir: str) -> Path:
    return Path(run_dir) / "pool" / "population.json"


def load_state(run_dir: str) -> dict[str, Any]:
    path = state_path(run_dir)
    if not path.is_file():
        raise SystemExit(f"Population state does not exist: {path}")
    with path.open(encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("version") != STATE_VERSION:
        raise SystemExit("Unsupported population state version")
    return state


def save_state(run_dir: str, state: dict[str, Any]) -> None:
    path = state_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def number(value: str | None, field: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as error:
        raise SystemExit(f"{field} must be numeric") from error


def rank_key(candidate: dict[str, Any], sense: str) -> tuple[float, float, float, float, str]:
    result = candidate.get("result") or {}
    if not result.get("valid", False):
        return (1.0, math.inf, math.inf, math.inf, candidate["id"])
    objective = result.get("objective")
    if objective is None:
        return (1.0, math.inf, math.inf, math.inf, candidate["id"])
    objective_rank = objective if sense == "min" else -objective
    runtime = result.get("runtime_seconds", math.inf)
    memory = result.get("memory_mb", math.inf)
    return (0.0, objective_rank, runtime, memory, candidate["id"])


def refresh_elites(state: dict[str, Any]) -> None:
    sense = state["objective_sense"]
    capacity = state["capacity"]
    candidates = state["candidates"]
    for island in state["islands"]:
        for candidate in candidates.values():
            if candidate["island"] == island["id"]:
                candidate["elite"] = False
        members = [
            candidate
            for candidate in candidates.values()
            if candidate["island"] == island["id"]
            and candidate["status"] == "evaluated"
            and candidate.get("active", True)
            and (candidate.get("result") or {}).get("valid", False)
        ]
        members.sort(key=lambda candidate: rank_key(candidate, sense))
        elite_ids = [candidate["id"] for candidate in members[:capacity]]
        island["elite_ids"] = elite_ids
        for candidate in members:
            candidate["elite"] = candidate["id"] in elite_ids


def best_elite(state: dict[str, Any], island: dict[str, Any]) -> dict[str, Any] | None:
    candidates = state["candidates"]
    elites = [candidates[candidate_id] for candidate_id in island["elite_ids"]]
    if not elites:
        return None
    return min(elites, key=lambda candidate: rank_key(candidate, state["objective_sense"]))


def reset_islands(state: dict[str, Any]) -> list[dict[str, str]]:
    refresh_elites(state)
    islands = state["islands"]
    if any(not island["elite_ids"] for island in islands):
        return []
    ordered = sorted(
        islands,
        key=lambda island: rank_key(best_elite(state, island), state["objective_sense"]),
    )
    split = len(ordered) // 2
    strong, weak = ordered[: len(ordered) - split], ordered[len(ordered) - split :]
    if not strong or not weak:
        return []

    state["reset_count"] += 1
    rng = random.Random(state["seed"] + state["reset_count"])
    events = []
    for island in weak:
        founder_island = rng.choice(strong)
        founder = best_elite(state, founder_island)
        for candidate in state["candidates"].values():
            if candidate["island"] == island["id"] and candidate.get("active", True):
                candidate["active"] = False
                candidate["elite"] = False

        base_id = f"{island['id']}F{state['reset_count']:03d}"
        founder_id = base_id
        suffix = 1
        while founder_id in state["candidates"]:
            founder_id = f"{base_id}_{suffix}"
            suffix += 1
        state["candidates"][founder_id] = {
            "id": founder_id,
            "island": island["id"],
            "parent_ids": [founder["id"]],
            "founder_source_id": founder["id"],
            "strategy_path": founder["strategy_path"],
            "hypothesis": f"Reset founder migrated from {founder_island['id']}",
            "created_at": now(),
            "status": "evaluated",
            "result": copy.deepcopy(founder["result"]),
            "selection_count": 0,
            "elite": True,
            "active": True,
        }
        island["elite_ids"] = [founder_id]
        island["visits"] = 0
        island["resets"] = island.get("resets", 0) + 1
        events.append(
            {
                "island": island["id"],
                "founder_island": founder_island["id"],
                "founder": founder_id,
                "source": founder["id"],
            }
        )
    refresh_elites(state)
    state["last_reset_epoch"] = time.time()
    for event in events:
        state["events"].append({"at": now(), "event": "reset", **event})
    return events


def maybe_reset_islands(state: dict[str, Any]) -> list[dict[str, str]]:
    elapsed = time.time() - state["last_reset_epoch"]
    if elapsed < state["reset_period_seconds"]:
        return []
    return reset_islands(state)


def command_init(args: argparse.Namespace) -> None:
    path = state_path(args.run_dir)
    if path.exists():
        raise SystemExit(f"Population state already exists: {path}")
    islands = [
        {"id": f"I{index:02d}", "elite_ids": [], "visits": 0, "resets": 0}
        for index in range(args.islands)
    ]
    state = {
        "version": STATE_VERSION,
        "created_at": now(),
        "updated_at": now(),
        "objective_sense": args.objective_sense,
        "capacity": args.capacity,
        "exploration": args.exploration,
        "reset_period_seconds": args.reset_period_seconds,
        "last_reset_epoch": time.time(),
        "reset_count": 0,
        "seed": args.seed,
        "islands": islands,
        "candidates": {},
        "events": [],
    }
    state["events"].append({"at": now(), "event": "init"})
    save_state(args.run_dir, state)
    print(json.dumps({"state": str(path), "islands": [item["id"] for item in islands]}))


def command_register(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    candidates = state["candidates"]
    island_ids = {item["id"] for item in state["islands"]}
    if args.id in candidates:
        raise SystemExit(f"Candidate already exists: {args.id}")
    if args.island not in island_ids:
        raise SystemExit(f"Unknown island: {args.island}")
    unknown_parents = [parent for parent in args.parent if parent not in candidates]
    if unknown_parents:
        raise SystemExit(f"Unknown parent: {unknown_parents[0]}")
    candidates[args.id] = {
        "id": args.id,
        "island": args.island,
        "parent_ids": [item for item in args.parent if item],
        "strategy_path": args.strategy_path,
        "hypothesis": args.hypothesis,
        "created_at": now(),
        "status": "pending",
        "selection_count": 0,
        "elite": False,
        "active": True,
    }
    state["events"].append(
        {"at": now(), "event": "register", "candidate": args.id, "island": args.island}
    )
    save_state(args.run_dir, state)
    print(json.dumps(candidates[args.id], indent=2))


def command_record(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    candidate = state["candidates"].get(args.id)
    if candidate is None:
        raise SystemExit(f"Unknown candidate: {args.id}")
    objective = number(args.objective, "objective")
    runtime = number(args.runtime_seconds, "runtime_seconds")
    memory = number(args.memory_mb, "memory_mb")
    if args.valid and objective is None:
        raise SystemExit("A valid result requires --objective")
    candidate["status"] = "evaluated"
    candidate["result"] = {
        "valid": bool(args.valid),
        "objective": objective,
        "runtime_seconds": runtime,
        "memory_mb": memory,
        "note": args.note,
        "recorded_at": now(),
    }
    refresh_elites(state)
    resets = maybe_reset_islands(state)
    island = next(item for item in state["islands"] if item["id"] == candidate["island"])
    state["events"].append(
        {
            "at": now(),
            "event": "record",
            "candidate": args.id,
            "island": candidate["island"],
            "elite": candidate["id"] in island["elite_ids"],
            "resets": resets,
        }
    )
    save_state(args.run_dir, state)
    print(
        json.dumps(
            {"candidate": candidate, "elite_ids": island["elite_ids"], "resets": resets},
            indent=2,
        )
    )


def island_value(state: dict[str, Any], island: dict[str, Any]) -> float:
    candidates = state["candidates"]
    elite = [candidates[candidate_id] for candidate_id in island["elite_ids"]]
    valid = [candidate for candidate in elite if (candidate.get("result") or {}).get("valid")]
    if not valid:
        return -1.0
    values = [candidate["result"]["objective"] for candidate in valid]
    all_values = [
        candidate["result"]["objective"]
        for candidate in candidates.values()
        if (candidate.get("result") or {}).get("valid") and candidate["result"].get("objective") is not None
    ]
    if len(set(all_values)) <= 1:
        return 0.0
    best = min(values) if state["objective_sense"] == "min" else max(values)
    low, high = min(all_values), max(all_values)
    normalized = (best - low) / (high - low)
    return -normalized if state["objective_sense"] == "min" else normalized


def command_select(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    candidates = state["candidates"]
    eligible = [item for item in state["islands"] if item["elite_ids"]]
    if not eligible:
        raise SystemExit("No evaluated candidate is available; evaluate bootstrap candidates first")
    total_visits = sum(item["visits"] for item in state["islands"])
    exploration = args.exploration if args.exploration is not None else state["exploration"]

    def ucb(item: dict[str, Any]) -> tuple[float, str]:
        bonus = exploration * math.sqrt(math.log(total_visits + 2) / (item["visits"] + 1))
        return (island_value(state, item) + bonus, item["id"])

    island = max(eligible, key=ucb)
    parents = [candidates[candidate_id] for candidate_id in island["elite_ids"]]
    parents.sort(
        key=lambda candidate: (
            candidate.get("selection_count", 0),
            rank_key(candidate, state["objective_sense"]),
        )
    )
    parent = parents[0]
    island["visits"] += 1
    parent["selection_count"] = parent.get("selection_count", 0) + 1
    state["events"].append(
        {"at": now(), "event": "select", "island": island["id"], "candidate": parent["id"]}
    )
    save_state(args.run_dir, state)
    print(
        json.dumps(
            {
                "island": island["id"],
                "parent": parent,
                "island_elites": island["elite_ids"],
                "ucb": ucb(island)[0],
            },
            indent=2,
        )
    )


def command_status(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    refresh_elites(state)
    save_state(args.run_dir, state)
    candidates = state["candidates"]
    summary = []
    for island in state["islands"]:
        summary.append(
            {
                "island": island["id"],
                "visits": island["visits"],
                "resets": island.get("resets", 0),
                "elite_ids": island["elite_ids"],
                "value": island_value(state, island),
            }
        )
    global_elites = sorted(
        [candidate for candidate in candidates.values() if candidate.get("elite")],
        key=lambda candidate: rank_key(candidate, state["objective_sense"]),
    )
    print(json.dumps({"islands": summary, "global_elites": global_elites}, indent=2))


def command_reset(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    resets = reset_islands(state)
    if not resets:
        raise SystemExit("Reset requires one valid active elite in every island")
    save_state(args.run_dir, state)
    print(json.dumps({"resets": resets}, indent=2))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage a FunSearch-style candidate population")
    commands = result.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--run-dir", required=True)
    init.add_argument("--objective-sense", choices=["min", "max"], required=True)
    init.add_argument("--islands", type=int, default=10)
    init.add_argument("--capacity", type=int, default=8)
    init.add_argument("--exploration", type=float, default=1.4)
    init.add_argument("--reset-period-seconds", type=float, default=4 * 60 * 60)
    init.add_argument("--seed", type=int, default=0)
    init.set_defaults(handler=command_init)

    register = commands.add_parser("register")
    register.add_argument("--run-dir", required=True)
    register.add_argument("--id", required=True)
    register.add_argument("--island", required=True)
    register.add_argument("--parent", action="append", default=[])
    register.add_argument("--strategy-path", required=True)
    register.add_argument("--hypothesis", required=True)
    register.set_defaults(handler=command_register)

    record = commands.add_parser("record")
    record.add_argument("--run-dir", required=True)
    record.add_argument("--id", required=True)
    record.add_argument("--valid", action="store_true")
    record.add_argument("--objective")
    record.add_argument("--runtime-seconds")
    record.add_argument("--memory-mb")
    record.add_argument("--note", default="")
    record.set_defaults(handler=command_record)

    select = commands.add_parser("select")
    select.add_argument("--run-dir", required=True)
    select.add_argument("--exploration", type=float)
    select.set_defaults(handler=command_select)

    status = commands.add_parser("status")
    status.add_argument("--run-dir", required=True)
    status.set_defaults(handler=command_status)

    reset = commands.add_parser("reset")
    reset.add_argument("--run-dir", required=True)
    reset.set_defaults(handler=command_reset)
    return result


def main() -> None:
    args = parser().parse_args()
    if getattr(args, "islands", 1) < 1 or getattr(args, "capacity", 1) < 1:
        raise SystemExit("islands and capacity must be positive")
    if getattr(args, "reset_period_seconds", 1) <= 0:
        raise SystemExit("reset_period_seconds must be positive")
    args.handler(args)


if __name__ == "__main__":
    main()
