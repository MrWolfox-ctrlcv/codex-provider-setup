from __future__ import annotations

import os
import sys
from pathlib import Path

from codex_provider.io_utils import read_text, write_text

_RC_NAMES = [".zshrc", ".bashrc", ".bash_profile", ".profile"]


def _rc_candidates(home: Path, shell: str | None = None) -> list[Path]:
    names = list(_RC_NAMES)
    if shell and shell.endswith("zsh"):
        names.remove(".zshrc")
        names.insert(0, ".zshrc")
    elif shell and shell.endswith("bash"):
        names.remove(".bashrc")
        names.insert(0, ".bashrc")
    return [home / name for name in names]


def _escape_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


def _upsert_export(path: Path, name: str, value: str) -> None:
    text = read_text(path).replace("\r\n", "\n") if path.exists() else ""
    has_nl = text.endswith("\n")
    lines = text.split("\n") if text else []
    if has_nl:
        lines.pop()
    prefix = f"export {name}="
    newline = f'export {name}="{_escape_value(value)}"'
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            out.append(newline)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(newline)
    write_text(path, "\n".join(out) + "\n")


def _remove_export(path: Path, name: str) -> None:
    if not path.exists():
        return
    text = read_text(path).replace("\r\n", "\n")
    if not text:
        return
    has_nl = text.endswith("\n")
    lines = text.split("\n")
    if has_nl:
        lines.pop()
    prefix = f"export {name}="
    out = [line for line in lines if not line.startswith(prefix)]
    if len(out) == len(lines):
        return
    write_text(path, "\n".join(out) + "\n" if out else "")


def _default_rc_files(home: Path | None) -> list[Path]:
    return _rc_candidates(home if home is not None else Path.home(), os.environ.get("SHELL"))


def persist_env(
    name: str,
    value: str,
    *,
    platform: str | None = None,
    rc_files: list[Path] | None = None,
    home: Path | None = None,
) -> None:
    plat = platform if platform is not None else sys.platform
    if plat.startswith("win"):
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        return
    if rc_files is None:
        rc_files = _default_rc_files(home)
    for path in rc_files:
        _upsert_export(path, name, value)


def remove_env(
    name: str,
    *,
    platform: str | None = None,
    rc_files: list[Path] | None = None,
    home: Path | None = None,
) -> None:
    plat = platform if platform is not None else sys.platform
    if plat.startswith("win"):
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
        return
    if rc_files is None:
        rc_files = _default_rc_files(home)
    for path in rc_files:
        _remove_export(path, name)
