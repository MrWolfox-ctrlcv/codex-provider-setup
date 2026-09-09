from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from codex_provider import upstream

PARSE_CASES = [
    (None, []),
    ({}, []),
    ({"data": {}}, []),
    ({"data": "x"}, []),
    ({"data": [{"id": " a "}]}, ["a"]),
    ({"data": [{"id": "a"}, {"id": "a"}]}, ["a"]),
    ({"data": [{"name": "b"}]}, ["b"]),
    ({"data": [{"model": "c"}]}, ["c"]),
    ({"data": [{"id": "x", "name": "y"}]}, ["x"]),
    ({"data": [{"name": "y", "model": "z"}]}, ["y"]),
    ({"data": [{"id": ""}, {"id": "   "}, {}]}, []),
    ({"data": [{"id": 7}]}, ["7"]),
    ({"data": [{"name": " b "}, {"model": "b"}, {"id": "c"}, {"id": "c"}]}, ["b", "c"]),
]

DETECT_CASES = [
    (None, None),
    ({}, None),
    ({"data": []}, None),
    ({"data": [{"id": "x"}]}, None),
    ({"data": [{"context_window": 0}, {"context_window": 2}]}, 2),
    ({"data": [{"context_window": -4, "max_context_window": 8192}]}, 8192),
    ({"data": [{"context_window": 0, "max_context_window": 8}]}, 8),
    ({"data": [{"context_length": "32768"}]}, 32768),
    ({"data": [{"context": 4096, "max_input_tokens": 100}]}, 4096),
    ({"data": [{"input_token_limit": 200000}]}, 200000),
    ({"data": [{"max_input_tokens": 120}]}, 120),
    ({"data": [{"context_window": " 65536 "}]}, 65536),
    ({"data": [{"context_window": 1.5}]}, None),
    ({"data": [{"max_context_window": True}]}, None),
]

CLASSIFY_CASES = [
    (0, "unknown"),
    (200, "unknown"),
    (201, "unknown"),
    (400, "unknown"),
    (401, "unusable"),
    (402, "unusable"),
    (403, "unusable"),
    (404, "unusable"),
    (405, "unknown"),
    (422, "unknown"),
    (429, "unknown"),
    (500, "unknown"),
    (503, "unknown"),
]


def make_handler(routes: dict) -> tuple[type, list]:
    seen: list = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def handle_one(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            with lock:
                seen.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "content_type": self.headers.get("Content-Type"),
                        "body": body,
                    }
                )
            rule = routes.get((self.command, self.path))
            if rule is None:
                status, payload = 404, {"error": "not found"}
            elif callable(rule):
                status, payload = rule(self.command, self.path, body, self.headers)
            else:
                status, payload = rule
            if isinstance(payload, dict):
                payload = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except OSError:
                pass

        do_GET = handle_one
        do_POST = handle_one

        def log_message(self, *args: object) -> None:
            pass

    return Handler, seen


@pytest.fixture
def serve():
    servers: list[ThreadingHTTPServer] = []

    def start(routes: dict) -> tuple[str, list]:
        handler, seen = make_handler(routes)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}", seen

    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("payload, expected", PARSE_CASES)
def test_parse_models_response(payload, expected):
    assert upstream.parse_models_response(payload) == expected


@pytest.mark.parametrize("payload, expected", DETECT_CASES)
def test_detect_context_window(payload, expected):
    assert upstream.detect_context_window(payload) == expected


@pytest.mark.parametrize("code, expected", CLASSIFY_CASES)
def test_classify_http(code, expected):
    assert upstream.classify_http(code) == expected


def test_fetch_models_success(serve):
    payload = {
        "data": [
            {"id": "model-a", "object": "model"},
            {"id": "model-b"},
            {"name": "model-b "},
            {},
            {"model": "model-c"},
            {"name": "  "},
            {"name": "model-d", "id": "model-c"},
        ]
    }
    url, seen = serve({("GET", "/models"): (200, payload)})
    result = upstream.fetch_models(url, "sk-test")
    assert result["ok"] is True
    assert result["models"] == ["model-a", "model-b", "model-c"]
    assert result["raw"] == payload
    assert len(seen) == 1
    req = seen[0]
    assert req["method"] == "GET"
    assert req["path"] == "/models"
    assert req["auth"] == "Bearer sk-test"


@pytest.mark.parametrize("suffix", ["/v1", "/v1/"])
def test_fetch_models_no_duplicate_v1_when_base_has_version(serve, suffix):
    payload = {"data": [{"id": "already-v1"}]}
    url, seen = serve({("GET", "/v1/models"): (200, payload)})
    result = upstream.fetch_models(url + suffix, "sk")
    assert result["ok"] is True
    assert result["models"] == ["already-v1"]
    assert [r["path"] for r in seen] == ["/v1/models"]


def test_fetch_models_falls_back_to_v1_models(serve):
    payload = {"data": [{"id": "fallback-v1-model"}]}
    routes = {
        ("GET", "/models"): (404, {"error": "no such endpoint"}),
        ("GET", "/v1/models"): (200, payload),
    }
    url, seen = serve(routes)
    result = upstream.fetch_models(url, "sk")
    assert result["ok"] is True
    assert result["models"] == ["fallback-v1-model"]
    assert result["raw"] == payload
    assert [r["path"] for r in seen] == ["/models", "/v1/models"]


def test_fetch_models_all_endpoints_fail(serve):
    routes = {
        ("GET", "/models"): (404, {"error": "no"}),
        ("GET", "/v1/models"): (404, {"error": "no"}),
    }
    url, seen = serve(routes)
    result = upstream.fetch_models(url, "sk")
    assert result["ok"] is False
    assert result["models"] == []
    assert result["raw"] is None
    assert "404" in result["error"]
    assert [r["path"] for r in seen] == ["/models", "/v1/models"]


def test_probe_model_usable(serve):
    url, seen = serve({("POST", "/chat/completions"): (200, {"id": "chatcmpl-x"})})
    ok, category, detail = upstream.probe_model(url, "sk-test", "demo-model")
    assert (ok, category, detail) == (True, "usable", "")
    req = seen[0]
    assert req["method"] == "POST"
    assert req["path"] == "/chat/completions"
    assert req["auth"] == "Bearer sk-test"
    assert req["content_type"] == "application/json"
    assert json.loads(req["body"]) == {
        "model": "demo-model",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }


def test_probe_model_unauthorized(serve):
    url, seen = serve({("POST", "/chat/completions"): (401, {"error": "bad key"})})
    ok, category, detail = upstream.probe_model(url, "sk", "demo-model")
    assert (ok, category, detail) == (False, "unusable", "HTTP 401")


def test_probe_model_server_error(serve):
    url, seen = serve({("POST", "/chat/completions"): (500, {"error": "boom"})})
    ok, category, detail = upstream.probe_model(url, "sk", "demo-model")
    assert (ok, category, detail) == (False, "unknown", "HTTP 500")


def test_probe_model_network_error_unknown():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler({})[0])
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    srv.server_close()
    ok, category, detail = upstream.probe_model(url, "sk", "demo-model")
    assert ok is False
    assert category == "unknown"
    assert detail


def test_probe_models_groups_and_calls_back(serve):
    def chat_rule(method, path, body, headers):
        slug = json.loads(body)["model"]
        if slug == "good":
            return 200, {"id": "x"}
        if slug == "bad":
            return 401, {"error": "denied"}
        return 500, {"error": "boom"}

    url, seen = serve({("POST", "/chat/completions"): chat_rule})
    calls: list[tuple] = []
    usable, unusable, unknown = upstream.probe_models(
        ["good", "bad", "weird"],
        url,
        "sk",
        on_result=lambda slug, ok, cat, detail: calls.append((slug, ok, cat, detail)),
    )
    assert usable == ["good"]
    assert unusable == ["bad"]
    assert unknown == ["weird"]
    assert calls == [
        ("good", True, "usable", ""),
        ("bad", False, "unusable", "HTTP 401"),
        ("weird", False, "unknown", "HTTP 500"),
    ]
