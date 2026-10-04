from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from codex_provider.io_utils import read_text, write_text

_RC_NAMES = [".zshrc", ".bashrc", ".bash_profile", ".profile"]
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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
    """Escape a value for a double-quoted POSIX shell assignment.

    Newlines are escaped too: a raw newline would split the ``export`` across
    two lines and leave a syntax error (or a stray command) in every new shell.
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def _is_real_export(line: str, prefix: str) -> bool:
    """Match an active ``export NAME=`` assignment, ignoring comments."""
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return False
    return stripped.startswith(prefix)


def _backup_once(path: Path) -> Path | None:
    """Keep one recoverable copy of an rc file before the first modification."""
    if not path.exists():
        return None
    bak = path.with_name(path.name + ".codex-provider-setup.bak")
    if bak.exists():
        return bak
    try:
        shutil.copy2(path, bak)
        return bak
    except OSError:
        return None


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
        if _is_real_export(line, prefix):
            out.append(newline)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(newline)
    _backup_once(path)
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
    out = [line for line in lines if not _is_real_export(line, prefix)]
    if len(out) == len(lines):
        return
    _backup_once(path)
    write_text(path, "\n".join(out) + "\n" if out else "")


def _default_rc_files(home: Path | None) -> list[Path]:
    return _rc_candidates(home if home is not None else Path.home(), os.environ.get("SHELL"))


def _write_targets(rc_files: list[Path]) -> list[Path]:
    """Only touch rc files that already exist.

    Writing the same secret into all four candidates created it in shells the
    user never configured; a file that does not exist is left alone.
    """
    existing = [p for p in rc_files if p.exists()]
    if existing:
        return existing
    # Nothing exists yet (fresh account): fall back to the first candidate so
    # the key still becomes available in the user's shell.
    return rc_files[:1]


def persist_env(
    name: str,
    value: str,
    *,
    platform: str | None = None,
    rc_files: list[Path] | None = None,
    home: Path | None = None,
) -> None:
    if not _ENV_NAME_RE.fullmatch(name or ""):
        raise ValueError(f"环境变量名不合法：{name!r}")
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
    for path in _write_targets(rc_files):
        _upsert_export(path, name, value)


def remove_env(
    name: str,
    *,
    platform: str | None = None,
    rc_files: list[Path] | None = None,
    home: Path | None = None,
) -> None:
    if not _ENV_NAME_RE.fullmatch(name or ""):
        return
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
