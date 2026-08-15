"""Kay 实时日志显示名测试。"""

from roundtable.core import Board
from roundtable.roles import Arthur, Kay, Merlin


def test_display_name_adds_chinese_alias():
    board = Board()
    kay = Kay(board, [], Merlin(board), Arthur(board))

    assert kay._display_name("Mordred") == "Mordred·破坏者"
    assert kay._display_name("Gawain") == "Gawain·侦察兵"
    assert kay._display_name("Unknown") == "Unknown"
