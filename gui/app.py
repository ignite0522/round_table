from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, abort, jsonify, redirect, render_template_string, request, url_for
from werkzeug.utils import secure_filename

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from roundtable.benchmark import BenchmarkAPIError, BenchmarkClient, ChallengeInfo, load_benchmark_config


GUI_RUNS_ROOT = REPO_ROOT / "round_table_work" / "gui-runs"
DEFAULT_DOCKER_IMAGE = None
LOG_TAIL_BYTES = 48_000
MAX_RUNNING_TASKS = 3
BENCHMARK_MAX_ACTIVE_INSTANCES = 3
QUEUE_POLL_SECONDS = 3.0
OPERATOR_INBOX_FILENAME = "_operator_inbox.jsonl"

_scheduler_lock = threading.Lock()
_scheduler_started = False
_history_backfilled = False

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024


@dataclass
class RunRecord:
    run_id: str
    launch_dir: Path
    workdir: Path
    log_path: Path
    board_path: Path
    attachments_dir: Path
    command: list[str]
    title: str
    url: str
    statement: str
    hints: list[str] = field(default_factory=list)
    attachment_names: list[str] = field(default_factory=list)
    docker_image: str | None = None
    benchmark_unique_code: str | None = None
    benchmark_base_url: str | None = None
    launch_state: str = "running"
    queue_rank: float | None = None
    queue_priority: bool = False
    solved: bool | None = None
    final_flag: str | None = None
    finished_at: float | None = None
    created_at: float = field(default_factory=time.time)
    pid: int | None = None
    pgid: int | None = None

    def status(self) -> str:
        if self.launch_state == "queued":
            return "queued"
        target = self.pgid or self.pid
        if target is None:
            return "exited"
        try:
            if self.pgid is not None:
                os.killpg(self.pgid, 0)
            else:
                os.kill(self.pid, 0)
        except OSError:
            return "exited"
        return "running"

    @property
    def operator_inbox_path(self) -> Path:
        return self.workdir / OPERATOR_INBOX_FILENAME

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "launch_dir": str(self.launch_dir),
            "workdir": str(self.workdir),
            "log_path": str(self.log_path),
            "board_path": str(self.board_path),
            "attachments_dir": str(self.attachments_dir),
            "command": self.command,
            "title": self.title,
            "url": self.url,
            "statement": self.statement,
            "hints": self.hints,
            "attachment_names": self.attachment_names,
            "docker_image": self.docker_image,
            "benchmark_unique_code": self.benchmark_unique_code,
            "benchmark_base_url": self.benchmark_base_url,
            "launch_state": self.launch_state,
            "queue_rank": self.queue_rank,
            "queue_priority": self.queue_priority,
            "solved": self.solved,
            "final_flag": self.final_flag,
            "finished_at": self.finished_at,
            "created_at": self.created_at,
            "pid": self.pid,
            "pgid": self.pgid,
        }

    @classmethod
    def from_path(cls, meta_path: Path) -> "RunRecord":
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return cls(
            run_id=data["run_id"],
            launch_dir=Path(data["launch_dir"]),
            workdir=Path(data["workdir"]),
            log_path=Path(data["log_path"]),
            board_path=Path(data["board_path"]),
            attachments_dir=Path(data["attachments_dir"]),
            command=list(data["command"]),
            title=data.get("title", ""),
            url=data.get("url", ""),
            statement=data.get("statement", ""),
            hints=list(data.get("hints", [])),
            attachment_names=list(data.get("attachment_names", [])),
            docker_image=data.get("docker_image"),
            benchmark_unique_code=data.get("benchmark_unique_code"),
            benchmark_base_url=data.get("benchmark_base_url"),
            launch_state=data.get("launch_state", "running"),
            queue_rank=data.get("queue_rank"),
            queue_priority=bool(data.get("queue_priority", False)),
            solved=data.get("solved"),
            final_flag=data.get("final_flag"),
            finished_at=data.get("finished_at"),
            created_at=float(data.get("created_at", time.time())),
            pid=data.get("pid"),
            pgid=data.get("pgid"),
        )


INDEX_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>圆桌骑士</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1020;
      --panel: #12192d;
      --panel-2: #18213a;
      --line: #2a3556;
      --text: #e7ebf7;
      --muted: #9eabc9;
      --accent: #5ac8fa;
      --accent-2: #9b8cff;
      --good: #4fd1a5;
      --warn: #f6c760;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        linear-gradient(180deg, rgba(6, 10, 20, 0.38) 0%, rgba(8, 12, 24, 0.56) 100%),
        url('/static/backgrounds/roundtable-bg.png') center top / cover fixed no-repeat;
      color: var(--text);
      min-height: 100vh;
    }
    main {
      max-width: 1320px;
      margin: 0 auto;
      min-height: 100vh;
      padding: 28px 24px 48px;
    }
    .stack {
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
      gap: 20px;
    }
    section {
      background: rgba(11, 16, 29, 0.44);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      backdrop-filter: blur(8px);
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.18);
    }
    section h2 {
      margin: 0 0 14px;
      font-size: 16px;
      font-weight: 700;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 20px;
    }
    .topbar h1 {
      margin: 0;
      font-size: 28px;
    }
    .topbar p {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.5;
      max-width: 880px;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .field.full {
      grid-column: 1 / -1;
    }
    label {
      font-size: 13px;
      color: var(--muted);
    }
    input[type="text"],
    textarea {
      width: 100%;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 12px 13px;
      font: inherit;
      resize: vertical;
    }
    textarea {
      min-height: 120px;
    }
    input[type="file"] {
      color: var(--muted);
      font: inherit;
    }
    .inline {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .inline input[type="checkbox"] {
      width: 16px;
      height: 16px;
    }
    .hint {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
    }
    .actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }
    button {
      border: 0;
      border-radius: 8px;
      padding: 11px 16px;
      font: inherit;
      font-weight: 600;
      color: #08101f;
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%);
      cursor: pointer;
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .error {
      margin-bottom: 14px;
      padding: 12px 13px;
      border-radius: 8px;
      background: rgba(180, 58, 76, 0.18);
      border: 1px solid rgba(240, 107, 127, 0.4);
      color: #ffd3db;
      line-height: 1.5;
    }
    .flash {
      margin-bottom: 14px;
      padding: 12px 13px;
      border-radius: 8px;
      background: rgba(90, 200, 250, 0.12);
      border: 1px solid rgba(90, 200, 250, 0.28);
      color: #d1f3ff;
      line-height: 1.5;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }
    .summary-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: rgba(18, 27, 46, 0.3);
    }
    .summary-card .label {
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .summary-card .value {
      font-size: 22px;
      font-weight: 700;
    }
    .summary-card .sub {
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }
    .runs {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .run-item {
      display: flex;
      align-items: stretch;
      gap: 10px;
      width: 100%;
    }
    .run-link {
      display: block;
      flex: 1;
      text-decoration: none;
      color: inherit;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(18, 27, 46, 0.38);
    }
    .run-link:hover {
      border-color: #45588f;
    }
    .delete-form {
      display: flex;
      align-items: stretch;
      margin: 0;
    }
    .delete-btn {
      min-width: 52px;
      padding: 0 10px;
      border: 1px solid rgba(240, 107, 127, 0.38);
      border-radius: 8px;
      background: rgba(120, 22, 40, 0.36);
      color: #ffd6dc;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .delete-btn:hover {
      background: rgba(140, 29, 50, 0.5);
    }
    .run-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
      font-size: 13px;
      color: var(--muted);
    }
    .status {
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .status.running { background: rgba(79, 209, 165, 0.16); color: #8af0cb; }
    .status.exited { background: rgba(246, 199, 96, 0.18); color: #ffe39a; }
    .status.queued { background: rgba(155, 140, 255, 0.16); color: #c9beff; }
    .status.idle { background: rgba(90, 200, 250, 0.16); color: #a9ebff; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      color: var(--muted);
      word-break: break-all;
    }
    .ghost-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 8px 12px;
      border: 1px solid rgba(100, 210, 255, 0.26);
      border-radius: 8px;
      background: rgba(14, 21, 38, 0.44);
      color: #a9ddff;
      font: inherit;
      font-size: 13px;
      cursor: pointer;
      text-decoration: none;
    }
    .ghost-btn:hover {
      background: rgba(18, 28, 50, 0.62);
    }
    .stop-btn {
      min-width: 52px;
      padding: 0 10px;
      border: 1px solid rgba(246, 199, 96, 0.34);
      border-radius: 8px;
      background: rgba(120, 86, 22, 0.36);
      color: #ffe39a;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .stop-btn:hover {
      background: rgba(149, 104, 24, 0.48);
    }
    .priority-btn {
      min-width: 52px;
      padding: 0 10px;
      border: 1px solid rgba(79, 209, 165, 0.38);
      border-radius: 8px;
      background: rgba(22, 92, 72, 0.4);
      color: #b8f5dd;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .priority-btn:hover {
      background: rgba(27, 122, 95, 0.54);
    }
    .priority-btn.active {
      border-color: rgba(168, 139, 250, 0.42);
      background: rgba(88, 63, 139, 0.42);
      color: #eadcff;
    }
    .priority-btn.active:hover {
      background: rgba(109, 79, 170, 0.56);
    }
    .challenge-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    .challenge-table th,
    .challenge-table td {
      padding: 11px 10px;
      border-bottom: 1px solid rgba(42, 53, 86, 0.72);
      text-align: left;
      vertical-align: top;
    }
    .challenge-table th {
      color: var(--muted);
      font-weight: 600;
      font-size: 12px;
    }
    .challenge-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .challenge-code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      color: #c9d4ef;
    }
    .challenge-desc {
      color: var(--muted);
      line-height: 1.5;
      max-width: 560px;
    }
    .muted {
      color: var(--muted);
    }
    @media (max-width: 980px) {
      .grid { grid-template-columns: 1fr; }
      .form-grid { grid-template-columns: 1fr; }
      .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .topbar { flex-direction: column; }
    }
  </style>
</head>
<body>
  <main>
    <div class="stack">
      <section>
        <div class="topbar">
          <div>
            <h1>圆桌骑士</h1>
            <p>第一页就是总控台。题目一旦进入队列，后台会尽量始终维持 {{ max_running_tasks }} 道题同时在解；你仍然可以随时手动停止、取消排队、重跑或单独启动。</p>
          </div>
          <div class="top-actions">
            <a class="ghost-btn" href="{{ url_for('index') }}">刷新列表</a>
            {% if benchmark_enabled and challenges %}
            <form action="{{ url_for('enqueue_all_benchmarks') }}" method="post">
              <button type="submit">题库全部入队</button>
            </form>
            {% endif %}
          </div>
        </div>
        {% if flash %}
        <div class="flash">{{ flash }}</div>
        {% endif %}
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <div class="summary-grid">
          <div class="summary-card">
            <div class="label">运行中任务</div>
            <div class="value">{{ running_count }}/{{ max_running_tasks }}</div>
            <div class="sub">最多并发 {{ max_running_tasks }} 道；多出来的会自动排队。</div>
          </div>
          <div class="summary-card">
            <div class="label">排队中任务</div>
            <div class="value">{{ queued_count }}</div>
            <div class="sub">空出名额后会自动开跑，不需要再点一次。</div>
          </div>
          <div class="summary-card">
            <div class="label">Benchmark 配置</div>
            <div class="value">{{ "已连接" if benchmark_enabled else "未配置" }}</div>
            <div class="sub">{{ benchmark_base_url or "需要 BENCHMARK_BASE_URL 和 BENCHMARK_TOKEN" }}</div>
          </div>
          <div class="summary-card">
            <div class="label">可见题目数</div>
            <div class="value">{{ challenges|length if benchmark_enabled and not benchmark_error else 0 }}</div>
            <div class="sub">{{ benchmark_error or ("最近任务 " ~ runs|length ~ " 个。") }}</div>
          </div>
        </div>
      </section>

      <div class="grid">
        <section>
          <h2>新建任务</h2>
          <form action="{{ url_for('launch_run') }}" method="post" enctype="multipart/form-data">
            <div class="form-grid">
              <div class="field">
                <label for="title">题目标题</label>
                <input id="title" type="text" name="title" placeholder="留空则从 URL 推断" value="{{ form.title }}">
              </div>
              <div class="field">
                <label for="url">题目 URL</label>
                <input id="url" type="text" name="url" placeholder="可留空，如逆向题/附件题" value="{{ form.url }}">
              </div>
              <div class="field full">
                <label for="statement">题目描述</label>
                <textarea id="statement" name="statement" placeholder="比如：登录页 + 一份附件，目标是拿到 flag。">{{ form.statement }}</textarea>
              </div>
              <div class="field full">
                <label for="attachments">附件</label>
                <input id="attachments" type="file" name="attachments" multiple>
              </div>
            </div>
            <div class="actions">
              <button type="submit">{{ "加入队列" if running_count >= max_running_tasks else "启动圆桌" }}</button>
              <div class="hint">自定义题和本地附件题从这里进。后台会持续补位，尽量保持两题并行。</div>
            </div>
          </form>
        </section>

        <section>
          <h2>任务总控</h2>
          <div class="runs">
            {% if benchmark_enabled %}
              <div class="hint">批量解题模式下，这里保持留白。</div>
            {% elif runs %}
              {% for run in runs %}
              <div class="run-item">
                <a class="run-link" href="{{ url_for('view_run', run_id=run.run_id) }}">
                  <div class="run-meta">
                    <span>{{ run.title or run.benchmark_unique_code or run.url or run.run_id }}</span>
                    <span class="status {{ run.status() }}">{{ run.status() }}</span>
                  </div>
                  {% if run.benchmark_unique_code %}
                  <div class="challenge-code">{{ run.benchmark_unique_code }}</div>
                  {% endif %}
                </a>
                {% if run.status() in ["running", "queued"] %}
                {% if run.status() == "queued" %}
                <form class="delete-form" action="{{ url_for('prioritize_run', run_id=run.run_id) }}" method="post">
                  <button class="priority-btn {{ 'active' if run.queue_priority else '' }}" type="submit">{{ "取消置顶" if run.queue_priority else "置顶" }}</button>
                </form>
                {% endif %}
                <form class="delete-form" action="{{ url_for('stop_run_route', run_id=run.run_id) }}" method="post">
                  <button class="stop-btn" type="submit">{{ "停止" if run.status() == "running" else "取消" }}</button>
                </form>
                {% endif %}
                <form class="delete-form" action="{{ url_for('delete_run', run_id=run.run_id) }}" method="post">
                  <button class="delete-btn" type="submit">删除</button>
                </form>
              </div>
              {% endfor %}
            {% else %}
              <div class="hint">还没有任务。可以从题库直接启动，也可以手动新建。</div>
            {% endif %}
          </div>
        </section>
      </div>

      <section>
        <h2>题库列表</h2>
        {% if not benchmark_enabled %}
          <div class="hint">当前没有可用 benchmark 配置，所以这里只显示空状态。把 `BENCHMARK_BASE_URL` 和 `BENCHMARK_TOKEN` 带着 GUI 一起启动后，这里会直接列出所有题目。</div>
        {% elif benchmark_error %}
          <div class="error">{{ benchmark_error }}</div>
        {% elif challenges %}
          <table class="challenge-table">
            <thead>
              <tr>
                <th>题目</th>
                <th>描述</th>
                <th>难度</th>
                <th>平台已完成</th>
                <th>本地已解</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {% for item in challenges %}
              {% set active_run = challenge_runs.get(item.unique_code) %}
              {% set solved_run = solved_runs.get(item.unique_code) %}
              <tr>
                <td>
                  <div class="challenge-code">{{ item.unique_code }}</div>
                  <div class="muted">level {{ item.level if item.level is not none else "-" }} / {{ item.total_score if item.total_score is not none else "-" }} 分</div>
                </td>
                <td class="challenge-desc">{{ item.description or "（无描述）" }}</td>
                <td>{{ item.difficulty or "-" }}</td>
                <td>
                  {% if item.is_completed %}
                    <span class="status running">completed</span>
                  {% else %}
                    <span class="status exited">pending</span>
                  {% endif %}
                </td>
                <td>
                  {% if item.unique_code in solved_codes %}
                    <span class="status running">solved</span>
                  {% elif active_run %}
                    <span class="status {{ active_run.status() }}">{{ active_run.status() }}</span>
                  {% else %}
                    <span class="status idle">idle</span>
                  {% endif %}
                </td>
                <td>
                  <div class="challenge-actions">
                    {% if item.unique_code in solved_codes %}
                      {% if solved_run %}
                        <a class="ghost-btn" href="{{ url_for('view_run', run_id=solved_run.run_id) }}">打开</a>
                      {% endif %}
                      <span class="hint">本地已解</span>
                    {% elif active_run %}
                      <a class="ghost-btn" href="{{ url_for('view_run', run_id=active_run.run_id) }}">打开</a>
                      {% if active_run.status() == "running" %}
                      <form action="{{ url_for('stop_run_route', run_id=active_run.run_id) }}" method="post">
                        <button class="stop-btn" type="submit">停止</button>
                      </form>
                      {% elif active_run.status() == "queued" %}
                      <form action="{{ url_for('prioritize_run', run_id=active_run.run_id) }}" method="post">
                        <button class="priority-btn {{ 'active' if active_run.queue_priority else '' }}" type="submit">{{ "取消置顶" if active_run.queue_priority else "置顶排队" }}</button>
                      </form>
                      <form action="{{ url_for('stop_run_route', run_id=active_run.run_id) }}" method="post">
                        <button class="stop-btn" type="submit">取消排队</button>
                      </form>
                      {% else %}
                      <form action="{{ url_for('launch_benchmark_run', unique_code=item.unique_code) }}" method="post">
                        <button type="submit">{{ "加入队列" if running_count >= max_running_tasks else "重跑" }}</button>
                      </form>
                      {% endif %}
                    {% else %}
                      <form action="{{ url_for('launch_benchmark_run', unique_code=item.unique_code) }}" method="post">
                        <button type="submit">{{ "加入队列" if running_count >= max_running_tasks else "启动" }}</button>
                      </form>
                    {% endif %}
                  </div>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        {% else %}
          <div class="hint">题库返回为空。</div>
        {% endif %}
      </section>
    </div>
  </main>
</body>
</html>
"""


RUN_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ run.title or run.url or run.run_id }}</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #09101e;
      --panel: #12192d;
      --panel-2: #17213b;
      --line: #293657;
      --text: #ecf1fb;
      --muted: #9da9c4;
      --accent: #64d2ff;
      --good: #52d4ad;
      --warn: #f5c266;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        linear-gradient(180deg, rgba(6, 10, 20, 0.4) 0%, rgba(8, 12, 24, 0.58) 100%),
        url('/static/backgrounds/roundtable-bg.png') center top / cover fixed no-repeat;
      color: var(--text);
      min-height: 100vh;
    }
    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px 24px 112px;
    }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 20px;
      margin-bottom: 22px;
    }
    .toolbar a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .toolbar-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .title h1 {
      margin: 0;
      font-size: 26px;
      text-shadow: 0 2px 18px rgba(0, 0, 0, 0.45);
    }
    .title p {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.5;
      max-width: 720px;
    }
    .status {
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      margin-left: 10px;
    }
    .status.running { background: rgba(82, 212, 173, 0.15); color: #90f0cf; }
    .status.exited { background: rgba(245, 194, 102, 0.16); color: #ffe099; }
    .status.queued { background: rgba(155, 140, 255, 0.16); color: #d3c9ff; }
    .note-form {
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }
    .note-form textarea {
      width: 100%;
      min-height: 110px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 12px 13px;
      font: inherit;
      resize: vertical;
    }
    .note-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 12px;
    }
    .note-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: rgba(18, 27, 46, 0.28);
    }
    .note-time {
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .delete-btn {
      min-width: 64px;
      padding: 8px 12px;
      border: 1px solid rgba(240, 107, 127, 0.38);
      border-radius: 8px;
      background: rgba(120, 22, 40, 0.36);
      color: #ffd6dc;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .delete-btn:hover {
      background: rgba(140, 29, 50, 0.5);
    }
    .layout {
      display: grid;
      grid-template-columns: 380px minmax(0, 1fr);
      gap: 20px;
    }
    section {
      background: rgba(11, 16, 29, 0.44);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      backdrop-filter: blur(8px);
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.18);
    }
    section h2 {
      margin: 0 0 14px;
      font-size: 16px;
    }
    .meta-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .meta-item label {
      display: block;
      margin-bottom: 5px;
      font-size: 12px;
      color: var(--muted);
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      word-break: break-all;
      color: var(--text);
    }
    .hint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }
    .pill {
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      background: rgba(100, 210, 255, 0.12);
      color: #99e5ff;
      margin-right: 6px;
      margin-bottom: 6px;
      font-size: 12px;
    }
    pre {
      margin: 0;
      border-radius: 8px;
      background: #0b1222;
      border: 1px solid #22304d;
      padding: 14px;
      color: #d8e1f5;
      white-space: pre-wrap;
      word-break: break-word;
      min-height: 540px;
      max-height: 78vh;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
    }
    .toolbar-buttons {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .ghost-btn {
      padding: 8px 12px;
      border: 1px solid rgba(100, 210, 255, 0.28);
      border-radius: 8px;
      background: rgba(14, 21, 38, 0.44);
      color: #a9ddff;
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }
    .ghost-btn:hover {
      background: rgba(18, 28, 50, 0.62);
    }
    .brand-footer {
      display: none;
    }
    @media (max-width: 980px) {
      .layout { grid-template-columns: 1fr; }
      .toolbar { flex-direction: column; }
    }
  </style>
</head>
<body>
  <main>
    <div class="toolbar">
      <div class="title">
        <a href="{{ url_for('index') }}">返回控制台</a>
        <h1>{{ run.title or run.url or run.run_id }} <span class="status {{ run.status() }}">{{ run.status() }}</span></h1>
        <p>{{ run.statement or "未填写题目描述。" }}</p>
      </div>
      <div class="toolbar-actions">
        <div class="toolbar-buttons">
          <button class="ghost-btn" type="button" id="toggle-refresh">自动刷新: 开</button>
          <button class="ghost-btn" type="button" id="refresh-now">立即刷新</button>
          {% if run.status() in ["running", "queued"] %}
          <form action="{{ url_for('stop_run_route', run_id=run.run_id) }}" method="post">
            <button class="ghost-btn" type="submit">{{ "停止任务" if run.status() == "running" else "取消排队" }}</button>
          </form>
          {% endif %}
          <form action="{{ url_for('delete_run', run_id=run.run_id) }}" method="post">
            <button class="delete-btn" type="submit">删除任务</button>
          </form>
        </div>
      </div>
    </div>

    <div class="layout">
      <section>
        <h2>任务信息</h2>
        <div class="meta-list">
          <div class="meta-item">
            <label>URL</label>
            <div class="mono">{{ run.url or "(未填写)" }}</div>
          </div>
          <div class="meta-item">
            <label>工作目录</label>
            <div class="mono">{{ run.workdir }}</div>
          </div>
          <div class="meta-item">
            <label>日志文件</label>
            <div class="mono">{{ run.log_path }}</div>
          </div>
          <div class="meta-item">
            <label>黑板文件</label>
            <div class="mono">{{ run.board_path }}</div>
          </div>
          <div class="meta-item">
            <label>附件目录</label>
            <div class="mono">{{ run.attachments_dir }}</div>
          </div>
          <div class="meta-item">
            <label>Docker Worker</label>
            <div class="mono">{{ run.docker_image or "(未启用)" }}</div>
          </div>
          <div class="meta-item">
            <label>附件</label>
            {% if run.attachment_names %}
              <div>{% for name in run.attachment_names %}<span class="pill">{{ name }}</span>{% endfor %}</div>
            {% else %}
              <div class="hint">(无)</div>
            {% endif %}
          </div>
          <div class="meta-item">
            <label>启动命令</label>
            <div class="mono">{{ command_text }}</div>
          </div>
          <div class="meta-item">
            <label>人工指令收件箱</label>
            <div class="mono">{{ operator_inbox_path }}</div>
          </div>
        </div>

        <div class="note-form">
          <h2>追加人工指令</h2>
          {% if run.status() == "running" %}
          <div class="hint">这里写下的新指令具有最高优先级。骑士会在下一轮 cycle 读取它。</div>
          {% elif run.status() == "queued" %}
          <div class="hint">任务还在排队。现在写下的指令会被保存，等任务开跑后第一时间读到。</div>
          {% else %}
          <div class="hint">任务已经结束，仍可留存备注，但不会再被执行。</div>
          {% endif %}
          <form action="{{ url_for('post_run_note', run_id=run.run_id) }}" method="post">
            <textarea name="note_text" placeholder="例如：优先测附件里的 redis 凭据，不要再花轮次扫 web；如果拿到 admin，立刻提交 flag。"></textarea>
            <div class="actions">
              <button type="submit">发送指令</button>
            </div>
          </form>
          <div class="note-list">
            {% if operator_notes %}
              {% for item in operator_notes|reverse %}
              <div class="note-item">
                <div class="note-time">{{ item.ts }}</div>
                <div>{{ item.text }}</div>
              </div>
              {% endfor %}
            {% else %}
              <div class="hint">还没有追加过人工指令。</div>
            {% endif %}
          </div>
        </div>
      </section>

      <section>
        <h2>实时日志</h2>
        <pre id="log-view">{{ log_text }}</pre>
      </section>
    </div>
  </main>
  <script>
    (() => {
      const runId = {{ run.run_id|tojson }};
      const logView = document.getElementById("log-view");
      const toggleBtn = document.getElementById("toggle-refresh");
      const refreshBtn = document.getElementById("refresh-now");
      const statusNodes = Array.from(document.querySelectorAll(".status"));
      let autoRefresh = true;
      let timer = null;

      function setAutoRefreshLabel() {
        toggleBtn.textContent = autoRefresh ? "自动刷新: 开" : "自动刷新: 关";
      }

      async function refreshLog() {
        try {
          const wasNearBottom = (logView.scrollHeight - logView.scrollTop - logView.clientHeight) < 24;
          const res = await fetch(`/runs/${runId}/log`, { cache: "no-store" });
          if (!res.ok) return;
          const data = await res.json();
          logView.textContent = data.log_text;
          if (wasNearBottom) {
            logView.scrollTop = logView.scrollHeight;
          }
          statusNodes.forEach((node) => {
            node.textContent = data.status;
            node.classList.remove("running", "exited", "queued", "unknown");
            node.classList.add(data.status);
          });
        } catch (_) {
        }
      }

      function schedule() {
        clearInterval(timer);
        if (autoRefresh) {
          timer = setInterval(refreshLog, 4000);
        }
      }

      toggleBtn.addEventListener("click", () => {
        autoRefresh = !autoRefresh;
        setAutoRefreshLabel();
        schedule();
      });

      refreshBtn.addEventListener("click", () => {
        refreshLog();
      });

      setAutoRefreshLabel();
      schedule();
    })();
  </script>
</body>
</html>
"""


def ensure_runs_root() -> None:
    GUI_RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def list_runs() -> list[RunRecord]:
    ensure_runs_root()
    runs: list[RunRecord] = []
    for meta_path in sorted(GUI_RUNS_ROOT.glob("run-*/task.json"), reverse=True):
        try:
            runs.append(refresh_record_cache(RunRecord.from_path(meta_path)))
        except Exception:
            continue
    runs.sort(key=lambda item: item.created_at, reverse=True)
    return runs


def running_runs(runs: list[RunRecord] | None = None) -> list[RunRecord]:
    items = runs if runs is not None else list_runs()
    return [run for run in items if run.status() == "running"]


def queued_runs(runs: list[RunRecord] | None = None) -> list[RunRecord]:
    items = runs if runs is not None else list_runs()
    return [run for run in items if run.status() == "queued"]


def running_benchmark_runs(runs: list[RunRecord] | None = None) -> list[RunRecord]:
    items = runs if runs is not None else list_runs()
    return [run for run in items if run.status() == "running" and bool(run.benchmark_unique_code)]


def queue_sort_key(run: RunRecord) -> tuple[float, float]:
    if run.queue_priority:
        return (-1.0, run.created_at)
    rank = run.queue_rank if run.queue_rank is not None else run.created_at
    return (rank, run.created_at)


def benchmark_client_from_env() -> BenchmarkClient | None:
    base_url, token = load_benchmark_config()
    if not base_url or not token:
        return None
    return BenchmarkClient(base_url=base_url, token=token)


def list_benchmark_challenges() -> tuple[list[ChallengeInfo], str | None, str | None]:
    base_url, token = load_benchmark_config()
    if not base_url or not token:
        return [], None, None
    try:
        client = BenchmarkClient(base_url=base_url, token=token)
        return client.list_challenges(), None, base_url
    except BenchmarkAPIError as e:
        return [], str(e), base_url


def latest_run_by_challenge(runs: list[RunRecord]) -> dict[str, RunRecord]:
    mapping: dict[str, RunRecord] = {}
    for run in runs:
        if not run.benchmark_unique_code:
            continue
        current = mapping.get(run.benchmark_unique_code)
        if current is None or run.created_at > current.created_at:
            mapping[run.benchmark_unique_code] = run
    return mapping


def latest_solved_run_by_challenge(runs: list[RunRecord]) -> dict[str, RunRecord]:
    mapping: dict[str, RunRecord] = {}
    for run in runs:
        if not run.benchmark_unique_code or not run.solved:
            continue
        current = mapping.get(run.benchmark_unique_code)
        if current is None or run.created_at > current.created_at:
            mapping[run.benchmark_unique_code] = run
    return mapping


def locally_solved_benchmark_codes(runs: list[RunRecord] | None = None) -> set[str]:
    items = runs if runs is not None else list_runs()
    solved: set[str] = set()
    for run in items:
        if run.benchmark_unique_code and run.solved:
            solved.add(run.benchmark_unique_code)
    return solved


def read_log_tail(path: Path) -> str:
    if not path.exists():
        return "(日志文件还没生成)"
    raw = path.read_bytes()[-LOG_TAIL_BYTES:]
    return raw.decode("utf-8", "replace")


def infer_result_from_log(log_path: Path) -> tuple[bool | None, str | None]:
    if not log_path.exists():
        return None, None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    solved_match = re.search(r"结果:\s*✔\s*解出\s*flag:\s*(.+)", text)
    if solved_match:
        flag = solved_match.group(1).strip()
        return True, None if flag == "None" else flag
    failed_match = re.search(r"结果:\s*✘\s*未解出\s*flag:\s*(.+)", text)
    if failed_match:
        flag = failed_match.group(1).strip()
        return False, None if flag == "None" else flag
    return None, None


def refresh_record_cache(record: RunRecord) -> RunRecord:
    changed = False
    status = record.status()
    if status == "running":
        return record
    if status == "queued":
        return record
    if record.finished_at is None and record.log_path.exists():
        try:
            record.finished_at = record.log_path.stat().st_mtime
            changed = True
        except OSError:
            pass
    if record.solved is None or (record.solved and not record.final_flag):
        solved, flag = infer_result_from_log(record.log_path)
        if solved is not None and record.solved != solved:
            record.solved = solved
            changed = True
        if flag and record.final_flag != flag:
            record.final_flag = flag
            changed = True
    if changed:
        write_task_meta(record)
    return record


def backfill_all_runs_cache() -> int:
    ensure_runs_root()
    updated = 0
    for meta_path in sorted(GUI_RUNS_ROOT.glob("run-*/task.json")):
        try:
            record = RunRecord.from_path(meta_path)
            before = (
                record.solved,
                record.final_flag,
                record.finished_at,
                record.launch_state,
            )
            record = refresh_record_cache(record)
            after = (
                record.solved,
                record.final_flag,
                record.finished_at,
                record.launch_state,
            )
            if after != before:
                updated += 1
        except Exception:
            continue
    return updated


def ensure_history_backfilled() -> None:
    global _history_backfilled
    if _history_backfilled:
        return
    backfill_all_runs_cache()
    _history_backfilled = True


def write_task_meta(record: RunRecord) -> None:
    record.launch_dir.mkdir(parents=True, exist_ok=True)
    (record.launch_dir / "task.json").write_text(
        json.dumps(record.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_run(run_id: str) -> RunRecord:
    meta_path = GUI_RUNS_ROOT / run_id / "task.json"
    if not meta_path.exists():
        abort(404)
    return refresh_record_cache(RunRecord.from_path(meta_path))


def _signal_run(record: RunRecord, sig: int) -> None:
    try:
        if record.pgid is not None:
            os.killpg(record.pgid, sig)
        elif record.pid is not None:
            os.kill(record.pid, sig)
    except OSError:
        pass


def stop_run(record: RunRecord, timeout: float = 3.0) -> None:
    if record.status() == "queued":
        record.launch_state = "exited"
        record.pid = None
        record.pgid = None
        return
    if record.status() != "running":
        return
    _signal_run(record, signal.SIGTERM)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if record.status() != "running":
            record.launch_state = "exited"
            return
        time.sleep(0.15)
    _signal_run(record, signal.SIGKILL)
    deadline = time.time() + 1.5
    while time.time() < deadline:
        if record.status() != "running":
            record.launch_state = "exited"
            return
        time.sleep(0.1)
    record.launch_state = "exited"


def close_benchmark_if_needed(record: RunRecord) -> str | None:
    if not record.benchmark_unique_code:
        return None
    if record.launch_state == "queued" and record.pid is None:
        return None
    client = benchmark_client_from_env()
    if client is None:
        return "benchmark 未配置，未执行远端 close"
    try:
        closed = client.close_challenge(record.benchmark_unique_code)
    except BenchmarkAPIError as e:
        return f"远端 close 失败: {e}"
    return "远端题目已关闭" if closed else "远端题目未确认关闭"


def delete_run_files(record: RunRecord) -> None:
    if record.launch_dir.exists():
        shutil.rmtree(record.launch_dir, ignore_errors=True)


def build_form_defaults() -> dict[str, Any]:
    return {
        "url": request.form.get("url", "").strip(),
        "title": request.form.get("title", "").strip(),
        "statement": request.form.get("statement", "").strip(),
    }


def read_operator_notes(record: RunRecord) -> list[dict[str, str]]:
    path = record.operator_inbox_path
    if not path.exists():
        return []
    notes: list[dict[str, str]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            notes.append(
                {
                    "ts": str(item.get("ts") or ""),
                    "text": str(item.get("text") or ""),
                }
            )
    except OSError:
        return []
    return notes[-12:]


def append_operator_note(record: RunRecord, text: str) -> None:
    payload = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "text": text.strip(),
    }
    record.operator_inbox_path.parent.mkdir(parents=True, exist_ok=True)
    with record.operator_inbox_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def start_record(record: RunRecord) -> RunRecord:
    proc = spawn_run(record.command, record.log_path, append=True)
    record.pid = proc.pid
    record.pgid = proc.pid
    record.launch_state = "running"
    record.queue_rank = None
    record.queue_priority = False
    write_task_meta(record)
    return record


def ensure_scheduler_started() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        thread = threading.Thread(target=_queue_scheduler_loop, name="roundtable-gui-queue", daemon=True)
        thread.start()
        _scheduler_started = True


def create_benchmark_record(unique_code: str, challenge: ChallengeInfo, client: BenchmarkClient) -> RunRecord:
    run_id = f"run-{uuid4().hex[:10]}"
    launch_dir, attachments_dir, log_path, workdir = create_run_dirs(run_id)
    board_path = workdir / "_board.jsonl"
    cmd = [
        sys.executable,
        "-m",
        "examples.run_ctf",
        "--cwd",
        str(workdir),
        "--resume-board",
        "--benchmark-unique-code",
        unique_code,
        "--title",
        challenge.unique_code,
        "--no-sandbox",
    ]
    should_queue = len(running_runs()) >= MAX_RUNNING_TASKS
    proc = None if should_queue else spawn_run(cmd, log_path)
    launch_state = "queued" if should_queue else "running"
    if should_queue:
        log_path.write_text(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Benchmark 任务已加入队列，等待空闲名额自动启动。\n",
            encoding="utf-8",
        )
    record = RunRecord(
        run_id=run_id,
        launch_dir=launch_dir,
        workdir=workdir,
        log_path=log_path,
        board_path=board_path,
        attachments_dir=attachments_dir,
        command=cmd,
        title=challenge.unique_code,
        url="",
        statement=challenge.description or "",
        attachment_names=[],
        docker_image=None,
        benchmark_unique_code=unique_code,
        benchmark_base_url=client.base_url,
        launch_state=launch_state,
        queue_rank=time.time() if should_queue else None,
        pid=proc.pid if proc else None,
        pgid=proc.pid if proc else None,
    )
    write_task_meta(record)
    return record


def _queue_scheduler_loop() -> None:
    while True:
        try:
            runs = list_runs()
            available = MAX_RUNNING_TASKS - len(running_runs(runs))
            if available > 0:
                for record in sorted(queued_runs(runs), key=queue_sort_key)[:available]:
                    start_record(record)
        except Exception:
            pass
        time.sleep(QUEUE_POLL_SECONDS)


def render_index(
    *,
    error: str | None = None,
    flash: str | None = None,
    form: dict[str, Any] | None = None,
):
    runs = list_runs()
    challenges, benchmark_error, benchmark_base_url = list_benchmark_challenges()
    solved_codes = locally_solved_benchmark_codes(runs)
    return render_template_string(
        INDEX_TEMPLATE,
        runs=runs[:16],
        error=error,
        flash=flash,
        form=form or {"url": "", "title": "", "statement": ""},
        challenges=challenges,
        challenge_runs=latest_run_by_challenge(runs),
        solved_runs=latest_solved_run_by_challenge(runs),
        solved_codes=solved_codes,
        running_count=len(running_runs(runs)),
        queued_count=len(queued_runs(runs)),
        max_running_tasks=MAX_RUNNING_TASKS,
        benchmark_enabled=bool(benchmark_base_url),
        benchmark_error=benchmark_error,
        benchmark_base_url=benchmark_base_url,
    )


def create_run_dirs(run_id: str) -> tuple[Path, Path, Path, Path]:
    launch_dir = GUI_RUNS_ROOT / run_id
    launch_dir.mkdir(parents=True, exist_ok=False)
    attachments_dir = launch_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    log_path = launch_dir / "runner.log"
    workdir = launch_dir / "workspace"
    workdir.mkdir(parents=True, exist_ok=True)
    return launch_dir, attachments_dir, log_path, workdir


def spawn_run(cmd: list[str], log_path: Path, *, append: bool = False) -> subprocess.Popen[bytes]:
    mode = "ab" if append else "wb"
    with log_path.open(mode) as log_file:
        return subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


@app.route("/", methods=["GET"])
def index():
    ensure_history_backfilled()
    ensure_scheduler_started()
    return render_index(flash=request.args.get("flash"))


@app.route("/launch", methods=["POST"])
def launch_run():
    ensure_history_backfilled()
    ensure_scheduler_started()
    form = build_form_defaults()
    url = form["url"]
    statement = form["statement"]
    title = form["title"]
    hints: list[str] = []
    attachments = [f for f in request.files.getlist("attachments") if f and f.filename]

    if not url and not attachments and not statement:
        return render_index(
            error="至少填写题目 URL、上传附件，或写一段题目描述。",
            form=form,
        )

    run_id = f"run-{uuid4().hex[:10]}"
    launch_dir, attachments_dir, log_path, workdir = create_run_dirs(run_id)
    board_path = workdir / "_board.jsonl"

    attachment_paths: list[Path] = []
    for storage in attachments:
        clean_name = secure_filename(storage.filename) or f"upload-{uuid4().hex[:6]}"
        dest = attachments_dir / clean_name
        storage.save(dest)
        attachment_paths.append(dest)

    cmd = [
        sys.executable,
        "-m",
        "examples.run_ctf",
        "--cwd",
        str(workdir),
        "--resume-board",
    ]
    if url:
        cmd.append(url)
    if title:
        cmd += ["--title", title]
    if statement:
        cmd += ["--statement", statement]
    for attachment_path in attachment_paths:
        cmd += ["--attach", str(attachment_path)]
    cmd += ["--no-sandbox"]

    should_queue = len(running_runs()) >= MAX_RUNNING_TASKS
    proc = None if should_queue else spawn_run(cmd, log_path)
    launch_state = "queued" if should_queue else "running"
    if should_queue:
        log_path.write_text(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务已加入队列，等待空闲名额自动启动。\n",
            encoding="utf-8",
        )

    record = RunRecord(
        run_id=run_id,
        launch_dir=launch_dir,
        workdir=workdir,
        log_path=log_path,
        board_path=board_path,
        attachments_dir=attachments_dir,
        command=cmd,
        title=title,
        url=url,
        statement=statement,
        hints=hints,
        attachment_names=[p.name for p in attachment_paths],
        docker_image=None,
        launch_state=launch_state,
        queue_rank=time.time() if should_queue else None,
        pid=proc.pid if proc else None,
        pgid=proc.pid if proc else None,
    )
    write_task_meta(record)
    flash = (
        f"{record.title or record.run_id} 已加入队列。"
        if should_queue
        else f"{record.title or record.run_id} 已启动。"
    )
    return redirect(url_for("index", flash=flash))


@app.route("/bench/start/<unique_code>", methods=["POST"])
def launch_benchmark_run(unique_code: str):
    ensure_history_backfilled()
    ensure_scheduler_started()

    existing = latest_run_by_challenge(list_runs()).get(unique_code)
    if existing and existing.status() in {"running", "queued"}:
        return redirect(url_for("view_run", run_id=existing.run_id))

    client = benchmark_client_from_env()
    if client is None:
        return render_index(error="缺少 BENCHMARK_BASE_URL 或 BENCHMARK_TOKEN，暂时不能从题库直接启动。")

    try:
        challenge = client.get_challenge(unique_code)
    except BenchmarkAPIError as e:
        return render_index(error=f"读取题目信息失败: {e}")

    record = create_benchmark_record(unique_code, challenge, client)
    flash = (
        f"{record.title or record.benchmark_unique_code or record.run_id} 已加入队列。"
        if record.launch_state == "queued"
        else f"{record.title or record.benchmark_unique_code or record.run_id} 已启动。"
    )
    return redirect(url_for("index", flash=flash))


@app.route("/bench/enqueue-all", methods=["POST"])
def enqueue_all_benchmarks():
    ensure_history_backfilled()
    ensure_scheduler_started()
    client = benchmark_client_from_env()
    if client is None:
        return render_index(error="缺少 BENCHMARK_BASE_URL 或 BENCHMARK_TOKEN，暂时不能从题库批量入队。")

    try:
        challenges = client.list_challenges()
    except BenchmarkAPIError as e:
        return render_index(error=f"读取题库失败: {e}")

    existing = latest_run_by_challenge(list_runs())
    created = 0
    skipped = 0
    for challenge in challenges:
        active = existing.get(challenge.unique_code)
        if active and active.status() in {"running", "queued"}:
            skipped += 1
            continue
        record = create_benchmark_record(challenge.unique_code, challenge, client)
        existing[challenge.unique_code] = record
        created += 1

    flash = f"已加入 {created} 道题到调度队列。"
    if skipped:
        flash += f" 跳过 {skipped} 道已在运行或排队中的题。"
    return redirect(url_for("index", flash=flash))


@app.route("/runs/<run_id>", methods=["GET"])
def view_run(run_id: str):
    ensure_history_backfilled()
    ensure_scheduler_started()
    run = load_run(run_id)
    log_text = read_log_tail(run.log_path)
    return render_template_string(
        RUN_TEMPLATE,
        run=run,
        log_text=log_text,
        command_text=" ".join(run.command),
        operator_inbox_path=run.operator_inbox_path,
        operator_notes=read_operator_notes(run),
        refresh=(run.status() == "running"),
    )


@app.route("/runs/<run_id>/log", methods=["GET"])
def view_run_log(run_id: str):
    ensure_history_backfilled()
    run = load_run(run_id)
    return jsonify(
        {
            "run_id": run.run_id,
            "status": run.status(),
            "log_text": read_log_tail(run.log_path),
        }
    )


@app.route("/runs/<run_id>/note", methods=["POST"])
def post_run_note(run_id: str):
    ensure_history_backfilled()
    run = load_run(run_id)
    text = request.form.get("note_text", "").strip()
    if not text:
        return redirect(url_for("view_run", run_id=run_id))
    append_operator_note(run, text)
    return redirect(url_for("view_run", run_id=run_id))


@app.route("/runs/<run_id>/prioritize", methods=["POST"])
def prioritize_run(run_id: str):
    ensure_history_backfilled()
    ensure_scheduler_started()
    run = load_run(run_id)
    if run.status() != "queued":
        return redirect(url_for("index", flash=f"{run.title or run.benchmark_unique_code or run.run_id} 当前不在排队中。"))
    queued = queued_runs()
    if run.queue_priority:
        run.queue_priority = False
        write_task_meta(run)
        return redirect(url_for("index", flash=f"{run.title or run.benchmark_unique_code or run.run_id} 已取消置顶。"))

    for item in queued:
        if item.run_id == run.run_id:
            continue
        if item.queue_priority:
            item.queue_priority = False
            write_task_meta(item)

    run.queue_priority = True
    if run.queue_rank is None:
        run.queue_rank = time.time()
    write_task_meta(run)
    return redirect(url_for("index", flash=f"{run.title or run.benchmark_unique_code or run.run_id} 已设为置顶排队。"))


@app.route("/runs/<run_id>/delete", methods=["POST"])
def delete_run(run_id: str):
    ensure_history_backfilled()
    ensure_scheduler_started()
    run = load_run(run_id)
    stop_run(run)
    close_message = close_benchmark_if_needed(run)
    delete_run_files(run)
    flash = f"{run.title or run.benchmark_unique_code or run.run_id} 已删除。"
    if close_message:
        flash = f"{flash} {close_message}"
    return redirect(url_for("index", flash=flash))


@app.route("/runs/<run_id>/stop", methods=["POST"])
def stop_run_route(run_id: str):
    ensure_history_backfilled()
    ensure_scheduler_started()
    run = load_run(run_id)
    was_queued = run.status() == "queued"
    stop_run(run)
    close_message = close_benchmark_if_needed(run)
    write_task_meta(run)
    action = "已取消排队" if was_queued else "已停止"
    flash = f"{run.title or run.benchmark_unique_code or run.run_id} {action}。"
    if close_message:
        flash = f"{flash} {close_message}"
    return redirect(url_for("index", flash=flash))


if __name__ == "__main__":
    ensure_runs_root()
    ensure_history_backfilled()
    ensure_scheduler_started()
    app.run(host="127.0.0.1", port=5055, debug=False)
