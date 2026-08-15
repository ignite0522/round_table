from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from .merlin_control import RerankFn, SelectedCandidate


_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "order": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
    },
    "required": ["order", "reason"],
}


class CodexCandidateReranker:
    """Use Codex CLI to rerank a short candidate list for Merlin.

    This keeps the dependency model aligned with the rest of the project:
    we already depend on `codex exec`, so Merlin can reuse it instead of
    introducing a second model SDK stack.
    """

    def __init__(self, *, codex_bin: str = "codex", model: str | None = None, sandbox: bool = False):
        self.codex_bin = codex_bin
        self.model = model
        self.sandbox = sandbox
        self._last_signature: str | None = None
        self._last_ranked_ids: list[str] | None = None
        self._last_reason: str = ""

    def __call__(self, candidates: list[SelectedCandidate]) -> list[SelectedCandidate]:
        if len(candidates) <= 1:
            return candidates
        signature = self._signature(candidates)
        if signature == self._last_signature and self._last_ranked_ids:
            return self._apply_order(candidates, self._last_ranked_ids)

        try:
            payload = self._invoke_codex(candidates)
        except Exception:
            return candidates

        order = [str(item) for item in payload.get("order") or [] if str(item)]
        if not order:
            return candidates
        ranked = self._apply_order(candidates, order)
        self._last_signature = signature
        self._last_ranked_ids = [item.candidate_id for item in ranked]
        self._last_reason = str(payload.get("reason") or "")
        return ranked

    @property
    def last_reason(self) -> str:
        return self._last_reason

    def _signature(self, candidates: list[SelectedCandidate]) -> str:
        slim = [
            {
                "candidate_id": item.candidate_id,
                "board_entry_id": item.board_entry_id,
                "objective": item.objective,
                "title": item.title,
                "tags": item.tags,
                "body": item.body,
            }
            for item in candidates
        ]
        return json.dumps(slim, ensure_ascii=False, sort_keys=True)

    def _apply_order(
        self, candidates: list[SelectedCandidate], ordered_ids: list[str]
    ) -> list[SelectedCandidate]:
        by_id = {item.candidate_id: item for item in candidates}
        ranked: list[SelectedCandidate] = []
        seen: set[str] = set()
        for candidate_id in ordered_ids:
            item = by_id.get(candidate_id)
            if item is None or candidate_id in seen:
                continue
            ranked.append(item)
            seen.add(candidate_id)
        for item in candidates:
            if item.candidate_id not in seen:
                ranked.append(item)
        return ranked

    def _invoke_codex(self, candidates: list[SelectedCandidate]) -> dict:
        with tempfile.TemporaryDirectory(prefix="roundtable-merlin-rerank-") as tmp:
            tmp_path = Path(tmp)
            out_path = tmp_path / "out.json"
            schema_path = tmp_path / "schema.json"
            schema_path.write_text(json.dumps(_OUTPUT_SCHEMA, ensure_ascii=False), encoding="utf-8")

            cmd = [
                self.codex_bin,
                "exec",
                "--skip-git-repo-check",
                "--output-last-message",
                str(out_path),
                "--output-schema",
                str(schema_path),
                "--sandbox",
                "workspace-write" if self.sandbox else "danger-full-access",
                "--cd",
                str(tmp_path),
            ]
            if self.model:
                cmd += ["--model", self.model]
            cmd.append("-")

            proc = subprocess.run(
                cmd,
                input=self._prompt(candidates),
                text=True,
                capture_output=True,
                env=os.environ.copy(),
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "codex rerank failed")
            raw = out_path.read_text(encoding="utf-8") if out_path.exists() else proc.stdout
            return json.loads(raw)

    def _prompt(self, candidates: list[SelectedCandidate]) -> str:
        payload = []
        for item in candidates:
            payload.append(
                {
                    "candidate_id": item.candidate_id,
                    "board_entry_id": item.board_entry_id,
                    "island": item.island,
                    "objective": item.objective,
                    "title": item.title,
                    "tags": list(item.tags),
                    "hypothesis": item.hypothesis,
                    "body": item.body[:900],
                    "refs": list(item.refs),
                }
            )
        return (
            "你是 Merlin 的短名单重排器。目标是对 CTF 攻击路线候选做二次排序。\n"
            "只根据候选本身的价值、可推进性、信息增益、与其他候选的差异度来排序。\n"
            "优先更可能带来新资产、新原语、稳定利用链、flag 闭环的候选。\n"
            "降低明显重复、已弱化、描述空泛、死路味道重的候选优先级。\n"
            "不要发明不存在的事实，也不要解释太长。\n"
            "返回 JSON：order 是从最好到最差的 candidate_id 列表；reason 是一句中文简述。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        )


def build_codex_reranker(
    *, enabled: bool, codex_bin: str = "codex", model: str | None = None, sandbox: bool = False
) -> RerankFn | None:
    if not enabled:
        return None
    return CodexCandidateReranker(codex_bin=codex_bin, model=model, sandbox=sandbox)
