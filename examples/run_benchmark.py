"""顺序跑 TSecBench 题目列表。

示例:
  BENCHMARK_BASE_URL=... BENCHMARK_TOKEN=... \
  python -m examples.run_benchmark --cwd ./round_table_work --no-sandbox
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from roundtable.benchmark import BenchmarkAPIError, BenchmarkClient, load_benchmark_config

ROUND_TABLE_MODEL = "gpt-5.4"
BASE_PER_CHALLENGE_HARD_TIMEOUT_S = 15 * 60


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
    p.add_argument("--max-cycles", type=int, default=7)
    p.add_argument("--revisit-max-cycles", type=int, default=24, help="未解题回刷时的轮数上限")
    p.add_argument("--final-revisit-max-cycles", type=int, default=24, help="二次回刷后仍未解题的最终轮数上限")
    p.add_argument("--time-budget-min", type=float, default=240.0)
    p.add_argument("--max-parallel", type=int, default=3, help="最多同时解几道题")
    p.add_argument("--revisit-unsolved", action="store_true", default=True, help="首轮扫完后，再回头补跑未解出的题")
    p.add_argument("--no-sandbox", action="store_true")
    p.add_argument("--benchmark-base-url", default=None)
    p.add_argument("--benchmark-token", default=None)
    p.add_argument("--only", action="append", default=[], help="只跑指定 unique_code，可多次")
    p.add_argument("--skip-completed", action="store_true", default=True)
    p.add_argument("--keep-open", action="store_true", help="子任务跑完后不自动 close challenge")
    p.add_argument("--shuffle-order", action="store_true", default=True, help="启动前打乱题目顺序")
    p.add_argument("--shuffle-seed", type=int, default=None, help="题目乱序随机种子，默认按当前时间生成")
    a = p.parse_args(argv)
    if a.model != ROUND_TABLE_MODEL:
        p.error(f"当前圆桌规定只跑 {ROUND_TABLE_MODEL}，收到: {a.model}")
    if a.merlin_funsearch_rerank_top_k < 1:
        p.error("--merlin-funsearch-rerank-top-k 必须 >= 1")
    if a.max_parallel < 1:
        p.error("--max-parallel 必须 >= 1")
    if a.revisit_max_cycles < 1:
        p.error("--revisit-max-cycles 必须 >= 1")
    if a.final_revisit_max_cycles < 1:
        p.error("--final-revisit-max-cycles 必须 >= 1")
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

    shuffle_seed = a.shuffle_seed if a.shuffle_seed is not None else int(time.time())
    if a.shuffle_order:
        rng = random.Random(shuffle_seed)
        rng.shuffle(selected)

    base_dir = Path(a.cwd).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1]
    selected_codes = {challenge.unique_code for challenge in selected}
    env = os.environ.copy()
    env["BENCHMARK_BASE_URL"] = a.benchmark_base_url
    env["BENCHMARK_TOKEN"] = a.benchmark_token
    env["PYTHONUNBUFFERED"] = "1"

    print(
        f"共 {len(selected)} 题待跑；首轮每题最多跑 {a.max_cycles} 轮，且总时长上限 15 分钟；"
        f"第一次回刷最多跑 {a.revisit_max_cycles} 轮，且总时长上限 30 分钟；"
        f"后续回刷统一最多跑 {a.final_revisit_max_cycles} 轮，且总时长上限按 45 / 60 / 75 分钟递增；"
        f"最多并发 {a.max_parallel} 题；"
        "单题总时长上限只在“最后回头补解”时递增。"
    )
    if a.shuffle_order:
        preview = ", ".join(ch.unique_code for ch in selected[:10])
        if len(selected) > 10:
            preview += ", ..."
        print(f"题目顺序已打乱；shuffle_seed={shuffle_seed}；前几个题目: {preview}")

    def build_cmd(challenge, *, max_cycles: int):
        result_json = base_dir / challenge.unique_code / "meeting_result.json"
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
            str(max_cycles),
            "--time-budget-min",
            str(a.time_budget_min),
            "--result-json",
            str(result_json),
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
        return cmd, result_json

    def load_result(path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def stream_prefixed_output(challenge_code: str, proc: subprocess.Popen[str]) -> threading.Thread | None:
        if proc.stdout is None:
            return None

        def _pump() -> None:
            assert proc.stdout is not None
            try:
                for raw_line in proc.stdout:
                    line = raw_line.rstrip("\n")
                    print(f"[{challenge_code}] {line}", flush=True)
            finally:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

        thread = threading.Thread(
            target=_pump,
            name=f"benchmark-log-{challenge_code}",
            daemon=True,
        )
        thread.start()
        return thread

    def close_challenge_with_retry(
        unique_code: str,
        *,
        context: str,
        status_hint: str | None = None,
    ) -> bool:
        attempts = 2
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                closed = client.close_challenge(unique_code)
                suffix = f" ({status_hint})" if status_hint else ""
                print(
                    f"[scheduler] {context} {unique_code}{suffix}: "
                    f"{'ok' if closed else 'not_closed'}"
                )
                return closed
            except Exception as e:
                last_error = e
                if attempt < attempts:
                    print(
                        f"[scheduler] {context} {unique_code} 第 {attempt} 次失败: "
                        f"{type(e).__name__}: {e}，2s 后重试"
                    )
                    time.sleep(2.0)
                    continue
                print(
                    f"[scheduler] {context} {unique_code} 最终失败: "
                    f"{type(e).__name__}: {e}"
                )
        return False

    def reconcile_orphaned_active_challenges(running_codes: set[str]) -> None:
        try:
            active_items = client.list_active_challenges()
        except BenchmarkAPIError as e:
            print(f"[scheduler] 扫描孤儿靶场失败: {e}")
            return

        for item in active_items:
            code = item.unique_code
            if code not in selected_codes:
                continue
            if code in running_codes:
                continue
            close_challenge_with_retry(
                code,
                context="检测到孤儿活跃靶场，自动补 close",
                status_hint=item.container_status,
            )

    def wave_timeout_seconds(wave_index: int) -> int:
        return BASE_PER_CHALLENGE_HARD_TIMEOUT_S * max(1, wave_index)

    def run_wave(
        challenges: list[tuple[int, object]],
        *,
        wave_name: str,
        max_cycles: int,
        wave_index: int,
    ) -> tuple[list[tuple[int, object]], int]:
        hard_timeout_s = wave_timeout_seconds(wave_index)
        print(
            f"\n===== {wave_name}（max_cycles={max_cycles}, "
            f"total_timeout={hard_timeout_s // 60}min） ====="
        )
        pending = list(challenges)
        running: list[dict[str, object]] = []
        unsolved: list[tuple[int, object]] = []
        failed_local = 0
        last_capacity_log_at = 0.0

        while pending or running:
            running_codes = {
                item["challenge"].unique_code
                for item in running
            }
            reconcile_orphaned_active_challenges(running_codes)
            blocked_by_capacity = False
            while pending and len(running) < a.max_parallel:
                try:
                    active_items = client.list_active_challenges()
                except BenchmarkAPIError as e:
                    print(f"[scheduler] 查询平台活跃靶场失败: {e}")
                    blocked_by_capacity = True
                    break
                remote_active = len(active_items)
                if remote_active >= a.max_parallel:
                    blocked_by_capacity = True
                    now = time.monotonic()
                    if now - last_capacity_log_at >= 10.0:
                        active_desc = ", ".join(
                            f"{item.unique_code}:{item.container_status}"
                            for item in active_items
                        ) or "(empty)"
                        print(
                            f"[scheduler] 平台活跃靶场已满({remote_active}/{a.max_parallel})，等待释放后再开新题: {active_desc}"
                        )
                        last_capacity_log_at = now
                    break
                idx, challenge = pending.pop(0)
                print(f"\n=== [{idx}/{len(selected)}] {challenge.unique_code} ===")
                cmd, result_json = build_cmd(challenge, max_cycles=max_cycles)
                print(" ".join(cmd))
                proc = subprocess.Popen(
                    cmd,
                    cwd=repo_root,
                    env=env,
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                log_thread = stream_prefixed_output(challenge.unique_code, proc)
                running.append(
                    {
                        "idx": idx,
                        "challenge": challenge,
                        "proc": proc,
                        "log_thread": log_thread,
                        "result_json": result_json,
                        "started_at": time.monotonic(),
                    }
                )
                print(f"[scheduler] started {challenge.unique_code} pid={proc.pid}")

            if blocked_by_capacity:
                time.sleep(2.0)

            if blocked_by_capacity and not running:
                continue

            if not running:
                break

            time.sleep(2.0)
            still_running: list[dict[str, object]] = []
            for item in running:
                proc = item["proc"]
                assert isinstance(proc, subprocess.Popen)
                started_at = float(item.get("started_at") or 0.0)
                elapsed_s = time.monotonic() - started_at if started_at else 0.0
                if proc.poll() is None and elapsed_s >= hard_timeout_s:
                    challenge = item["challenge"]
                    print(
                        f"[scheduler] {challenge.unique_code} 运行超过 {hard_timeout_s // 60} 分钟，"
                        "强制终止并补 close challenge"
                    )
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except OSError:
                        proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    log_thread = item.get("log_thread")
                    if isinstance(log_thread, threading.Thread):
                        log_thread.join(timeout=1.0)
                    close_challenge_with_retry(
                        challenge.unique_code,
                        context="超时题目自动 close",
                    )
                    failed_local += 1
                    unsolved.append((item["idx"], challenge))
                    continue
                code = proc.poll()
                if code is None:
                    still_running.append(item)
                    continue
                challenge = item["challenge"]
                result = load_result(item["result_json"])
                solved = bool(result and result.get("solved"))
                reason = str(result.get("reason")) if result else "unknown"
                log_thread = item.get("log_thread")
                if isinstance(log_thread, threading.Thread):
                    log_thread.join(timeout=1.0)
                print(f"[scheduler] finished {challenge.unique_code} rc={code} solved={solved} reason={reason}")
                if code != 0:
                    failed_local += 1
                    print(f"题目 {challenge.unique_code} 运行失败，退出码 {code}")
                if not solved:
                    unsolved.append((item["idx"], challenge))
            running = still_running
            running_codes = {
                item["challenge"].unique_code
                for item in running
            }
            reconcile_orphaned_active_challenges(running_codes)
        return unsolved, failed_local

    first_wave = list(enumerate(selected, start=1))
    unsolved, failed = run_wave(
        first_wave,
        wave_name="首轮扫题",
        max_cycles=a.max_cycles,
        wave_index=1,
    )

    if a.revisit_unsolved and unsolved:
        print(f"\n首轮未解出 {len(unsolved)} 题，开始回刷。")
        second_unsolved, failed_second = run_wave(
            unsolved,
            wave_name="未解题回刷",
            max_cycles=a.revisit_max_cycles,
            wave_index=2,
        )
        failed += failed_second
        revisit_round = 2
        remaining = second_unsolved
        while remaining:
            revisit_round += 1
            print(
                f"\n第 {revisit_round} 轮回刷仍有 {len(remaining)} 题未解，"
                f"继续按 {a.final_revisit_max_cycles} 轮深挖。"
            )
            remaining, failed_round = run_wave(
                remaining,
                wave_name=f"第 {revisit_round} 轮回刷",
                max_cycles=a.final_revisit_max_cycles,
                wave_index=revisit_round,
            )
            failed += failed_round

    if failed:
        print(f"\n共有 {failed} 题运行失败。")


if __name__ == "__main__":
    main()
