"""圆桌 —— 共享黑板。

所有骑士协作的中心。核心特性:
- **append-mostly**:新增条目;对已有条目只能 endorse / challenge / claim。
- **并发安全**:写操作用 asyncio.Lock 保护,读走快照。
- **JSONL 持久化**:每次写入 append 一行事件,天然可复盘与崩溃恢复。
- **倒排索引**:按 tag / type / author 建索引,供 Merlin 快速生成 digest。
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from collections import defaultdict
from pathlib import Path

from .entry import BoardEntry, Challenge, EntryStatus, EntryType


class Board:
    def __init__(self, jsonl_path: str | Path | None = None):
        self._entries: dict[str, BoardEntry] = {}
        self._lock = asyncio.Lock()
        self._id_counter = itertools.count(1)

        # 倒排索引
        self._by_tag: dict[str, set[str]] = defaultdict(set)
        self._by_type: dict[EntryType, set[str]] = defaultdict(set)
        self._by_author: dict[str, set[str]] = defaultdict(set)

        # 持久化
        self._jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self._jsonl_path:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        # 实时事件回调:每次 post/endorse/challenge/claim 触发一次,供 UI 即时打印。
        # 签名:on_event(kind: str, entry: BoardEntry, extra: dict) -> None
        self.on_event = None

    # ——————————————————————————— 内部工具 ———————————————————————————

    def _new_id(self, entry_type: EntryType) -> str:
        return f"{entry_type.value[:4]}-{next(self._id_counter):04d}"

    def _index(self, entry: BoardEntry) -> None:
        for tag in entry.tags:
            self._by_tag[tag].add(entry.id)
        self._by_type[entry.type].add(entry.id)
        self._by_author[entry.author].add(entry.id)

    def _append_jsonl(self, event: str, payload: dict) -> None:
        if not self._jsonl_path:
            return
        rec = {"ts": time.time(), "event": event, **payload}
        with self._jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _emit(self, kind: str, entry: "BoardEntry", **extra) -> None:
        cb = self.on_event
        if cb is None:
            return
        try:
            cb(kind, entry, extra)
        except Exception:
            pass  # UI 回调不得影响黑板逻辑

    # ——————————————————————————— 写操作(加锁) ———————————————————————————

    async def post(
        self,
        *,
        type: EntryType | str,
        author: str,
        title: str,
        body: str = "",
        confidence: float = 0.5,
        refs: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> BoardEntry:
        """发布一条新条目。返回带 id 的条目。"""
        async with self._lock:
            etype = EntryType(type) if not isinstance(type, EntryType) else type
            entry = BoardEntry(
                id=self._new_id(etype),
                type=etype,
                author=author,
                title=title,
                body=body,
                confidence=max(0.0, min(1.0, confidence)),
                refs=list(refs or []),
                tags=list(tags or []),
            )
            self._entries[entry.id] = entry
            self._index(entry)
            self._append_jsonl("post", {"entry": entry.to_dict()})
        self._emit("post", entry)
        return entry

    async def endorse(self, entry_id: str, author: str) -> bool:
        """认可一条条目。同一骑士重复 endorse 幂等。"""
        async with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False
            if author not in entry.endorsements:
                entry.endorsements.append(author)
                entry.updated_at = time.time()
                self._append_jsonl("endorse", {"entry_id": entry_id, "author": author})
        if entry is not None:
            self._emit("endorse", entry, by=author)
        return True

    async def challenge(self, entry_id: str, author: str, reason: str) -> bool:
        """质疑一条条目(必须带理由)。质疑累积可使其转 refuted(由 Merlin 判定)。"""
        async with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False
            entry.challenges.append(Challenge(author=author, reason=reason))
            entry.updated_at = time.time()
            self._append_jsonl(
                "challenge", {"entry_id": entry_id, "author": author, "reason": reason}
            )
        self._emit("challenge", entry, by=author, reason=reason)
        return True

    async def claim(self, entry_id: str, author: str) -> bool:
        """认领一条条目深挖。已被他人认领则失败(防撞车)。"""
        async with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False
            if entry.claimed_by is not None and entry.claimed_by != author:
                return False
            entry.claimed_by = author
            entry.status = EntryStatus.CLAIMED
            entry.updated_at = time.time()
            self._append_jsonl("claim", {"entry_id": entry_id, "author": author})
        self._emit("claim", entry, by=author)
        return True

    async def set_status(self, entry_id: str, status: EntryStatus) -> bool:
        """更新条目状态(Merlin 标记 dead_end / Arthur 标记 resolved 等)。"""
        async with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False
            entry.status = status
            entry.updated_at = time.time()
            self._append_jsonl("status", {"entry_id": entry_id, "status": status.value})
            return True

    # ——————————————————————————— 读操作(快照) ———————————————————————————

    def get(self, entry_id: str) -> BoardEntry | None:
        return self._entries.get(entry_id)

    def all(self) -> list[BoardEntry]:
        return list(self._entries.values())

    def by_type(self, entry_type: EntryType) -> list[BoardEntry]:
        return [self._entries[i] for i in self._by_type.get(entry_type, set())]

    def by_tag(self, tag: str) -> list[BoardEntry]:
        return [self._entries[i] for i in self._by_tag.get(tag, set())]

    def by_author(self, author: str) -> list[BoardEntry]:
        return [self._entries[i] for i in self._by_author.get(author, set())]

    def dead_ends(self) -> list[BoardEntry]:
        return self.by_type(EntryType.DEAD_END)

    def flag_candidates(self) -> list[BoardEntry]:
        return self.by_type(EntryType.FLAG_CANDIDATE)

    def open_next_steps(self) -> list[BoardEntry]:
        return [
            e
            for e in self.by_type(EntryType.NEXT_STEP)
            if e.status == EntryStatus.OPEN and e.claimed_by is None
        ]

    def __len__(self) -> int:
        return len(self._entries)

    # ——————————————————————————— 复盘 ———————————————————————————

    @classmethod
    def replay(cls, jsonl_path: str | Path) -> "Board":
        """从 JSONL 事件日志重建黑板状态(崩溃恢复 / 复盘)。"""
        board = cls(jsonl_path=None)
        path = Path(jsonl_path)
        if not path.exists():
            return board
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            event = rec.get("event")
            if event == "post":
                entry = BoardEntry.from_dict(rec["entry"])
                board._entries[entry.id] = entry
                board._index(entry)
            elif event == "endorse":
                e = board._entries.get(rec["entry_id"])
                if e and rec["author"] not in e.endorsements:
                    e.endorsements.append(rec["author"])
            elif event == "challenge":
                e = board._entries.get(rec["entry_id"])
                if e:
                    e.challenges.append(
                        Challenge(author=rec["author"], reason=rec["reason"])
                    )
            elif event == "claim":
                e = board._entries.get(rec["entry_id"])
                if e:
                    e.claimed_by = rec["author"]
                    e.status = EntryStatus.CLAIMED
            elif event == "status":
                e = board._entries.get(rec["entry_id"])
                if e:
                    e.status = EntryStatus(rec["status"])
        return board
