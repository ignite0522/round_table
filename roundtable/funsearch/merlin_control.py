from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.entry import BoardEntry, EntryStatus, EntryType


POPULATION_SCRIPT = Path(__file__).with_name("population.py")


def candidate_objective(entry: BoardEntry) -> float:
    type_bonus = {
        EntryType.FACT: 3.0,
        EntryType.HYPOTHESIS: 5.0,
        EntryType.NEXT_STEP: 6.0,
        EntryType.TOOL_OUTPUT: 7.0,
        EntryType.ARTIFACT: 10.0,
        EntryType.FLAG_CANDIDATE: 40.0,
        EntryType.DEAD_END: -8.0,
    }.get(entry.type, 0.0)
    status_bonus = {
        EntryStatus.OPEN: 0.0,
        EntryStatus.CLAIMED: 1.5,
        EntryStatus.RESOLVED: 8.0,
        EntryStatus.REFUTED: -10.0,
    }.get(entry.status, 0.0)
    ref_bonus = min(4.0, 0.5 * len(entry.refs))
    body_bonus = min(3.0, len((entry.body or "").strip()) / 240.0)
    return (
        20.0 * entry.confidence
        + 2.5 * entry.endorse_count
        - 2.0 * entry.challenge_count
        + type_bonus
        + status_bonus
        + ref_bonus
        + body_bonus
    )


@dataclass
class SelectedCandidate:
    island: str
    candidate_id: str
    board_entry_id: str
    objective: float
    hypothesis: str
    title: str = ""
    tags: tuple[str, ...] = ()
    body: str = ""
    refs: tuple[str, ...] = ()


RerankFn = Callable[[list[SelectedCandidate]], list[SelectedCandidate]]

class MerlinFunSearchControl:
    def __init__(
        self,
        run_dir: str | Path,
        *,
        islands: int = 10,
        capacity: int = 6,
        exploration: float = 1.4,
        reset_period_seconds: float = 4 * 60 * 60,
        seed: int = 0,
        rerank_top_k: int = 0,
        reranker: RerankFn | None = None,
    ):
        self.run_dir = Path(run_dir)
        self.pool_dir = self.run_dir / "pool"
        self.candidates_dir = self.pool_dir / "candidates"
        self.reports_dir = self.run_dir / "reports"
        self.meta_path = self.pool_dir / "merlin_funsearch_meta.json"
        self.islands = islands
        self.capacity = capacity
        self.exploration = exploration
        self.reset_period_seconds = reset_period_seconds
        self.seed = seed
        self.rerank_top_k = rerank_top_k
        self.reranker = reranker
        self.enabled = POPULATION_SCRIPT.is_file()

    def ensure_initialized(self) -> None:
        if not self.enabled:
            return
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        if not (self.pool_dir / "population.json").exists():
            self._run_population(
                "init",
                "--objective-sense",
                "max",
                "--islands",
                str(self.islands),
                "--capacity",
                str(self.capacity),
                "--exploration",
                str(self.exploration),
                "--reset-period-seconds",
                str(self.reset_period_seconds),
                "--seed",
                str(self.seed),
            )
        if not self.meta_path.exists():
            self._write_meta(
                {
                    "cluster_to_island": {},
                    "entry_to_candidate": {},
                    "next_island_index": 0,
                }
            )

    def sync_board(self, entries: list[BoardEntry]) -> dict[str, Any]:
        if not self.enabled:
            return {"registered": [], "recorded": []}
        self.ensure_initialized()
        meta = self._read_meta()
        registered: list[str] = []
        recorded: list[str] = []

        for entry in sorted(entries, key=lambda item: item.created_at):
            if not self._eligible(entry):
                continue
            if entry.id in meta["entry_to_candidate"]:
                continue
            island = self._assign_island(meta, self._cluster_key(entry))
            candidate_id = self._candidate_id(island, entry.id)
            strategy_dir = self.candidates_dir / candidate_id
            strategy_dir.mkdir(parents=True, exist_ok=True)
            strategy_path = strategy_dir / "strategy.json"
            result_path = strategy_dir / "result.json"
            strategy_path.write_text(
                json.dumps(
                    {
                        "entry_id": entry.id,
                        "title": entry.title,
                        "body": entry.body,
                        "tags": entry.tags,
                        "refs": entry.refs,
                        "author": entry.author,
                        "type": entry.type.value,
                        "score": candidate_objective(entry),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._run_population(
                "register",
                "--id",
                candidate_id,
                "--island",
                island,
                "--strategy-path",
                str(strategy_path),
                "--hypothesis",
                self._hypothesis_text(entry),
            )
            objective = candidate_objective(entry)
            self._run_population(
                "record",
                "--id",
                candidate_id,
                "--valid",
                "--objective",
                str(objective),
                "--runtime-seconds",
                "0",
                "--memory-mb",
                "0",
                "--note",
                f"board:{entry.id}",
            )
            result_path.write_text(
                json.dumps(
                    {
                        "entry_id": entry.id,
                        "objective": objective,
                        "entry_score": entry.score(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            meta["entry_to_candidate"][entry.id] = candidate_id
            registered.append(candidate_id)
            recorded.append(candidate_id)

        self._write_meta(meta)
        return {"registered": registered, "recorded": recorded}

    def select_candidate(self) -> SelectedCandidate | None:
        if not self.enabled:
            return None
        self.ensure_initialized()
        try:
            payload = self._run_population("select")
        except RuntimeError:
            return None
        primary = self._selected_from_payload(payload)
        if primary is None:
            return None
        if self.reranker is None or self.rerank_top_k <= 1:
            return primary
        shortlist = self._shortlist_candidates(limit=self.rerank_top_k)
        merged = [primary]
        seen = {primary.candidate_id}
        for item in shortlist:
            if item.candidate_id in seen:
                continue
            seen.add(item.candidate_id)
            merged.append(item)
        reranked = self.reranker(merged) or merged
        choice = reranked[0]
        if choice.candidate_id != primary.candidate_id:
            reason = getattr(self.reranker, "last_reason", "")
            suffix = f" | {reason}" if reason else ""
            self.append_timeline(
                f"- rerank override `{primary.candidate_id}` -> `{choice.candidate_id}`{suffix}"
            )
        return choice

    def append_timeline(self, line: str) -> None:
        if not self.enabled:
            return
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timeline = self.reports_dir / "timeline.md"
        with timeline.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")

    def _eligible(self, entry: BoardEntry) -> bool:
        if entry.status == EntryStatus.REFUTED:
            return False
        return entry.type in {
            EntryType.FACT,
            EntryType.HYPOTHESIS,
            EntryType.NEXT_STEP,
            EntryType.ARTIFACT,
            EntryType.TOOL_OUTPUT,
            EntryType.FLAG_CANDIDATE,
        }

    def _cluster_key(self, entry: BoardEntry) -> str:
        if entry.tags:
            return "|".join(sorted(entry.tags)[:3])
        return f"type:{entry.type.value}"

    def _assign_island(self, meta: dict[str, Any], cluster_key: str) -> str:
        current = meta["cluster_to_island"].get(cluster_key)
        if current:
            return current
        idx = int(meta["next_island_index"]) % self.islands
        island = f"I{idx:02d}"
        meta["cluster_to_island"][cluster_key] = island
        meta["next_island_index"] = idx + 1
        return island

    def _candidate_id(self, island: str, entry_id: str) -> str:
        cleaned = entry_id.replace("-", "").upper()
        return f"{island}C{cleaned}"

    def _hypothesis_text(self, entry: BoardEntry) -> str:
        return f"{entry.type.value}:{entry.title}"

    def _read_meta(self) -> dict[str, Any]:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def _write_meta(self, meta: dict[str, Any]) -> None:
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_population(self, command: str, *args: str) -> dict[str, Any]:
        cmd = [
            sys.executable,
            str(POPULATION_SCRIPT),
            command,
            "--run-dir",
            str(self.run_dir),
            *args,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"population {command} failed")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _selected_from_payload(self, payload: dict[str, Any]) -> SelectedCandidate | None:
        parent = payload.get("parent") or {}
        if not parent:
            return None
        strategy_path = Path(parent.get("strategy_path", ""))
        try:
            strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return SelectedCandidate(
            island=str(payload.get("island", parent.get("island", ""))),
            candidate_id=str(parent.get("id", "")),
            board_entry_id=str(strategy.get("entry_id", "")),
            objective=float((parent.get("result") or {}).get("objective") or 0.0),
            hypothesis=str(parent.get("hypothesis") or strategy.get("title") or ""),
            title=str(strategy.get("title") or ""),
            tags=tuple(strategy.get("tags") or ()),
            body=str(strategy.get("body") or ""),
            refs=tuple(strategy.get("refs") or ()),
        )

    def _shortlist_candidates(self, limit: int) -> list[SelectedCandidate]:
        try:
            payload = self._run_population("status")
        except RuntimeError:
            return []
        out: list[SelectedCandidate] = []
        for candidate in payload.get("global_elites", [])[:limit]:
            selected = self._selected_from_payload({"parent": candidate, "island": candidate.get("island", "")})
            if selected is not None:
                out.append(selected)
        return out
