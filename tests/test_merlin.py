"""Merlin 测试:死路检测、重新指向卡住的骑士、收束模式。"""

import time

import pytest

from roundtable.core import Board, EntryType, EntryStatus
from roundtable.roles import Merlin
from roundtable.funsearch.merlin_control import MerlinFunSearchControl, POPULATION_SCRIPT, SelectedCandidate


class _FakeKnight:
    def __init__(self, name, idle=0):
        self.name = name
        self.idle_cycles = idle
        self.closing_mode = False


class _FakeFunSearch:
    def __init__(self, entry_id=None):
        self.entry_id = entry_id
        self.synced = []
        self.timeline = []

    def sync_board(self, entries):
        self.synced.append([e.id for e in entries])
        return {"registered": [e.id for e in entries], "recorded": []}

    def select_candidate(self):
        if not self.entry_id:
            return None

        class _Choice:
            island = "I00"
            candidate_id = "I00CFAKE"
            board_entry_id = self.entry_id
            objective = 42.0
            hypothesis = "test choice"

        return _Choice()

    def append_timeline(self, line):
        self.timeline.append(line)


async def test_dead_end_detection_marks_and_broadcasts():
    board = Board()
    e = await board.post(type=EntryType.HYPOTHESIS, author="A", title="试试 LFI", tags=["lfi"])
    await board.challenge(e.id, "B", "路径过滤了")
    # 手动把 updated_at 推到过去,制造『久无进展』
    board.get(e.id).updated_at = 0.0
    merlin = Merlin(board, stale_seconds=90.0)
    report = await merlin.tick([_FakeKnight("A")], now=1000.0)
    assert e.id in report["dead_ends_marked"]
    assert board.get(e.id).status == EntryStatus.REFUTED
    assert any("死路" in de.title for de in board.dead_ends())


async def test_idle_knight_gets_redirected():
    board = Board()
    ns = await board.post(type=EntryType.NEXT_STEP, author="Gawain", title="看看 /admin", confidence=0.7)
    merlin = Merlin(board, idle_threshold=2)
    idle_knight = _FakeKnight("Lancelot", idle=3)
    await merlin.tick([idle_knight], now=1000.0)
    directives = merlin.take_directives("Lancelot")
    assert directives
    assert directives[0].kind == "redirect"
    assert directives[0].entry_id == ns.id


async def test_closing_mode_picks_best_and_notifies_all():
    board = Board()
    weak = await board.post(type=EntryType.HYPOTHESIS, author="A", title="弱线索", confidence=0.3)
    strong = await board.post(type=EntryType.ARTIFACT, author="B", title="强线索:半成品 exploit", confidence=0.85)
    await board.endorse(strong.id, "C")
    merlin = Merlin(board)
    knights = [_FakeKnight("Gawain"), _FakeKnight("Lancelot")]
    best = merlin.enter_closing_mode(knights)
    assert best.id == strong.id
    assert all(k.closing_mode for k in knights)
    for k in knights:
        ds = merlin.take_directives(k.name)
        assert ds and ds[0].kind == "closing"


async def test_pileup_triggers_divergence():
    board = Board()
    # 两个骑士认领标签高度重叠的条目 → 集中度高
    a = await board.post(type=EntryType.NEXT_STEP, author="X", title="line A", tags=["sqli", "login"])
    b = await board.post(type=EntryType.NEXT_STEP, author="X", title="line B", tags=["sqli", "login"])
    await board.claim(a.id, "Mordred")
    await board.claim(b.id, "Lancelot")
    # 一个被忽视的 fact 供分散
    await board.post(type=EntryType.FACT, author="Gawain", title="被忽视:有个 /backup 端点", tags=["backup"])
    merlin = Merlin(board, claim_concentration_limit=0.6)
    knights = [_FakeKnight("Gawain"), _FakeKnight("Percival")]
    report = await merlin.tick(knights, now=1000.0)
    # 应给闲置骑士派出分散指令
    assert report["diverge"]


async def test_funsearch_redirect_prefers_selected_candidate():
    board = Board()
    fact = await board.post(type=EntryType.FACT, author="Merlin", title="优先继续这条线", tags=["auth"])
    await board.post(type=EntryType.NEXT_STEP, author="Merlin", title="普通 next step", tags=["auth"])
    control = _FakeFunSearch(entry_id=fact.id)
    merlin = Merlin(board, idle_threshold=1, search_mode="funsearch", funsearch_control=control)
    knight = _FakeKnight("Mordred", idle=2)

    report = await merlin.tick([knight], now=1000.0)
    directives = merlin.take_directives("Mordred")

    assert report["funsearch"]["registered"]
    assert directives
    assert directives[0].entry_id == fact.id
    assert "高价值路线" in directives[0].message
    assert control.timeline


async def test_merlin_scope_violation_uses_environment_fingerprints_not_loopback_alone():
    board = Board()
    loopback_only = await board.post(
        type=EntryType.FACT,
        author="Mordred",
        title="可能 SSRF 到 127.0.0.1:8080",
        body="这里只出现了 loopback 地址，本身不应直接判死。",
        tags=["ssrf"],
    )
    env_fingerprint = await board.post(
        type=EntryType.TOOL_OUTPUT,
        author="Gawain",
        title="tinyproxy/AirTunes 命中",
        body="Server: AirTunes/850.19.1 ; Via: tinyproxy/1.11.2 ; container via direct connection",
        tags=["proxy"],
    )
    merlin = Merlin(board)

    report = await merlin.tick([_FakeKnight("Gawain")], now=1000.0)

    assert loopback_only.id not in report["scope_violations"]
    assert board.get(loopback_only.id).status == EntryStatus.OPEN
    assert env_fingerprint.id in report["scope_violations"]
    assert board.get(env_fingerprint.id).status == EntryStatus.REFUTED


async def test_merlin_llm_scope_judge_is_non_blocking_and_applies_next_tick():
    board = Board()
    candidate = await board.post(
        type=EntryType.FACT,
        author="Mordred",
        title="127.0.0.1:5000 返回 AirTunes",
        body="Server: AirTunes/850.19.1",
        tags=["ssrf"],
    )

    class _Judge:
        def __call__(self, root_entry, entry):
            time.sleep(0.05)
            from roundtable.roles.merlin_scope_judge import ScopeJudgment

            return ScopeJudgment(verdict="local_env", reason="更像本地环境指纹")

    merlin = Merlin(board, scope_judge=_Judge())

    report1 = await merlin.tick([_FakeKnight("Gawain")], now=1000.0)
    assert candidate.id not in report1["scope_violations"]
    assert board.get(candidate.id).status == EntryStatus.OPEN

    await asyncio_sleep_briefly()
    report2 = await merlin.tick([_FakeKnight("Gawain")], now=1001.0)
    assert candidate.id in report2["scope_violations"]
    assert board.get(candidate.id).status == EntryStatus.REFUTED


def test_funsearch_population_script_is_vendored_in_project():
    control = MerlinFunSearchControl("/tmp/roundtable-funsearch-test")
    assert POPULATION_SCRIPT.is_file()
    assert "roundtable/funsearch/population.py" in str(POPULATION_SCRIPT)
    assert control.enabled is True


def test_funsearch_reranker_can_override_primary_choice():
    primary = SelectedCandidate(
        island="I00",
        candidate_id="I00CPRIMARY",
        board_entry_id="fact-0001",
        objective=10.0,
        hypothesis="primary",
        title="primary",
    )
    alternate = SelectedCandidate(
        island="I01",
        candidate_id="I01CALT",
        board_entry_id="fact-0002",
        objective=8.0,
        hypothesis="alternate",
        title="alternate",
    )
    control = MerlinFunSearchControl(
        "/tmp/roundtable-funsearch-rerank",
        rerank_top_k=2,
        reranker=lambda items: sorted(items, key=lambda item: item.candidate_id, reverse=True),
    )
    control.enabled = True
    control.ensure_initialized = lambda: None
    control._run_population = lambda command, *args: (  # noqa: SLF001
        {
            "island": primary.island,
            "parent": {
                "id": primary.candidate_id,
                "island": primary.island,
                "hypothesis": primary.hypothesis,
                "strategy_path": "/tmp/primary.json",
                "result": {"objective": primary.objective},
            },
        }
        if command == "select"
        else {
            "global_elites": [
                {
                    "id": alternate.candidate_id,
                    "island": alternate.island,
                    "hypothesis": alternate.hypothesis,
                    "strategy_path": "/tmp/alternate.json",
                    "result": {"objective": alternate.objective},
                }
            ]
        }
    )
    control.append_timeline = lambda line: None

    import json
    from pathlib import Path

    Path("/tmp/primary.json").write_text(json.dumps({"entry_id": primary.board_entry_id, "title": primary.title}), encoding="utf-8")
    Path("/tmp/alternate.json").write_text(json.dumps({"entry_id": alternate.board_entry_id, "title": alternate.title}), encoding="utf-8")

    choice = control.select_candidate()
    assert choice is not None
    assert choice.candidate_id == alternate.candidate_id


async def asyncio_sleep_briefly():
    import asyncio

    await asyncio.sleep(0.08)
