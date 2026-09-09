from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib import error, request

VERSION_SUFFIX_RE = re.compile(r"/v\d+/?$", re.IGNORECASE)

CONTEXT_WINDOW_KEYS = (
    "context_window",
    "max_context_window",
    "context_length",
    "context",
    "max_input_tokens",
    "input_token_limit",
)


def _normalize_base(base_url: str) -> str:
    return base_url.strip().rstrip("/") + "/"


def parse_models_response(data: Any) -> list[str]:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    slugs: list[str] = []
    seen: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        candidate = ""
        for key in ("id", "name", "model"):
            value = entry.get(key)
            if isinstance(value, str):
                candidate = value
                break
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                candidate = str(value)
                break
        slug = candidate.strip()
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def detect_context_window(data: Any) -> int | None:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    for entry in items:
        if not isinstance(entry, dict):
            continue
        for key in CONTEXT_WINDOW_KEYS:
            value = entry.get(key)
            if value is None or isinstance(value, bool):
                continue
            text = str(value).strip()
            if text.lstrip("-").isdigit():
                number = int(text)
                if number > 0:
                    return number
    return None


def classify_http(code: int) -> str:
    if code in (401, 402, 403, 404):
        return "unusable"
    return "unknown"


def fetch_models(base_url: str, api_key: str, timeout: int = 20) -> dict:
    base = _normalize_base(base_url)
    uris = [base + "models"]
    if not VERSION_SUFFIX_RE.search(base):
        uris.append(base + "v1/models")
    last_error = ""
    for uri in uris:
        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            req = request.Request(uri, headers=headers)
            with request.urlopen(req, timeout=timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "models": parse_models_response(raw), "raw": raw}
        except Exception as exc:
            last_error = str(exc)
    return {"ok": False, "models": [], "raw": None, "error": last_error}


def probe_model(
    base_url: str, api_key: str, slug: str, timeout: int = 20
) -> tuple[bool, str, str]:
    base = _normalize_base(base_url)
    uri = base + "chat/completions"
    body = json.dumps(
        {"model": slug, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    ).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    req = request.Request(uri, data=body, method="POST", headers=headers)
    try:
        with request.urlopen(req, timeout=timeout):
            return True, "usable", ""
    except error.HTTPError as exc:
        return False, classify_http(exc.code), f"HTTP {exc.code}"
    except Exception as exc:
        return False, "unknown", str(exc)


def probe_models(
    models: list[str],
    base_url: str,
    api_key: str,
    timeout: int = 20,
    on_result: Callable[[str, bool, str, str], None] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    usable: list[str] = []
    unusable: list[str] = []
    unknown: list[str] = []
    for slug in models:
        ok, category, detail = probe_model(base_url, api_key, slug, timeout=timeout)
        if on_result is not None:
            on_result(slug, ok, category, detail)
        if ok:
            usable.append(slug)
        elif category == "unusable":
            unusable.append(slug)
        else:
            unknown.append(slug)
    return usable, unusable, unknown
