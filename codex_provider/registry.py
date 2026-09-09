from __future__ import annotations

from pathlib import Path

from codex_provider.io_utils import read_json, write_json


def load(path: Path) -> dict | None:
    data = read_json(path)
    if not isinstance(data, dict):
        return None
    return data


def dump(path: Path, providers: list[dict]) -> None:
    write_json(path, {"providers": providers})


def upsert(providers: list[dict], entry: dict) -> list[dict]:
    pid = entry.get("id")
    return [p for p in providers if p.get("id") != pid] + [entry]


def find(providers: list[dict], pid: str) -> dict | None:
    for p in providers:
        if p.get("id") == pid:
            return p
    return None


def meta_overrides_for(providers: list[dict], pid: str) -> dict:
    p = find(providers, pid)
    if p is None:
        return {}
    ov = p.get("meta_overrides")
    return ov if isinstance(ov, dict) else {}


def set_meta_override(
    providers: list[dict], pid: str, slug: str, overrides: dict | None
) -> list[dict]:
    out: list[dict] = []
    for p in providers:
        if p.get("id") != pid:
            out.append(p)
            continue
        ov = p.get("meta_overrides")
        new_ov = dict(ov) if isinstance(ov, dict) else {}
        if overrides is None:
            new_ov.pop(slug, None)
        else:
            new_ov[slug] = dict(overrides)
        entry = dict(p)
        entry["meta_overrides"] = new_ov
        out.append(entry)
    return out
