from __future__ import annotations

import tomllib

from codex_provider.toml_edit import EditResult, edit_config, switch_model

SAMPLE = r'''model = "deepseek-v4-flash"
model_provider = "deepseek"
openai_base_url = "https://api.openai.com/v1"
sandbox_mode = "danger-full-access"

[model_providers.deepseek]
name = "deepseek"
base_url = "https://api.deepseek.com/"
wire_api = "responses"
experimental_bearer_token = "sk-test"

[model_providers.other]
name = "other"
base_url = "https://example.com/v1"
wire_api = "chat"
env_key = "OTHER_KEY"

[desktop]
localeOverride = "zh-CN"

[projects.'e:\aipic']
trust_level = "trusted"

[profiles.claude]
model = "deepseek-v4-flash"
'''

CATALOG = "C:/Users/x/.codex/models.json"


def install_mimo(src: str) -> EditResult:
    return edit_config(
        source=src,
        provider_id="mimo",
        base_url="https://api.xiaomimimo.com/v1",
        wire_api="responses",
        use_env_key=True,
        env_var_name="MIMO_API_KEY_SELFTEST",
        api_key_value="sk-selftest-key",
        model_slug="mimo-v2.5-pro",
        reasoning_effort="high",
        catalog_value=CATALOG,
        disable_web_search=True,
    )


def test_install_mimo_env_key():
    r = install_mimo(SAMPLE)
    t = r.text
    assert t.count("[model_providers.mimo]") == 1
    assert 'env_key = "MIMO_API_KEY_SELFTEST"' in t
    assert 'model = "mimo-v2.5-pro"' in t
    assert 'model_provider = "mimo"' in t
    assert 'preferred_auth_method = "apikey"' in t
    assert 'forced_login_method = "api"' in t
    assert 'model_reasoning_effort = "high"' in t
    assert f'model_catalog_json = "{CATALOG}"' in t
    assert t.count('web_search = "disabled"') == 1
    assert "openai_base_url" not in t
    assert "[profiles" not in t
    assert "[model_providers.deepseek]" in t
    assert '[model_providers.other]' in t
    assert 'wire_api = "responses"' in t
    assert "[desktop]" in t
    assert 'localeOverride = "zh-CN"' in t
    assert 'trust_level = "trusted"' in t
    assert 'sandbox_mode = "danger-full-access"' in t
    assert 'experimental_bearer_token = "sk-test"' in t
    tomllib.loads(t)


def test_install_idempotent():
    r1 = install_mimo(SAMPLE)
    r2 = install_mimo(r1.text)
    assert r2.text.count("[model_providers.mimo]") == 1
    assert r2.text.count('web_search = "disabled"') == 1
    assert 'model = "mimo-v2.5-pro"' in r2.text
    tomllib.loads(r2.text)


def test_install_deepseek_bearer_token():
    r = edit_config(
        SAMPLE,
        "deepseek",
        "https://api.deepseek.com/",
        "responses",
        False,
        "",
        "sk-deepseek",
        "deepseek-v4-flash",
        "high",
        "~/.codex/models.json",
        disable_web_search=False,
    )
    t = r.text
    sec = t.split("[model_providers.deepseek]")[1].split("[")[0]
    assert 'experimental_bearer_token = "sk-deepseek"' in sec
    assert "env_key" not in sec
    assert "web_search" not in t
    assert 'model_catalog_json = "~/.codex/models.json"' in t
    assert t.count("[model_providers.deepseek]") == 1
    tomllib.loads(t)


def test_empty_config():
    r = edit_config(
        "",
        "mimo",
        "https://api.xiaomimimo.com/v1",
        "responses",
        True,
        "MIMO_API_KEY_SELFTEST",
        "sk",
        "mimo-v2.5-pro",
        "high",
        CATALOG,
        disable_web_search=True,
    )
    t = r.text
    for k in ("model", "model_provider", "preferred_auth_method", "forced_login_method",
              "model_reasoning_effort", "model_catalog_json", "web_search"):
        assert k in t
    assert 'model = "mimo-v2.5-pro"' in t
    tomllib.loads(t)


def test_missing_keys_inserted_before_first_section():
    src = 'sandbox_mode = "danger-full-access"\n\n[desktop]\nlocaleOverride = "zh-CN"\n'
    r = edit_config(src, "x", "https://x/v1", "responses", True, "XK", "sk", "m", "high", CATALOG, True)
    lines = r.lines
    assert "[desktop]" in lines
    lead = "\n".join(lines[: lines.index("[desktop]")])
    assert 'model = "m"' in lead
    assert "model_provider" in lead
    assert "web_search" in lead
    tomllib.loads(r.text)


def test_remove_multiline_del_b():
    src = 'model = "a"\nmodel_provider = "b"\ncompact_prompt = """\nsome\nmulti\nline\n"""\n[desktop]\nx = 1\n'
    r = edit_config(src, "x", "https://x", "responses", True, "XK", "sk", "m", "high", CATALOG, True)
    assert "compact_prompt" not in r.text
    assert "multi" not in r.text
    assert "[desktop]" in r.text
    assert "x = 1" in r.text
    tomllib.loads(r.text)


def test_keep_non_target_multiline():
    src = 'foo = """\nbar\n"""\n[desktop]\nx = 1\n'
    r = edit_config(src, "x", "https://x", "responses", True, "XK", "sk", "m", "high", CATALOG, False)
    assert 'foo = """' in r.text
    assert "bar" in r.text
    assert "[desktop]" in r.text
    tomllib.loads(r.text)


def test_other_provider_wire_api_is_left_untouched():
    """Installing one provider must not rewrite another provider's wire_api:
    many OpenAI-compatible relays only speak chat completions."""
    src = '[model_providers.other]\nname = "other"\nbase_url = "https://r/v1"\nwire_api = "chat"\n'
    r = edit_config(src, "wolfox", "https://api.wolfoxlabs.xyz/v1", "chat",
                    False, "", "sk-w", "spe/deepseek-v4-flash", "high", CATALOG, False)
    assert '[model_providers.other]' in r.text
    other_sec = r.text.split("[model_providers.other]")[1].split("[")[0]
    assert 'wire_api = "chat"' in other_sec
    assert "Fixed wire_api" not in "\n".join(r.report)
    tomllib.loads(r.text)


def test_target_provider_wire_api_matches_provider():
    src = '[model_providers.other]\nwire_api = "chat"\n'
    r = edit_config(src, "wolfox", "https://api.wolfoxlabs.xyz/v1", "chat",
                    False, "", "sk-w", "spe/deepseek-v4-flash", "high", CATALOG, False)
    wolfox_sec = r.text.split("[model_providers.wolfox]")[1]
    assert 'wire_api = "chat"' in wolfox_sec
    assert 'wire_api = "responses"' not in r.text


def test_remove_del_a_and_report():
    r = edit_config(SAMPLE, "mimo", "https://api.xiaomimimo.com/v1", "responses",
                    True, "K", "sk", "m", "high", CATALOG, True)
    joined = "\n".join(r.report)
    assert "openai_base_url" in joined
    assert "profiles" in joined


def test_switch_model():
    src = 'model = "deepseek-v4-flash"\nmodel_provider = "deepseek"\n\n[desktop]\nx = 1\n'
    t = switch_model(src, "mimo-v2.5")
    assert 'model = "mimo-v2.5"' in t
    assert 'model_provider = "deepseek"' in t
    assert "[desktop]" in t
    assert t.count("model =") == 1
    tomllib.loads(t)


def test_switch_model_when_no_model_key():
    t = switch_model("[desktop]\nx = 1\n", "m")
    assert 'model = "m"' in t
    tomllib.loads(t)
