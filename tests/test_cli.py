from __future__ import annotations

import builtins

import pytest

from codex_provider import cli, interact


def test_eof_error_is_abort_not_crash(monkeypatch, tmp_codex_home):
    """input() hitting EOF must raise AbortError (handled gracefully), not a raw traceback."""
    calls: list[str] = []

    def fake_input(_p=""):
        calls.append("input-called")
        raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)
    monkeypatch.setattr(interact, "_active", None)
    with pytest.raises(interact.AbortError):
        interact.main_menu()


def test_abort_error_message_mentions_terminal():
    exc = None
    try:
        raise interact.AbortError("输入流已关闭（EOF）。请在一个正常终端窗口中运行本程序。")
    except interact.AbortError as e:
        exc = e
    assert "EOF" in str(exc)
    assert "终端" in str(exc)


def test_main_abort_error_returns_2(monkeypatch, tmp_codex_home, capsys):
    monkeypatch.setattr(interact, "_active", None)

    def boom(_argv=None):
        raise interact.AbortError("EOF")

    monkeypatch.setattr(cli, "_main", boom)
    monkeypatch.setattr(cli, "_pause_before_exit", lambda: None)
    assert cli.main([]) == 2
    out = capsys.readouterr().out
    assert "输入流已关闭" in out or "EOF" in out


def test_main_unexpected_exception_returns_1(monkeypatch, tmp_codex_home, capsys):
    def boom(_argv=None):
        raise RuntimeError("something exploded")

    monkeypatch.setattr(cli, "_main", boom)
    monkeypatch.setattr(cli, "_pause_before_exit", lambda: None)
    assert cli.main([]) == 1
    out = capsys.readouterr().out
    assert "未预期" in out
    assert "something exploded" in out


def test_main_system_exit_passthrough(monkeypatch, tmp_codex_home):
    def boom(_argv=None):
        raise SystemExit(7)

    monkeypatch.setattr(cli, "_main", boom)
    with pytest.raises(SystemExit) as ei:
        cli.main([])
    assert ei.value.code == 7


def test_read_wrapper_eof(monkeypatch):
    def fake_input(_p=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)
    with pytest.raises(interact.AbortError):
        interact._read("x")


def test_doctor_returns_1_when_problems_found(monkeypatch, tmp_codex_home):
    """doctor must signal problems via exit code so scripts can react."""
    monkeypatch.setattr(cli, "_pause_before_exit", lambda: None)
    (tmp_codex_home / "config.toml").write_text("# nothing\n", encoding="utf-8")
    args = cli._build_parser().parse_args(["doctor"])
    assert cli._cmd_doctor(args) == 1


def test_doctor_returns_0_when_healthy(monkeypatch, tmp_codex_home):
    import json as _json

    models = tmp_codex_home / "models.json"
    models.write_text(_json.dumps({"models": [{"slug": "spe/deepseek-v4-flash"}]}), encoding="utf-8")
    (tmp_codex_home / "config.toml").write_text(
        'model = "spe/deepseek-v4-flash"\n'
        'model_provider = "wolfox"\n'
        f'model_catalog_json = "{str(models).replace(chr(92), "/")}"\n'
        "\n[model_providers.wolfox]\n"
        'base_url = "https://api.wolfoxlabs.xyz/v1"\n'
        'wire_api = "chat"\n'
        'experimental_bearer_token = "sk-x"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_pause_before_exit", lambda: None)
    args = cli._build_parser().parse_args(["doctor"])
    assert cli._cmd_doctor(args) == 0


def test_doctor_json_output(monkeypatch, tmp_codex_home, capsys):
    import json as _json

    (tmp_codex_home / "config.toml").write_text("# nothing\n", encoding="utf-8")
    args = cli._build_parser().parse_args(["doctor", "--json"])
    cli._cmd_doctor(args)
    payload = _json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is False
    assert any(f["level"] == "bad" for f in payload["findings"])


def test_doctor_fix_refuses_while_codex_running(monkeypatch, tmp_codex_home):
    from codex_provider import doctor

    (tmp_codex_home / "config.toml").write_text('model = "m"\nmodel_provider = "p"\n', encoding="utf-8")
    (tmp_codex_home / ".codex-global-state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(doctor, "find_codex_processes", lambda: ["Codex.exe"])
    monkeypatch.setattr(cli, "_pause_before_exit", lambda: None)
    args = cli._build_parser().parse_args(["doctor", "--fix"])
    assert cli._cmd_doctor(args) == 2
    assert (tmp_codex_home / ".codex-global-state.json").exists()


def test_main_module_propagates_exit_code():
    """`python -m codex_provider` must exit with main()'s return value."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [_sys.executable, "-m", "codex_provider", "doctor", "--json"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode in (0, 1, 2)
    assert "findings" in proc.stdout
