"""Merlin —— 元认知 / 调度层。系统能否用的关键。

Merlin **不解题**,每次 tick 扫一遍黑板,做四件事:
1. 去重:两个骑士在做同一件事 → 让其一转向(记录建议)。
2. 死路检测:challenge≥endorse 且久无进展 → 标 dead_end 并广播。
3. (digest 由 core.digest 生成,Merlin 提供参数与相关性提示)
4. 重新指向卡住的骑士:连续 K 轮空转 → 派未认领的高价值 next_step / 最久无人碰的 fact。

外加:
- 防全员撞路:活跃 claim 高度集中 → 触发强制分散(记录指令)。
- 收束模式:时间进入尾声 → 通知所有骑士集中火力到最强线索。

Merlin 的判断在 Phase 1/3 用**规则**实现;语义级判断(『这几条是不是同一条死路』)
预留 LLM 钩子(hook_semantic_dedup),默认关闭。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core.board import Board
from ..core.entry import BoardEntry, EntryStatus, EntryType
from ..funsearch import MerlinFunSearchControl

LOOPBACK_SCOPE_MARKERS = (
    "localhost",
    "127.0.0.1",
    "::1",
    "host.docker.internal",
)

LOCAL_SCOPE_MARKERS = (
    "tinyproxy",
    "airtunes",
    "container via direct connection",
    "x-apple-processingtime",
    "x-apple-requestreceived",
    "server: airtunes",
)


@dataclass
class MerlinDirective:
    """Merlin 对某骑士下达的一条指令(骑士下一 cycle 可读取)。"""

    kind: str            # "redirect" | "diverge" | "closing" | "dedup"
    target_knight: str
    message: str
    entry_id: str | None = None
    created_at: float = field(default_factory=time.time)


class Merlin:
    def __init__(
        self,
        board: Board,
        *,
        idle_threshold: int = 2,           # 连续空转多少 cycle 判定卡住
        stale_seconds: float = 90.0,       # 条目多久无更新算『久无进展』
        claim_concentration_limit: float = 0.6,  # 活跃 claim 集中度上限
        search_mode: str = "classic",
        funsearch_run_dir: str | Path | None = None,
        funsearch_control: MerlinFunSearchControl | None = None,
        funsearch_rerank_top_k: int = 0,
        funsearch_reranker=None,
        scope_judge=None,
    ):
        self.board = board
        self.idle_threshold = idle_threshold
        self.stale_seconds = stale_seconds
        self.claim_concentration_limit = claim_concentration_limit
        self.search_mode = search_mode

        self.directives: dict[str, list[MerlinDirective]] = {}   # knight -> 指令队列
        self.dead_end_ids: set[str] = set()
        self.scope_violation_ids: set[str] = set()
        self.scope_reviewed_ids: set[str] = set()
        self.scope_review_tasks: dict[str, asyncio.Task] = {}
        self.closing_mode = False
        self.funsearch_rerank_top_k = funsearch_rerank_top_k
        self.funsearch_reranker = funsearch_reranker
        self.scope_judge = scope_judge
        self.funsearch = self._init_funsearch(funsearch_run_dir, funsearch_control)

    # ——————————————————————— 对外:骑士取指令 ———————————————————————

    def take_directives(self, knight: str) -> list[MerlinDirective]:
        out = self.directives.pop(knight, [])
        return out

    def _push(self, d: MerlinDirective) -> None:
        self.directives.setdefault(d.target_knight, []).append(d)

    # ——————————————————————— 主 tick ———————————————————————

    async def tick(self, knights, *, now: float | None = None) -> dict:
        """扫黑板一次,产出指令与状态变更。返回一份摘要供 timeline 记录。

        knights: 当前骑士列表(用于读 idle_cycles / 分派)。
        """
        now = now if now is not None else time.time()
        report = {
            "dead_ends_marked": [],
            "redirects": [],
            "diverge": [],
            "dedup": [],
            "funsearch": {},
            "scope_violations": [],
        }

        if self.funsearch is not None:
            report["funsearch"] = self.funsearch.sync_board(self.board.all())

        # 0) 目标范围检查: 先收已完成的 LLM 裁决,再异步派发新的可疑条目
        await self._collect_scope_judgments(report)
        self._schedule_scope_reviews()

        # 0.1) 无 LLM 时,用强环境指纹做同步兜底
        for e in self.board.all():
            if e.id in self.scope_violation_ids:
                continue
            if e.id in self.scope_reviewed_ids:
                continue
            if e.author in {"Kay", "Arthur", "Merlin"}:
                continue
            if e.type == EntryType.DEAD_END:
                continue
            if e.status in (EntryStatus.RESOLVED, EntryStatus.REFUTED):
                continue
            if self.scope_judge is not None:
                continue
            if not self._looks_like_local_scope_violation(e):
                continue
            await self._mark_scope_violation(
                e,
                report,
                reason=(
                    "当前命中了 `tinyproxy/AirTunes/container via direct connection` 等更强的本地环境指纹，"
                    "默认按越界线索处理；仅出现 `localhost/127.0.0.1` 本身不会触发此规则。"
                ),
            )

        # 1) 死路检测
        for e in self.board.all():
            if e.type in (EntryType.DEAD_END, EntryType.FLAG_CANDIDATE):
                continue
            if e.status in (EntryStatus.RESOLVED, EntryStatus.REFUTED):
                continue
            stale = (now - e.updated_at) >= self.stale_seconds
            losing = e.challenge_count >= max(1, e.endorse_count) and e.challenge_count > 0
            if losing and stale and e.id not in self.dead_end_ids:
                await self.board.set_status(e.id, EntryStatus.REFUTED)
                de = await self.board.post(
                    type=EntryType.DEAD_END,
                    author="Merlin",
                    title=f"死路:{e.title}",
                    body=f"源条目 {e.id} 被质疑 {e.challenge_count} 次且 {int(now - e.updated_at)}s 无进展。",
                    confidence=0.7,
                    refs=[e.id],
                    tags=["dead_end"] + e.tags,
                )
                self.dead_end_ids.add(e.id)
                report["dead_ends_marked"].append(e.id)

        # 2) 去重:多个骑士认领了标签高度重叠的条目
        report["dedup"] = self._detect_collisions()

        # 3) 防全员撞路:活跃 claim 集中度过高 → 强制分散
        report["diverge"] = self._detect_pileup(knights)

        # 4) 重新指向卡住的骑士
        report["redirects"] = self._redirect_idle(knights)

        return report

    # ——————————————————————— 子模块 ———————————————————————

    def _active_claims(self) -> list[BoardEntry]:
        return [
            e for e in self.board.all()
            if e.claimed_by is not None and e.status == EntryStatus.CLAIMED
        ]

    def _detect_collisions(self) -> list[str]:
        """两个骑士认领的条目标签高度重叠 → 提示后认领者转向。"""
        claims = self._active_claims()
        notes: list[str] = []
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                a, b = claims[i], claims[j]
                if a.claimed_by == b.claimed_by:
                    continue
                ta, tb = set(a.tags), set(b.tags)
                if not ta or not tb:
                    continue
                jac = len(ta & tb) / len(ta | tb)
                if jac >= 0.6:
                    # 让净支持较低的一方转向
                    loser = a if a.score() <= b.score() else b
                    self._push(MerlinDirective(
                        kind="dedup",
                        target_knight=loser.claimed_by,
                        message=f"你与他人在做高度重叠的线索({loser.id} ↔ 另一条),考虑转向未认领的方向。",
                        entry_id=loser.id,
                    ))
                    notes.append(f"{a.id}~{b.id}")
        return notes

    def _detect_pileup(self, knights) -> list[str]:
        """活跃 claim 过度集中在少数标签上 → 给闲置姿态派新方向。"""
        claims = self._active_claims()
        if len(claims) < 2:
            return []
        tag_count: dict[str, int] = {}
        for e in claims:
            for t in e.tags:
                tag_count[t] = tag_count.get(t, 0) + 1
        if not tag_count:
            return []
        top = max(tag_count.values())
        concentration = top / len(claims)
        notes: list[str] = []
        if concentration >= self.claim_concentration_limit:
            # 找最久无人碰的 open fact 派给某个骑士
            open_facts = sorted(
                (e for e in self.board.by_type(EntryType.FACT)
                 if e.claimed_by is None and e.status == EntryStatus.OPEN),
                key=lambda e: e.updated_at,
            )
            targets = [k for k in knights if not self._has_pending(k.name)]
            for k, fact in zip(targets, open_facts):
                self._push(MerlinDirective(
                    kind="diverge",
                    target_knight=k.name,
                    message=f"全员挤在少数线索上,请转向被忽视的事实 {fact.id}:{fact.title}",
                    entry_id=fact.id,
                ))
                notes.append(f"{k.name}->{fact.id}")
        return notes

    def _redirect_idle(self, knights) -> list[str]:
        """连续空转的骑士 → 派未认领的高价值 next_step 或最久无人碰的 fact。"""
        notes: list[str] = []
        pool = self._build_redirect_pool()
        for k in knights:
            if getattr(k, "idle_cycles", 0) >= self.idle_threshold and not self._has_pending(k.name):
                if not pool:
                    break
                target = pool.pop(0)
                message = f"你已空转 {k.idle_cycles} 轮,接手 {target.id}:{target.title}"
                if self.search_mode == "funsearch" and self.funsearch is not None:
                    message = f"你已空转 {k.idle_cycles} 轮,沿当前高价值路线继续推进 {target.id}:{target.title}"
                self._push(MerlinDirective(
                    kind="redirect",
                    target_knight=k.name,
                    message=message,
                    entry_id=target.id,
                ))
                notes.append(f"{k.name}->{target.id}")
        return notes

    def _has_pending(self, knight: str) -> bool:
        return bool(self.directives.get(knight))

    # ——————————————————————— 收束模式 ———————————————————————

    def enter_closing_mode(self, knights) -> BoardEntry | None:
        """时间进入尾声:选出最强线索,通知全员集中火力。返回最强条目。"""
        self.closing_mode = True
        ranked = sorted(
            (e for e in self.board.all()
             if e.type in (EntryType.HYPOTHESIS, EntryType.ARTIFACT, EntryType.FLAG_CANDIDATE)
             and e.status not in (EntryStatus.REFUTED,)),
            key=lambda e: e.score(),
            reverse=True,
        )
        best = ranked[0] if ranked else None
        for k in knights:
            k.closing_mode = True
            msg = "收束模式:停止发散,集中火力闭环最强线索。"
            if best:
                msg += f" 当前最强:{best.id} — {best.title}"
            self._push(MerlinDirective(
                kind="closing", target_knight=k.name, message=msg,
                entry_id=best.id if best else None,
            ))
        return best

    # ——————————————————————— LLM 钩子(预留) ———————————————————————

    async def hook_semantic_dedup(self, entries: list[BoardEntry]) -> list[tuple[str, str]]:
        """预留:用轻量 LLM 判断『这几条是不是同一条死路/同一件事』。Phase 3+ 接入。"""
        return []

    def _looks_like_local_scope_violation(self, entry: BoardEntry) -> bool:
        haystack = " ".join(
            [
                entry.title or "",
                entry.body or "",
                " ".join(entry.tags or []),
            ]
        ).lower()
        return any(marker in haystack for marker in LOCAL_SCOPE_MARKERS)

    def _should_review_scope(self, entry: BoardEntry) -> bool:
        haystack = " ".join(
            [
                entry.title or "",
                entry.body or "",
                " ".join(entry.tags or []),
            ]
        ).lower()
        return any(marker in haystack for marker in LOOPBACK_SCOPE_MARKERS + LOCAL_SCOPE_MARKERS)

    def _problem_root_entry(self) -> BoardEntry | None:
        for entry in self.board.all():
            if entry.author == "Kay" and "problem" in entry.tags and "root" in entry.tags:
                return entry
        return None

    def _schedule_scope_reviews(self) -> None:
        if self.scope_judge is None:
            return
        root_entry = self._problem_root_entry()
        for entry in self.board.all():
            if entry.id in self.scope_violation_ids or entry.id in self.scope_reviewed_ids:
                continue
            if entry.id in self.scope_review_tasks:
                continue
            if entry.author in {"Kay", "Arthur", "Merlin"}:
                continue
            if entry.type == EntryType.DEAD_END:
                continue
            if entry.status in (EntryStatus.RESOLVED, EntryStatus.REFUTED):
                continue
            if not self._should_review_scope(entry):
                continue
            self.scope_review_tasks[entry.id] = asyncio.create_task(
                asyncio.to_thread(self.scope_judge, root_entry, entry)
            )

    async def _collect_scope_judgments(self, report: dict) -> None:
        done_ids = [entry_id for entry_id, task in self.scope_review_tasks.items() if task.done()]
        for entry_id in done_ids:
            task = self.scope_review_tasks.pop(entry_id)
            entry = self.board.get(entry_id)
            if entry is None:
                self.scope_reviewed_ids.add(entry_id)
                continue
            try:
                judgment = task.result()
            except Exception:
                self.scope_reviewed_ids.add(entry_id)
                continue
            self.scope_reviewed_ids.add(entry_id)
            if getattr(judgment, "verdict", "") != "local_env":
                continue
            reason = getattr(judgment, "reason", "") or "LLM 复核后判断更像本地环境服务，不像题目目标面。"
            await self._mark_scope_violation(entry, report, reason=reason)

    async def _mark_scope_violation(self, entry: BoardEntry, report: dict, *, reason: str) -> None:
        await self.board.set_status(entry.id, EntryStatus.REFUTED)
        await self.board.post(
            type=EntryType.DEAD_END,
            author="Merlin",
            title=f"越界目标面:{entry.title}",
            body=f"源条目 {entry.id} 明显落在本机/宿主/worker loopback 或环境服务面，不属于题目明确目标范围。{reason}",
            confidence=0.95,
            refs=[entry.id],
            tags=["dead_end", "scope_violation", "local_env"] + entry.tags,
        )
        self.scope_violation_ids.add(entry.id)
        report["scope_violations"].append(entry.id)

    def _init_funsearch(
        self,
        funsearch_run_dir: str | Path | None,
        funsearch_control: MerlinFunSearchControl | None,
    ) -> MerlinFunSearchControl | None:
        if funsearch_control is not None:
            return funsearch_control
        if self.search_mode != "funsearch":
            return None
        run_dir: Path | None = None
        if funsearch_run_dir is not None:
            run_dir = Path(funsearch_run_dir)
        elif self.board._jsonl_path is not None:
            run_dir = self.board._jsonl_path.parent / "merlin_funsearch"
        if run_dir is None:
            return None
        return MerlinFunSearchControl(
            run_dir,
            rerank_top_k=self.funsearch_rerank_top_k,
            reranker=self.funsearch_reranker,
        )

    def _build_redirect_pool(self) -> list[BoardEntry]:
        selected: list[BoardEntry] = []
        if self.search_mode == "funsearch" and self.funsearch is not None:
            choice = self.funsearch.select_candidate()
            if choice is not None:
                entry = self.board.get(choice.board_entry_id)
                if entry is not None and entry.status != EntryStatus.REFUTED:
                    selected.append(entry)
                    self.funsearch.append_timeline(
                        f"- redirect parent `{choice.candidate_id}` ({choice.island}) -> {entry.id} {entry.title}"
                    )

        candidates = sorted(self.board.open_next_steps(), key=lambda e: e.score(), reverse=True)
        facts = sorted(
            (
                e
                for e in self.board.by_type(EntryType.FACT)
                if e.claimed_by is None and e.status == EntryStatus.OPEN
            ),
            key=lambda e: e.updated_at,
        )

        pool: list[BoardEntry] = []
        seen: set[str] = set()
        for entry in [*selected, *candidates, *facts]:
            if entry.id in seen:
                continue
            seen.add(entry.id)
            pool.append(entry)
        return pool
