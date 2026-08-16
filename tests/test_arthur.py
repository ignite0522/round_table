"""Arthur 测试:flag 格式校验、真验证器、幻觉误报隔离。"""

import pytest

from roundtable.core import Board, EntryStatus, EntryType
from roundtable.roles import Arthur


async def test_valid_flag_format_resolves():
    board = Board()
    await board.post(
        type=EntryType.FLAG_CANDIDATE, author="Percival",
        title="拿到了!", body="flag{h3llo_w0rld}", confidence=0.9,
    )
    arthur = Arthur(board)
    flag = await arthur.check()
    assert flag == "flag{h3llo_w0rld}"
    assert arthur.winning_flag == flag


async def test_prefixed_flag_format_resolves():
    board = Board()
    await board.post(
        type=EntryType.FLAG_CANDIDATE,
        author="Percival",
        title="命中",
        body="CTF2{0ea3703a-3a7e-4990-9c78-c322c931891a}",
        confidence=0.9,
    )
    arthur = Arthur(board)
    flag = await arthur.check()
    assert flag == "CTF2{0ea3703a-3a7e-4990-9c78-c322c931891a}"
    assert arthur.winning_flag == flag


async def test_bad_format_is_refuted_not_accepted():
    board = Board()
    e = await board.post(
        type=EntryType.FLAG_CANDIDATE, author="Gawain",
        title="也许是这个", body="just some random text no braces", confidence=0.9,
    )
    arthur = Arthur(board)
    flag = await arthur.check()
    assert flag is None
    assert board.get(e.id).status == EntryStatus.REFUTED


async def test_verifier_rejects_wrong_flag():
    board = Board()
    e = await board.post(
        type=EntryType.FLAG_CANDIDATE, author="Mordred",
        title="猜的", body="flag{wrong_guess}", confidence=0.5,
    )

    async def verifier(flag: str) -> bool:
        return flag == "flag{correct}"

    arthur = Arthur(board, verifier=verifier)
    flag = await arthur.check()
    assert flag is None
    assert board.get(e.id).status == EntryStatus.REFUTED


async def test_verifier_accepts_right_flag():
    board = Board()
    await board.post(
        type=EntryType.FLAG_CANDIDATE, author="Lancelot",
        title="确认", body="flag{correct}", confidence=0.95,
    )

    async def verifier(flag: str) -> bool:
        return flag == "flag{correct}"

    arthur = Arthur(board, verifier=verifier)
    assert await arthur.check() == "flag{correct}"


async def test_candidate_processed_once():
    board = Board()
    await board.post(
        type=EntryType.FLAG_CANDIDATE, author="A", title="x", body="no flag here",
    )
    arthur = Arthur(board)
    assert await arthur.check() is None
    # 第二次不再重复处理(已在 _seen 中)
    assert await arthur.check() is None
