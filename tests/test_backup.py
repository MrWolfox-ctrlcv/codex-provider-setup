from __future__ import annotations

from pathlib import Path

from codex_provider.backup import backup_config_and_models, restore, write_manifest


def sample_fields(env_key_used: int = 1, env_var_name: str = "MIMO_API_KEY_SELFTEST") -> dict[str, str]:
    return {
        "script_version": "1.0.0",
        "provider_id": "mimo",
        "installed_at": "2026-09-08 10:00:00",
        "original_config_existed": "1",
        "models_json_existed": "1",
        "env_key_used": str(env_key_used),
        "env_var_name": env_var_name,
        "default_model": "mimo-v2.5-pro",
        "base_url": "https://api.xiaomimimo.com/v1",
        "catalog_value": "C:/Users/x/.codex/models.json",
    }


def write_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def test_first_backup_copies(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    config_path = tmp_path / "config.toml"
    models_path = tmp_path / "models.json"
    write_file(config_path, b"cfg-original")
    write_file(models_path, b"models-original")
    c, m = backup_config_and_models(backup_dir, config_path, models_path)
    assert c is True
    assert m is True
    assert (backup_dir / "config.toml").read_bytes() == b"cfg-original"
    assert (backup_dir / "models.json").read_bytes() == b"models-original"


def test_second_run_does_not_overwrite(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    config_path = tmp_path / "config.toml"
    models_path = tmp_path / "models.json"
    write_file(config_path, b"cfg-original")
    write_file(models_path, b"models-original")
    backup_config_and_models(backup_dir, config_path, models_path)
    write_file(config_path, b"cfg-changed")
    write_file(models_path, b"models-changed")
    c, m = backup_config_and_models(backup_dir, config_path, models_path)
    assert c is False
    assert m is False
    assert (backup_dir / "config.toml").read_bytes() == b"cfg-original"
    assert (backup_dir / "models.json").read_bytes() == b"models-original"


def test_restore_restores_originals(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    config_path = tmp_path / "config.toml"
    models_path = tmp_path / "models.json"
    orig_cfg = b"cfg-original\x00\xff"
    orig_models = b"models-original\n"
    write_file(config_path, orig_cfg)
    write_file(models_path, orig_models)
    backup_config_and_models(backup_dir, config_path, models_path)
    write_file(config_path, b"cfg-modified")
    write_file(models_path, b"models-modified")
    restore(backup_dir, config_path, models_path)
    assert config_path.read_bytes() == orig_cfg
    assert models_path.read_bytes() == orig_models


def test_restore_deletes_when_no_backup(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    config_path = tmp_path / "config.toml"
    models_path = tmp_path / "models.json"
    write_file(config_path, b"cfg")
    write_file(models_path, b"models")
    backup_dir.mkdir()
    restore(backup_dir, config_path, models_path)
    assert not config_path.exists()
    assert not models_path.exists()


def test_manifest_content(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    report = ["Removed openai_base_url", "Rewrote model: a -> b"]
    write_manifest(backup_dir, sample_fields(), report)
    lines = (backup_dir / "manifest.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "script_version=1.0.0"
    assert lines[1] == "provider_id=mimo"
    assert lines[2] == "installed_at=2026-09-08 10:00:00"
    assert lines[3] == "original_config_existed=1"
    assert lines[4] == "models_json_existed=1"
    assert lines[5] == "env_key_used=1"
    assert lines[6] == "env_var_name=MIMO_API_KEY_SELFTEST"
    assert lines[7] == "default_model=mimo-v2.5-pro"
    assert lines[8] == "base_url=https://api.xiaomimimo.com/v1"
    assert lines[9] == "catalog_value=C:/Users/x/.codex/models.json"
    assert lines[10] == ""
    assert lines[11] == "--- changes made to config.toml ---"
    assert lines[12:] == report


def test_restore_removes_backup_dir(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    config_path = tmp_path / "config.toml"
    models_path = tmp_path / "models.json"
    write_file(config_path, b"cfg")
    write_file(models_path, b"models")
    backup_config_and_models(backup_dir, config_path, models_path)
    restore(backup_dir, config_path, models_path)
    assert not backup_dir.exists()


def test_restore_calls_remove_env(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    config_path = tmp_path / "config.toml"
    models_path = tmp_path / "models.json"
    write_file(config_path, b"cfg")
    write_file(models_path, b"models")
    backup_config_and_models(backup_dir, config_path, models_path)
    write_manifest(backup_dir, sample_fields(), [])
    calls: list[str] = []
    restore(backup_dir, config_path, models_path, remove_env=calls.append)
    assert calls == ["MIMO_API_KEY_SELFTEST"]


def test_restore_skips_remove_env_when_not_used(tmp_path):
    backup_dir = tmp_path / "backup-mimo"
    config_path = tmp_path / "config.toml"
    models_path = tmp_path / "models.json"
    write_file(config_path, b"cfg")
    write_file(models_path, b"models")
    backup_config_and_models(backup_dir, config_path, models_path)
    write_manifest(backup_dir, sample_fields(env_key_used=0), [])
    calls: list[str] = []
    restore(backup_dir, config_path, models_path, remove_env=calls.append)
    assert calls == []
