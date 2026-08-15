"""digest 测试:按需投喂、死路必给、body 不泄漏。"""

import pytest

from roundtable.core import Board, EntryType, build_digest


async def test_digest_excludes_body_but_keeps_meta():
    board = Board()
    e = await board.post(
        type=EntryType.HYPOTHESIS, author="A", title="可能是 SQLi",
        body="超长的工具输出" * 500, confidence=0.8, tags=["sqli"],
    )
    await board.endorse(e.id, "B")
    d = build_digest(board, "Lancelot", knight_tags=["sqli"])
    rendered = d.render()
    assert "可能是 SQLi" in rendered           # 标题在
    assert "超长的工具输出" not in rendered      # body 不泄漏
    assert "conf=0.8" in rendered              # 元信息在


async def test_dead_ends_always_listed():
    board = Board()
    await board.post(type=EntryType.DEAD_END, author="Merlin", title="此路不通:LFI")
    d = build_digest(board, "Gawain")
    assert any("此路不通" in ln.title for ln in d.dead_ends)


async def test_top_entries_ranked_by_score():
    board = Board()
    low = await board.post(type=EntryType.HYPOTHESIS, author="A", title="low", confidence=0.2)
    high = await board.post(type=EntryType.HYPOTHESIS, author="B", title="high", confidence=0.9)
    await board.endorse(high.id, "C")
    d = build_digest(board, "X", top_k=5)
    assert d.top_entries[0].id == high.id
    assert d.top_entries[0].title == "high"


async def test_relevant_filtered_by_knight_tags():
    board = Board()
    # 一个高分条目占据 top,避免相关条目被 top 吸走
    await board.post(type=EntryType.HYPOTHESIS, author="Z", title="dominant", confidence=0.95)
    await board.post(type=EntryType.FACT, author="A", title="crypto thing", tags=["rsa"], confidence=0.3)
    await board.post(type=EntryType.FACT, author="A", title="web thing", tags=["http"], confidence=0.3)
    d = build_digest(board, "Galahad", knight_tags=["rsa"], top_k=1)
    titles = [ln.title for ln in d.relevant_entries]
    assert "crypto thing" in titles
    assert "web thing" not in titles   # 标签不匹配,不进相关
