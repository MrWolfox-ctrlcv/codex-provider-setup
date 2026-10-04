from __future__ import annotations

import builtins

import pytest

from codex_provider import interact
from codex_provider.provider import Provider


def make_rec(models: list[str] | None = None) -> dict:
    return {
        "id": "mimo",
        "name": "Mimo 测试",
        "base_url": "https://api.mimo.test/v1",
        "wire_api": "responses",
        "env_key": "",
        "models": list(models or ["m1", "m2"]),
        "vision": False,
        "reasoning_levels": [],
        "truncation_mode": "tokens",
        "apply_patch": False,
        "search": False,
        "disable_web_search": False,
        "meta_overrides": {},
    }


def test_read_choice_list_basic(monkeypatch):
    assert interact.read_choice_list("1,3", 5) == [0, 2]
    assert interact.read_choice_list("1，3", 5) == [0, 2]
    assert interact.read_choice_list("1;3、5 2", 5) == [0, 2, 4, 1]
    assert interact.read_choice_list("5-7", 10) == [4, 5, 6]
    assert interact.read_choice_list("7-5", 10) == [4, 5, 6]
    assert interact.read_choice_list("1,3 5-7", 7) == [0, 2, 4, 5, 6]
    assert interact.read_choice_list("1,3 5-7", 3) == [0, 2]
    assert interact.read_choice_list("1,1,2", 5) == [0, 1]
    assert interact.read_choice_list("", 5) == []
    assert interact.read_choice_list("abc", 5) == []
    assert interact.read_choice_list("9", 3) == []
    assert interact.read_choice_list("1", 0) == []


def test_read_choice_list_all_and_quit():
    assert interact.read_choice_list("a", 5) == [0, 1, 2, 3, 4]
    assert interact.read_choice_list("A", 3) == [0, 1, 2]
    assert interact.read_choice_list("q", 5) is None
    assert interact.read_choice_list("Q", 5) is None


def test_confirm_y_n(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "y")
    assert interact.confirm("继续?") is True
    monkeypatch.setattr(builtins, "input", lambda _p="": "Y")
    assert interact.confirm("继续?", default=False) is True
    monkeypatch.setattr(builtins, "input", lambda _p="": "n")
    assert interact.confirm("继续?", default=True) is False
    monkeypatch.setattr(builtins, "input", lambda _p="": "N")
    assert interact.confirm("继续?") is False


def test_confirm_default(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "")
    assert interact.confirm("继续?") is False
    assert interact.confirm("继续?", default=True) is True


def test_read_required_input(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "  hello  ")
    assert interact.read_required("label") == "hello"
    monkeypatch.setattr(builtins, "input", lambda _p="": "")
    assert interact.read_required("label", default="dflt") == "dflt"
    assert interact.read_required("label") == ""


def test_read_required_from_param(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(builtins, "input", lambda _p="": calls.append("input") or "unused")
    assert interact.read_required("label", from_param="param-value") == "param-value"
    assert calls == []


def test_choose_provider_preset(monkeypatch):
    ds = Provider(id="deepseek", name="DeepSeek 官方", base_url="https://api.deepseek.com/", models=["ds-1"])
    monkeypatch.setattr(interact.presets, "deepseek_preset", lambda: ds)
    monkeypatch.setattr(interact.service, "installed_providers", lambda: [])
    monkeypatch.setattr(builtins, "input", lambda _p="": "1")
    assert interact.choose_provider(allow_custom=True) is ds


def test_choose_provider_wolfox_preset(monkeypatch):
    ds = Provider(id="deepseek", name="DeepSeek 官方", base_url="https://api.deepseek.com/", models=["ds-1"])
    wx = Provider(id="wolfox", name="Wolfox AI", base_url="https://api.wolfoxlabs.xyz/v1", models=["w1"])
    monkeypatch.setattr(interact.presets, "deepseek_preset", lambda: ds)
    monkeypatch.setattr(interact.presets, "wolfox_preset", lambda: wx)
    monkeypatch.setattr(interact.service, "installed_providers", lambda: [])
    monkeypatch.setattr(builtins, "input", lambda _p="": "2")
    assert interact.choose_provider(allow_custom=True) is wx


def test_choose_provider_installed(monkeypatch):
    ds = Provider(id="deepseek", name="DeepSeek 官方", base_url="https://api.deepseek.com/", models=["ds-1"])
    monkeypatch.setattr(interact.presets, "deepseek_preset", lambda: ds)
    monkeypatch.setattr(interact.service, "installed_providers", lambda: [make_rec(["x"])])
    built = Provider(id="mimo", name="Mimo 测试", base_url="https://api.mimo.test/v1", models=["x"])
    monkeypatch.setattr(interact.service, "provider_from_installed", lambda rec: built)
    monkeypatch.setattr(builtins, "input", lambda _p="": "3")
    assert interact.choose_provider(allow_custom=False) is built


def test_choose_provider_custom_branch(monkeypatch):
    ds = Provider(id="deepseek", name="DeepSeek 官方", base_url="https://api.deepseek.com/", models=["ds-1"])
    monkeypatch.setattr(interact.presets, "deepseek_preset", lambda: ds)
    monkeypatch.setattr(interact.service, "installed_providers", lambda: [])
    custom = Provider(id="myapi", name="My", base_url="https://my.example/v1", models=["a"])
    monkeypatch.setattr(interact, "custom_provider_wizard", lambda: custom)
    monkeypatch.setattr(builtins, "input", lambda _p="": "3")
    assert interact.choose_provider(allow_custom=True) is custom


def test_choose_provider_invalid(monkeypatch):
    ds = Provider(id="deepseek", name="DeepSeek 官方", base_url="https://api.deepseek.com/", models=["ds-1"])
    monkeypatch.setattr(interact.presets, "deepseek_preset", lambda: ds)
    monkeypatch.setattr(interact.service, "installed_providers", lambda: [])
    monkeypatch.setattr(builtins, "input", lambda _p="": "9")
    assert interact.choose_provider(allow_custom=False) is None


def test_custom_provider_wizard_invalid_id(monkeypatch):
    monkeypatch.setattr(interact, "read_required", lambda label, default="", from_param="": "bad id!")
    assert interact.custom_provider_wizard() is None


def test_custom_provider_wizard_invalid_base_url(monkeypatch):
    monkeypatch.setattr(interact, "read_required", lambda label, default="", from_param="": "not a url")
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: pytest.fail("不应取 key"))
    assert interact.custom_provider_wizard() is None


def test_custom_provider_wizard_no_key(monkeypatch):
    vals = iter(["myapi", "My", "https://my.example/v1", "sk-"])
    monkeypatch.setattr(interact, "read_required", lambda label, default="", from_param="": next(vals))
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: None)
    assert interact.custom_provider_wizard() is None


def test_custom_provider_wizard_fetch_fail_manual(monkeypatch):
    vals = iter([
        "MyApi", "My API", "https://api.x.com/v1", "sk-",
        "m1, m2", "524288", "none,high,max", "high", "MY_API_KEY", "responses",
    ])
    monkeypatch.setattr(interact, "read_required", lambda label, default="", from_param="": next(vals))
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk-abc")
    monkeypatch.setattr(interact.upstream, "fetch_models", lambda *a, **k: {"ok": False, "models": [], "raw": None, "error": "boom"})
    confirms = iter([False, False, True])
    monkeypatch.setattr(interact, "confirm", lambda prompt, default=False: next(confirms))
    prov = interact.custom_provider_wizard()
    assert prov is not None
    assert prov.id == "myapi"
    assert prov.name == "My API"
    assert prov.base_url == "https://api.x.com/v1"
    assert prov.key_prefix == "sk-"
    assert prov.models == ["m1", "m2"]
    assert prov.context_window == 524288
    assert prov.reasoning_levels == ["none", "high", "max"]
    assert prov.env_var_name == "MY_API_KEY"
    assert prov.use_env_key is True
    assert prov.instructions_mode == "short"
    assert prov.vision is False
    assert prov.search_support is True
    assert prov.disable_web_search is False
    assert prov.apply_patch_tool_type == ""
    assert prov.support_verbosity is False
    assert prov.parallel_tool_calls is False
    assert prov.base_instructions == (
        "You are My API, an AI assistant provided via the My API API. Today's date: {date} {week}."
    )


def test_custom_provider_wizard_fetch_ok_detected(monkeypatch):
    vals = iter([
        "myapi", "My", "https://api.x.com/v1", "sk-",
        "262144", "low,high", "low", "", "chat",
    ])
    monkeypatch.setattr(interact, "read_required", lambda label, default="", from_param="": next(vals))
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk-abc")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["gpt-4o", "qwen-vl"], "raw": {"data": [{"id": "qwen-vl", "context_window": 262144}]}},
    )
    monkeypatch.setattr(interact, "select_fetched_models", lambda ids: list(ids))
    confirms = iter([True, True, False])
    monkeypatch.setattr(interact, "confirm", lambda prompt, default=False: next(confirms))
    prov = interact.custom_provider_wizard()
    assert prov is not None
    assert prov.models == ["gpt-4o", "qwen-vl"]
    assert prov.context_window == 262144
    assert prov.wire_api == "chat"
    assert prov.instructions_mode == "full"
    assert prov.vision is True
    assert prov.search_support is False
    assert prov.disable_web_search is True
    assert prov.env_var_name == ""
    assert prov.use_env_key is False


def test_custom_provider_wizard_slug_quotes(monkeypatch):
    vals = iter(["myapi", "My", "https://api.x.com/v1", "sk-", 'm"1'])
    monkeypatch.setattr(interact, "read_required", lambda label, default="", from_param="": next(vals))
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk-abc")
    monkeypatch.setattr(interact.upstream, "fetch_models", lambda *a, **k: {"ok": False, "models": [], "raw": None, "error": "boom"})
    assert interact.custom_provider_wizard() is None


def test_custom_provider_wizard_bad_context_window(monkeypatch):
    vals = iter(["myapi", "My", "https://api.x.com/v1", "sk-", "m1", "100", "none,high", "high", "", "responses"])
    monkeypatch.setattr(interact, "read_required", lambda label, default="", from_param="": next(vals))
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk-abc")
    monkeypatch.setattr(interact.upstream, "fetch_models", lambda *a, **k: {"ok": False, "models": [], "raw": None, "error": "boom"})
    assert interact.custom_provider_wizard() is None


def test_prompt_api_key(monkeypatch):
    p = Provider(id="x", name="X", base_url="https://x/v1", key_prefix="sk-")
    monkeypatch.setattr(interact, "getpass", lambda prompt: "  sk-secret  ")
    assert interact.prompt_api_key(p) == "sk-secret"
    monkeypatch.setattr(interact, "getpass", lambda prompt: "")
    assert interact.prompt_api_key(p) is None


def test_select_fetched_models_all(monkeypatch):
    ids = ["gpt-5.6-sol", "gpt-5.6-terra", "qwen-max"]
    monkeypatch.setattr(builtins, "input", lambda _p="": "1")
    assert interact.select_fetched_models(ids) == ids


def test_select_fetched_models_manual(monkeypatch):
    ids = ["gpt-5.6-sol", "gpt-5.6-terra", "qwen-max"]
    monkeypatch.setattr(builtins, "input", lambda _p="": "3")
    assert interact.select_fetched_models(ids) is None


def test_select_fetched_models_filter(monkeypatch):
    ids = ["gpt-5.6-sol", "gpt-5.6-terra", "qwen-max"]
    answers = iter(["2", "5.6", "2"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert interact.select_fetched_models(ids) == ["gpt-5.6-terra"]


def test_select_fetched_models_filter_all_matches(monkeypatch):
    ids = ["gpt-5.6-sol", "gpt-5.6-terra", "qwen-max"]
    answers = iter(["2", "gpt", "a"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert interact.select_fetched_models(ids) == ["gpt-5.6-sol", "gpt-5.6-terra"]


def test_select_fetched_models_filter_requery(monkeypatch):
    ids = ["gpt-5.6-sol", "gpt-5.6-terra", "qwen-max"]
    answers = iter(["2", "5.6", "q", "", "3"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert interact.select_fetched_models(ids) == ["qwen-max"]


def test_select_fetched_models_bad_three_times(monkeypatch):
    ids = ["gpt-5.6-sol", "gpt-5.6-terra", "qwen-max"]
    answers = iter(["9", "9", "9"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert interact.select_fetched_models(ids) is None


def test_select_fetched_models_no_match_three_times(monkeypatch):
    ids = ["gpt-5.6-sol", "gpt-5.6-terra"]
    answers = iter(["2", "zzz", "zzz", "zzz"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert interact.select_fetched_models(ids) is None


def test_manage_models_no_key(monkeypatch, tmp_codex_home):
    calls: list[str] = []
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: calls.append("k") or None)
    monkeypatch.setattr(interact.upstream, "fetch_models", lambda *a, **k: pytest.fail("不应拉取"))
    interact.manage_models(make_rec())
    assert calls == ["k"]


def test_manage_models_fetch_fail(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": False, "models": [], "raw": None, "error": "boom"},
    )
    interact.manage_models(make_rec())


def test_manage_models_add_and_apply(monkeypatch, tmp_codex_home):
    rec = make_rec(["m1", "m2"])
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["m1", "m2", "n1", "n2"], "raw": {}},
    )
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    applied: list[tuple[object, list[str], list[str]]] = []
    monkeypatch.setattr(interact.service, "update_provider_models", lambda p, cur, fin: applied.append((p, cur, fin)))
    answers = iter(["1", "1", "7"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.manage_models(rec)
    assert len(applied) == 1
    _prov, cur, fin = applied[0]
    assert cur == ["m1", "m2"]
    assert fin == ["m1", "m2", "n1"]


def test_manage_models_manual_add_not_in_upstream(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["m1"], "raw": {}},
    )
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    applied: list[tuple[object, list[str], list[str]]] = []
    monkeypatch.setattr(interact.service, "update_provider_models", lambda p, cur, fin: applied.append((p, cur, fin)))
    answers = iter(["2", "ghost-1", "y", "7"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    rec = make_rec(["m1"])
    interact.manage_models(rec)
    assert len(applied) == 1
    assert applied[0][2] == ["m1", "ghost-1"]


def test_manage_models_remove_then_switch_default(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["m1", "m2", "m3"], "raw": {}},
    )
    states = iter([("x", "other"), ("m1", "mimo")])
    monkeypatch.setattr(interact.service, "current_state", lambda: next(states))
    applied: list[tuple[object, list[str], list[str]]] = []
    monkeypatch.setattr(interact.service, "update_provider_models", lambda p, cur, fin: applied.append((p, cur, fin)))
    switched: list[str] = []
    monkeypatch.setattr(interact.service, "switch_default_model", lambda slug: switched.append(slug))
    answers = iter(["2", "m3", "3", "1,2", "7", "1"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.manage_models(make_rec(["m1", "m2"]))
    assert switched == ["m3"]
    assert len(applied) == 1
    assert applied[0][1] == ["m1", "m2"]
    assert applied[0][2] == ["m3"]


def test_manage_models_remove_blocked_default(monkeypatch, tmp_codex_home, capsys):
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["m1", "m2"], "raw": {}},
    )
    monkeypatch.setattr(interact.service, "current_state", lambda: ("m1", "mimo"))
    answers = iter(["3", "1,2", "8"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.manage_models(make_rec(["m1", "m2"]))
    out = capsys.readouterr().out
    assert "是当前默认模型" in out
    assert "待移除: m2" in out


def test_manage_models_probe_remove(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["m1", "m2"], "raw": {}},
    )
    monkeypatch.setattr(
        interact.upstream,
        "probe_models",
        lambda models, base, key: (["m2"], ["m1"], []),
    )
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    applied: list[tuple[object, list[str], list[str]]] = []
    monkeypatch.setattr(interact.service, "update_provider_models", lambda p, cur, fin: applied.append((p, cur, fin)))
    answers = iter(["5", "y", "8"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.manage_models(make_rec(["m1", "m2"]))
    assert len(applied) == 1
    assert applied[0][2] == ["m2"]


def test_manage_models_cancel_option8(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["m1"], "raw": {}},
    )
    called: list[object] = []
    monkeypatch.setattr(interact.service, "update_provider_models", lambda *a, **k: called.append(a))
    answers = iter(["8"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.manage_models(make_rec(["m1"]))
    assert called == []


def test_manage_models_edit_params(monkeypatch, tmp_codex_home):
    models_p = tmp_codex_home / "models.json"
    models_p.write_text(
        '{"models": [{"slug": "m1", "context_window": 200000, "effective_context_window_percent": 80, "auto_compact_token_limit": 150000}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk")
    monkeypatch.setattr(
        interact.upstream,
        "fetch_models",
        lambda *a, **k: {"ok": True, "models": ["m1", "m2"], "raw": {}},
    )
    set_calls: list[tuple[object, str, int, int, int | None]] = []
    monkeypatch.setattr(
        interact.service,
        "set_model_params",
        lambda p, slug, cw, ep, ac: set_calls.append((p, slug, cw, ep, ac)),
    )
    answers = iter(["4", "1", "", "", "", "y", "8"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.manage_models(make_rec(["m1", "m2"]))
    assert len(set_calls) == 1
    _prov, slug, cw, ep, ac = set_calls[0]
    assert slug == "m1"
    assert cw == 200000
    assert ep == 80
    assert ac is None


def test_show_status_none(monkeypatch, tmp_codex_home, capsys):
    monkeypatch.setattr(interact.service, "current_state", lambda: ("ds-model", "deepseek"))
    monkeypatch.setattr(interact.service, "installed_providers", lambda: [make_rec()])
    interact.show_status()
    out = capsys.readouterr().out
    assert "默认模型        : ds-model" in out
    assert "默认 Provider    : deepseek" in out
    assert "已接入 provider  : mimo" in out


def test_show_status_provider(monkeypatch, tmp_codex_home, capsys):
    cfg = tmp_codex_home / "config.toml"
    cfg.write_text(
        'model = "m1"\nmodel_provider = "mimo"\n\n[model_providers.mimo]\nbase_url = "https://api.mimo.test/v1"\n',
        encoding="utf-8",
    )
    models_p = tmp_codex_home / "models.json"
    models_p.write_text('{"models": [{"slug": "m1"}, {"slug": "m2"}]}', encoding="utf-8")
    monkeypatch.setenv("MIMO_TEST_ENV", "1")
    prov = Provider(
        id="mimo",
        name="Mimo 测试",
        base_url="https://api.mimo.test/v1",
        env_var_name="MIMO_TEST_ENV",
        use_env_key=True,
        models=["m1", "m2", "gone"],
    )
    monkeypatch.setattr(interact.service, "installed_providers", lambda: [make_rec()])
    interact.show_status(prov)
    out = capsys.readouterr().out
    assert "默认模型        : m1" in out
    assert "已配置" in out
    assert "models.json 模型 : m1 / m2" in out
    assert "环境变量 MIMO_TEST_ENV      : 已设置" in out
    assert "配置路径" in out


def test_main_menu_exit(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact, "_active", None)
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    monkeypatch.setattr(builtins, "input", lambda _p="": "7")
    interact.main_menu()


def test_main_menu_invalid_three_times(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact, "_active", None)
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    answers = iter(["x", "x", "x"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.main_menu()


def test_main_menu_switch_model(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact, "_active", None)
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    prov = Provider(id="mimo", name="Mimo", base_url="https://api.mimo.test/v1", models=["a", "b"])
    monkeypatch.setattr(interact, "choose_provider", lambda allow_custom: prov)
    switched: list[str] = []
    monkeypatch.setattr(interact.service, "switch_default_model", lambda slug: switched.append(slug))
    answers = iter(["3", "2", "7"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.main_menu()
    assert switched == ["b"]
    assert interact._active is prov


def test_main_menu_switch_by_slug(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact, "_active", None)
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    prov = Provider(id="mimo", name="Mimo", base_url="https://api.mimo.test/v1", models=[])
    monkeypatch.setattr(interact, "choose_provider", lambda allow_custom: prov)
    monkeypatch.setattr(interact.service, "all_catalog_slugs", lambda: ["reg-a", "reg-b"])
    switched: list[str] = []
    monkeypatch.setattr(interact.service, "switch_default_model", lambda slug: switched.append(slug))
    answers = iter(["3", "reg-b", "7"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.main_menu()
    assert switched == ["reg-b"]


def test_main_menu_install_flow(monkeypatch, tmp_codex_home):
    monkeypatch.setattr(interact, "_active", None)
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    prov = Provider(id="deepseek", name="DeepSeek 官方", base_url="https://api.deepseek.com/", models=["ds-1"])
    monkeypatch.setattr(interact, "choose_provider", lambda allow_custom: prov)
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk-x")
    monkeypatch.setattr(
        interact.registry,
        "load",
        lambda _p: {"providers": [{"id": "deepseek", "meta_overrides": {"ds-1": {"context_window": 111}}}]},
    )
    monkeypatch.setattr(interact.service, "sync_from_upstream", lambda *a, **k: ["merged-1", "merged-2"])
    installed: list[tuple[object, str]] = []
    monkeypatch.setattr(interact.service, "install_provider", lambda p, k: installed.append((p, k)))
    # keep the flow deterministic regardless of whether Codex runs on this machine
    monkeypatch.setattr(interact.doctor, "find_codex_processes", lambda: [])
    monkeypatch.setattr(interact.doctor, "ui_state_files", lambda: [])
    answers = iter(["1", "y", "7"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.main_menu()
    assert len(installed) == 1
    prov, key = installed[0]
    assert key == "sk-x"
    assert prov.meta_overrides == {"ds-1": {"context_window": 111}}
    assert prov.models == ["merged-1", "merged-2"]


def test_main_menu_install_warns_when_codex_running(monkeypatch, tmp_codex_home, capsys):
    """Installing while the desktop app runs risks it overwriting config.toml,
    so the user must confirm (and can abort)."""
    monkeypatch.setattr(interact, "_active", None)
    monkeypatch.setattr(interact.service, "current_state", lambda: ("(未设置)", "(未设置)"))
    prov = Provider(id="wolfox", name="Wolfox AI", base_url="https://api.wolfoxlabs.xyz/v1", models=["w1"])
    monkeypatch.setattr(interact, "choose_provider", lambda allow_custom: prov)
    monkeypatch.setattr(interact.service, "get_api_key", lambda *a, **k: "sk-x")
    monkeypatch.setattr(interact.doctor, "find_codex_processes", lambda: ["Codex.exe"])
    called: list[str] = []
    monkeypatch.setattr(interact.service, "install_provider", lambda p, k: called.append("install"))
    # decline the "continue anyway?" prompt, then exit
    answers = iter(["1", "n", "7"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    interact.main_menu()
    assert called == []
    out = capsys.readouterr().out
    assert "正在运行" in out
    assert "未写入任何文件" in out


def test_main_menu_no_codex_home(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(interact, "_active", None)
    interact.main_menu()
    out = capsys.readouterr().out
    assert "未找到 Codex 配置目录" in out
