from __future__ import annotations

import os
from pathlib import Path


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    return Path(env) if env else Path.home() / ".codex"


def config_path() -> Path:
    return codex_home() / "config.toml"


def models_path() -> Path:
    return codex_home() / "models.json"


def registry_path() -> Path:
    return codex_home() / "providers-registry.json"


def backup_dir(provider_id: str) -> Path:
    return codex_home() / f"backup-{provider_id}"


def catalog_value() -> str:
    return str(models_path()).replace("\\", "/")
