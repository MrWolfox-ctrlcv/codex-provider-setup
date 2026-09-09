from __future__ import annotations

import pytest

from codex_provider import paths, registry, service
from codex_provider.io_utils import read_json, read_text
from codex_provider.provider import Provider
from codex_provider.presets import deepseek_preset


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


def test_install_mimo_env_key(tmp_codex_home):
    service.install_provider(make_mimo(), "sk-selftest-key", in_selftest=True)
    cfg = read_text(paths.config_path())
    assert cfg.count("[model_providers.mimo]") == 1
    assert 'env_key = "MIMO_API_KEY_SELFTEST"' in cfg
    assert 'model = "mimo-v2.5-pro"' in cfg
    data = read_json(paths.models_path())
    slugs = [m["slug"] for m in data["models"]]
    assert "mimo-v2.5-pro" in slugs and "mimo-v2.5" in slugs
    reg = registry.load(paths.registry_path())
    assert any(p["id"] == "mimo" for p in reg["providers"])
    assert (paths.backup_dir("mimo") / "manifest.txt").exists()


def test_install_idempotent(tmp_codex_home):
    p = make_mimo()
    service.install_provider(p, "sk", in_selftest=True)
    service.install_provider(p, "sk", in_selftest=True)
    cfg = read_text(paths.config_path())
    assert cfg.count("[model_providers.mimo]") == 1
    assert cfg.count('web_search = "disabled"') == 1


def test_install_deepseek_and_switch(tmp_codex_home):
    prov = deepseek_preset()
    service.install_provider(prov, "sk-deepseek", in_selftest=True)
    cfg = read_text(paths.config_path())
    assert 'experimental_bearer_token = "sk-deepseek"' in cfg
    assert 'model = "deepseek-v4-flash"' in cfg
    service.switch_default_model("deepseek-v4-pro")
    cfg2 = read_text(paths.config_path())
    assert 'model = "deepseek-v4-pro"' in cfg2
    model, provider = service.current_state()
    assert model == "deepseek-v4-pro" and provider == "deepseek"


def test_update_provider_models_removes(tmp_codex_home):
    p = make_mimo()
    service.install_provider(p, "sk", in_selftest=True)
    service.switch_default_model("mimo-v2.5")
    service.update_provider_models(p, ["mimo-v2.5-pro", "mimo-v2.5"], ["mimo-v2.5", "mimo-v3"])
    data = read_json(paths.models_path())
    slugs = [m["slug"] for m in data["models"]]
    assert "mimo-v2.5-pro" not in slugs
    assert "mimo-v2.5" in slugs and "mimo-v3" in slugs


def test_default_model_protection(tmp_codex_home):
    p = make_mimo()
    service.install_provider(p, "sk", in_selftest=True)
    with pytest.raises(ValueError):
        service.update_provider_models(p, ["mimo-v2.5-pro", "mimo-v2.5"], ["mimo-v2.5"])


def test_restore_removes(tmp_codex_home):
    p = make_mimo()
    service.install_provider(p, "sk", in_selftest=True)
    assert paths.config_path().exists()
    service.restore_provider(p)
    assert not paths.config_path().exists()
    assert not paths.models_path().exists()
    assert not paths.backup_dir("mimo").exists()


def test_set_model_params(tmp_codex_home):
    p = make_mimo()
    service.install_provider(p, "sk", in_selftest=True)
    service.set_model_params(p, "mimo-v2.5", 524288, 80, 400000)
    data = read_json(paths.models_path())
    m = next(x for x in data["models"] if x["slug"] == "mimo-v2.5")
    assert m["context_window"] == 524288
    assert m["effective_context_window_percent"] == 80
    assert m["auto_compact_token_limit"] == 400000


def test_installed_providers(tmp_codex_home):
    service.install_provider(make_mimo(), "sk", in_selftest=True)
    recs = service.installed_providers()
    assert any(r["id"] == "mimo" for r in recs)
