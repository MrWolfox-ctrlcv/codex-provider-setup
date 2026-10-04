from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib import error, request


class _NoRedirect(request.HTTPRedirectHandler):
    """Refuse to follow redirects.

    urllib's default handler re-sends every header except content-length and
    content-type, which means an ``Authorization: Bearer <key>`` header is
    forwarded to whatever host the redirect names.  A user-supplied
    ``--base-url`` (or a compromised/misconfigured gateway) could therefore
    harvest the API key; treat any redirect as a hard error instead.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = request.build_opener(_NoRedirect)


def open_url(req: request.Request, timeout: int):
    return _OPENER.open(req, timeout=timeout)

VERSION_SUFFIX_RE = re.compile(r"/v\d+/?$", re.IGNORECASE)

CONTEXT_WINDOW_KEYS = (
    "context_window",
    "max_context_window",
    "context_length",
    "context",
    "max_input_tokens",
    "input_token_limit",
)

# Some gateways (New-API 中转站、CDN/WAF) reject the default
# "Python-urllib/3.x" User-Agent with 400/403.  Send a browser-like UA so
# such providers behave identically to a normal OpenAI-compatible client.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Cap the /models body we are willing to buffer: a broken or hostile gateway
# could otherwise stream gigabytes and exhaust memory.
MAX_RESPONSE_BYTES = 8_000_000


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
            headers = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": BROWSER_UA,
            }
            req = request.Request(uri, headers=headers)
            with open_url(req, timeout=timeout) as resp:
                raw = json.loads(resp.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="replace"))
            return {"ok": True, "models": parse_models_response(raw), "raw": raw}
        except Exception as exc:
            last_error = str(exc)
    return {"ok": False, "models": [], "raw": None, "error": last_error}


def probe_endpoints(wire_api: str) -> list[str]:
    """Request paths to try when probing one model.

    A ``responses`` provider must be probed on ``/responses``; posting to
    ``/chat/completions`` makes a perfectly usable model look broken, which
    previously caused ``prune`` to delete working models.
    """
    if (wire_api or "").strip().lower() == "responses":
        return ["responses"]
    return ["chat/completions", "responses"]


def _probe_body(wire_api: str, slug: str) -> bytes:
    if wire_api == "responses":
        return json.dumps({"model": slug, "input": "hi"}).encode("utf-8")
    return json.dumps(
        {"model": slug, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    ).encode("utf-8")


def probe_model(
    base_url: str,
    api_key: str,
    slug: str,
    timeout: int = 20,
    wire_api: str = "chat",
) -> tuple[bool, str, str]:
    base = _normalize_base(base_url)
    last: tuple[bool, str, str] = (False, "unknown", "no endpoint tried")
    for path in probe_endpoints(wire_api):
        # A responses probe that fails with 404 may just mean the gateway does
        # not implement that route; fall through to the next candidate.
        uri = base + path
        body = _probe_body("responses" if path == "responses" else "chat", slug)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
        }
        req = request.Request(uri, data=body, method="POST", headers=headers)
        try:
            with open_url(req, timeout=timeout) as resp:
                resp.read(1024)
            return True, "usable", ""
        except error.HTTPError as exc:
            last = (False, classify_http(exc.code), f"HTTP {exc.code}")
            if exc.code != 404:
                return last
        except Exception as exc:
            last = (False, "unknown", str(exc))
            return last
    return last


def probe_models(
    models: list[str],
    base_url: str,
    api_key: str,
    timeout: int = 20,
    on_result: Callable[[str, bool, str, str], None] | None = None,
    wire_api: str = "chat",
) -> tuple[list[str], list[str], list[str]]:
    usable: list[str] = []
    unusable: list[str] = []
    unknown: list[str] = []
    for slug in models:
        ok, category, detail = probe_model(base_url, api_key, slug, timeout=timeout, wire_api=wire_api)
        if on_result is not None:
            on_result(slug, ok, category, detail)
        if ok:
            usable.append(slug)
        elif category == "unusable":
            unusable.append(slug)
        else:
            unknown.append(slug)
    return usable, unusable, unknown
