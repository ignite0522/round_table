"""顺序跑 TSecBench 题目列表。

示例:
  BENCHMARK_BASE_URL=... BENCHMARK_TOKEN=... \
  python -m examples.run_benchmark --cwd ./round_table_work --docker-image roundtable-kali:latest --no-sandbox
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from roundtable.benchmark import BenchmarkClient, load_benchmark_config

ROUND_TABLE_MODEL = "gpt-5.4"


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="圆桌骑士 · TSecBench 跑分入口")
    p.add_argument("--cwd", default="./round_table_work/benchmark-runs", help="每题工作目录的父目录")
    p.add_argument("--model", default=ROUND_TABLE_MODEL, help=f"当前圆桌仅允许 {ROUND_TABLE_MODEL}")
    p.add_argument("--codex-bin", default="codex")
    p.add_argument("--docker-image", default=None)
    p.add_argument("--docker-platform", default="linux/amd64")
    p.add_argument("--merlin-search-mode", choices=["classic", "funsearch"], default="funsearch")
    p.add_argument("--merlin-funsearch-enable-llm-rerank", action="store_true", default=True)
    p.add_argument("--merlin-funsearch-rerank-top-k", type=int, default=4)
    p.add_argument("--merlin-funsearch-rerank-model", default=None)
    p.add_argument("--max-cycles", type=int, default=20)
    p.add_argument("--time-budget-min", type=float, default=240.0)
    p.add_argument("--no-sandbox", action="store_true")
    p.add_argument("--benchmark-base-url", default=None)
    p.add_argument("--benchmark-token", default=None)
    p.add_argument("--only", action="append", default=[], help="只跑指定 unique_code，可多次")
    p.add_argument("--skip-completed", action="store_true", default=True)
    p.add_argument("--keep-open", action="store_true", help="子任务跑完后不自动 close challenge")
    a = p.parse_args(argv)
    if a.model != ROUND_TABLE_MODEL:
        p.error(f"当前圆桌规定只跑 {ROUND_TABLE_MODEL}，收到: {a.model}")
    if a.merlin_funsearch_rerank_top_k < 1:
        p.error("--merlin-funsearch-rerank-top-k 必须 >= 1")
    a.benchmark_base_url, a.benchmark_token = load_benchmark_config(
        base_url=a.benchmark_base_url,
        token=a.benchmark_token,
    )
    if not a.benchmark_base_url or not a.benchmark_token:
        p.error("必须提供 BENCHMARK_BASE_URL 与 BENCHMARK_TOKEN（参数或环境变量）")
    return a


def main():
    a = parse_args()
    client = BenchmarkClient(a.benchmark_base_url, a.benchmark_token)
    all_challenges = client.list_challenges()
    selected = []
    only = set(a.only)
    for challenge in all_challenges:
        if only and challenge.unique_code not in only:
            continue
        if a.skip_completed and challenge.is_completed:
            continue
        selected.append(challenge)

    if not selected:
        print("没有待跑题目。")
        return

    base_dir = Path(a.cwd).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["BENCHMARK_BASE_URL"] = a.benchmark_base_url
    env["BENCHMARK_TOKEN"] = a.benchmark_token

    print(f"共 {len(selected)} 题待跑。")
    for idx, challenge in enumerate(selected, start=1):
        print(f"\n=== [{idx}/{len(selected)}] {challenge.unique_code} ===")
        cmd = [
            sys.executable,
            "-m",
            "examples.run_ctf",
            "--cwd",
            str(base_dir / challenge.unique_code),
            "--resume-board",
            "--benchmark-unique-code",
            challenge.unique_code,
            "--model",
            a.model,
            "--codex-bin",
            a.codex_bin,
            "--docker-platform",
            a.docker_platform,
            "--merlin-search-mode",
            a.merlin_search_mode,
            "--merlin-funsearch-rerank-top-k",
            str(a.merlin_funsearch_rerank_top_k),
            "--max-cycles",
            str(a.max_cycles),
            "--time-budget-min",
            str(a.time_budget_min),
        ]
        if a.merlin_funsearch_enable_llm_rerank:
            cmd.append("--merlin-funsearch-enable-llm-rerank")
        if a.merlin_funsearch_rerank_model:
            cmd += ["--merlin-funsearch-rerank-model", a.merlin_funsearch_rerank_model]
        if a.docker_image:
            cmd += ["--docker-image", a.docker_image]
        if a.no_sandbox:
            cmd.append("--no-sandbox")
        if a.keep_open:
            cmd.append("--keep-benchmark-open")
        print(" ".join(cmd))
        completed = subprocess.run(cmd, cwd=repo_root, env=env)
        if completed.returncode != 0:
            print(f"题目 {challenge.unique_code} 运行失败，退出码 {completed.returncode}")


if __name__ == "__main__":
    main()
