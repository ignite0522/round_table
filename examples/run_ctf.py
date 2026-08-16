"""真骑士圆桌入口(Phase 2)—— 用 Codex CLI 驱动五骑士解一道真题。

前置:
  安装并登录 Codex CLI,确保 `codex exec --help` 可用。

用法:
  python -m examples.run_ctf \
      --title "Baby RSA" \
      --statement "附件 chall.py + out.txt,求 flag" \
      --attach ./work/chall.py --attach ./work/out.txt \
      --cwd ./work \
      --max-cycles 20

骑士在 --cwd 指定的沙箱工作目录里真跑 shell / python / 逆向工具。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4
from urllib.parse import urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener

from roundtable.assemble import assemble_codex
from roundtable.benchmark import BenchmarkAPIError, BenchmarkClient, load_benchmark_config
from roundtable.roles import Problem
from roundtable.roles.arthur import DEFAULT_FLAG_REGEX, VerificationResult

ROUND_TABLE_MODEL = "gpt-5.4"


class _HrefExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(str(value))


def _http_probe_base_urls(addr: str) -> list[str]:
    addr = addr.strip()
    if not addr:
        return []
    if addr.startswith(("http://", "https://")):
        return [addr]
    if ":" not in addr:
        return [f"http://{addr}/", f"https://{addr}/"]
    host, port = addr.rsplit(":", 1)
    if not host or not port.isdigit():
        return [f"http://{addr}/", f"https://{addr}/"]
    if port == "443":
        return [f"https://{addr}/", f"http://{addr}/"]
    return [f"http://{addr}/", f"https://{addr}/"]


def _safe_attachment_name(url: str, headers: dict[str, str], *, fallback_prefix: str) -> str:
    dispo = headers.get("content-disposition", "")
    match = re.search(r'filename="?([^";]+)"?', dispo, flags=re.I)
    if match:
        return match.group(1).strip()
    parsed = urlparse(url)
    tail = Path(parsed.path).name
    if tail:
        return tail
    return fallback_prefix


def _looks_like_download_link(href: str) -> bool:
    href_l = href.lower()
    return any(token in href_l for token in ("/download", "download=", "attachment", ".zip", ".tar", ".gz", ".7z", ".bin", ".elf", ".exe"))


def _download_benchmark_attachments(addrs: list[str], attachments_dir: Path) -> list[str]:
    attachments_dir.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))
    saved: list[str] = []
    seen_urls: set[str] = set()

    for addr in addrs:
        for base_url in _http_probe_base_urls(addr):
            try:
                req = Request(base_url, headers={"User-Agent": "roundtable-benchmark-prefetch/1.0", "Accept": "*/*"})
                with opener.open(req, timeout=10) as resp:
                    body = resp.read()
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    ctype = headers.get("content-type", "").lower()
                    if "text/html" not in ctype:
                        continue
                    text = body.decode("utf-8", "replace")
            except Exception:
                continue

            parser = _HrefExtractor()
            parser.feed(text)
            candidates = []
            for href in parser.hrefs:
                if href.startswith(("javascript:", "#", "mailto:")):
                    continue
                if not _looks_like_download_link(href):
                    continue
                url = urljoin(base_url, href)
                if url not in seen_urls:
                    seen_urls.add(url)
                    candidates.append(url)

            for idx, url in enumerate(candidates, start=1):
                try:
                    req = Request(url, headers={"User-Agent": "roundtable-benchmark-prefetch/1.0", "Accept": "*/*"})
                    with opener.open(req, timeout=15) as resp:
                        payload = resp.read()
                        headers = {k.lower(): v for k, v in resp.headers.items()}
                except Exception:
                    continue

                if not payload:
                    continue
                ctype = headers.get("content-type", "").lower()
                dispo = headers.get("content-disposition", "").lower()
                if "text/html" in ctype and "attachment" not in dispo:
                    continue

                name = _safe_attachment_name(url, headers, fallback_prefix=f"artifact-{idx}")
                dest = attachments_dir / name
                if dest.exists():
                    stem = dest.stem
                    suffix = dest.suffix
                    counter = 2
                    while dest.exists():
                        dest = attachments_dir / f"{stem}-{counter}{suffix}"
                        counter += 1
                dest.write_bytes(payload)
                saved.append(str(dest))
    return saved


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="圆桌骑士 · 真骑士 CTF 求解")
    p.add_argument("url", nargs="?", default=None, help="题目 URL(实战通常只给这个)")
    p.add_argument("--url", dest="url_opt", default=None, help="题目 URL(与位置参数二选一)")
    p.add_argument("--title", default=None, help="题目名,不给则从 URL 自动推断")
    p.add_argument("--statement", default="", help="题面描述,不给则自动生成")
    p.add_argument("--attach", action="append", default=[], help="附件路径,可多次")
    p.add_argument("--hint", action="append", default=[], help="提示,可多次")
    p.add_argument("--cwd", default="./round_table_work", help="沙箱工作基目录;默认每题自动创建新的随机子目录")
    p.add_argument(
        "--resume-board",
        action="store_true",
        help="保留当前工作目录下已有的 _board.jsonl,用于续跑同一道题",
    )
    p.add_argument("--model", default=ROUND_TABLE_MODEL, help=f"Codex 使用的模型名;当前圆桌仅允许 {ROUND_TABLE_MODEL}")
    p.add_argument("--codex-bin", default="codex", help="Codex CLI 可执行文件路径")
    p.add_argument("--docker-image", default=None, help="若提供,骑士改为在该 Docker worker 镜像内运行 codex exec")
    p.add_argument("--docker-platform", default="linux/amd64", help="Docker worker 平台,默认 linux/amd64")
    p.add_argument("--merlin-search-mode", choices=["classic", "funsearch"], default="funsearch", help="Merlin 搜索模式，默认 funsearch")
    p.add_argument("--merlin-funsearch-enable-llm-rerank", action="store_true", default=True, help="启用 Merlin 的 Codex LLM 短名单重排，默认开启")
    p.add_argument("--merlin-funsearch-rerank-top-k", type=int, default=4, help="LLM rerank 的 shortlist 大小")
    p.add_argument("--merlin-funsearch-rerank-model", default=None, help="Merlin LLM rerank 使用的模型;默认沿用圆桌模型")
    p.add_argument("--flag-regex", default=DEFAULT_FLAG_REGEX)
    p.add_argument("--benchmark-base-url", default=None, help="TSecBench API base URL; 默认读 BENCHMARK_BASE_URL")
    p.add_argument("--benchmark-token", default=None, help="TSecBench token; 默认读 BENCHMARK_TOKEN")
    p.add_argument("--benchmark-unique-code", default=None, help="TSecBench 题目 unique_code")
    p.add_argument("--benchmark-timeout-s", type=float, default=15.0, help="TSecBench API 超时秒数")
    p.add_argument("--keep-benchmark-open", action="store_true", help="跑完后不自动 close challenge")
    p.add_argument("--max-cycles", type=int, default=20)
    p.add_argument("--time-budget-min", type=float, default=240.0, help="时间预算(分钟),默认 4 小时")
    p.add_argument("--result-json", default=None, help="若提供，则将本次 meeting 结果写入该 JSON 文件")
    p.add_argument("--no-sandbox", action="store_true")
    p.add_argument("--allow-domain", action="append", default=[],
                   help="沙箱网络白名单域名,可多次;不给则放行全部网络。题目 host 会自动加入")
    p.add_argument("--lock-network", action="store_true",
                   help="启用网络白名单模式(仅放行题目 host 与 --allow-domain);默认放行全部")
    a = p.parse_args(argv)

    if a.model != ROUND_TABLE_MODEL:
        p.error(f"当前圆桌规定只跑 {ROUND_TABLE_MODEL}，收到: {a.model}")
    if a.merlin_funsearch_rerank_top_k < 1:
        p.error("--merlin-funsearch-rerank-top-k 必须 >= 1")

    a.url = a.url or a.url_opt
    a.benchmark_base_url, a.benchmark_token = load_benchmark_config(
        base_url=a.benchmark_base_url,
        token=a.benchmark_token,
    )
    a.use_benchmark = bool(a.benchmark_unique_code)
    if a.use_benchmark and (not a.benchmark_base_url or not a.benchmark_token):
        p.error("启用 --benchmark-unique-code 时，必须提供 BENCHMARK_BASE_URL 与 BENCHMARK_TOKEN（参数或环境变量）")
    if not a.url and not a.attach and not a.statement and not a.use_benchmark:
        p.error("至少要给一个 URL(位置参数或 --url)、--attach 附件、填写 --statement，或提供 --benchmark-unique-code")

    # 只给 URL 时,自动补全 title 与 statement
    host = None
    if a.url:
        host = urlparse(a.url).netloc or a.url
        if not a.title:
            a.title = host
        if not a.statement:
            a.statement = (
                f"这是一道 CTF 题,目标 URL:{a.url}\n"
                "请先抓取/访问该 URL 侦察(curl、浏览器请求、端口探测等),"
                "判断题型并寻找 flag。附件(如有)在沙箱工作目录中。"
            )
    elif not a.title:
        a.title = "Untitled Challenge"

    # 网络白名单:默认放行全部(allowed_domains=None);--lock-network 才启用白名单
    if a.lock_network:
        domains = list(a.allow_domain)
        if host and host not in domains:
            domains.append(host)
        a.allowed_domains = domains
    else:
        a.allowed_domains = None
    return a


def _guess_url_from_addr(addrs: list[str]) -> str | None:
    if len(addrs) != 1:
        return None
    addr = addrs[0].strip()
    if not addr:
        return None
    if addr.startswith(("http://", "https://")):
        return addr
    if ":" not in addr:
        return None
    host, port = addr.rsplit(":", 1)
    if not host or not port.isdigit():
        return None
    if port == "443":
        return f"https://{addr}/"
    if port in {"80", "8000", "8080", "5000", "3000", "8888"}:
        return f"http://{addr}/"
    return None


def _is_capacity_conflict(error: BenchmarkAPIError) -> bool:
    if error.status != 409:
        return False
    return "max active challenge instances reached" in str(error).lower()


async def _start_benchmark_challenge_with_retry(
    client: BenchmarkClient,
    unique_code: str,
    *,
    wait_s: float = 3.0,
) -> list[str]:
    while True:
        try:
            return await asyncio.to_thread(client.start_challenge, unique_code)
        except BenchmarkAPIError as e:
            if not _is_capacity_conflict(e):
                raise
            active_items = await asyncio.to_thread(client.list_active_challenges)
            active_desc = ", ".join(
                f"{item.unique_code}:{item.container_status}"
                for item in active_items
            ) or "(empty)"
            print(
                f"   [TSecBench] start {unique_code} 命中平台活跃靶场上限，"
                f"{wait_s:.0f}s 后重试。当前活跃: {active_desc}",
                flush=True,
            )
            await asyncio.sleep(wait_s)


def _build_problem_from_benchmark(
    challenge,
    *,
    addrs: list[str],
    title_override: str | None,
    statement_override: str,
    hints: list[str],
) -> Problem:
    body_parts: list[str] = []
    if statement_override:
        body_parts.append(statement_override)
    if challenge.description:
        body_parts.append(f"平台描述: {challenge.description}")
    body_parts.append(f"TSecBench unique_code: {challenge.unique_code}")
    if challenge.difficulty:
        body_parts.append(f"难度: {challenge.difficulty}")
    if challenge.level is not None:
        body_parts.append(f"关卡: {challenge.level}")
    if challenge.total_score is not None:
        body_parts.append(f"满分: {challenge.total_score}")
    if challenge.flag_count is not None:
        body_parts.append(f"flag 数: {challenge.flag_count}")
    if addrs:
        body_parts.append("题目入口(需先连 VPN): " + ", ".join(addrs))
    else:
        body_parts.append("题目入口尚未返回，请检查 challenge start 状态。")
    if hints:
        body_parts.append("提示: " + " | ".join(hints))
    body_parts.append("请围绕以上入口与题面进行侦察、利用并寻找 flag。")
    return Problem(
        title=title_override or challenge.unique_code,
        statement="\n".join(body_parts),
        url=_guess_url_from_addr(addrs),
        attachments=[],
        hints=[],
    )


def prepare_workdir(cwd: str, *, resume_board: bool) -> Path:
    base_dir = Path(cwd)
    if resume_board:
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    run_dir = base_dir / f"run-{uuid4().hex[:12]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def prepare_board_file(cwd: str, *, resume_board: bool) -> Path:
    board_path = Path(cwd) / "_board.jsonl"
    if board_path.exists() and not resume_board:
        board_path.unlink()
    return board_path


def _load_submitted_flag_cache(path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if not path.exists():
        return cache
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            flag = str(item.get("flag") or "").strip()
            if flag:
                cache[flag] = item
    except OSError:
        return {}
    return cache


def _append_submitted_flag_cache(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


async def main():
    a = parse_args()
    workdir = prepare_workdir(a.cwd, resume_board=a.resume_board)
    board_path = prepare_board_file(str(workdir), resume_board=a.resume_board)
    submitted_flags_path = workdir / "_submitted_flags.jsonl"
    submitted_flags = _load_submitted_flag_cache(submitted_flags_path)
    downloaded_attachments: list[str] = []
    verifier = None
    benchmark_client = None
    benchmark_unique_code = None
    benchmark_started = False

    if a.use_benchmark:
        benchmark_client = BenchmarkClient(
            a.benchmark_base_url,
            a.benchmark_token,
            timeout_s=a.benchmark_timeout_s,
        )
        benchmark_unique_code = a.benchmark_unique_code
        challenge = benchmark_client.get_challenge(benchmark_unique_code)
        addrs = await _start_benchmark_challenge_with_retry(
            benchmark_client,
            benchmark_unique_code,
        )
        benchmark_started = True
        downloaded_attachments = await asyncio.to_thread(
            _download_benchmark_attachments,
            addrs,
            workdir / "attachments",
        )
        problem = _build_problem_from_benchmark(
            challenge,
            addrs=addrs,
            title_override=a.title,
            statement_override=a.statement,
            hints=a.hint,
        )
        problem.attachments = downloaded_attachments

        async def _verify(flag: str) -> bool | VerificationResult:
            cached = submitted_flags.get(flag)
            if cached is not None:
                correct = bool(cached.get("correct"))
                complete = bool(cached.get("complete"))
                correct_count = int(cached.get("correct_flag_count") or 0)
                total_count = int(cached.get("total_flag_count") or 0)
                count_text = f" [{correct_count}/{total_count}]" if total_count else ""
                print(
                    f"   [TSecBench] skip duplicate(local-cache){count_text}: {flag}",
                    flush=True,
                )
                if correct:
                    return VerificationResult(
                        accepted=True,
                        should_stop=complete,
                        reason="该 flag 之前已提交过，本次跳过重复提交。",
                    )
                return VerificationResult(
                    accepted=False,
                    should_stop=False,
                    reason="该 flag 之前已提交过且未通过，本次跳过重复提交。",
                )

            result = await asyncio.to_thread(
                benchmark_client.submit_flag,
                benchmark_unique_code,
                flag,
            )
            award_text = f", +{result.awarded} 分" if result.awarded else ""
            duplicate_text = " (duplicate)" if result.duplicate else ""
            count_text = (
                f" [{result.correct_flag_count}/{result.total_flag_count}]"
                if result.total_flag_count
                else ""
            )
            print(
                "   [TSecBench] submit "
                f"{'correct' if result.correct else 'wrong'}{award_text}{duplicate_text}{count_text}",
                flush=True,
            )
            complete = bool(
                result.correct
                and result.total_flag_count
                and result.correct_flag_count >= result.total_flag_count
            )
            record = {
                "flag": flag,
                "correct": bool(result.correct),
                "duplicate": bool(result.duplicate),
                "awarded": int(result.awarded),
                "correct_flag_count": int(result.correct_flag_count),
                "total_flag_count": int(result.total_flag_count),
                "complete": complete,
            }
            submitted_flags[flag] = record
            _append_submitted_flag_cache(submitted_flags_path, record)
            if result.correct:
                return VerificationResult(
                    accepted=True,
                    should_stop=complete,
                    reason=(
                        "该 flag 已验证正确，且本题 flag 已全部提交完成。"
                        if complete
                        else "该 flag 已验证正确，但本题还有其他 flag 未提交。"
                    ),
                )
            return VerificationResult(
                accepted=False,
                should_stop=False,
                reason=f"提交验证未通过:{flag}",
            )

        verifier = _verify
    else:
        problem = Problem(
            title=a.title, statement=a.statement, url=a.url,
            attachments=a.attach, hints=a.hint,
        )

    board, knights, merlin, arthur, kay = assemble_codex(
        jsonl_path=str(board_path),
        model=a.model,
        sandbox=not a.no_sandbox,
        cwd=str(workdir),
        docker_image=a.docker_image,
        docker_platform=a.docker_platform,
        flag_regex=a.flag_regex,
        verifier=verifier,
        max_cycles=a.max_cycles,
        time_budget_s=a.time_budget_min * 60,
        allowed_domains=a.allowed_domains,
        codex_bin=a.codex_bin,
        merlin_search_mode=a.merlin_search_mode,
        merlin_funsearch_rerank_top_k=a.merlin_funsearch_rerank_top_k,
        merlin_funsearch_enable_llm_rerank=a.merlin_funsearch_enable_llm_rerank,
        merlin_funsearch_rerank_model=a.merlin_funsearch_rerank_model,
        verbose=True,
    )

    print(f"⚔  圆桌会议开始:{problem.title}  (沙箱:{workdir},模型:{a.model})")
    print(f"   目标:{problem.url or a.url or a.attach or benchmark_unique_code}")
    if a.docker_image:
        print(f"   Docker worker:{a.docker_image} [{a.docker_platform}]")
    if benchmark_unique_code:
        print(f"   TSecBench:{benchmark_unique_code} @ {a.benchmark_base_url}")
    if downloaded_attachments:
        print(f"   自动下载附件:{', '.join(downloaded_attachments)}")
    print(f"   五骑士会按 cycle 启动 codex exec 子进程,首轮召集可能较慢,请稍候……\n")
    try:
        result = await kay.run(problem)
    finally:
        if benchmark_client and benchmark_started and benchmark_unique_code and not a.keep_benchmark_open:
            try:
                closed = await asyncio.to_thread(
                    benchmark_client.close_challenge,
                    benchmark_unique_code,
                )
                print(f"   [TSecBench] close challenge: {'ok' if closed else 'not_closed'}", flush=True)
            except BenchmarkAPIError as e:
                print(f"   [TSecBench] close challenge failed: {e}", flush=True)

    print("=" * 60)
    print(f"结果: {'✔ 解出' if result.solved else '✘ 未解出'}   flag: {result.flag}")
    print(f"终止: {result.reason} | cycles: {result.cycles} | 用时: {result.elapsed:.0f}s | 条目: {result.board_size}")
    print("=" * 60)
    print("\n—— 最终黑板 ——")
    for e in board.all():
        tag = f" #{' #'.join(e.tags)}" if e.tags else ""
        print(f"  [{e.id}] {e.type.value:14s} {e.author:9s} (+{e.endorse_count}/-{e.challenge_count}) {e.title}{tag}")

    if a.result_json:
        result_path = Path(a.result_json)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "solved": result.solved,
                    "flag": result.flag,
                    "reason": result.reason,
                    "cycles": result.cycles,
                    "elapsed": result.elapsed,
                    "board_size": result.board_size,
                    "benchmark_unique_code": benchmark_unique_code,
                    "title": problem.title,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    asyncio.run(main())
