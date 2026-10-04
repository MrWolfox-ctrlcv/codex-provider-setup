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
    """Read a config file, tolerating a legacy non-UTF-8 encoding.

    A config.toml hand-edited on a Chinese Windows box (or written by an older
    tool) is often GBK/cp936 rather than UTF-8.  Crashing there would lock the
    user out of the tool entirely, so decode with a fallback chain instead;
    the result is re-written as UTF-8 on the next save.
    """
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return sanitize_ctrl(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    for encoding in ("gbk", "cp936", "big5", "latin-1"):
        try:
            return sanitize_ctrl(raw.decode(encoding))
        except (UnicodeDecodeError, LookupError):
            continue
    return sanitize_ctrl(raw.decode("utf-8", errors="replace"))


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


def toml_quote(value: str) -> str:
    """Render ``value`` as a TOML basic string, escaping anything illegal.

    Values reaching the writers can originate from the command line or a user's
    clipboard (API keys, base URLs), so a bare ``f'"{value}"'`` could emit
    unparseable TOML and leave the user with a config Codex cannot read.
    """
    out: list[str] = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def is_legal_provider_id(provider_id: str) -> bool:
    """Provider ids become TOML section names, so keep them to a safe charset."""
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", provider_id or ""))


def is_legal_base_url(base_url: str) -> bool:
    """Accept only http(s) URLs that survive being written as a TOML string."""
    text = (base_url or "").strip()
    if not re.match(r"^https?://", text, re.IGNORECASE):
        return False
    if any(ch in text for ch in ('"', "'", "\n", "\r", "\t")) or " " in text:
        return False
    return True


def is_legal_model_slug(slug: str) -> bool:
    """Model slugs also end up inside TOML strings and JSON keys."""
    if not slug or slug != slug.strip():
        return False
    if any(ch in slug for ch in ('"', "'", "\n", "\r", "\t")):
        return False
    return not any(ch.isspace() for ch in slug)
