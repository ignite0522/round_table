"""Arthur —— Flag 仲裁者。

监听 flag_candidate,校验格式,(可选)真提交验证,通过则宣布散会。
flag_candidate 与 resolved 分离:防止幻觉误报直接终止会议。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..core.board import Board
from ..core.entry import BoardEntry, EntryStatus, EntryType

@dataclass(slots=True)
class VerificationResult:
    accepted: bool
    should_stop: bool = True
    reason: str | None = None


# 可选的真验证器:给定 flag 字符串,返回是否正确(如调用赛题 submit 接口)。
Verifier = Callable[[str], Awaitable[bool | VerificationResult]]
DEFAULT_FLAG_REGEX = r"[A-Za-z0-9_]+\{[^}\n]*\}"


class Arthur:
    def __init__(
        self,
        board: Board,
        *,
        flag_regex: str = DEFAULT_FLAG_REGEX,
        verifier: Verifier | None = None,
    ):
        self.board = board
        self.flag_re = re.compile(flag_regex)
        self.verifier = verifier
        self._seen: set[str] = set()   # 已处理过的候选条目 id
        self._seen_flags: dict[str, VerificationResult] = {}
        self.winning_flag: str | None = None

    def extract_flag(self, text: str) -> str | None:
        m = self.flag_re.search(text or "")
        return m.group(0) if m else None

    def _candidate_entries(self) -> list[BoardEntry]:
        entries = list(self.board.flag_candidates())
        for entry in self.board.all():
            if entry.type not in {EntryType.ARTIFACT, EntryType.TOOL_OUTPUT}:
                continue
            if entry.confidence < 0.98:
                continue
            flag = self.extract_flag(entry.title) or self.extract_flag(entry.body)
            if not flag:
                continue
            entries.append(entry)
        entries.sort(key=lambda e: e.created_at)
        return entries

    @staticmethod
    def _normalize_verification(result: bool | VerificationResult) -> VerificationResult:
        if isinstance(result, VerificationResult):
            return result
        return VerificationResult(accepted=bool(result))

    async def check(self) -> str | None:
        """扫描 flag 候选。返回确认通过的 flag(否则 None)。"""
        for entry in self._candidate_entries():
            if entry.id in self._seen or entry.status == EntryStatus.REFUTED:
                continue
            self._seen.add(entry.id)

            flag = self.extract_flag(entry.title) or self.extract_flag(entry.body)
            if not flag:
                await self.board.challenge(
                    entry.id, "Arthur", "格式不符:未匹配到合法 flag 格式。"
                )
                await self.board.set_status(entry.id, EntryStatus.REFUTED)
                continue

            prior = self._seen_flags.get(flag)
            if prior is not None:
                if prior.accepted:
                    await self.board.set_status(entry.id, EntryStatus.RESOLVED)
                    await self.board.post(
                        type=EntryType.FACT,
                        author="Arthur",
                        title=f"✔ FLAG 已确认(重复候选):{flag}",
                        body=prior.reason or "该 flag 之前已验证过，本次不再重复提交。",
                        confidence=1.0,
                        tags=["resolved", "flag", "duplicate"],
                    )
                    if prior.should_stop:
                        self.winning_flag = flag
                        return flag
                    continue
                await self.board.challenge(
                    entry.id, "Arthur", prior.reason or f"重复候选，之前已判失败:{flag}"
                )
                await self.board.set_status(entry.id, EntryStatus.REFUTED)
                continue

            # 有真验证器则真提交;否则仅凭格式通过(Phase 1)。
            verdict = VerificationResult(accepted=True)
            if self.verifier is not None:
                verdict = self._normalize_verification(await self.verifier(flag))
            self._seen_flags[flag] = verdict

            if verdict.accepted:
                await self.board.set_status(entry.id, EntryStatus.RESOLVED)
                if verdict.should_stop:
                    await self.board.post(
                        type=EntryType.FACT,
                        author="Arthur",
                        title=f"✔ FLAG 已确认:{flag} — 圆桌会议结束。",
                        body=f"来源条目 {entry.id}(作者 {entry.author})。",
                        confidence=1.0,
                        tags=["resolved", "flag"],
                    )
                    self.winning_flag = flag
                    return flag
                await self.board.post(
                    type=EntryType.FACT,
                    author="Arthur",
                    title=f"✔ FLAG 已确认(继续寻找其余 flag):{flag}",
                    body=verdict.reason or f"来源条目 {entry.id}(作者 {entry.author})。",
                    confidence=1.0,
                    tags=["resolved", "flag", "partial"],
                )
                continue

            await self.board.challenge(
                entry.id, "Arthur", verdict.reason or f"提交验证未通过:{flag}"
            )
            await self.board.set_status(entry.id, EntryStatus.REFUTED)

        return None
