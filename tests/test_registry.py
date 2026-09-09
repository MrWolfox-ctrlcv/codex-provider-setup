from __future__ import annotations

import json

from codex_provider.registry import (
    dump,
    find,
    load,
    meta_overrides_for,
    set_meta_override,
    upsert,
)


def make_entry(pid: str = "mimo") -> dict:
    return {
        "id": pid,
        "name": "Mimo",
        "base_url": "https://api.example.com/v1",
        "wire_api": "responses",
        "env_key": "",
        "models": ["m1", "m2"],
        "vision": False,
        "reasoning_levels": [],
        "truncation_mode": "tokens",
        "apply_patch": True,
        "search": True,
        "disable_web_search": False,
        "meta_overrides": {},
    }


def test_load_missing_returns_none(tmp_path):
    assert load(tmp_path / "providers-registry.json") is None


def test_load_bad_json_returns_none(tmp_path):
    p = tmp_path / "providers-registry.json"
    p.write_text('{ "providers": [', encoding="utf-8")
    assert load(p) is None


def test_dump_load_roundtrip(tmp_path):
    p = tmp_path / "providers-registry.json"
    providers = [make_entry("mimo"), make_entry("deep")]
    dump(p, providers)
    assert load(p) == {"providers": providers}


def test_upsert_replaces_same_id_keeps_order():
    a = make_entry("mimo")
    a["models"] = ["old"]
    b = make_entry("deep")
    new = make_entry("mimo")
    new["models"] = ["new-m"]
    got = upsert([a, b], new)
    assert [g["id"] for g in got] == ["deep", "mimo"]
    assert got[1]["models"] == ["new-m"]
    assert [g["id"] for g in upsert([a, b], new)] == ["deep", "mimo"]


def test_upsert_appends_new_id():
    got = upsert([make_entry("mimo")], make_entry("deep"))
    assert [g["id"] for g in got] == ["mimo", "deep"]


def test_find():
    providers = [make_entry("mimo"), make_entry("deep")]
    assert find(providers, "deep")["id"] == "deep"
    assert find(providers, "deep") is providers[1]
    assert find(providers, "nope") is None


def test_meta_overrides_for_default_empty():
    assert meta_overrides_for([make_entry("mimo")], "mimo") == {}
    assert meta_overrides_for([make_entry("mimo")], "nope") == {}


def test_meta_overrides_for_existing():
    e = make_entry("mimo")
    e["meta_overrides"] = {"m1": {"context_window": 200000}}
    assert meta_overrides_for([e], "mimo") == {"m1": {"context_window": 200000}}


def test_set_meta_override_add_update():
    e1 = make_entry("mimo")
    e2 = make_entry("deep")
    got = set_meta_override([e1, e2], "mimo", "m1", {"context_window": 1000})
    assert find(got, "mimo")["meta_overrides"] == {"m1": {"context_window": 1000}}
    assert find(got, "deep")["meta_overrides"] == {}
    got = set_meta_override(got, "mimo", "m1", {"context_window": 2000, "extra": 1})
    assert find(got, "mimo")["meta_overrides"] == {"m1": {"context_window": 2000, "extra": 1}}


def test_set_meta_override_delete_slug():
    e = make_entry("mimo")
    e["meta_overrides"] = {"m1": {"context_window": 1000}, "m2": {"x": 1}}
    got = set_meta_override([e], "mimo", "m1", None)
    assert find(got, "mimo")["meta_overrides"] == {"m2": {"x": 1}}
    got = set_meta_override(got, "mimo", "m1", None)
    assert find(got, "mimo")["meta_overrides"] == {"m2": {"x": 1}}


def test_set_meta_override_missing_provider_noop():
    e = make_entry("mimo")
    got = set_meta_override([e], "nope", "m1", {"context_window": 1})
    assert got == [e]


def test_set_meta_override_dump_and_load_back(tmp_path):
    p = tmp_path / "providers-registry.json"
    providers = [make_entry("mimo")]
    providers = set_meta_override(providers, "mimo", "m1", {"context_window": 1048576})
    dump(p, providers)
    reg = load(p)
    assert reg is not None
    assert reg["providers"][0]["meta_overrides"] == {"m1": {"context_window": 1048576}}


def test_dump_file_readable_by_json(tmp_path):
    p = tmp_path / "providers-registry.json"
    providers = [make_entry("mimo"), make_entry("deep")]
    dump(p, providers)
    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert [pr["id"] for pr in raw["providers"]] == ["mimo", "deep"]
    assert isinstance(providers[0]["models"], list)
