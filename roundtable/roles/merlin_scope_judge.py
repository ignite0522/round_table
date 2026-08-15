from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..core.entry import BoardEntry


_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["local_env", "target_side", "uncertain"],
        },
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


@dataclass
class ScopeJudgment:
    verdict: str
    reason: str


class CodexScopeJudge:
    """Merlin's LLM judge for ambiguous local-vs-target scope entries."""

    def __init__(self, *, codex_bin: str = "codex", model: str | None = None, sandbox: bool = False):
        self.codex_bin = codex_bin
        self.model = model
        self.sandbox = sandbox
        self._cache: dict[str, ScopeJudgment] = {}

    def __call__(self, root_entry: BoardEntry | None, candidate: BoardEntry) -> ScopeJudgment:
        signature = self._signature(root_entry, candidate)
        cached = self._cache.get(signature)
        if cached is not None:
            return cached
        try:
            payload = self._invoke_codex(root_entry, candidate)
            judgment = ScopeJudgment(
                verdict=str(payload.get("verdict") or "uncertain"),
                reason=str(payload.get("reason") or ""),
            )
        except Exception:
            judgment = ScopeJudgment(verdict="uncertain", reason="")
        self._cache[signature] = judgment
        return judgment

    def _signature(self, root_entry: BoardEntry | None, candidate: BoardEntry) -> str:
        payload = {
            "root_title": root_entry.title if root_entry else "",
            "root_body": root_entry.body if root_entry else "",
            "candidate_title": candidate.title,
            "candidate_body": candidate.body,
            "candidate_tags": candidate.tags,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _invoke_codex(self, root_entry: BoardEntry | None, candidate: BoardEntry) -> dict:
        with tempfile.TemporaryDirectory(prefix="roundtable-merlin-scope-") as tmp:
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
                input=self._prompt(root_entry, candidate),
                text=True,
                capture_output=True,
                env=os.environ.copy(),
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "codex scope judge failed")
            raw = out_path.read_text(encoding="utf-8") if out_path.exists() else proc.stdout
            return json.loads(raw)

    def _prompt(self, root_entry: BoardEntry | None, candidate: BoardEntry) -> str:
        root_payload = {
            "title": root_entry.title if root_entry else "",
            "body": (root_entry.body if root_entry else "")[:1500],
        }
        candidate_payload = {
            "id": candidate.id,
            "type": candidate.type.value,
            "title": candidate.title,
            "body": candidate.body[:1800],
            "tags": candidate.tags,
        }
        return (
            "你是 Merlin 的目标范围裁决器。\n"
            "任务：判断一条黑板条目是在讨论“目标侧 SSRF/代理/CONNECT 可达的内部面”，"
            "还是已经偏到“本地执行环境/宿主/worker 自身服务”。\n"
            "只返回 JSON。\n\n"
            "裁决标准：\n"
            "- `target_side`: 更像题目目标自身经 SSRF/Host/CONNECT 等方式触达的内部面。\n"
            "- `local_env`: 更像当前执行环境、容器、宿主机、代理链本地服务，不该继续深挖。\n"
            "- `uncertain`: 证据不足，宁可不误杀。\n"
            "如果只看到 `localhost/127.0.0.1` 本身，但没有更强环境指纹，通常应偏向 `uncertain` 或 `target_side`，不要草率判 `local_env`。\n"
            "如果出现 `tinyproxy`、`AirTunes`、`container via direct connection`、Apple/AirPlay 指纹等，更偏向 `local_env`。\n\n"
            f"题目根信息:\n{json.dumps(root_payload, ensure_ascii=False, indent=2)}\n\n"
            f"待判定条目:\n{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}\n"
        )


def build_codex_scope_judge(
    *, enabled: bool, codex_bin: str = "codex", model: str | None = None, sandbox: bool = False
) -> CodexScopeJudge | None:
    if not enabled:
        return None
    return CodexScopeJudge(codex_bin=codex_bin, model=model, sandbox=sandbox)
