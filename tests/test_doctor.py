from __future__ import annotations

import json

from codex_provider import doctor, paths
from codex_provider.io_utils import write_text


def _seed_config(home, *, model="spe/deepseek-v4-flash", provider="wolfox", catalog=True, absolute=True):
    catalog_path = home / "models.json"
    write_text(
        catalog_path,
        json.dumps({"models": [{"slug": "spe/deepseek-v4-flash"}, {"slug": "spe/deepseek-v4-pro"}]}),
    )
    ref = str(catalog_path).replace("\\", "/") if absolute else "models.json"
    lines = [
        f'model = "{model}"',
        f'model_provider = "{provider}"',
    ]
    if catalog:
        lines.append(f'model_catalog_json = "{ref}"')
    lines += [
        "",
        f"[model_providers.{provider}]",
        f'name = "{provider}"',
        'base_url = "https://api.wolfoxlabs.xyz/v1"',
        'wire_api = "chat"',
        'experimental_bearer_token = "sk-test"',
    ]
    write_text(home / "config.toml", "\n".join(lines) + "\n")


def _titles(d: doctor.Diagnosis) -> str:
    return " | ".join(f.title for f in d.findings)


def test_diagnose_healthy(tmp_codex_home):
    _seed_config(tmp_codex_home)
    d = doctor.diagnose()
    assert d.ok
    assert "config.toml 解析正常" in _titles(d)
    assert "当前默认 provider: wolfox" in _titles(d)


def test_diagnose_missing_codex_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nope"))
    d = doctor.diagnose()
    assert not d.ok
    assert "找不到 Codex 配置目录" in _titles(d)


def test_diagnose_broken_config(tmp_codex_home):
    write_text(tmp_codex_home / "config.toml", 'model = "x"\nbroken = = =\n')
    d = doctor.diagnose()
    assert not d.ok
    assert "config.toml 无法解析" in _titles(d)


def test_diagnose_missing_model_and_provider(tmp_codex_home):
    write_text(tmp_codex_home / "config.toml", "# empty\n")
    d = doctor.diagnose()
    assert not d.ok
    t = _titles(d)
    assert "config.toml 顶部缺少 model" in t
    assert "config.toml 顶部缺少 model_provider" in t


def test_diagnose_missing_provider_section(tmp_codex_home):
    write_text(
        tmp_codex_home / "config.toml",
        'model = "spe/deepseek-v4-flash"\nmodel_provider = "wolfox"\n',
    )
    d = doctor.diagnose()
    assert not d.ok
    assert "config.toml 里没有 [model_providers.wolfox]" in _titles(d)


def test_diagnose_relative_catalog_path(tmp_codex_home):
    _seed_config(tmp_codex_home, absolute=False)
    d = doctor.diagnose()
    assert not d.ok
    assert "model_catalog_json 是相对路径" in _titles(d)


def test_diagnose_catalog_missing_default_model(tmp_codex_home):
    _seed_config(tmp_codex_home, model="not-in-catalog")
    d = doctor.diagnose()
    assert not d.ok
    assert "模型目录里没有默认模型 not-in-catalog" in _titles(d)


def test_diagnose_no_catalog_key(tmp_codex_home):
    _seed_config(tmp_codex_home, catalog=False)
    d = doctor.diagnose()
    assert "config.toml 未设置 model_catalog_json" in _titles(d)


def test_diagnose_missing_credentials(tmp_codex_home):
    write_text(
        tmp_codex_home / "config.toml",
        'model = "spe/deepseek-v4-flash"\n'
        'model_provider = "wolfox"\n'
        f'model_catalog_json = "{str(tmp_codex_home / "models.json").replace(chr(92), "/")}"\n'
        "\n[model_providers.wolfox]\n"
        'base_url = "https://api.wolfoxlabs.xyz/v1"\n',
    )
    write_text(tmp_codex_home / "models.json", json.dumps({"models": [{"slug": "spe/deepseek-v4-flash"}]}))
    d = doctor.diagnose()
    assert "已配置" in _titles(d)
    assert any(f.level == "warn" and "没有凭据" in f.title for f in d.findings)


def test_ui_state_files_detects_all_variants(tmp_codex_home):
    (tmp_codex_home / ".codex-global-state.json").write_text("{}", encoding="utf-8")
    (tmp_codex_home / ".codex-global-state.json.bak").write_text("{}", encoding="utf-8")
    (tmp_codex_home / "..codex-global-state.json.tmp-1-abc").write_text("{}", encoding="utf-8")
    names = {p.name for p in doctor.ui_state_files()}
    assert names == {
        ".codex-global-state.json",
        ".codex-global-state.json.bak",
        "..codex-global-state.json.tmp-1-abc",
    }


def test_reset_ui_state_moves_and_backs_up(tmp_codex_home):
    state = tmp_codex_home / ".codex-global-state.json"
    state.write_text('{"a":1}', encoding="utf-8")
    (tmp_codex_home / ".codex-global-state.json.bak").write_text("{}", encoding="utf-8")
    result = doctor.reset_ui_state(stamp="test-stamp")
    assert not state.exists()
    assert not (tmp_codex_home / ".codex-global-state.json.bak").exists()
    assert result["moved"]
    backup = tmp_codex_home / "backup-ui-state-test-stamp"
    assert backup.is_dir()
    assert (backup / ".codex-global-state.json").read_text(encoding="utf-8") == '{"a":1}'


def test_reset_ui_state_noop_when_nothing_to_clean(tmp_codex_home):
    result = doctor.reset_ui_state(stamp="empty")
    assert result["moved"] == []
    assert result["backup_dir"] is None


def test_reset_ui_state_can_include_web_dir(tmp_codex_home, monkeypatch, tmp_path):
    state = tmp_codex_home / ".codex-global-state.json"
    state.write_text("{}", encoding="utf-8")
    web = tmp_path / "Codex" / "web"
    (web / "Cache").mkdir(parents=True)
    (web / "Cache" / "x.bin").write_bytes(b"x")
    monkeypatch.setattr(doctor, "desktop_web_dir", lambda: web)
    result = doctor.reset_ui_state(include_web=True, stamp="with-web")
    assert not web.exists()
    assert "web" in result["moved"]


def test_find_codex_processes_ignores_self(monkeypatch):
    class R:
        stdout = '"codex.exe","123","Console","1","1,000 K"\n"codex-provider-setup.exe","456","Console","1","1 K"\n"explorer.exe","789","Console","1","1 K"\n'

    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: R())
    procs = doctor.find_codex_processes()
    assert procs == ["codex.exe"]


def test_diagnose_flags_running_codex(monkeypatch, tmp_codex_home):
    _seed_config(tmp_codex_home)
    monkeypatch.setattr(doctor, "find_codex_processes", lambda: ["Codex.exe"])
    d = doctor.diagnose()
    assert any("正在运行" in f.title for f in d.findings)


def test_diagnose_flags_ui_cache(monkeypatch, tmp_codex_home):
    _seed_config(tmp_codex_home)
    monkeypatch.setattr(doctor, "find_codex_processes", lambda: [])
    (tmp_codex_home / ".codex-global-state.json").write_text("{}", encoding="utf-8")
    d = doctor.diagnose()
    assert any("UI 状态缓存" in f.title for f in d.findings)


def test_desktop_web_dir_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert doctor.desktop_web_dir() == tmp_path / "Roaming" / "Codex" / "web"


def test_desktop_web_dir_macos(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(doctor.Path, "home", classmethod(lambda cls: doctor.Path("/Users/tester")))
    assert doctor.desktop_web_dir() == doctor.Path("/Users/tester/Library/Application Support/Codex/web")


def test_paths_used_by_doctor(tmp_codex_home):
    assert paths.codex_home() == tmp_codex_home


def test_restore_ui_state_merges_missing_keys(tmp_codex_home):
    import json as _json

    backup = tmp_codex_home / "backup-ui-state-20260101-000000"
    backup.mkdir()
    (backup / ".codex-global-state.json").write_text(
        _json.dumps({"project-order": ["a"], "thread-project-assignments": {"t": "a"}, "shared": "old"}),
        encoding="utf-8",
    )
    (tmp_codex_home / ".codex-global-state.json").write_text(
        _json.dumps({"shared": "new", "selected-project": "b"}),
        encoding="utf-8",
    )
    result = doctor.restore_ui_state(stamp="stamp")
    assert sorted(result["restored_keys"]) == ["project-order", "thread-project-assignments"]
    live = _json.loads((tmp_codex_home / ".codex-global-state.json").read_text(encoding="utf-8"))
    assert live["project-order"] == ["a"]
    assert live["thread-project-assignments"] == {"t": "a"}
    assert live["shared"] == "new"
    assert live["selected-project"] == "b"
    assert result["backup_of_current"] is not None
    assert (result["backup_of_current"] / ".codex-global-state.json").exists()


def test_restore_ui_state_no_backup(tmp_codex_home):
    result = doctor.restore_ui_state()
    assert result["restored_keys"] == []
    assert result["errors"]


def test_restore_ui_state_explicit_dir(tmp_codex_home):
    import json as _json

    d = tmp_codex_home / "backup-ui-state-20260101-111111"
    d.mkdir()
    (d / ".codex-global-state.json").write_text(_json.dumps({"only-in-backup": 1}), encoding="utf-8")
    (tmp_codex_home / ".codex-global-state.json").write_text("{}", encoding="utf-8")
    result = doctor.restore_ui_state(d, stamp="s2")
    assert result["restored_keys"] == ["only-in-backup"]


def test_restore_ui_state_creates_live_file_when_missing(tmp_codex_home):
    import json as _json

    d = tmp_codex_home / "backup-ui-state-20260101-222222"
    d.mkdir()
    (d / ".codex-global-state.json").write_text(_json.dumps({"k": "v"}), encoding="utf-8")
    result = doctor.restore_ui_state(d, stamp="s3")
    assert result["restored_keys"] == ["k"]
    live = _json.loads((tmp_codex_home / ".codex-global-state.json").read_text(encoding="utf-8"))
    assert live == {"k": "v"}


def test_ui_state_backups_newest_first(tmp_codex_home):
    for name in ("backup-ui-state-20260101-000000", "backup-ui-state-20260909-120000"):
        (tmp_codex_home / name).mkdir()
    found = [p.name for p in doctor.ui_state_backups()]
    assert found == ["backup-ui-state-20260909-120000", "backup-ui-state-20260101-000000"]
