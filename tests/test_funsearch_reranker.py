from roundtable.funsearch.codex_reranker import CodexCandidateReranker
from roundtable.funsearch.merlin_control import SelectedCandidate


def _candidate(candidate_id: str, entry_id: str, title: str) -> SelectedCandidate:
    return SelectedCandidate(
        island="I00",
        candidate_id=candidate_id,
        board_entry_id=entry_id,
        objective=1.0,
        hypothesis=title,
        title=title,
        body=f"body:{title}",
        tags=("web",),
    )


def test_codex_reranker_reorders_candidates():
    reranker = CodexCandidateReranker()
    calls = {"n": 0}

    def fake_invoke(candidates):
        calls["n"] += 1
        return {"order": [candidates[1].candidate_id, candidates[0].candidate_id], "reason": "第二条更具体"}

    reranker._invoke_codex = fake_invoke  # noqa: SLF001
    ranked = reranker([_candidate("A", "fact-1", "A"), _candidate("B", "fact-2", "B")])

    assert [item.candidate_id for item in ranked] == ["B", "A"]
    assert calls["n"] == 1
    assert reranker.last_reason == "第二条更具体"


def test_codex_reranker_uses_signature_cache():
    reranker = CodexCandidateReranker()
    calls = {"n": 0}

    def fake_invoke(candidates):
        calls["n"] += 1
        return {"order": [candidates[1].candidate_id, candidates[0].candidate_id], "reason": "cached"}

    reranker._invoke_codex = fake_invoke  # noqa: SLF001
    candidates = [_candidate("A", "fact-1", "A"), _candidate("B", "fact-2", "B")]
    ranked1 = reranker(candidates)
    ranked2 = reranker(candidates)

    assert [item.candidate_id for item in ranked1] == ["B", "A"]
    assert [item.candidate_id for item in ranked2] == ["B", "A"]
    assert calls["n"] == 1
