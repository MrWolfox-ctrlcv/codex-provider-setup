"""Regression tests for the channel lifecycle.

These lock in the fixes for the reported workflow problems:

* a revoked API key could not be replaced at all (``get_api_key`` always
  preferred the stored credential and never prompted);
* the only way out was ``restore``, which rolled the whole config back and
  therefore also destroyed *other* channels and any later hand edits;
* rotating a key left models the new key cannot use registered in Codex.
"""
from __future__ import annotations

import json
import tomllib

import pytest

from codex_provider import paths, service, toml_edit, upstream
from codex_provider.provider import Provider
from codex_provider.presets import deepseek_preset, wolfox_preset


def make_channel(pid: str, url: str = "https://a.example.com/v1", models=None) -> Provider:
    return Provider(
        id=pid,
        name=pid,
        base_url=url,
        key_prefix="sk-",
        models=list(models or ["m1", "m2"]),
        wire_api="responses",
        context_window=1048576,
        use_env_key=False,
    )


def seed_user_config(tmp_codex_home) -> None:
    paths.config_path().write_text(
        'model = "gpt-5"\n'
        'model_provider = "openai"\n'
        'approval_policy = "on-request"\n'
        "\n"
        "[mcp_servers.filesystem]\n"
        'command = "npx"\n',
        encoding="utf-8",
    )


def slugs() -> list[str]:
    data = json.loads(paths.models_path().read_text(encoding="utf-8"))
    return [m["slug"] for m in data["models"]]


# --------------------------------------------------------------------------
# K1: the stored key must be replaceable
# --------------------------------------------------------------------------


def test_get_api_key_prefers_stored_key(tmp_codex_home):
    """Re-installs stay non-interactive: the stored key is reused."""
    service.install_provider(deepseek_preset(), "sk-OLD", in_selftest=True)
    assert service.get_api_key(deepseek_preset()) == "sk-OLD"


def test_update_api_key_rotates_stored_credential(tmp_codex_home):
    service.install_provider(deepseek_preset(), "sk-OLD-DEAD", in_selftest=True)
    service.update_api_key(deepseek_preset(), "sk-BRAND-NEW")
    assert service.get_api_key(deepseek_preset()) == "sk-BRAND-NEW"
    assert service.stored_api_key("deepseek") == "sk-BRAND-NEW"


def test_update_api_key_touches_only_that_channel(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    service.install_provider(make_channel("chan1"), "sk-one", in_selftest=True)
    service.install_provider(make_channel("chan2", "https://b.example.com/v1"), "sk-two", in_selftest=True)

    service.update_api_key(make_channel("chan1"), "sk-one-new")

    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["model_providers"]["chan1"]["experimental_bearer_token"] == "sk-one-new"
    # The other channel, the user's MCP server and unrelated top-level keys survive.
    assert cfg["model_providers"]["chan2"]["experimental_bearer_token"] == "sk-two"
    assert cfg["mcp_servers"]["filesystem"]["command"] == "npx"
    assert cfg["approval_policy"] == "on-request"


def test_update_api_key_keeps_later_hand_edits(tmp_codex_home):
    """Rotating a key must not roll back the user's own edits."""
    service.install_provider(make_channel("chan1"), "sk-old", in_selftest=True)
    text = paths.config_path().read_text(encoding="utf-8")
    paths.config_path().write_text(
        text + '\n[mcp_servers.added_later]\ncommand = "mine"\n', encoding="utf-8"
    )

    service.update_api_key(make_channel("chan1"), "sk-new")

    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["mcp_servers"]["added_later"]["command"] == "mine"


def test_update_api_key_takes_a_safety_snapshot(tmp_codex_home):
    service.install_provider(make_channel("chan1"), "sk-old", in_selftest=True)
    service.update_api_key(make_channel("chan1"), "sk-new")
    safety = [p for p in paths.codex_home().iterdir() if p.name.startswith("safety-")]
    assert safety, "key rotation must leave a recoverable copy"
    assert any((d / "config.toml").exists() for d in safety)


def test_update_api_key_rejects_empty(tmp_codex_home):
    service.install_provider(make_channel("chan1"), "sk-old", in_selftest=True)
    with pytest.raises(ValueError):
        service.update_api_key(make_channel("chan1"), "   ")
    assert service.stored_api_key("chan1") == "sk-old"


def test_update_api_key_escapes_quotes(tmp_codex_home):
    """A key containing a quote must not corrupt config.toml."""
    service.install_provider(make_channel("chan1"), "sk-old", in_selftest=True)
    weird = 'sk-we"ird\\key'
    service.update_api_key(make_channel("chan1"), weird)
    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["model_providers"]["chan1"]["experimental_bearer_token"] == weird


# --------------------------------------------------------------------------
# K2: removing one channel must not harm the others
# --------------------------------------------------------------------------


def test_remove_channel_leaves_other_channels_intact(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    service.install_provider(make_channel("chan1"), "sk-one", in_selftest=True)
    service.install_provider(make_channel("chan2", "https://b.example.com/v1", ["m3"]), "sk-two", in_selftest=True)

    service.remove_channel("chan1", confirm=lambda: True)

    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert "chan1" not in cfg["model_providers"]
    assert cfg["model_providers"]["chan2"]["base_url"] == "https://b.example.com/v1"
    assert cfg["mcp_servers"]["filesystem"]["command"] == "npx"


def test_remove_channel_drops_only_its_own_models(tmp_codex_home):
    service.install_provider(make_channel("chan1", models=["shared", "only-1"]), "k1", in_selftest=True)
    service.install_provider(make_channel("chan2", "https://b/v1", ["shared", "only-2"]), "k2", in_selftest=True)

    service.remove_channel("chan1", confirm=lambda: True)

    remaining = slugs()
    # A model still used by chan2 stays; chan1's exclusive model goes.
    assert "shared" in remaining
    assert "only-2" in remaining
    assert "only-1" not in remaining


def test_remove_channel_updates_registry(tmp_codex_home):
    service.install_provider(make_channel("chan1"), "k1", in_selftest=True)
    service.install_provider(make_channel("chan2", "https://b/v1"), "k2", in_selftest=True)
    service.remove_channel("chan1", confirm=lambda: True)
    reg = json.loads(paths.registry_path().read_text(encoding="utf-8"))
    assert [p["id"] for p in reg["providers"]] == ["chan2"]


def test_remove_channel_cancel_changes_nothing(tmp_codex_home):
    service.install_provider(make_channel("chan1"), "k1", in_selftest=True)
    before = paths.config_path().read_text(encoding="utf-8")
    service.remove_channel("chan1", confirm=lambda: False)
    assert paths.config_path().read_text(encoding="utf-8") == before


def test_remove_unknown_channel_raises(tmp_codex_home):
    service.install_provider(make_channel("chan1"), "k1", in_selftest=True)
    with pytest.raises(ValueError):
        service.remove_channel("nope", confirm=lambda: True)


# --------------------------------------------------------------------------
# B1: restore must warn about collateral damage
# --------------------------------------------------------------------------


def test_restore_impact_lists_other_channels(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    service.install_provider(deepseek_preset(), "sk-1", in_selftest=True)
    service.install_provider(wolfox_preset(), "sk-2", in_selftest=True)
    assert service.restore_impact("deepseek") == ["wolfox"]


def test_restore_warns_before_destroying_other_channels(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    service.install_provider(deepseek_preset(), "sk-1", in_selftest=True)
    service.install_provider(wolfox_preset(), "sk-2", in_selftest=True)

    out: list[str] = []
    service.restore_provider(deepseek_preset(), echo=out.append, confirm=lambda: False)
    text = "\n".join(out)
    assert "wolfox" in text
    assert "删除渠道" in text


def test_restore_cancel_is_a_no_op(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    service.install_provider(deepseek_preset(), "sk-1", in_selftest=True)
    service.install_provider(wolfox_preset(), "sk-2", in_selftest=True)
    before = paths.config_path().read_text(encoding="utf-8")

    service.restore_provider(deepseek_preset(), echo=lambda _m: None, confirm=lambda: False)

    assert paths.config_path().read_text(encoding="utf-8") == before
    assert "wolfox" in paths.config_path().read_text(encoding="utf-8")


def test_restore_with_others_takes_safety_snapshot(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    service.install_provider(deepseek_preset(), "sk-1", in_selftest=True)
    service.install_provider(wolfox_preset(), "sk-2", in_selftest=True)

    service.restore_provider(deepseek_preset(), echo=lambda _m: None, confirm=lambda: True)

    safety = [p for p in paths.codex_home().iterdir() if p.name.startswith("safety-")]
    assert safety, "a restore that clobbers other channels must snapshot first"


# --------------------------------------------------------------------------
# B3: switch must never write an unparseable config
# --------------------------------------------------------------------------


def test_switch_rejects_illegal_slug(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    with pytest.raises(ValueError):
        service.switch_default_model('evil"model')
    # config.toml still parses, i.e. it was not corrupted.
    tomllib.loads(paths.config_path().read_text(encoding="utf-8"))


def test_switch_writes_valid_toml_and_backs_up(tmp_codex_home):
    seed_user_config(tmp_codex_home)
    service.switch_default_model("gpt-5.6-sol")
    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["model"] == "gpt-5.6-sol"
    assert any(p.name.startswith("safety-") for p in paths.codex_home().iterdir())


# --------------------------------------------------------------------------
# K3: the model list must follow the credential
# --------------------------------------------------------------------------


def test_sync_from_upstream_adds_new_models(tmp_codex_home, monkeypatch):
    service.install_provider(deepseek_preset(), "sk-1", in_selftest=True)
    monkeypatch.setattr(
        upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["deepseek-v4-flash", "deepseek-v4-pro", "brand-new"], "raw": {}},
    )
    merged = service.sync_from_upstream(deepseek_preset(), "sk-1", echo=lambda _m: None)
    assert merged is not None
    assert "brand-new" in slugs()


# --------------------------------------------------------------------------
# prune must probe the endpoint the provider actually speaks
# --------------------------------------------------------------------------


def test_probe_endpoints_follow_wire_api():
    assert upstream.probe_endpoints("responses") == ["responses"]
    assert upstream.probe_endpoints("chat")[0] == "chat/completions"


def test_probe_models_passes_wire_api(tmp_codex_home, monkeypatch):
    seen: list[str] = []

    def fake_probe(base, key, slug, timeout=20, wire_api="chat"):
        seen.append(wire_api)
        return True, "usable", ""

    monkeypatch.setattr(upstream, "probe_model", fake_probe)
    upstream.probe_models(["m1"], "https://a/v1", "sk", wire_api="responses")
    assert seen == ["responses"]


def test_prune_uses_provider_wire_api(tmp_codex_home, monkeypatch):
    seen: list[str] = []

    def fake_probe(models, base, key, timeout=20, on_result=None, wire_api="chat"):
        seen.append(wire_api)
        return (list(models), [], [])

    monkeypatch.setattr(upstream, "probe_models", fake_probe)
    prov = deepseek_preset()  # wire_api="responses"
    service.prune_unusable(prov, "sk", echo=lambda _m: None)
    assert seen == ["responses"]


# --------------------------------------------------------------------------
# Redirects must not leak the credential
# --------------------------------------------------------------------------


def test_redirect_handler_refuses_to_follow():
    handler = upstream._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x") is None


def test_fetch_models_does_not_leak_key_on_redirect():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: dict[str, str | None] = {}

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen["origin"] = self.headers.get("Authorization")
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{srv2.server_port}/steal")
            self.end_headers()

        def log_message(self, *a):  # noqa: ANN002
            pass

    class Thief(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen["stolen"] = self.headers.get("Authorization")
            body = json.dumps({"data": [{"id": "m"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # noqa: ANN002
            pass

    srv2 = HTTPServer(("127.0.0.1", 0), Thief)
    srv1 = HTTPServer(("127.0.0.1", 0), Origin)
    for srv in (srv1, srv2):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        upstream.fetch_models(f"http://127.0.0.1:{srv1.server_port}/v1", "sk-SECRET")
    finally:
        srv1.shutdown()
        srv2.shutdown()

    assert seen.get("origin") == "Bearer sk-SECRET"
    assert seen.get("stolen") is None, "the API key must never reach a redirect target"


# --------------------------------------------------------------------------
# I1: the reasoning-effort answer must survive into config.toml
# --------------------------------------------------------------------------


def test_install_honours_provider_reasoning_effort(tmp_codex_home):
    prov = deepseek_preset()
    prov.reasoning_effort = "low"
    service.install_provider(prov, "sk-1", in_selftest=True)
    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["model_reasoning_effort"] == "low"


def test_explicit_argument_overrides_provider_default(tmp_codex_home):
    prov = deepseek_preset()
    prov.reasoning_effort = "low"
    service.install_provider(prov, "sk-1", reasoning_effort="max", in_selftest=True)
    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["model_reasoning_effort"] == "max"


# --------------------------------------------------------------------------
# Non-UTF-8 configs must not crash the tool
# --------------------------------------------------------------------------


def test_non_utf8_config_is_readable(tmp_codex_home):
    paths.config_path().write_bytes('# 中文注释\nmodel = "gpt-5"\n'.encode("gbk"))
    # Should not raise; the config is re-written as UTF-8 on the next save.
    from codex_provider.io_utils import read_text

    assert "gpt-5" in read_text(paths.config_path())


def test_install_over_non_utf8_config(tmp_codex_home):
    paths.config_path().write_bytes('model = "gpt-5"\nmodel_provider = "openai"\n# 中文\n'.encode("gbk"))
    service.install_provider(deepseek_preset(), "sk-1", in_selftest=True)
    cfg = tomllib.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["model_provider"] == "deepseek"


# --------------------------------------------------------------------------
# toml_edit primitives
# --------------------------------------------------------------------------


def test_set_bearer_token_only_touches_target_section():
    src = (
        '[model_providers.a]\nbase_url = "https://a/v1"\nexperimental_bearer_token = "old-a"\n'
        '\n[model_providers.b]\nbase_url = "https://b/v1"\nexperimental_bearer_token = "old-b"\n'
    )
    out = toml_edit.set_bearer_token(src, "a", "new-a")
    parsed = tomllib.loads(out)
    assert parsed["model_providers"]["a"]["experimental_bearer_token"] == "new-a"
    assert parsed["model_providers"]["b"]["experimental_bearer_token"] == "old-b"


def test_set_bearer_token_unknown_provider_is_a_noop():
    """An unknown id must not append a stray top-level key (invalid TOML)."""
    src = '[model_providers.a]\nbase_url = "https://a/v1"\nexperimental_bearer_token = "old"\n'
    out = toml_edit.set_bearer_token(src, "nope", "new")
    assert out == src
    tomllib.loads(out)


def test_set_bearer_token_adds_line_to_env_key_section():
    """A section configured with env_key has no bearer line; one is appended
    inside that section, not at the end of the file."""
    src = (
        '[model_providers.a]\nbase_url = "https://a/v1"\nenv_key = "A_KEY"\n'
        '\n[model_providers.b]\nbase_url = "https://b/v1"\n'
    )
    out = toml_edit.set_bearer_token(src, "a", "new-a")
    parsed = tomllib.loads(out)
    assert parsed["model_providers"]["a"]["experimental_bearer_token"] == "new-a"
    # The injected key belongs to section a, so b must stay untouched.
    assert "experimental_bearer_token" not in parsed["model_providers"]["b"]
    assert parsed["model_providers"]["a"]["env_key"] == "A_KEY"


def test_remove_provider_section_keeps_rest():
    src = (
        'model = "gpt-5"\n\n[mcp_servers.x]\ncommand = "c"\n\n'
        '[model_providers.a]\nbase_url = "https://a/v1"\n\n'
        '[model_providers.b]\nbase_url = "https://b/v1"\n'
    )
    out, removed = toml_edit.remove_provider_section(src, "a")
    parsed = tomllib.loads(out)
    assert removed
    assert list(parsed["model_providers"]) == ["b"]
    assert parsed["mcp_servers"]["x"]["command"] == "c"
    assert parsed["model"] == "gpt-5"


def test_edit_config_escapes_hostile_values():
    cfg = toml_edit.edit_config(
        source='model = "gpt-5"\n',
        provider_id="p1",
        base_url='https://a/v1"x',
        wire_api="responses",
        use_env_key=False,
        env_var_name="",
        api_key_value='sk-a"b\nc',
        model_slug='we"ird',
        reasoning_effort="high",
        catalog_value="/tmp/m.json",
    )
    parsed = tomllib.loads(cfg.text)
    assert parsed["model_providers"]["p1"]["base_url"] == 'https://a/v1"x'
    assert parsed["model_providers"]["p1"]["experimental_bearer_token"] == 'sk-a"b\nc'


# --------------------------------------------------------------------------
# Version must be single-sourced (it previously drifted: 0.1.0 vs 1.1.0)
# --------------------------------------------------------------------------


def test_version_is_single_sourced():
    from codex_provider import __version__
    from codex_provider.service import SCRIPT_VERSION

    assert SCRIPT_VERSION == __version__


def test_pyproject_does_not_hardcode_a_second_version():
    """pyproject must take the version dynamically from the package."""
    import tomllib as _tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    data = _tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert "version" not in project, "pyproject hardcodes a version again"
    assert "version" in project.get("dynamic", [])
    assert data["tool"]["hatch"]["version"]["path"] == "codex_provider/__init__.py"


def test_selftest_survives_a_non_utf8_console():
    """The UI is Chinese; a cp1252/GBK console must not crash it.

    CI runners default to cp1252 and Chinese Windows consoles to GBK, where
    printing a normal message raised UnicodeEncodeError and killed the program
    while it was reporting an error.
    """
    import io
    import subprocess
    import sys

    env = dict(**__import__("os").environ)
    env["PYTHONIOENCODING"] = "cp1252"
    proc = subprocess.run(
        [sys.executable, "-m", "codex_provider", "selftest"],
        capture_output=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert b"UnicodeEncodeError" not in proc.stderr


def test_print_helpers_never_raise_on_unencodable_console(monkeypatch):
    """_safe_print must degrade instead of raising."""
    import io
    import sys as _sys

    from codex_provider import interact

    class BadStream(io.TextIOBase):
        encoding = "cp1252"

        def write(self, s):  # noqa: ANN001
            raise UnicodeEncodeError("cp1252", s, 0, 1, "nope")

    monkeypatch.setattr(_sys, "stdout", BadStream())
    # Must not raise.
    interact.ok("中文消息")
    interact.err("中文错误")
