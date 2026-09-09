from __future__ import annotations

import json

from codex_provider import catalog, paths, registry, service
from codex_provider.io_utils import read_json, read_text, write_text
from codex_provider.provider import Provider

SAMPLE_CFG = r'''model = "deepseek-v4-flash"
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


def make_mimo() -> Provider:
    return Provider(
        id="mimo",
        name="MiMo 自测",
        base_url="https://api.xiaomimimo.com/v1",
        key_prefix="sk-",
        env_var_name="MIMO_API_KEY_SELFTEST",
        use_env_key=True,
        models=["mimo-v2.5-pro", "mimo-v2.5"],
        wire_api="responses",
        context_window=1048576,
        vision=True,
        instructions_mode="short",
        reasoning_levels=["none", "high"],
        base_instructions="st",
        description="st",
        apply_patch_tool_type="",
        search_support=False,
        parallel_tool_calls=False,
        support_verbosity=False,
        truncation_mode="bytes",
        vision_by_model={"mimo-v2.5-pro": False, "mimo-v2.5": True},
        disable_web_search=True,
    )


def _seed_deepseek() -> Provider:
    return Provider(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/",
        key_prefix="sk-",
        env_var_name="",
        use_env_key=False,
        models=["deepseek-v4-flash"],
        wire_api="responses",
        context_window=1048576,
        vision=False,
        instructions_mode="short",
        reasoning_levels=["low", "high", "max"],
        base_instructions="DeepSeek selftest",
        description="st",
        apply_patch_tool_type="freeform",
        search_support=True,
    )


def _seed_home() -> tuple[bytes, bytes]:
    write_text(paths.config_path(), SAMPLE_CFG)
    seed_prov = _seed_deepseek()
    write_text(paths.models_path(), json.dumps({"models": [catalog.build_model_metadata(seed_prov, 0)]}, ensure_ascii=False))
    return paths.config_path().read_bytes(), paths.models_path().read_bytes()


def _seed_deepseek_registry() -> None:
    reg = registry.load(paths.registry_path())
    providers = list(reg["providers"]) if reg else []
    providers = registry.upsert(providers, {
        "id": "deepseek",
        "name": "deepseek",
        "base_url": "https://api.deepseek.com/",
        "wire_api": "responses",
        "env_key": "",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "vision": False,
        "reasoning_levels": ["low", "high", "max"],
        "truncation_mode": "tokens",
        "apply_patch": True,
        "search": True,
        "disable_web_search": False,
    })
    registry.dump(paths.registry_path(), providers)


def test_e2e_seed_and_install_mimo(tmp_codex_home):
    _seed_home()
    service.install_provider(make_mimo(), "sk-selftest-key", in_selftest=True)
    cfg = read_text(paths.config_path())
    assert cfg.count("[model_providers.mimo]") == 1
    assert 'env_key = "MIMO_API_KEY_SELFTEST"' in cfg
    assert 'model = "mimo-v2.5-pro"' in cfg
    assert 'model_provider = "mimo"' in cfg
    assert 'preferred_auth_method = "apikey"' in cfg
    assert cfg.count('web_search = "disabled"') == 1
    assert "openai_base_url" not in cfg
    assert "[profiles" not in cfg
    assert "[model_providers.deepseek]" in cfg
    assert 'experimental_bearer_token = "sk-test"' in cfg
    assert "[model_providers.other]" in cfg
    other_sec = cfg.split("[model_providers.other]")[1].split("[")[0]
    assert 'wire_api = "responses"' in other_sec
    assert "[desktop]" in cfg
    assert 'localeOverride = "zh-CN"' in cfg
    assert 'trust_level = "trusted"' in cfg
    assert 'sandbox_mode = "danger-full-access"' in cfg
    data = read_json(paths.models_path())
    slugs = [m["slug"] for m in data["models"]]
    assert "deepseek-v4-flash" in slugs
    assert "mimo-v2.5-pro" in slugs
    assert "mimo-v2.5" in slugs
    pro = next(m for m in data["models"] if m["slug"] == "mimo-v2.5-pro")
    base = next(m for m in data["models"] if m["slug"] == "mimo-v2.5")
    deep = next(m for m in data["models"] if m["slug"] == "deepseek-v4-flash")
    assert "apply_patch_tool_type" not in pro
    assert pro["supports_search_tool"] is False
    assert pro["supports_parallel_tool_calls"] is False
    assert pro["support_verbosity"] is False
    assert pro["truncation_policy"]["mode"] == "bytes"
    assert pro["input_modalities"] == ["text"]
    assert "image" in base["input_modalities"]
    assert deep["apply_patch_tool_type"] == "freeform"
    assert deep["supports_search_tool"] is True


def test_e2e_install_idempotent(tmp_codex_home):
    _seed_home()
    p = make_mimo()
    service.install_provider(p, "sk-selftest-key", in_selftest=True)
    service.install_provider(p, "sk-selftest-key", in_selftest=True)
    cfg = read_text(paths.config_path())
    assert cfg.count("[model_providers.mimo]") == 1
    assert cfg.count('web_search = "disabled"') == 1


def test_e2e_quick_switch(tmp_codex_home):
    _seed_home()
    service.install_provider(make_mimo(), "sk-selftest-key", in_selftest=True)
    service.switch_default_model("mimo-v2.5")
    cfg = read_text(paths.config_path())
    assert 'model = "mimo-v2.5"' in cfg
    assert 'model_provider = "mimo"' in cfg
    assert cfg.count("model =") == 1


def test_e2e_installed_providers(tmp_codex_home):
    _seed_home()
    service.install_provider(make_mimo(), "sk-selftest-key", in_selftest=True)
    service.switch_default_model("mimo-v2.5")
    inst = service.installed_providers()
    ids = [r["id"] for r in inst]
    assert ids == ["deepseek", "mimo", "other"]
    mimo = next(r for r in inst if r["id"] == "mimo")
    assert "mimo-v2.5-pro" in mimo["models"]
    assert "mimo-v2.5" in mimo["models"]
    other = next(r for r in inst if r["id"] == "other")
    assert other["env_key"] == "OTHER_KEY"
    assert service.current_state() == ("mimo-v2.5", "mimo")
    assert paths.registry_path().exists()
    rebuilt = service.provider_from_installed(mimo)
    assert "mimo-v2.5-pro" in rebuilt.models
    assert "mimo-v2.5" in rebuilt.models
    assert rebuilt.use_env_key


def test_e2e_model_list_management(tmp_codex_home):
    _seed_home()
    p = make_mimo()
    service.install_provider(p, "sk-selftest-key", in_selftest=True)
    service.switch_default_model("mimo-v2.5")
    _seed_deepseek_registry()

    service.update_provider_models(p, ["mimo-v2.5-pro", "mimo-v2.5"], ["mimo-v2.5", "mimo-v3-test"])
    data = read_json(paths.models_path())
    slugs = [m["slug"] for m in data["models"]]
    assert "mimo-v2.5-pro" not in slugs
    assert "mimo-v2.5" in slugs
    assert "mimo-v3-test" in slugs
    v3 = next(m for m in data["models"] if m["slug"] == "mimo-v3-test")
    v25 = next(m for m in data["models"] if m["slug"] == "mimo-v2.5")
    assert v3["context_window"] == 1048576
    assert "image" in v3["input_modalities"]
    assert "image" in v25["input_modalities"]
    assert any(m["slug"] == "deepseek-v4-flash" for m in data["models"])
    cfg = read_text(paths.config_path())
    assert 'model = "mimo-v2.5"' in cfg
    reg = registry.load(paths.registry_path())
    mimo_reg = next(r for r in reg["providers"] if r["id"] == "mimo")
    assert mimo_reg["models"] == ["mimo-v2.5", "mimo-v3-test"]

    service.update_provider_models(p, ["mimo-v2.5", "mimo-v3-test"], ["mimo-v2.5", "mimo-v3-test", "deepseek-v4-flash"])
    data = read_json(paths.models_path())
    ds = [m for m in data["models"] if m["slug"] == "deepseek-v4-flash"]
    assert len(ds) == 1
    assert ds[0]["apply_patch_tool_type"] == "freeform"
    assert ds[0]["supports_search_tool"] is True
    reg = registry.load(paths.registry_path())
    mimo_reg = next(r for r in reg["providers"] if r["id"] == "mimo")
    assert "deepseek-v4-flash" in mimo_reg["models"]

    service.update_provider_models(p, ["mimo-v2.5", "mimo-v3-test", "deepseek-v4-flash"], ["mimo-v2.5", "mimo-v3-test"])
    data = read_json(paths.models_path())
    ds = [m for m in data["models"] if m["slug"] == "deepseek-v4-flash"]
    assert len(ds) == 1
    reg = registry.load(paths.registry_path())
    mimo_reg = next(r for r in reg["providers"] if r["id"] == "mimo")
    assert "deepseek-v4-flash" not in mimo_reg["models"]
    assert len(mimo_reg["models"]) == 2


def test_e2e_model_params(tmp_codex_home):
    _seed_home()
    p = make_mimo()
    service.install_provider(p, "sk-selftest-key", in_selftest=True)
    service.switch_default_model("mimo-v2.5")
    service.update_provider_models(p, ["mimo-v2.5-pro", "mimo-v2.5"], ["mimo-v2.5", "mimo-v3-test"])
    service.set_model_params(p, "mimo-v3-test", 524288, 80, 400000)
    data = read_json(paths.models_path())
    v3 = next(m for m in data["models"] if m["slug"] == "mimo-v3-test")
    assert v3["context_window"] == 524288
    assert v3["max_context_window"] == 524288
    assert v3["auto_compact_token_limit"] == 400000
    assert v3["effective_context_window_percent"] == 80
    reg = registry.load(paths.registry_path())
    mimo_reg = next(r for r in reg["providers"] if r["id"] == "mimo")
    ov = mimo_reg["meta_overrides"]["mimo-v3-test"]
    assert ov["context_window"] == 524288
    assert ov["auto_compact_token_limit"] == 400000
    inst = next(r for r in service.installed_providers() if r["id"] == "mimo")
    rebuilt = service.provider_from_installed(inst)
    cloned = rebuilt.clone(["mimo-v3-test"])
    meta = catalog.build_model_metadata(cloned, 0)
    assert meta["context_window"] == 524288
    assert meta["auto_compact_token_limit"] == 400000
    assert meta["effective_context_window_percent"] == 80


def test_e2e_restore(tmp_codex_home):
    cfg_bytes, mdl_bytes = _seed_home()
    p = make_mimo()
    service.install_provider(p, "sk-selftest-key", in_selftest=True)
    service.switch_default_model("mimo-v2.5")
    service.update_provider_models(p, ["mimo-v2.5-pro", "mimo-v2.5"], ["mimo-v2.5", "mimo-v3-test"])
    assert paths.config_path().read_bytes() != cfg_bytes
    assert paths.models_path().read_bytes() != mdl_bytes
    service.restore_provider(p)
    assert paths.config_path().read_bytes() == cfg_bytes
    assert paths.models_path().read_bytes() == mdl_bytes
    assert not paths.backup_dir("mimo").exists()
