from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from codex_provider.io_utils import read_text, write_text


def backup_config_and_models(backup_dir: Path, config_path: Path, models_path: Path) -> tuple[bool, bool]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    bak_config = backup_dir / "config.toml"
    bak_models = backup_dir / "models.json"
    config_backed_up = False
    if config_path.exists() and not bak_config.exists():
        shutil.copy2(config_path, bak_config)
        config_backed_up = True
    models_backed_up = False
    if models_path.exists() and not bak_models.exists():
        shutil.copy2(models_path, bak_models)
        models_backed_up = True
    return config_backed_up, models_backed_up


def write_manifest(backup_dir: Path, fields: dict[str, str], report: list[str]) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in fields.items()]
    lines.append("")
    lines.append("--- changes made to config.toml ---")
    lines.extend(report)
    write_text(backup_dir / "manifest.txt", "\n".join(lines) + "\n")


def restore(
    backup_dir: Path,
    config_path: Path,
    models_path: Path,
    remove_env: Callable[[str], None] | None = None,
) -> None:
    bak_config = backup_dir / "config.toml"
    if bak_config.exists():
        shutil.copy2(bak_config, config_path)
    elif config_path.exists():
        config_path.unlink()
    bak_models = backup_dir / "models.json"
    if bak_models.exists():
        shutil.copy2(bak_models, models_path)
    elif models_path.exists():
        models_path.unlink()
    manifest_path = backup_dir / "manifest.txt"
    if manifest_path.exists() and remove_env is not None:
        env_used = False
        env_name = ""
        for line in read_text(manifest_path).splitlines():
            if line.startswith("env_key_used=1"):
                env_used = True
            if line.startswith("env_var_name="):
                env_name = line.split("=", 1)[1].strip()
        if env_used and env_name:
            remove_env(env_name)
    shutil.rmtree(backup_dir)
