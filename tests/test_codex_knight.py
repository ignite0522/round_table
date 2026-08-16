"""CodexKnight 本地逻辑测试:不调用真实 Codex CLI。"""

from pathlib import Path
from types import SimpleNamespace

from roundtable.core import Board, BoardTools, EntryType
from roundtable.knights.codex_knight import CodexKnight, _OUTPUT_SCHEMA
from roundtable.knights.roster import GAWAIN


async def test_codex_knight_applies_structured_operations():
    board = Board()
    seed = await board.post(type=EntryType.FACT, author="Kay", title="seed")
    tools = BoardTools(board, "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(GAWAIN, tools)

    ops = knight._parse_operations(
        """
        {
          "operations": [
            {"op": "post_entry", "type": "hypothesis", "title": "maybe base64", "confidence": 1.2, "refs": ["fact-0001"], "tags": ["decode"]},
            {"op": "endorse", "entry_id": "fact-0001"},
            {"op": "claim", "entry_id": "fact-0001"}
          ]
        }
        """
    )
    n_posts = await knight._apply_operations(ops)

    assert n_posts == 1
    assert board.get(seed.id).endorsements == ["Gawain"]
    assert board.get(seed.id).claimed_by == "Gawain"
    posted = [e for e in board.all() if e.author == "Gawain" and e.type == EntryType.HYPOTHESIS][0]
    assert posted.confidence == 1.0
    assert posted.refs == ["fact-0001"]


async def test_codex_knight_records_flag_candidate_to_local_files(tmp_path):
    board = Board()
    tools = BoardTools(board, "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(GAWAIN, tools, cwd=str(tmp_path))

    await knight._apply_operations(
        [
            {
                "op": "post_entry",
                "type": "flag_candidate",
                "title": "FLAG: flag{abc123}",
                "body": "got it",
                "confidence": 0.99,
                "refs": [],
                "tags": ["flag"],
            }
        ]
    )

    assert "flag{abc123}" in (tmp_path / "FLAGS_FOUND.md").read_text(encoding="utf-8")
    assert "flag{abc123}" in (tmp_path / "FLAGS_FOUND.jsonl").read_text(encoding="utf-8")


def test_codex_output_schema_requires_all_operation_properties():
    item_schema = _OUTPUT_SCHEMA["properties"]["operations"]["items"]
    assert set(item_schema["required"]) == set(item_schema["properties"])


def test_codex_knight_adds_problem_hosts_to_no_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    tools = BoardTools(Board(), "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(GAWAIN, tools)
    knight._codex_home_dir = "/tmp/roundtable-codex-home-test"

    env = knight._build_child_env("URL: http://example.ctf.test/path")

    assert "example.ctf.test" in env["NO_PROXY"].split(",")
    assert "example.ctf.test" in env["no_proxy"].split(",")
    assert env["CODEX_HOME"] == "/tmp/roundtable-codex-home-test"


def test_codex_knight_builds_docker_command(monkeypatch, tmp_path):
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    (tmp_path / "codex-home").mkdir()
    docker_calls = []

    def fake_run(cmd, **kwargs):
        docker_calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("roundtable.knights.codex_knight.subprocess.run", fake_run)
    CodexKnight._shared_docker_sessions.clear()
    tools = BoardTools(Board(), "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(
        GAWAIN,
        tools,
        model="gpt-5.4",
        cwd=str(tmp_path / "workdir"),
        docker_image="roundtable-kali:latest",
    )
    (tmp_path / "workdir").mkdir()
    import asyncio
    asyncio.run(knight.connect())

    cmd = knight._build_cmd(tmp_path / "last_message.json", tmp_path / "schema.json")

    assert docker_calls[0][:5] == ["docker", "run", "-d", "--rm", "--platform"]
    assert "roundtable-kali:latest" in docker_calls[0]
    assert cmd[:5] == ["docker", "exec", "-i", "-w", "/workspace/Gawain"]
    assert knight._docker_container_name in cmd
    assert "--model" in cmd
    assert "gpt-5.4" in cmd
    assert "/workspace/Gawain" in cmd

    asyncio.run(knight.disconnect())


def test_codex_knight_reuses_shared_container(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    (tmp_path / "codex-home").mkdir()
    docker_calls = []

    def fake_run(cmd, **kwargs):
        docker_calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("roundtable.knights.codex_knight.subprocess.run", fake_run)
    CodexKnight._shared_docker_sessions.clear()
    board = Board()
    tools1 = BoardTools(board, "Gawain", knight_tags=GAWAIN.preferred_tags)
    tools2 = BoardTools(board, "Gawain", knight_tags=GAWAIN.preferred_tags)
    workspace_root = tmp_path / "run" / "knights"
    knight1 = CodexKnight(GAWAIN, tools1, cwd=str(workspace_root / "Gawain"), docker_image="roundtable-kali:latest")
    knight2 = CodexKnight(GAWAIN, tools2, cwd=str(workspace_root / "Percival"), docker_image="roundtable-kali:latest")

    import asyncio
    asyncio.run(knight1.connect())
    asyncio.run(knight2.connect())

    assert len(docker_calls) == 1
    assert knight1._docker_container_name == knight2._docker_container_name

    asyncio.run(knight1.disconnect())
    assert len(docker_calls) == 1
    asyncio.run(knight2.disconnect())
    assert docker_calls[-1][:3] == ["docker", "rm", "-f"]


async def test_codex_knight_connect_seeds_isolated_codex_home(tmp_path, monkeypatch):
    source_home = tmp_path / "source-codex-home"
    source_home.mkdir()
    auth_path = source_home / "auth.json"
    auth_path.write_text('{"token":"ok"}', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(source_home))

    tools = BoardTools(Board(), "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(GAWAIN, tools)

    await knight.connect()

    assert knight._codex_home_dir is not None
    isolated_auth = Path(knight._codex_home_dir) / "auth.json"
    assert isolated_auth.read_text(encoding="utf-8") == auth_path.read_text(encoding="utf-8")

    await knight.disconnect()
    assert knight._codex_home_dir is None


def test_codex_knight_writes_failure_debug_bundle(tmp_path):
    tools = BoardTools(Board(), "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(GAWAIN, tools, cwd=str(tmp_path))
    out_path = tmp_path / "last_message.json"
    out_path.write_text('{"operations":[]}', encoding="utf-8")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text('{"type":"object"}', encoding="utf-8")

    bundle_dir = knight._write_failure_debug_bundle(
        prompt="prompt",
        stdout="stdout",
        stderr="stderr",
        out_path=out_path,
        schema_path=schema_path,
    )

    assert (bundle_dir / "prompt.txt").read_text(encoding="utf-8") == "prompt"
    assert (bundle_dir / "stdout.txt").read_text(encoding="utf-8") == "stdout"
    assert (bundle_dir / "stderr.txt").read_text(encoding="utf-8") == "stderr"
    assert (bundle_dir / "last_message.json").exists()
    assert (bundle_dir / "schema.json").exists()


async def test_codex_knight_prompt_includes_board_file_hints():
    board = Board()
    await board.post(
        type=EntryType.FACT,
        author="Kay",
        title="[题目] Baby Encoding",
        body="附件里有一段 base64 字符串。",
        confidence=1.0,
        tags=["problem"],
    )
    tools = BoardTools(board, "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(GAWAIN, tools)

    prompt = knight._cycle_prompt()

    assert "黑板访问" in prompt
    assert "board_digest.md" in prompt
    assert "board_entries.json" in prompt
    assert '"operations"' in prompt


async def test_codex_knight_prompt_includes_resolve_hint(monkeypatch):
    board = Board()
    await board.post(
        type=EntryType.FACT,
        author="Kay",
        title="[题目] Web",
        body="URL: http://target.ctf.test/",
        confidence=1.0,
        tags=["problem"],
    )
    tools = BoardTools(board, "Gawain", knight_tags=GAWAIN.preferred_tags)
    knight = CodexKnight(GAWAIN, tools)
    monkeypatch.setattr(knight, "_resolve_host", lambda host, port: ["203.0.113.8"])

    prompt = knight._cycle_prompt()

    assert "宿主已解析 target.ctf.test:80 -> 203.0.113.8" in prompt
    assert "--resolve target.ctf.test:80:203.0.113.8" in prompt
