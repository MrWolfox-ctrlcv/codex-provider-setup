from __future__ import annotations

import json

from codex_provider.catalog import build_model_metadata, catalog_text, merge_catalog, write_catalog
from codex_provider.provider import Provider
from codex_provider.prompts import load_codex_instructions


def mimo_provider(meta_overrides: dict[str, dict] | None = None) -> Provider:
    return Provider(
        id="mimo",
        name="MiMo 按量付费",
        base_url="https://api.xiaomimimo.com/v1",
        env_var_name="MIMO_API_KEY",
        use_env_key=True,
        models=["mimo-v2.5-pro", "mimo-v2.5"],
        wire_api="responses",
        context_window=1048576,
        vision=True,
        instructions_mode="short",
        reasoning_levels=["none", "high"],
        base_instructions="You are MiMo, an AI assistant developed by Xiaomi.",
        description="MiMo 按量付费",
        apply_patch_tool_type="",
        search_support=False,
        parallel_tool_calls=False,
        support_verbosity=False,
        truncation_mode="bytes",
        vision_by_model={"mimo-v2.5-pro": False, "mimo-v2.5": True},
        disable_web_search=True,
        meta_overrides=meta_overrides or {},
    )


def test_mimo_style_metadata():
    p = mimo_provider()
    pro = build_model_metadata(p, 0)
    plain = build_model_metadata(p, 1)
    assert pro["slug"] == "mimo-v2.5-pro"
    assert "apply_patch_tool_type" not in pro
    assert "web_search_tool_type" not in pro
    assert pro["supports_search_tool"] is False
    assert pro["truncation_policy"] == {"mode": "bytes", "limit": 10000}
    assert pro["supports_parallel_tool_calls"] is False
    assert pro["support_verbosity"] is False
    assert "default_verbosity" not in pro
    assert pro["input_modalities"] == ["text"]
    assert pro["supports_image_detail_original"] is False
    assert plain["input_modalities"] == ["text", "image"]
    assert plain["supports_image_detail_original"] is True
    assert "default_verbosity" not in plain
    assert pro["context_window"] == 1048576
    assert pro["max_context_window"] == 1048576
    assert pro["effective_context_window_percent"] == 95
    assert pro["auto_compact_token_limit"] is None
    assert pro["supported_reasoning_levels"] == [
        {"effort": "none", "description": "Disable Thinking"},
        {"effort": "high", "description": "Extra high reasoning depth for complex problems"},
    ]
    assert pro["priority"] == 1
    assert plain["priority"] == 2
    assert pro["minimal_client_version"] == "0.144.0"
    assert pro["multi_agent_version"] == "v2"
    assert "model_messages" not in pro


def test_deepseek_style_full_instructions():
    base = "You are Codex, an agent based on GPT-5. You and the user share one workspace."
    p = Provider(
        id="deepseek",
        name="DeepSeek 官方",
        base_url="https://api.deepseek.com/",
        env_var_name="DEEPSEEK_API_KEY",
        use_env_key=False,
        models=["deepseek-v4-flash"],
        instructions_mode="full",
        reasoning_levels=["low", "high", "max"],
        base_instructions=base,
        description="DeepSeek API",
        apply_patch_tool_type="freeform",
        search_support=True,
        parallel_tool_calls=True,
        support_verbosity=True,
        truncation_mode="tokens",
    )
    m = build_model_metadata(p, 0)
    assert m["apply_patch_tool_type"] == "freeform"
    assert m["web_search_tool_type"] == "text"
    assert m["supports_search_tool"] is True
    assert m["support_verbosity"] is True
    assert m["default_verbosity"] == "low"
    assert m["default_reasoning_level"] == "high"
    assert m["default_reasoning_summary"] == "none"
    assert m["display_name"] == "deepseek-v4-flash"
    assert m["description"] == "DeepSeek API - deepseek-v4-flash"
    assert m["truncation_policy"] == {"mode": "tokens", "limit": 10000}
    assert m["model_messages"]["instructions_template"] == load_codex_instructions()
    assert m["model_messages"]["instructions_template"] != base
    assert m["model_messages"]["approvals"] is None
    assert m["model_messages"]["instructions_variables"] == {
        "personality_default": "",
        "personality_friendly": "",
        "personality_pragmatic": "",
    }
    assert m["base_instructions"] == base
    assert m["supported_reasoning_levels"][0] == {"effort": "low", "description": "Fast responses with lighter reasoning"}
    assert m["supported_reasoning_levels"][1] == {
        "effort": "high",
        "description": "Extra high reasoning depth for complex problems",
    }
    assert m["supported_reasoning_levels"][2] == {
        "effort": "max",
        "description": "Maximum reasoning depth for the hardest problems",
    }
    assert json.loads(json.dumps(m, ensure_ascii=False)) == m
    assert json.loads(json.dumps({"models": [m]}, ensure_ascii=False)) == {"models": [m]}


def test_merge_catalog():
    deepseek_entry = {
        "slug": "deepseek-v4-flash",
        "display_name": "deepseek-v4-flash",
        "description": "DeepSeek API - deepseek-v4-flash",
        "priority": 1,
    }
    stale_pro = {"slug": "mimo-v2.5-pro", "context_window": 111, "description": "stale pro"}
    stale_plain = {"slug": "mimo-v2.5", "description": "stale plain"}
    existing = [deepseek_entry, stale_pro, stale_plain]
    p = mimo_provider()
    merged, replaced = merge_catalog(existing, p)
    assert replaced == 2
    assert len(merged) == 3
    assert merged[0] is deepseek_entry
    assert [m["slug"] for m in merged] == ["deepseek-v4-flash", "mimo-v2.5-pro", "mimo-v2.5"]
    assert merged[1]["priority"] == 1
    assert merged[2]["priority"] == 2
    assert merged[1]["description"] == "MiMo 按量付费 - mimo-v2.5-pro"
    assert merged[1]["context_window"] == 1048576
    assert merged[2]["input_modalities"] == ["text", "image"]


def test_meta_overrides():
    ov = {
        "mimo-v2.5-pro": {
            "context_window": 262144,
            "auto_compact_token_limit": 180000,
            "effective_context_window_percent": 90,
            "max_context_window": 300000,
            "no_such_key": 1,
            "supports_search_tool": None,
        }
    }
    m = build_model_metadata(mimo_provider(meta_overrides=ov), 0)
    assert m["context_window"] == 262144
    assert m["max_context_window"] == 300000
    assert m["auto_compact_token_limit"] == 180000
    assert m["effective_context_window_percent"] == 90
    assert "no_such_key" not in m
    assert m["supports_search_tool"] is False

    ov2 = {"mimo-v2.5-pro": {"max_context_window": 500000}}
    m2 = build_model_metadata(mimo_provider(meta_overrides=ov2), 0)
    assert m2["max_context_window"] == 500000
    assert m2["context_window"] == 1048576

    ov3 = {"mimo-v2.5-pro": {"context_window": None, "auto_compact_token_limit": None}}
    m3 = build_model_metadata(mimo_provider(meta_overrides=ov3), 0)
    assert m3["context_window"] == 1048576
    assert m3["max_context_window"] == 1048576
    assert m3["auto_compact_token_limit"] is None


def test_catalog_text_and_write(tmp_path):
    p = mimo_provider()
    models, replaced = merge_catalog([], p)
    assert replaced == 0
    text = catalog_text(models, had_existing=False)
    assert not text.endswith("\r\n")
    assert json.loads(text) == {"models": models}

    text_crlf = catalog_text(models, had_existing=True)
    assert text_crlf.endswith("\r\n")
    assert json.loads(text_crlf) == {"models": models}

    path = tmp_path / "models.json"
    write_catalog(path, models, had_existing=True)
    assert path.read_bytes().endswith(b"\r\n")
    with open(path, "r", encoding="utf-8", newline="") as f:
        assert f.read() == text_crlf
    assert json.loads(path.read_bytes()) == {"models": models}
