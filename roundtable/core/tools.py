"""黑板工具接口层 —— 骑士与黑板之间的唯一交互面。

这 6 个操作是骑士能对圆桌做的全部事情。刻意做成框架无关的 async facade:
- Phase 1 的脚本模拟骑士直接调用这些方法;
- Phase 2 的 Codex 骑士把结构化输出回放到这些方法上。

两者共享同一套语义,保证『脚本验证过的协作机制』和『真骑士』行为一致。
"""

from __future__ import annotations

from .board import Board
from .digest import Digest, build_digest
from .entry import BoardEntry, EntryType


def _empty_digest(for_knight: str) -> Digest:
    return Digest(
        for_knight=for_knight,
        top_entries=[],
        relevant_entries=[],
        dead_ends=[],
        open_next_steps=[],
        flag_candidates=[],
        board_size=0,
    )


class BoardTools:
    """绑定到某个骑士身份的黑板工具句柄。

    每个骑士拿到一个 BoardTools(board, knight_name),
    这样 endorse/challenge/post 的 author 自动带上,骑士无需自己填名字。
    """

    def __init__(
        self,
        board: Board,
        knight_name: str,
        *,
        knight_tags: list[str] | None = None,
        can_read_board: bool = True,
        can_endorse: bool = True,
        can_challenge: bool = True,
        can_claim: bool = True,
    ):
        self.board = board
        self.knight = knight_name
        self.knight_tags = knight_tags or []
        self.can_read_board = can_read_board
        self.can_endorse = can_endorse
        self.can_challenge = can_challenge
        self.can_claim = can_claim

    # 1) 读桌面简报(默认入口,不含 body)
    def read_board_digest(self, *, top_k: int = 8, relevant_k: int = 6) -> Digest:
        if not self.can_read_board:
            return _empty_digest(self.knight)
        return build_digest(
            self.board,
            self.knight,
            knight_tags=self.knight_tags,
            top_k=top_k,
            relevant_k=relevant_k,
        )

    # 2) 按需拉取某条完整详情(含 body)
    def read_entry(self, entry_id: str) -> BoardEntry | None:
        if not self.can_read_board:
            return None
        return self.board.get(entry_id)

    # 3) 发布新条目
    async def post_entry(
        self,
        *,
        type: EntryType | str,
        title: str,
        body: str = "",
        confidence: float = 0.5,
        refs: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> BoardEntry:
        etype = EntryType(type) if isinstance(type, str) else type
        return await self.board.post(
            type=etype,
            author=self.knight,
            title=title,
            body=body,
            confidence=confidence,
            refs=refs,
            tags=tags,
        )

    # 4) 认可(接纳)
    async def endorse(self, entry_id: str) -> bool:
        if not self.can_endorse:
            return False
        return await self.board.endorse(entry_id, self.knight)

    # 5) 质疑(不接纳,必带理由)
    async def challenge(self, entry_id: str, reason: str) -> bool:
        if not self.can_challenge:
            return False
        return await self.board.challenge(entry_id, self.knight, reason)

    # 6) 认领深挖(防撞车)
    async def claim(self, entry_id: str) -> bool:
        if not self.can_claim:
            return False
        return await self.board.claim(entry_id, self.knight)
