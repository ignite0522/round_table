"""Kay 宿主侧 URL 预抓取测试。"""

from roundtable.core import Board, EntryType
from roundtable.roles import Arthur, Kay, Merlin, Problem


async def test_deal_posts_host_prefetch_result():
    board = Board()
    kay = Kay(board, [], Merlin(board), Arthur(board))

    def fake_fetch(url):
        return {
            "summary": "HTTP 200",
            "body": f"URL: {url}\nHTTP status: 200\n\nBody first bytes:\nok",
        }

    kay._host_fetch_url = fake_fetch
    await kay.deal(Problem(title="web", url="http://example.test/"))

    entries = board.all()
    assert [e.type for e in entries] == [EntryType.FACT, EntryType.TOOL_OUTPUT]
    assert entries[1].author == "Kay"
    assert "host_fetch" in entries[1].tags
    assert "HTTP status: 200" in entries[1].body


async def test_deal_can_disable_host_prefetch():
    board = Board()
    kay = Kay(board, [], Merlin(board), Arthur(board), host_prefetch=False)
    await kay.deal(Problem(title="web", url="http://example.test/"))

    assert len(board.all()) == 1
