"""黑板条目类型与数据结构。

黑板是圆桌系统的唯一真相源。它是 **append-mostly** 的:骑士只能新增条目,
或对已有条目 endorse / challenge / claim,不能删除或改写别人的条目。这保留了
完整的推理轨迹,便于回溯与 Merlin 的语义分析。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum


class EntryType(str, Enum):
    """条目类型。结构化是让『接纳/不接纳』变成可执行信号的前提。"""

    FACT = "fact"                    # 客观观察:文件是 ELF、端口开着、有个 base64 串。无需推断
    HYPOTHESIS = "hypothesis"        # 假设:这可能是 SQL 注入 / RSA 共模攻击
    ARTIFACT = "artifact"            # 产出物:反编译代码、解密脚本、中间文件路径、请求响应
    TOOL_OUTPUT = "tool_output"      # 工具原始输出(可折叠,避免污染他人上下文)
    DEAD_END = "dead_end"            # 死路:这条线试过了不通,原因是……(防重复劳动)
    NEXT_STEP = "next_step"          # 建议的下一步动作(可被别的骑士认领)
    FLAG_CANDIDATE = "flag_candidate"  # flag 候选,交给 Arthur 验证


class EntryStatus(str, Enum):
    OPEN = "open"          # 未被认领,待处理
    CLAIMED = "claimed"    # 被某骑士认领深挖
    RESOLVED = "resolved"  # 已闭环 / 被证实
    REFUTED = "refuted"    # 被证伪 / 判定为死路


@dataclass
class Challenge:
    """对某条目的质疑。不接纳必须带理由,不能纯反对。"""

    author: str
    reason: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BoardEntry:
    """黑板上的一条结构化条目。"""

    id: str
    type: EntryType
    author: str
    title: str                        # 一行摘要,供他人快速扫描
    body: str = ""                    # 详情(工具输出折叠存储,digest 默认只给摘要)
    confidence: float = 0.5           # 0~1,作者的置信度
    refs: list[str] = field(default_factory=list)          # 引用的其他条目 id,形成推理图谱
    tags: list[str] = field(default_factory=list)          # 便于检索:["login","sqli"]
    endorsements: list[str] = field(default_factory=list)  # 认可它的骑士名
    challenges: list[Challenge] = field(default_factory=list)
    status: EntryStatus = EntryStatus.OPEN
    claimed_by: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ——— 派生属性:供 Merlin / digest 排序用 ———

    @property
    def endorse_count(self) -> int:
        return len(self.endorsements)

    @property
    def challenge_count(self) -> int:
        return len(self.challenges)

    @property
    def net_support(self) -> int:
        """净支持度 = 认可数 - 质疑数。死路检测的信号之一。"""
        return self.endorse_count - self.challenge_count

    def score(self) -> float:
        """条目权重:置信度 + 净支持,供 digest 排序与收束模式选线。"""
        return self.confidence + 0.15 * self.net_support

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BoardEntry":
        d = dict(d)
        d["type"] = EntryType(d["type"])
        d["status"] = EntryStatus(d.get("status", "open"))
        d["challenges"] = [Challenge(**c) for c in d.get("challenges", [])]
        return cls(**d)
