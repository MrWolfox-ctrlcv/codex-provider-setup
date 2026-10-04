from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Control characters that are illegal inside TOML/JSON files but often sneak
# in via copy-paste from web pages/documents (e.g. \x16 SYN).  Tab / LF / CR
# are legal and preserved.
_ILLEGAL_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BOM = "\ufeff"


def sanitize_ctrl(text: str) -> str:
    """Remove control characters that are illegal inside TOML/JSON files.

    Keeps \\t (0x09), \\n (0x0a) and \\r (0x0d); strips everything else in the
    C0/C1 range plus DEL, and a leading UTF-8 BOM.  Useful when the source
    config.toml was polluted by copy-paste and would otherwise fail TOML
    validation.
    """
    text = _ILLEGAL_CTRL_RE.sub("", text)
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    return text


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return sanitize_ctrl(f.read())


def write_text(path: Path, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def atomic_write(path: Path, content: str, tmp_suffix: str = ".tmp") -> None:
    tmp = path.with_name(path.name + tmp_suffix)
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    os.replace(tmp, path)


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path))
    except (ValueError, OSError):
        return None


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))
