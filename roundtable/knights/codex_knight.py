"""CodexKnight —— 用 Codex CLI 驱动的真骑士。

Codex CLI 以非交互模式执行一个 cycle:读取本轮 digest,在工作目录里使用
Codex 自带的 shell/文件能力推进题目,最后返回一组结构化黑板操作。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

from ..core.entry import EntryType
from ..core.tools import BoardTools
from .base import Knight
from .policy import KnightPolicy


_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": ["post_entry", "endorse", "challenge", "claim"],
                    },
                    "type": {
                        "type": ["string", "null"],
                        "enum": [e.value for e in EntryType] + [None],
                    },
                    "title": {"type": ["string", "null"]},
                    "body": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                    "refs": {"type": ["array", "null"], "items": {"type": "string"}},
                    "tags": {"type": ["array", "null"], "items": {"type": "string"}},
                    "entry_id": {"type": ["string", "null"]},
                    "reason": {"type": ["string", "null"]},
                },
                "required": [
                    "op",
                    "type",
                    "title",
                    "body",
                    "confidence",
                    "refs",
                    "tags",
                    "entry_id",
                    "reason",
                ],
            },
        }
    },
    "required": ["operations"],
}


class CodexKnight(Knight):
    _shared_docker_sessions: ClassVar[dict[tuple[str, str, str], dict[str, Any]]] = {}

    def __init__(
        self,
        policy: KnightPolicy,
        tools: BoardTools,
        *,
        model: str | None = None,
        sandbox: bool = True,
        cwd: str | None = None,
        codex_bin: str = "codex",
        docker_image: str | None = None,
        docker_platform: str = "linux/amd64",
        max_turns_per_cycle: int = 12,
        operator_inbox_path: str | None = None,
    ):
        super().__init__(policy, tools)
        self.model = model
        self.sandbox = sandbox
        self.cwd = cwd
        self.codex_bin = codex_bin
        self.docker_image = docker_image
        self.docker_platform = docker_platform
        self.max_turns_per_cycle = max_turns_per_cycle
        self.operator_inbox_path = operator_inbox_path
        self._codex_home_dir: str | None = None
        self._docker_session_key: tuple[str, str, str] | None = None
        self._docker_container_name: str | None = None

    async def connect(self) -> None:
        if self.docker_image:
            self._connect_shared_docker_worker()
            return
        if self._codex_home_dir is not None:
            return
        self._codex_home_dir = tempfile.mkdtemp(prefix="roundtable-codex-home-")
        self._seed_codex_home(Path(self._codex_home_dir))

    async def disconnect(self) -> None:
        if self.docker_image:
            self._disconnect_shared_docker_worker()
            return
        if self._codex_home_dir is None:
            return
        shutil.rmtree(self._codex_home_dir, ignore_errors=True)
        self._codex_home_dir = None

    def _cycle_prompt(self) -> str:
        directives = getattr(self, "pending_directives", []) or []
        digest = self.tools.read_board_digest()
        board_files = self._write_board_context_files(digest) if self.policy.can_read_board else {}
        lines = [
            self.policy.render_system_prompt(closing_mode=self.closing_mode),
            "",
            "你现在运行在 Codex CLI 的一个非交互 cycle 里。",
            "【重要】若当前是 Docker worker 模式,则你运行在一个预装多种安全工具的 Kali Linux 容器里。",
            "可以在当前工作目录中使用 shell/文件工具分析题目附件或访问授权靶机。",
            "【重要】优先使用 Kali 容器内现成的安全工具、知识库与利用脚本,不要把它当成普通裸环境。",
            "【重要】所有骑士在适当且合适的时候,都应主动想到调用 Kali/系统内现成工具、知识库、字典、payload 仓库与利用脚本来验证、侦察、下载、解码、逆向或利用,不要只靠口头推理。",
            "【重要】默认只攻击题目给定的目标地址、附件，以及由目标页面/目标服务直接暴露的资源；不要自行把攻击面扩展到无关主机。",
            "【重要】禁止把你当前机器、宿主机、Docker worker 或代理链里的 `localhost`、`127.0.0.1`、`::1`、`host.docker.internal` 当作靶机。",
            "【重要】默认也禁止通过伪造 `Host: localhost`、`Host: 127.0.0.1:PORT`、绝对 URI、本地 vhost 猜测或类似技巧去探测这些地址；这仍然算在打本机/宿主/worker，不算在打题目目标。",
            "【重要】只有当你已经从题目目标本身拿到明确、直接、强证据，证明该请求确实由目标后端代发/转发到这些地址时，才可把它们视作目标攻击面的延伸；若没有这种证据，就把这类方向视为越界并停止。",
            "【重要】开局先自行探测当前环境里可用的命令、工具与知识库路径,再决定利用路径。",
            "【重要】不要把 `command -v` 当成可用性证明; 需要用一次轻量 dry-run 或 `--help/--version` 级别实测确认工具真的能执行。",
            "【重要】当前 worker 里 `nmap` 可能存在命令包装器但底层执行会被拒绝; 做端口/服务侦察优先改用 `naabu`、`ncat`、`nc`、`curl`、`openssl s_client`、`whatweb`、`httpx` 等可执行工具。",
            "【重要】由于每个 cycle 都会重新调用一次 codex exec,你的进程内短期记忆不会保留。",
            "【重要】请把阶段性笔记、中间结论、待验证思路、关键命令结果写入你自己的当前工作目录文件中,以便下一轮继续利用。",
            "【重要】这些笔记应尽量简洁、结构化、可续写;例如 NOTES.md、findings.txt、scratch.json 等。",
            "【重要】若本题通过 GUI/宿主上传了附件,在共享 Docker worker 中通常可先查看 `/workspace/attachments` 与 `/workspace/workspace` 两处。",
            "访问题目 URL 时优先绕过本地代理,例如 curl 使用 `--noproxy '*'`,避免 localhost 代理在沙箱中不可用。",
            "黑板不能直接调用工具写入;你必须在最终回答里返回 JSON,由宿主程序代你执行黑板操作。",
            "",
            self._render_target_scope(),
            self._render_operator_notes(),
            self._render_board_navigator(digest, board_files) if self.policy.can_read_board else "## 黑板访问\n你被禁止读取黑板内容或黑板导出文件。你只能写黑板(post_entry)，不能 endorse/challenge/claim，也不能据此读取别人的发现。\n",
            self._render_network_hints(digest) if self.policy.can_read_board else "## 宿主网络预检\n(当前角色不读取黑板，因此不提供基于黑板派生的网络提示)",
        ]
        if directives:
            lines.append("## Merlin 给你的指令")
            for d in directives:
                lines.append(f"- [{d.kind}] {d.message}")
            lines.append("")
        lines += [
            "## 最终回答格式",
            "只返回一个 JSON 对象,不要 Markdown,不要解释。格式如下:",
            json.dumps({"operations": self._prompt_operation_examples()}, ensure_ascii=False),
            "所有 operation 都必须包含上述全部字段;与该 op 无关的字段填 null。",
            "没有值得写入黑板的发现时返回 {\"operations\": []}。",
        ]
        return "\n".join(lines)

    def _render_operator_notes(self) -> str:
        notes = self._read_operator_notes(limit=8)
        if not notes:
            return "## 人工指令\n(当前没有新的人工指令)\n"
        lines = [
            "## 人工指令",
            "以下是用户在控制台任务详情页追加的最新指令。",
            "【最高优先级】除非它与更晚的人工指令冲突，或明显违反当前已写死的安全/目标范围约束，否则你必须优先响应这些指令，再安排其余探索动作：",
        ]
        for item in notes:
            ts = str(item.get("ts") or "").strip()
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            prefix = f"- [{ts}] " if ts else "- "
            lines.append(prefix + text)
        lines.append("")
        return "\n".join(lines)

    def _read_operator_notes(self, *, limit: int = 8) -> list[dict[str, Any]]:
        if not self.operator_inbox_path:
            return []
        path = Path(self.operator_inbox_path)
        if not path.exists():
            return []
        notes: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    notes.append(item)
        except OSError:
            return []
        return notes[-limit:]

    def _prompt_operation_examples(self) -> list[dict[str, Any]]:
        examples = [
            {
                "op": "post_entry",
                "type": "fact|hypothesis|artifact|tool_output|dead_end|next_step|flag_candidate",
                "title": "一行摘要",
                "body": "必要详情,工具输出只放关键片段",
                "confidence": 0.5,
                "refs": ["fact-0001"],
                "tags": ["recon"],
                "entry_id": None,
                "reason": None,
            }
        ]
        if self.tools.can_endorse:
            examples.append(
                {
                    "op": "endorse",
                    "type": None,
                    "title": None,
                    "body": None,
                    "confidence": None,
                    "refs": None,
                    "tags": None,
                    "entry_id": "fact-0001",
                    "reason": None,
                }
            )
        if self.tools.can_challenge:
            examples.append(
                {
                    "op": "challenge",
                    "type": None,
                    "title": None,
                    "body": None,
                    "confidence": None,
                    "refs": None,
                    "tags": None,
                    "entry_id": "hyp-0002",
                    "reason": "复现失败",
                }
            )
        if self.tools.can_claim:
            examples.append(
                {
                    "op": "claim",
                    "type": None,
                    "title": None,
                    "body": None,
                    "confidence": None,
                    "refs": None,
                    "tags": None,
                    "entry_id": "next-0003",
                    "reason": None,
                }
            )
        return examples

    def _render_board_navigator(self, digest, board_files: dict[str, str]) -> str:
        blocks = [
            "## 黑板访问",
            "本轮不要依赖宿主把整块黑板正文灌进 prompt;请先自行查看黑板文件,再按需深读。",
            f"- 桌面简报: {board_files['digest']}",
            f"- 全量快照(JSON): {board_files['entries_json']}",
            f"- 全量详情(Markdown): {board_files['entries_md']}",
        ]
        if board_files.get("events_jsonl"):
            blocks.append(f"- 事件日志(JSONL): {board_files['events_jsonl']}")
        blocks.append("")
        blocks.append(f"当前黑板共 {digest.board_size} 条。")

        def add_lines(title: str, lines) -> None:
            blocks.append(title)
            if not lines:
                blocks.append("(空)")
                return
            for line in lines[:8]:
                blocks.append(f"- [{line.id}] {line.author}: {line.title}")

        add_lines("重点条目(优先自己查看正文)", digest.top_entries)
        add_lines("死路(不要重走,除非有新证据)", digest.dead_ends)
        add_lines("待认领 next_step", digest.open_next_steps)
        return "\n".join(blocks)

    def _render_network_hints(self, digest) -> str:
        text_parts: list[str] = []
        for group in (
            digest.flag_candidates,
            digest.top_entries,
            digest.relevant_entries,
            digest.open_next_steps,
        ):
            for line in group:
                text_parts.append(line.title)
                entry = self.tools.read_entry(line.id)
                if entry is not None:
                    text_parts.append(entry.body)

        urls = self._extract_urls("\n".join(text_parts))
        if not urls:
            return "## 宿主网络预检\n(未发现 URL)"

        blocks = ["## 宿主网络预检"]
        for url in urls[:6]:
            parsed = urlparse(url)
            host = parsed.hostname
            if not host:
                continue
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            ips = self._resolve_host(host, port)
            if ips:
                ip_text = ", ".join(ips)
                blocks.append(
                    "\n".join(
                        [
                            f"- {url}",
                            f"  - 宿主已解析 {host}:{port} -> {ip_text}",
                            f"  - 若沙箱 DNS 失败,用: curl -sS -i --max-time 10 --noproxy '*' --resolve {host}:{port}:{ips[0]} {url}",
                        ]
                    )
                )
            else:
                blocks.append(f"- {url}\n  - 宿主当前也未能解析 {host}:{port}")
        return "\n".join(blocks)

    def _render_target_scope(self) -> str:
        root = None
        for entry in self.tools.board.all():
            if entry.author == "Kay" and "problem" in entry.tags and "root" in entry.tags:
                root = entry
                break

        if root is None:
            return "\n".join(
                [
                    "## 本题目标范围",
                    "- 允许: 题目给定的 URL、附件、题目页面/题目服务直接暴露的资源。",
                    "- 禁止: 宿主机、worker、本机、代理链本地地址，以及仅靠 `Host` 头/本地 vhost 猜测出来的地址。",
                    "",
                ]
            )

        urls: list[str] = []
        attachments: list[str] = []
        hints: list[str] = []
        for raw in root.body.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("URL:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    urls.append(value)
            elif line.startswith("附件:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    attachments.extend([part.strip() for part in value.split(",") if part.strip()])
            elif line.startswith("提示:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    hints.append(value)

        blocks = ["## 本题目标范围"]
        if urls:
            blocks.append("- 明确目标 URL:")
            for url in urls[:6]:
                blocks.append(f"  - {url}")
        if attachments:
            blocks.append("- 明确题目附件:")
            for item in attachments[:12]:
                blocks.append(f"  - {item}")
        if hints:
            blocks.append("- 题面提示:")
            for item in hints[:6]:
                blocks.append(f"  - {item}")
        blocks += [
            "- 允许攻击面: 上述 URL、附件，以及由这些目标页面/目标服务直接返回、直接暴露、直接链接出来的资源。",
            "- 禁止攻击面: 宿主机、worker、本机、代理链本地地址，以及仅靠 `Host` 头改写、`localhost/127.0.0.1`、绝对 URI、本地 vhost 猜测出来的地址。",
            "- 判断原则: 若某个新地址/端口/服务不是题目明确给出的，也不是目标页面直接暴露出来的，就默认不在本题范围内。",
            "",
        ]
        return "\n".join(blocks)

    def _write_board_context_files(self, digest) -> dict[str, str]:
        context_dir = self._board_context_dir()
        context_dir.mkdir(parents=True, exist_ok=True)

        digest_path = context_dir / "board_digest.md"
        digest_path.write_text(digest.render(), encoding="utf-8")

        entries = sorted(self.tools.board.all(), key=lambda e: e.id)
        entries_json_path = context_dir / "board_entries.json"
        entries_json_path.write_text(
            json.dumps([entry.to_dict() for entry in entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        entries_md_path = context_dir / "board_entries.md"
        entries_md_path.write_text(self._render_full_board_details(entries), encoding="utf-8")

        files = {
            "digest": self._display_path_for_prompt(digest_path),
            "entries_json": self._display_path_for_prompt(entries_json_path),
            "entries_md": self._display_path_for_prompt(entries_md_path),
        }

        board_log = getattr(self.tools.board, "_jsonl_path", None)
        if board_log:
            source = Path(board_log)
            if source.exists():
                events_path = context_dir / "board_events.jsonl"
                shutil.copy2(source, events_path)
                files["events_jsonl"] = self._display_path_for_prompt(events_path)
        return files

    def _render_full_board_details(self, entries) -> str:
        blocks = ["# 圆桌黑板全量详情"]
        if not entries:
            blocks.append("(空)")
            return "\n".join(blocks)
        for entry in entries:
            body = entry.body.strip()
            blocks.append(
                "\n".join(
                    [
                        f"## [{entry.id}] {entry.type.value} · {entry.author}",
                        f"title: {entry.title}",
                        f"confidence: {entry.confidence}",
                        f"status: {entry.status.value}",
                        f"claimed_by: {entry.claimed_by or '(none)'}",
                        f"endorsements: {', '.join(entry.endorsements) if entry.endorsements else '(none)'}",
                        f"tags: {', '.join(entry.tags) if entry.tags else '(none)'}",
                        f"refs: {', '.join(entry.refs) if entry.refs else '(none)'}",
                        "body:",
                        body or "(empty)",
                    ]
                )
            )
        return "\n\n".join(blocks)

    async def cycle(self) -> int:
        tmp_parent = self.cwd if self.docker_image and self.cwd else None
        with tempfile.TemporaryDirectory(prefix="roundtable-codex-", dir=tmp_parent) as tmp:
            out_path = Path(tmp) / "last_message.json"
            schema_path = Path(tmp) / "schema.json"
            schema_path.write_text(json.dumps(_OUTPUT_SCHEMA), encoding="utf-8")
            prompt = self._cycle_prompt()
            cmd = self._build_cmd(out_path, schema_path)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_child_env(prompt),
            )
            try:
                stdout, stderr = await proc.communicate(prompt.encode("utf-8"))
            except asyncio.CancelledError:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()
                raise
            if proc.returncode != 0:
                debug_dir = self._write_failure_debug_bundle(
                    prompt=prompt,
                    stdout=stdout.decode("utf-8", "replace"),
                    stderr=stderr.decode("utf-8", "replace"),
                    out_path=out_path,
                    schema_path=schema_path,
                )
                raise RuntimeError(
                    f"Codex CLI failed for {self.name}: "
                    f"debug saved to {debug_dir}\n"
                    f"{stderr.decode('utf-8', 'replace') or stdout.decode('utf-8', 'replace')}"
                )

            raw = out_path.read_text(encoding="utf-8") if out_path.exists() else stdout.decode("utf-8", "replace")
            ops = self._parse_operations(raw)
            n_posts = await self._apply_operations(ops)
            self.note_productive(n_posts)
            return n_posts

    def _build_cmd(self, out_path: Path, schema_path: Path) -> list[str]:
        rendered_out_path = str(out_path)
        rendered_schema_path = str(schema_path)
        extra_mounts: dict[Path, str] = {}
        if self.docker_image and self.cwd:
            cwd_path = Path(self.cwd).resolve()
            rendered_out_path = self._containerize_path(out_path.resolve(), cwd_path, extra_mounts)
            rendered_schema_path = self._containerize_path(schema_path.resolve(), cwd_path, extra_mounts)
        inner_cmd = [
            self.codex_bin,
            "exec",
            "--skip-git-repo-check",
            "--output-last-message",
            rendered_out_path,
            "--output-schema",
            rendered_schema_path,
            "--sandbox",
            "workspace-write" if self.sandbox else "danger-full-access",
        ]
        if self.cwd:
            inner_cmd += ["--cd", self.cwd if not self.docker_image else self._container_workspace()]
        if self.model:
            inner_cmd += ["--model", self.model]
        inner_cmd.append("-")
        if not self.docker_image:
            return inner_cmd
        return self._build_docker_cmd(inner_cmd, extra_mounts)

    def _build_child_env(self, prompt: str) -> dict[str, str]:
        env = os.environ.copy()
        if self._codex_home_dir is not None and not self.docker_image:
            env["CODEX_HOME"] = self._codex_home_dir
        hosts = sorted(self._extract_hosts(prompt))
        if hosts:
            for key in ("NO_PROXY", "no_proxy"):
                current = [x.strip() for x in env.get(key, "").split(",") if x.strip()]
                merged = current + [h for h in hosts if h not in current]
                env[key] = ",".join(merged)
        return env

    def _seed_codex_home(self, codex_home: Path) -> None:
        auth_src = self._default_codex_home() / "auth.json"
        if not auth_src.exists():
            raise FileNotFoundError(f"Codex auth not found: {auth_src}")
        shutil.copy2(auth_src, codex_home / "auth.json")

    def _default_codex_home(self) -> Path:
        raw = os.environ.get("CODEX_HOME")
        if raw:
            return Path(raw)
        return Path.home() / ".codex"

    def _build_docker_cmd(self, inner_cmd: list[str], extra_mounts: dict[Path, str] | None = None) -> list[str]:
        if not self.cwd:
            raise ValueError("docker worker mode requires cwd")
        if not self._docker_container_name:
            raise ValueError("docker worker container is not connected")
        cmd = [
            "docker",
            "exec",
            "-i",
            "-w",
            self._container_workspace(),
        ]
        cmd.append(self._docker_container_name)
        cmd.extend(inner_cmd)
        return cmd

    def _containerize_path(self, path: Path, cwd_path: Path, extra_mounts: dict[Path, str] | None = None) -> str:
        if path.is_relative_to(cwd_path):
            rel = path.relative_to(cwd_path)
            return str(Path(self._container_workspace()) / rel)

        parent = path.parent
        if extra_mounts is None:
            raise ValueError(f"path outside cwd requires extra mount: {path}")
        mount_point = extra_mounts.get(parent)
        if mount_point is None:
            mount_point = f"/roundtable-io/{len(extra_mounts)}"
            extra_mounts[parent] = mount_point
        return str(Path(mount_point) / path.name)

    def _containerize_proxy(self, value: str) -> str:
        parsed = urlparse(value)
        host = parsed.hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return value

        netloc = parsed.netloc
        if "@" in netloc:
            userinfo, _, hostport = netloc.rpartition("@")
            prefix = f"{userinfo}@"
        else:
            prefix = ""
            hostport = netloc

        replacement = hostport.replace(host, "host.docker.internal", 1)
        new_netloc = f"{prefix}{replacement}"
        return parsed._replace(netloc=new_netloc).geturl()

    def _knight_workspace(self) -> Path:
        if not self.cwd:
            raise ValueError("knight workspace requires cwd")
        return Path(self.cwd).resolve()

    def _board_context_dir(self) -> Path:
        if self.cwd:
            return self._shared_docker_root() / ".roundtable"
        return Path(tempfile.gettempdir()) / "roundtable-board-context" / self.name

    def _display_path_for_prompt(self, path: Path) -> str:
        if self.docker_image:
            root = self._shared_docker_root()
            rel = path.resolve().relative_to(root)
            return str(Path("/workspace") / rel)
        return str(path.resolve())

    def _container_workspace(self) -> str:
        rel = self._knight_workspace().resolve().relative_to(self._shared_docker_root())
        return str(Path("/workspace") / rel)

    def _shared_docker_root(self) -> Path:
        workspace = self._knight_workspace().resolve()
        if workspace.parent.name == "knights" and workspace.parent.parent.name == "workspace":
            return workspace.parent.parent.parent
        return workspace.parent

    def _shared_docker_session(self) -> dict[str, Any]:
        if self._docker_session_key is None:
            raise ValueError("docker worker session is not connected")
        return self._shared_docker_sessions[self._docker_session_key]

    def _connect_shared_docker_worker(self) -> None:
        workspace_root = self._shared_docker_root()
        workspace_root.mkdir(parents=True, exist_ok=True)
        self._knight_workspace().mkdir(parents=True, exist_ok=True)
        key = (str(workspace_root), self.docker_image or "", self.docker_platform)
        session = self._shared_docker_sessions.get(key)
        if session is None:
            container_name = f"roundtable-{workspace_root.name}-{abs(hash(key)) & 0xfffffff:x}"
            session = {"name": container_name, "refcount": 0}
            self._start_shared_docker_worker(container_name, workspace_root)
            self._shared_docker_sessions[key] = session
        session["refcount"] += 1
        self._docker_session_key = key
        self._docker_container_name = str(session["name"])

    def _disconnect_shared_docker_worker(self) -> None:
        if self._docker_session_key is None:
            return
        session = self._shared_docker_sessions.get(self._docker_session_key)
        if session is None:
            self._docker_session_key = None
            self._docker_container_name = None
            return
        session["refcount"] -= 1
        if session["refcount"] <= 0:
            subprocess.run(
                ["docker", "rm", "-f", str(session["name"])],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._shared_docker_sessions.pop(self._docker_session_key, None)
        self._docker_session_key = None
        self._docker_container_name = None

    def _start_shared_docker_worker(self, container_name: str, workspace_root: Path) -> None:
        host_codex_home = str(self._default_codex_home().resolve())
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--platform",
            self.docker_platform,
            "--name",
            container_name,
            "--add-host",
            "host.docker.internal:host-gateway",
            "-e",
            "HOST_CODEX_HOME=/host-codex-home",
            "-v",
            f"{workspace_root}:/workspace",
            "-v",
            f"{host_codex_home}:/host-codex-home:ro",
            "-w",
            "/workspace",
        ]
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"):
            value = os.environ.get(key)
            if value:
                cmd += ["-e", f"{key}={self._containerize_proxy(value)}"]
        cmd += [
            self.docker_image or "",
            "bash",
            "-lc",
            "mkdir -p /workspace && while true; do sleep 3600; done",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def _write_failure_debug_bundle(
        self,
        *,
        prompt: str,
        stdout: str,
        stderr: str,
        out_path: Path,
        schema_path: Path,
    ) -> Path:
        base_dir = Path(self.cwd or ".") / ".roundtable_failures"
        base_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        bundle_dir = base_dir / f"{self.name.lower()}-{stamp}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        (bundle_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (bundle_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (bundle_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        if out_path.exists():
            shutil.copy2(out_path, bundle_dir / "last_message.json")
        if schema_path.exists():
            shutil.copy2(schema_path, bundle_dir / "schema.json")
        return bundle_dir

    def _extract_hosts(self, text: str) -> set[str]:
        hosts: set[str] = set()
        for raw in self._extract_urls(text):
            host = urlparse(raw).hostname
            if host:
                hosts.add(host)
        return hosts

    def _extract_urls(self, text: str) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for raw in re.findall(r"https?://[^\s）)\"'<>]+", text):
            url = raw.rstrip(".,;")
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    def _resolve_host(self, host: str, port: int) -> list[str]:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            return []
        hosts: set[str] = set()
        for *_, sockaddr in infos:
            if sockaddr:
                hosts.add(str(sockaddr[0]))
        return sorted(hosts)

    def _parse_operations(self, raw: str) -> list[dict[str, Any]]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group(0))
        if isinstance(data, list):
            return data
        ops = data.get("operations", [])
        return ops if isinstance(ops, list) else []

    async def _apply_operations(self, ops: list[dict[str, Any]]) -> int:
        n_posts = 0
        for op in ops:
            kind = op.get("op")
            if kind == "post_entry":
                try:
                    confidence = float(op.get("confidence", 0.5))
                except (TypeError, ValueError):
                    confidence = 0.5
                confidence = max(0.0, min(1.0, confidence))
                await self.tools.post_entry(
                    type=op.get("type", EntryType.FACT.value),
                    title=str(op.get("title", "")).strip()[:240] or "(untitled)",
                    body=str(op.get("body", "")),
                    confidence=confidence,
                    refs=self._string_list(op.get("refs")),
                    tags=self._string_list(op.get("tags")),
                )
                n_posts += 1
            elif kind == "endorse" and op.get("entry_id"):
                await self.tools.endorse(str(op["entry_id"]))
            elif kind == "challenge" and op.get("entry_id") and op.get("reason"):
                await self.tools.challenge(str(op["entry_id"]), str(op["reason"]))
            elif kind == "claim" and op.get("entry_id"):
                await self.tools.claim(str(op["entry_id"]))
        return n_posts

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(x) for x in value]
