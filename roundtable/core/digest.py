"""桌面简报 (digest) —— 防 token 爆炸的关键。

骑士每轮**不接收整块黑板**,而是接收一份为它定制的简报:
- 高价值条目的**标题 + 元信息**(不含完整 body)
- 与该骑士姿态相关的条目(标签匹配)
- **全部死路的标题**(必须全给,避免重复劳动)
- 最新 flag_candidate 状态

骑士想看某条详情时显式调用 read_entry(id) 拉取完整 body。
这把『自由交流』变成**按需拉取**,而非全量广播。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .board import Board
from .entry import BoardEntry, EntryStatus, EntryType


@dataclass
class DigestLine:
    """简报中的一行:只给摘要级信息,不含 body。"""

    id: str
    type: str
    author: str
    title: str
    confidence: float
    endorse_count: int
    challenge_count: int
    status: str
    claimed_by: str | None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, e: BoardEntry) -> "DigestLine":
        return cls(
            id=e.id,
            type=e.type.value,
            author=e.author,
            title=e.title,
            confidence=round(e.confidence, 2),
            endorse_count=e.endorse_count,
            challenge_count=e.challenge_count,
            status=e.status.value,
            claimed_by=e.claimed_by,
            tags=list(e.tags),
        )


@dataclass
class Digest:
    """给某个骑士的一份桌面简报。"""

    for_knight: str
    top_entries: list[DigestLine]        # 全局高价值条目
    relevant_entries: list[DigestLine]   # 与该骑士姿态/标签相关
    dead_ends: list[DigestLine]          # 全部死路(必给)
    open_next_steps: list[DigestLine]    # 待认领的下一步
    flag_candidates: list[DigestLine]    # flag 候选状态
    board_size: int

    def render(self) -> str:
        """渲染成给 LLM 骑士看的文本简报。"""
        out: list[str] = [f"# 圆桌桌面简报 (给 {self.for_knight})", f"当前黑板共 {self.board_size} 条。\n"]

        def block(title: str, lines: list[DigestLine], empty: str = "(空)") -> None:
            out.append(f"## {title}")
            if not lines:
                out.append(empty)
            for ln in lines:
                claim = f" [认领:{ln.claimed_by}]" if ln.claimed_by else ""
                out.append(
                    f"- [{ln.id}] ({ln.type}, conf={ln.confidence}, "
                    f"+{ln.endorse_count}/-{ln.challenge_count}, {ln.status}{claim}) "
                    f"{ln.author}: {ln.title}"
                    + (f"  #{' #'.join(ln.tags)}" if ln.tags else "")
                )
            out.append("")

        if self.flag_candidates:
            block("⚑ FLAG 候选(优先关注)", self.flag_candidates)
        block("🔥 高价值条目", self.top_entries)
        block("🎯 与你相关", self.relevant_entries)
        block("⛔ 死路(切勿重走)", self.dead_ends, empty="(暂无死路)")
        block("📌 待认领的下一步", self.open_next_steps, empty="(暂无)")
        return "\n".join(out)


def build_digest(
    board: Board,
    for_knight: str,
    *,
    knight_tags: list[str] | None = None,
    top_k: int = 8,
    relevant_k: int = 6,
) -> Digest:
    """为某骑士构建定制简报。

    knight_tags: 该骑士姿态偏好的标签,用于筛 relevant_entries。
    """
    knight_tags = knight_tags or []
    all_entries = board.all()

    # 高价值:按 score 排序,排除死路(死路单列)
    ranked = sorted(
        (e for e in all_entries if e.type != EntryType.DEAD_END),
        key=lambda e: e.score(),
        reverse=True,
    )
    top = [DigestLine.of(e) for e in ranked[:top_k]]

    # 相关:标签命中该骑士偏好,或该骑士自己尚未看过的 open 条目
    top_ids = {e.id for e in ranked[:top_k]}
    relevant: list[DigestLine] = []
    if knight_tags:
        tagset = set(knight_tags)
        for e in ranked:
            if e.id in top_ids:
                continue
            if tagset & set(e.tags):
                relevant.append(DigestLine.of(e))
            if len(relevant) >= relevant_k:
                break

    dead = [DigestLine.of(e) for e in board.dead_ends()]
    next_steps = [DigestLine.of(e) for e in board.open_next_steps()]
    flags = [
        DigestLine.of(e)
        for e in board.flag_candidates()
        if e.status not in (EntryStatus.REFUTED,)
    ]

    return Digest(
        for_knight=for_knight,
        top_entries=top,
        relevant_entries=relevant,
        dead_ends=dead,
        open_next_steps=next_steps,
        flag_candidates=flags,
        board_size=len(board),
    )
