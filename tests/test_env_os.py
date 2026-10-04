from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from codex_provider.env_os import (
    _rc_candidates,
    _remove_export,
    _upsert_export,
    persist_env,
    remove_env,
)
from codex_provider.io_utils import read_text, write_text

HOME = Path("/home/dev")

RC_NAMES = [".zshrc", ".bashrc", ".bash_profile", ".profile"]


def _all_rc(home: Path) -> list[Path]:
    return [home / n for n in RC_NAMES]


def test_rc_candidates_default_order():
    got = _rc_candidates(HOME)
    assert got == [HOME / n for n in RC_NAMES]


def test_rc_candidates_zsh_shell_first():
    got = _rc_candidates(HOME, "/usr/bin/zsh")
    assert got[0] == HOME / ".zshrc"
    assert got == [HOME / ".zshrc", HOME / ".bashrc", HOME / ".bash_profile", HOME / ".profile"]


def test_rc_candidates_bash_shell_first():
    got = _rc_candidates(HOME, "/bin/bash")
    assert got[0] == HOME / ".bashrc"
    assert got == [HOME / ".bashrc", HOME / ".zshrc", HOME / ".bash_profile", HOME / ".profile"]


def test_rc_candidates_unknown_shell_keeps_default():
    got = _rc_candidates(HOME, "/usr/bin/fish")
    assert got == [HOME / n for n in RC_NAMES]


def test_upsert_export_creates_missing_file(tmp_path):
    p = tmp_path / "rc"
    _upsert_export(p, "MIMO_API_KEY", "sk-abc")
    assert read_text(p) == 'export MIMO_API_KEY="sk-abc"\n'


def test_upsert_export_appends_keeps_content(tmp_path):
    p = tmp_path / "rc"
    write_text(p, "alias ll='ls -la'\n# comment\n")
    _upsert_export(p, "MIMO_API_KEY", "sk-abc")
    t = read_text(p)
    assert "alias ll='ls -la'\n# comment\n" in t
    assert t.count("export MIMO_API_KEY=") == 1
    assert t.endswith('export MIMO_API_KEY="sk-abc"\n')


def test_upsert_export_replaces_same_name_keeps_others(tmp_path):
    p = tmp_path / "rc"
    write_text(p, 'export OLD=1\n# keep\nexport OLD=2\nx=1\n')
    _upsert_export(p, "OLD", "new-val")
    assert read_text(p) == 'export OLD="new-val"\n# keep\nexport OLD="new-val"\nx=1\n'


def test_upsert_export_idempotent(tmp_path):
    p = tmp_path / "rc"
    _upsert_export(p, "K", "a")
    _upsert_export(p, "K", "a")
    _upsert_export(p, "K", "a")
    t = read_text(p)
    assert t == 'export K="a"\n'
    assert t.count("export K=") == 1


def test_upsert_export_skips_comment_and_non_prefix(tmp_path):
    p = tmp_path / "rc"
    write_text(p, '# export K=1\nexportK=2\n')
    _upsert_export(p, "K", "v")
    assert read_text(p) == '# export K=1\nexportK=2\nexport K="v"\n'


def test_upsert_export_value_special_chars(tmp_path):
    p = tmp_path / "rc"
    _upsert_export(p, "MIMO_API_KEY", 'sk-a"b\\c$d`e')
    assert read_text(p) == r'export MIMO_API_KEY="sk-a\"b\\c\$d\`e"' + "\n"


def test_upsert_export_value_with_spaces(tmp_path):
    p = tmp_path / "rc"
    _upsert_export(p, "K", "sk-xx yy==z")
    assert read_text(p) == 'export K="sk-xx yy==z"\n'


def test_remove_export_no_file(tmp_path):
    _remove_export(tmp_path / "missing", "K")
    assert not (tmp_path / "missing").exists()


def test_remove_export_empty_file_untouched(tmp_path):
    p = tmp_path / "rc"
    write_text(p, "")
    _remove_export(p, "K")
    assert read_text(p) == ""


def test_remove_export_deletes_matching_keeps_rest(tmp_path):
    p = tmp_path / "rc"
    write_text(p, 'export K="1"\n# keep\nexport OTHER="x"\nexport K="2"\n')
    _remove_export(p, "K")
    assert read_text(p) == '# keep\nexport OTHER="x"\n'


def test_remove_export_no_match_does_not_rewrite(tmp_path):
    p = tmp_path / "rc"
    write_text(p, "x=1")
    _remove_export(p, "K")
    assert read_text(p) == "x=1"


def test_remove_export_all_matched_leaves_empty(tmp_path):
    p = tmp_path / "rc"
    write_text(p, 'export K="1"\nexport K="2"\n')
    _remove_export(p, "K")
    assert read_text(p) == ""


def test_persist_env_linux_writes_each_rc_file(tmp_path):
    rc1 = tmp_path / "one"
    rc2 = tmp_path / "two"
    rc1_exists = rc1
    write_text(rc1_exists, "keep=1\n")
    persist_env("MIMO_API_KEY", "sk-x", platform="linux", rc_files=[rc1, rc2])
    assert read_text(rc1) == 'keep=1\nexport MIMO_API_KEY="sk-x"\n'
    # A candidate rc file that does not exist is no longer created: the secret
    # must not be injected into shells the user never configured.
    assert not rc2.exists()


def test_persist_env_linux_idempotent(tmp_path):
    rc1 = tmp_path / "one"
    rc1.write_text("x=1\n", encoding="utf-8")
    for _ in range(2):
        persist_env("K", "v", platform="linux", rc_files=[rc1])
    t = read_text(rc1)
    assert t.count("export K=") == 1
    assert t == 'x=1\nexport K="v"\n'


def test_persist_env_darwin_uses_rc_files(tmp_path):
    rc = tmp_path / ".zshrc"
    rc.write_text("# zsh\n", encoding="utf-8")
    persist_env("K", "sk-darwin", platform="darwin", rc_files=[rc])
    assert read_text(rc) == '# zsh\nexport K="sk-darwin"\n'


def test_persist_env_default_rc_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")
    # With no rc file present, exactly one default candidate is created.
    persist_env("K", "sk-default", platform="linux", home=tmp_path)
    written = [p for p in _all_rc(tmp_path) if p.exists()]
    assert len(written) == 1
    assert read_text(written[0]) == 'export K="sk-default"\n'


def test_persist_env_backs_up_rc_before_rewrite(tmp_path):
    rc = tmp_path / ".zshrc"
    write_text(rc, "original=1\n")
    persist_env("K", "v", platform="linux", rc_files=[rc])
    bak = tmp_path / ".zshrc.codex-provider-setup.bak"
    assert bak.exists()
    assert read_text(bak) == "original=1\n"


def test_persist_env_rejects_illegal_name(tmp_path):
    rc = tmp_path / ".zshrc"
    write_text(rc, "x=1\n")
    with pytest.raises(ValueError):
        persist_env("BAD NAME", "v", platform="linux", rc_files=[rc])


def test_persist_env_escapes_newline(tmp_path):
    rc = tmp_path / ".zshrc"
    write_text(rc, "x=1\n")
    persist_env("K", "line1\nline2", platform="linux", rc_files=[rc])
    # A raw newline would split the export across lines and break every shell.
    assert read_text(rc) == 'x=1\nexport K="line1\\nline2"\n'


def test_remove_env_linux(tmp_path):
    rc1 = tmp_path / "one"
    rc2 = tmp_path / "two"
    write_text(rc1, "a=1\n")
    write_text(rc2, "b=2\n")
    persist_env("K", "v", platform="linux", rc_files=[rc1, rc2])
    remove_env("K", platform="linux", rc_files=[rc1, rc2])
    assert read_text(rc1) == "a=1\n"
    assert read_text(rc2) == "b=2\n"


def test_remove_env_linux_keeps_unrelated(tmp_path):
    rc = tmp_path / "rc"
    write_text(rc, 'export K="1"\nexport OTHER="x"\n# keep\n')
    remove_env("K", platform="linux", rc_files=[rc])
    assert read_text(rc) == 'export OTHER="x"\n# keep\n'


def test_remove_env_missing_rc_files(tmp_path):
    remove_env("K", platform="linux", rc_files=[tmp_path / "a", tmp_path / "b"])
    assert not (tmp_path / "a").exists()


def test_remove_env_default_rc_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    rc = tmp_path / ".bashrc"
    write_text(rc, 'export K="v"\nkeep=1\n')
    remove_env("K", platform="linux", home=tmp_path)
    assert read_text(rc) == "keep=1\n"


class _FakeWinRegKey:
    def __init__(self) -> None:
        self.values: dict[str, tuple[int, str]] = {}

    def __enter__(self) -> "_FakeWinRegKey":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _fake_winreg(store: dict[str, tuple[int, str]], key: _FakeWinRegKey):
    mod = types.ModuleType("winreg")
    mod.HKEY_CURRENT_USER = "HKCU"
    mod.KEY_SET_VALUE = 0x0002
    mod.REG_SZ = 1

    def openkey(hive, subkey, res, access):
        assert hive == "HKCU"
        assert subkey == "Environment"
        return key

    def setvalue(k, name, res, vtype, value):
        store[name] = (vtype, value)

    def deletevalue(k, name):
        if name not in store:
            raise FileNotFoundError(name)
        del store[name]

    mod.OpenKey = openkey
    mod.SetValueEx = setvalue
    mod.DeleteValue = deletevalue
    return mod


def test_persist_env_windows_writes_registry(monkeypatch):
    store: dict[str, tuple[int, str]] = {}
    key = _FakeWinRegKey()
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store, key))
    persist_env("MIMO_API_KEY", "sk-win", platform="win32")
    assert store == {"MIMO_API_KEY": (1, "sk-win")}


def test_remove_env_windows_registry(monkeypatch):
    store: dict[str, tuple[int, str]] = {"K": (1, "v")}
    key = _FakeWinRegKey()
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store, key))
    remove_env("K", platform="win32")
    assert store == {}
    remove_env("MISSING", platform="win32")
    assert store == {}
