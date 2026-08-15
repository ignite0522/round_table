"""骑士基类 —— mock 骑士与真骑士共享的形状。

一个骑士的生命周期就是不断执行 cycle():读简报 → 干活 → 写黑板。
Kay 的主循环反复调度每个骑士的 cycle。
"""

from __future__ import annotations

import abc

from ..core.tools import BoardTools
from .policy import KnightPolicy


class Knight(abc.ABC):
    def __init__(self, policy: KnightPolicy, tools: BoardTools):
        self.policy = policy
        self.tools = tools
        self.name = policy.name
        self.idle_cycles = 0        # 连续无有效产出的 cycle 数(Merlin 用于判定卡住)
        self.total_posts = 0
        self.closing_mode = False   # 收束模式开关(Merlin 可切)

    @abc.abstractmethod
    async def cycle(self) -> int:
        """执行一个 cycle。返回本轮新产出的有效条目数(0 表示空转)。"""
        ...

    def note_productive(self, n_posts: int) -> None:
        """由子类在 cycle 末尾调用,更新空转计数。"""
        self.total_posts += n_posts
        if n_posts > 0:
            self.idle_cycles = 0
        else:
            self.idle_cycles += 1
