"""一键组装圆桌:黑板 + 五骑士 + Merlin + Arthur + Kay。

mode="mock":Phase 1,脚本骑士,需传 behaviors。
mode="codex":Phase 2,真骑士(Codex CLI),需已安装并登录 Codex。
"""

from __future__ import annotations

from pathlib import Path

from .core import Board, BoardTools
from .funsearch import build_codex_reranker
from .knights import ALL_KNIGHTS, MockKnight
from .roles import Arthur, Kay, Merlin
from .roles.merlin_scope_judge import build_codex_scope_judge
from .roles.arthur import DEFAULT_FLAG_REGEX


def assemble_mock(behaviors: dict, *, jsonl_path=None, **kay_kwargs):
    board = Board(jsonl_path=jsonl_path)
    knights = []
    for policy in ALL_KNIGHTS:
        tools = BoardTools(
            board,
            policy.name,
            knight_tags=policy.preferred_tags,
            can_read_board=policy.can_read_board,
            can_endorse=policy.can_read_board,
            can_challenge=policy.can_read_board,
            can_claim=policy.can_read_board,
        )
        knights.append(MockKnight(policy, tools, behaviors[policy.name]))
    merlin_kwargs = {
        "search_mode": kay_kwargs.pop("merlin_search_mode", "classic"),
        "funsearch_run_dir": kay_kwargs.pop("merlin_funsearch_run_dir", None),
        "funsearch_rerank_top_k": kay_kwargs.pop("merlin_funsearch_rerank_top_k", 0),
        "funsearch_reranker": kay_kwargs.pop("merlin_funsearch_reranker", None),
        "scope_judge": kay_kwargs.pop("merlin_scope_judge", None),
    }
    merlin = Merlin(board, **merlin_kwargs)
    arthur = Arthur(board)
    kay = Kay(board, knights, merlin, arthur, **kay_kwargs)
    return board, knights, merlin, arthur, kay


def assemble_codex(
    *,
    jsonl_path=None,
    model: str | None = None,
    sandbox: bool = True,
    cwd: str | None = None,
    docker_image: str | None = None,
    docker_platform: str = "linux/amd64",
    flag_regex: str = DEFAULT_FLAG_REGEX,
    verifier=None,
    allowed_domains: list[str] | None = None,
    codex_bin: str = "codex",
    merlin_search_mode: str = "classic",
    merlin_funsearch_run_dir: str | None = None,
    merlin_funsearch_rerank_top_k: int = 0,
    merlin_funsearch_enable_llm_rerank: bool = False,
    merlin_funsearch_rerank_model: str | None = None,
    merlin_enable_llm_scope_judge: bool = True,
    merlin_scope_judge_model: str | None = None,
    **kay_kwargs,
):
    """组装 Codex 真骑士圆桌。调用方需在 run 后 await 各骑士 disconnect。

    allowed_domains 当前保留为兼容参数;Codex CLI 的网络限制建议交给外层容器/系统沙箱。
    """
    from .knights.codex_knight import CodexKnight

    board = Board(jsonl_path=jsonl_path)
    base_cwd = Path(cwd).resolve() if cwd else None
    if base_cwd:
        base_cwd.mkdir(parents=True, exist_ok=True)
    operator_inbox_path = str(base_cwd / "_operator_inbox.jsonl") if base_cwd else None
    knights = []
    for policy in ALL_KNIGHTS:
        tools = BoardTools(
            board,
            policy.name,
            knight_tags=policy.preferred_tags,
            can_read_board=policy.can_read_board,
            can_endorse=policy.can_read_board,
            can_challenge=policy.can_read_board,
            can_claim=policy.can_read_board,
        )
        knight_cwd = str(base_cwd / "knights" / policy.name) if base_cwd else None
        knights.append(
            CodexKnight(
                policy,
                tools,
                model=model,
                sandbox=sandbox,
                cwd=knight_cwd,
                codex_bin=codex_bin,
                docker_image=docker_image,
                docker_platform=docker_platform,
                operator_inbox_path=operator_inbox_path,
            )
        )
    reranker = build_codex_reranker(
        enabled=merlin_funsearch_enable_llm_rerank,
        codex_bin=codex_bin,
        model=merlin_funsearch_rerank_model or model,
        sandbox=sandbox,
    )
    scope_judge = build_codex_scope_judge(
        enabled=merlin_enable_llm_scope_judge,
        codex_bin=codex_bin,
        model=merlin_scope_judge_model or model,
        sandbox=sandbox,
    )
    merlin = Merlin(
        board,
        search_mode=merlin_search_mode,
        funsearch_run_dir=merlin_funsearch_run_dir,
        funsearch_rerank_top_k=merlin_funsearch_rerank_top_k,
        funsearch_reranker=reranker,
        scope_judge=scope_judge,
    )
    arthur = Arthur(board, flag_regex=flag_regex, verifier=verifier)
    kay = Kay(board, knights, merlin, arthur, **kay_kwargs)
    return board, knights, merlin, arthur, kay


def assemble_sdk(**kwargs):
    """Backward-compatible alias for callers that still import assemble_sdk."""
    return assemble_codex(**kwargs)
