import pytest

from examples.run_ctf import ROUND_TABLE_MODEL, parse_args, prepare_board_file, prepare_workdir
from roundtable.roles.arthur import DEFAULT_FLAG_REGEX


def test_prepare_board_file_clears_stale_board_by_default(tmp_path):
    board_path = tmp_path / "_board.jsonl"
    board_path.write_text("old-board\n", encoding="utf-8")

    got = prepare_board_file(str(tmp_path), resume_board=False)

    assert got == board_path
    assert not board_path.exists()


def test_prepare_board_file_keeps_board_when_resuming(tmp_path):
    board_path = tmp_path / "_board.jsonl"
    board_path.write_text("old-board\n", encoding="utf-8")

    got = prepare_board_file(str(tmp_path), resume_board=True)

    assert got == board_path
    assert board_path.read_text(encoding="utf-8") == "old-board\n"


def test_parse_args_uses_general_flag_regex_by_default():
    args = parse_args(["--attach", "dummy.txt"])
    assert args.flag_regex == DEFAULT_FLAG_REGEX
    assert args.model == ROUND_TABLE_MODEL


def test_prepare_workdir_creates_random_child_by_default(tmp_path):
    workdir = prepare_workdir(str(tmp_path), resume_board=False)

    assert workdir.parent == tmp_path
    assert workdir.name.startswith("run-")
    assert workdir.exists()


def test_prepare_workdir_reuses_exact_dir_when_resuming(tmp_path):
    workdir = prepare_workdir(str(tmp_path / "resume-here"), resume_board=True)

    assert workdir == tmp_path / "resume-here"
    assert workdir.exists()


def test_parse_args_rejects_non_round_table_model():
    with pytest.raises(SystemExit):
        parse_args(["--attach", "dummy.txt", "--model", "gpt-5.6-sol"])


def test_parse_args_accepts_docker_worker_options():
    args = parse_args(["--attach", "dummy.txt", "--docker-image", "roundtable-kali:latest"])

    assert args.docker_image == "roundtable-kali:latest"
    assert args.docker_platform == "linux/amd64"


def test_parse_args_accepts_statement_only_problem():
    args = parse_args(["--title", "Silver Wolf", "--statement", "给你一段 ncat 命令，目标提权到 root。"])

    assert args.title == "Silver Wolf"
    assert "ncat" in args.statement
