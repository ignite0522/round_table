"""Kay —— 总管 / 发牌器 / Orchestrator。

职责:
- 发牌:摄入题目(题面/URL/附件),作为根 FACT 放上桌。
- 召集骑士,驱动主循环(骑士异步推进,不必步调一致)。
- 每轮让 Merlin 扫桌、Arthur 验旗。
- 终止判定:成功 / 超时 / 全员停滞。
- 时间线记录 + 收束模式切换。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from ..core.board import Board
from ..core.entry import EntryType
from ..knights.base import Knight
from .arthur import Arthur
from .merlin import Merlin


DISPLAY_NAMES = {
    "Gawain": "工具师",
    "Percival": "直给者",
    "Mordred": "破坏者",
    "Lancelot": "钻探者",
    "Tristan": "缝合者",
    "Kay": "发牌器",
    "Merlin": "调度者",
    "Arthur": "仲裁者",
}


@dataclass
class Problem:
    title: str
    statement: str = ""
    url: str | None = None
    attachments: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)


@dataclass
class MeetingResult:
    solved: bool
    flag: str | None
    reason: str            # "flag" | "timeout" | "stalled" | "max_cycles"
    cycles: int
    elapsed: float
    board_size: int


class Kay:
    def __init__(
        self,
        board: Board,
        knights: list[Knight],
        merlin: Merlin,
        arthur: Arthur,
        *,
        time_budget_s: float = 4 * 3600,       # 4 小时硬上限
        closing_fraction: float = 0.7,         # 进度到此切收束模式(更早集中火力)
        stall_patience_cycles: int = 6,        # 全员连续空转多少轮判定停滞
        merlin_tick_every: int = 1,            # 每几轮让 Merlin 扫一次
        max_cycles: int | None = None,         # 调试/测试用硬上限
        clock=time.monotonic,                  # 可注入的时钟(测试用)
        verbose: bool = False,                 # 实时打印进度
        host_prefetch: bool = True,            # 发牌时由宿主侧预抓取 URL
        host_prefetch_timeout_s: float = 10.0,
    ):
        self.board = board
        self.knights = knights
        self.merlin = merlin
        self.arthur = arthur
        self.time_budget_s = time_budget_s
        self.closing_fraction = closing_fraction
        self.stall_patience_cycles = stall_patience_cycles
        self.merlin_tick_every = merlin_tick_every
        self.max_cycles = max_cycles
        self.clock = clock
        self.verbose = verbose
        self.host_prefetch = host_prefetch
        self.host_prefetch_timeout_s = host_prefetch_timeout_s

        self.timeline: list[dict] = []
        self._closing_entered = False
        self._flag_cancel_timeout_s = 2.0

    def _say(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    def _log(self, event: str, **kw) -> None:
        self.timeline.append({"t": self.clock(), "event": event, **kw})

    def _display_name(self, name: str | None) -> str:
        if not name:
            return "(unknown)"
        cn = DISPLAY_NAMES.get(name)
        return f"{name}·{cn}" if cn else name

    async def deal(self, problem: Problem) -> None:
        """发牌:把题目放上桌。"""
        body_parts = [problem.statement]
        if problem.url:
            body_parts.append(f"URL: {problem.url}")
        if problem.attachments:
            body_parts.append("附件: " + ", ".join(problem.attachments))
        if problem.hints:
            body_parts.append("提示: " + " | ".join(problem.hints))
        await self.board.post(
            type=EntryType.FACT,
            author="Kay",
            title=f"[题目] {problem.title}",
            body="\n".join(p for p in body_parts if p),
            confidence=1.0,
            tags=["problem", "root"],
        )
        if problem.url and self.host_prefetch:
            await self._post_host_prefetch(problem.url)
        self._log("deal", title=problem.title)

    async def _post_host_prefetch(self, url: str) -> None:
        result = await asyncio.to_thread(self._host_fetch_url, url)
        await self.board.post(
            type=EntryType.TOOL_OUTPUT,
            author="Kay",
            title=f"宿主侧预抓取 URL:{result['summary']}",
            body=result["body"],
            confidence=0.9,
            tags=["host_fetch", "network", "url"],
        )

    def _host_fetch_url(self, url: str) -> dict[str, str]:
        req = Request(
            url,
            headers={
                "User-Agent": "roundtable-host-prefetch/1.0",
                "Accept": "*/*",
            },
        )
        opener = build_opener(ProxyHandler({}))  # 宿主预检绕过 localhost 代理变量
        try:
            with opener.open(req, timeout=self.host_prefetch_timeout_s) as resp:
                status = getattr(resp, "status", resp.getcode())
                headers = dict(resp.headers.items())
                raw = resp.read(4096)
                body = raw.decode("utf-8", "replace")
                return {
                    "summary": f"HTTP {status}",
                    "body": self._format_prefetch_body(url, status, headers, body),
                }
        except HTTPError as e:
            raw = e.read(4096)
            body = raw.decode("utf-8", "replace")
            return {
                "summary": f"HTTP {e.code}",
                "body": self._format_prefetch_body(url, e.code, dict(e.headers.items()), body),
            }
        except URLError as e:
            return {
                "summary": f"失败:{e.reason}",
                "body": f"URL: {url}\n宿主侧预抓取失败:{e.reason}",
            }
        except Exception as e:
            return {
                "summary": f"失败:{type(e).__name__}",
                "body": f"URL: {url}\n宿主侧预抓取失败:{type(e).__name__}: {e}",
            }

    def _format_prefetch_body(self, url: str, status: int, headers: dict[str, str], body: str) -> str:
        header_text = "\n".join(f"{k}: {v}" for k, v in list(headers.items())[:24])
        return "\n".join(
            [
                f"URL: {url}",
                f"HTTP status: {status}",
                "Headers:",
                header_text or "(empty)",
                "",
                "Body first bytes:",
                body[:4000] or "(empty)",
            ]
        )

    async def run(self, problem: Problem) -> MeetingResult:
        # 实时事件:骑士一发帖/表态就立刻打印,不必等整轮结束。
        if self.verbose:
            def _on_event(kind, entry, extra):
                if kind == "post":
                    if entry.author in ("Kay", "Arthur", "Merlin"):
                        return
                    self._say(f"    ✏  [{self._display_name(entry.author)}] {entry.type.value}: {entry.title}")
                elif kind == "endorse":
                    self._say(f"    👍 {self._display_name(extra.get('by'))} 认可 {entry.id}")
                elif kind == "challenge":
                    self._say(f"    ✋ {self._display_name(extra.get('by'))} 质疑 {entry.id}:{extra.get('reason','')[:40]}")
                elif kind == "claim":
                    self._say(f"    🖐 {self._display_name(extra.get('by'))} 认领 {entry.id}")
            self.board.on_event = _on_event

        await self.deal(problem)
        # 骑士生命周期:真骑士可 connect/disconnect;mock 骑士没有则跳过。
        for k in self.knights:
            if hasattr(k, "connect"):
                self._say(f"  · 召集骑士 {k.name} …")
                await k.connect()
                self._say(f"    ✓ {k.name} 就位")
        self._say("圆桌就绪,开始会议。\n")
        try:
            return await self._loop(problem)
        finally:
            for k in self.knights:
                if hasattr(k, "disconnect"):
                    try:
                        await k.disconnect()
                    except Exception as e:
                        self._log("disconnect_error", knight=k.name, error=repr(e))

    async def _loop(self, problem: Problem) -> MeetingResult:
        start = self.clock()
        cycle = 0

        while True:
            cycle += 1
            self._say(f"── cycle {cycle} 开始(五骑士并发)…")
            n_before = len(self.board)

            # —— 时间预算 & 收束模式 ——
            elapsed = self.clock() - start
            if not self._closing_entered and elapsed >= self.time_budget_s * self.closing_fraction:
                best = self.merlin.enter_closing_mode(self.knights)
                self._closing_entered = True
                self._log("closing_mode", best=best.id if best else None)
                self._say(f"  ⚠ 进入收束模式,集中火力:{best.title if best else '(无)'}")

            if elapsed >= self.time_budget_s:
                final_flag = await self._final_arthur_check(reason="timeout", cycle=cycle)
                if final_flag:
                    return self._finish("flag", cycle, start, flag=final_flag)
                return self._finish("timeout", cycle, start)

            # —— 五骑士并发跑一个 cycle；若中途已有可验证 flag，立即收口并中断其余骑士 ——
            all_before = {e.id for e in self.board.all()}
            knight_by_task = {}
            task_by_knight = {}
            for k in self.knights:
                task = asyncio.create_task(self._run_knight(k))
                task_by_knight[k.name] = task
                knight_by_task[task] = k
            pending = set(task_by_knight.values())
            posts_this_cycle = 0
            early_flag: str | None = None

            try:
                while pending:
                    done, pending = await asyncio.wait(
                        pending,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in done:
                        result = task.result()
                        if isinstance(result, int):
                            posts_this_cycle += result

                    # 只要有骑士先产出 flag 候选/高置信旗子，就立刻让 Arthur 验旗。
                    early_flag = await self.arthur.check()
                    if early_flag:
                        await self._cancel_pending_tasks(pending, knight_by_task, reason="early_flag")
                        pending.clear()
                        break
            finally:
                if pending:
                    await self._cancel_pending_tasks(pending, knight_by_task, reason="cycle_cleanup")

            self._log("cycle", n=cycle, posts=posts_this_cycle)

            new_entries = [e for e in self.board.all() if e.id not in all_before]
            for k in self.knights:
                if isinstance(getattr(k, "_last_error", None), str):
                    self._say(f"  ! {k.name} 报错:{k._last_error}")
                    k._last_error = None
            self._say(f"── cycle {cycle} 结束,本轮新增 {len(new_entries)} 条,黑板共 {len(self.board)} 条\n")

            # —— Arthur 已在本轮中途确认 flag：直接散会，不再触发 Merlin / rerank / 额外 LLM 调用 ——
            if early_flag:
                self._log("flag", flag=early_flag, cycle=cycle)
                self._say(f"  🏁 Arthur 确认 flag:{early_flag}")
                return self._finish("flag", cycle, start, flag=early_flag)

            # —— Merlin 扫桌 ——
            if cycle % self.merlin_tick_every == 0:
                report = await self.merlin.tick(self.knights, now=self.clock())
                if any(report.values()):
                    self._log("merlin", n=cycle, **{k: v for k, v in report.items() if v})
                    active = {k: v for k, v in report.items() if v}
                    self._say(f"  -> Merlin:{active}")

            # —— Arthur 验旗 ——
            flag = await self.arthur.check()
            if flag:
                self._log("flag", flag=flag, cycle=cycle)
                self._say(f"  🏁 Arthur 确认 flag:{flag}")
                return self._finish("flag", cycle, start, flag=flag)

            # —— 停滞判定 ——
            if all(getattr(k, "idle_cycles", 0) >= self.stall_patience_cycles for k in self.knights):
                final_flag = await self._final_arthur_check(reason="stalled", cycle=cycle)
                if final_flag:
                    return self._finish("flag", cycle, start, flag=final_flag)
                return self._finish("stalled", cycle, start)

            # —— 调试上限 ——
            if self.max_cycles is not None and cycle >= self.max_cycles:
                final_flag = await self._final_arthur_check(reason="max_cycles", cycle=cycle)
                if final_flag:
                    return self._finish("flag", cycle, start, flag=final_flag)
                return self._finish("max_cycles", cycle, start)

    async def _final_arthur_check(self, *, reason: str, cycle: int) -> str | None:
        flag = await self.arthur.check()
        if flag:
            self._log("final_flag", reason=reason, cycle=cycle, flag=flag)
            self._say(f"  🏁 Arthur 临门复核命中 flag:{flag}")
        return flag

    async def _run_knight(self, knight: Knight) -> int:
        """跑单个骑士的一个 cycle,注入 Merlin 指令。"""
        directives = self.merlin.take_directives(knight.name)
        # 把指令挂到骑士上,骑士 cycle 内可读取(mock behavior 或真骑士 prompt)
        setattr(knight, "pending_directives", directives)
        try:
            return await knight.cycle()
        except Exception as e:  # 单个骑士崩溃不拖垮全桌
            self._log("knight_error", knight=knight.name, error=repr(e))
            knight._last_error = repr(e)
            return 0

    async def _cancel_pending_tasks(
        self,
        pending: set[asyncio.Task],
        knight_by_task: dict[asyncio.Task, Knight],
        *,
        reason: str,
    ) -> None:
        if not pending:
            return
        for task in pending:
            task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=self._flag_cancel_timeout_s,
            )
        except asyncio.TimeoutError:
            lingering = [task for task in pending if not task.done()]
            for task in lingering:
                knight = knight_by_task.get(task)
                force_terminate = getattr(knight, "force_terminate", None)
                if callable(force_terminate):
                    try:
                        await force_terminate()
                    except Exception as e:
                        self._log(
                            "force_terminate_error",
                            reason=reason,
                            knight=getattr(knight, "name", "(unknown)"),
                            error=repr(e),
                        )
            self._log(
                "cancel_timeout",
                reason=reason,
                pending=len(lingering),
                timeout_s=self._flag_cancel_timeout_s,
            )
            self._say(
                f"  ⚠ 其余骑士取消超时({self._flag_cancel_timeout_s:.0f}s)，直接进入收尾。"
            )

    def _finish(self, reason: str, cycle: int, start: float, flag: str | None = None) -> MeetingResult:
        elapsed = self.clock() - start
        self._log("adjourn", reason=reason, cycle=cycle, elapsed=elapsed)
        return MeetingResult(
            solved=(reason == "flag"),
            flag=flag or self.arthur.winning_flag,
            reason=reason,
            cycles=cycle,
            elapsed=elapsed,
            board_size=len(self.board),
        )
