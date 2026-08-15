"""脚本模拟骑士(无 LLM)—— 用于验证协作机制本身正确。

MockKnight 不调用任何 LLM。它把『大脑』外置成一个可插拔的 behavior 回调,
由具体场景(examples/)提供姿态相关的脚本化行为。这样:
- 协作骨架(读简报→干活→写黑板→endorse/challenge/claim)完全脱离 LLM 即可跑通并测试;
- Phase 2 只需把 behavior 换成 Codex CLI cycle,骨架不变。

behavior 签名:
    async def behavior(knight: MockKnight, digest: Digest) -> int
返回本轮新产出的有效条目数。
"""

from __future__ import annotations

from typing import Awaitable, Callable

from ..core.digest import Digest
from ..core.tools import BoardTools
from .base import Knight
from .policy import KnightPolicy

Behavior = Callable[["MockKnight", Digest], Awaitable[int]]


class MockKnight(Knight):
    def __init__(self, policy: KnightPolicy, tools: BoardTools, behavior: Behavior):
        super().__init__(policy, tools)
        self._behavior = behavior

    async def cycle(self) -> int:
        # 骨架:按 policy 决定是否先读简报,再交给 behavior 干活。
        digest = self.tools.read_board_digest()
        n = await self._behavior(self, digest)
        self.note_productive(n)
        return n
