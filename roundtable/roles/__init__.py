"""圆桌框架角色:Kay(发牌/主循环)、Merlin(元认知)、Arthur(验旗)。"""

from .arthur import Arthur
from .kay import Kay, MeetingResult, Problem
from .merlin import Merlin, MerlinDirective
from .merlin_scope_judge import CodexScopeJudge, ScopeJudgment

__all__ = [
    "Arthur",
    "Kay",
    "MeetingResult",
    "Merlin",
    "MerlinDirective",
    "CodexScopeJudge",
    "Problem",
    "ScopeJudgment",
]
