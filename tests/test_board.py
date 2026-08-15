"""黑板核心测试:并发安全、append-mostly、endorse/challenge/claim、持久化复盘。"""

import asyncio

import pytest

from roundtable.core import Board, BoardTools, EntryStatus, EntryType


async def test_post_assigns_unique_ids_and_indexes():
    board = Board()
    e1 = await board.post(type=EntryType.FACT, author="Gawain", title="a", tags=["x"])
    e2 = await board.post(type=EntryType.HYPOTHESIS, author="Mordred", title="b", tags=["x", "y"])
    assert e1.id != e2.id
    assert len(board) == 2
    assert board.by_type(EntryType.FACT) == [e1]
    assert {e.id for e in board.by_tag("x")} == {e1.id, e2.id}
    assert board.by_author("Mordred") == [e2]


async def test_endorse_is_idempotent_per_knight():
    board = Board()
    e = await board.post(type=EntryType.HYPOTHESIS, author="A", title="h")
    assert await board.endorse(e.id, "B")
    assert await board.endorse(e.id, "B")  # 重复幂等
    assert await board.endorse(e.id, "C")
    assert board.get(e.id).endorse_count == 2


async def test_challenge_requires_reason_and_accumulates():
    board = Board()
    e = await board.post(type=EntryType.HYPOTHESIS, author="A", title="h")
    await board.challenge(e.id, "B", "站不住脚")
    await board.challenge(e.id, "C", "我复现失败")
    got = board.get(e.id)
    assert got.challenge_count == 2
    assert got.net_support == -2
    assert all(c.reason for c in got.challenges)


async def test_claim_prevents_collision():
    board = Board()
    e = await board.post(type=EntryType.NEXT_STEP, author="A", title="dig")
    assert await board.claim(e.id, "Lancelot")
    assert not await board.claim(e.id, "Mordred")   # 已被认领,失败
    assert await board.claim(e.id, "Lancelot")      # 同一人再认领 OK
    assert board.get(e.id).claimed_by == "Lancelot"
    assert board.get(e.id).status == EntryStatus.CLAIMED


async def test_concurrent_posts_do_not_lose_entries():
    """并发写不丢条目、不重 id —— append-mostly + Lock 的核心保证。"""
    board = Board()

    async def spammer(name: str, n: int):
        for i in range(n):
            await board.post(type=EntryType.FACT, author=name, title=f"{name}-{i}")

    await asyncio.gather(*(spammer(f"K{k}", 50) for k in range(5)))
    assert len(board) == 250
    ids = [e.id for e in board.all()]
    assert len(set(ids)) == 250   # 无重复 id


async def test_boardtools_binds_author():
    board = Board()
    tools = BoardTools(board, "Percival")
    e = await tools.post_entry(type="fact", title="via tools")
    assert e.author == "Percival"
    assert await tools.endorse(e.id)
    assert board.get(e.id).endorsements == ["Percival"]


async def test_jsonl_persistence_and_replay(tmp_path):
    path = tmp_path / "board.jsonl"
    board = Board(jsonl_path=path)
    e = await board.post(type=EntryType.HYPOTHESIS, author="A", title="h", tags=["t"])
    await board.endorse(e.id, "B")
    await board.challenge(e.id, "C", "no")
    await board.claim(e.id, "D")

    # 从事件日志重建,状态应一致
    replayed = Board.replay(path)
    r = replayed.get(e.id)
    assert r is not None
    assert r.title == "h"
    assert r.endorsements == ["B"]
    assert r.challenge_count == 1
    assert r.claimed_by == "D"
    assert r.status == EntryStatus.CLAIMED
