from __future__ import annotations

import json
from pathlib import Path

from codex_provider.io_utils import atomic_write
from codex_provider.provider import Provider
from codex_provider.prompts import load_codex_instructions

_REASONING_DESCRIPTIONS = {
    "none": "Disable Thinking",
    "low": "Fast responses with lighter reasoning",
    "high": "Extra high reasoning depth for complex problems",
    "max": "Maximum reasoning depth for the hardest problems",
}


def _reasoning_description(level: str) -> str:
    if level in _REASONING_DESCRIPTIONS:
        return _REASONING_DESCRIPTIONS[level]
    return f"Reasoning level: {level}"


def build_model_metadata(provider: Provider, index: int) -> dict:
    slug = provider.models[index]
    levels = [{"effort": e, "description": _reasoning_description(e)} for e in provider.reasoning_levels]
    m = {}
    m["slug"] = slug
    m["prefer_websockets"] = False
    m["support_verbosity"] = provider.support_verbosity
    if provider.support_verbosity:
        m["default_verbosity"] = "low"
    if provider.apply_patch_tool_type:
        m["apply_patch_tool_type"] = provider.apply_patch_tool_type
    if provider.search_support:
        m["web_search_tool_type"] = "text"
    vision = provider.vision
    if slug in provider.vision_by_model:
        vision = provider.vision_by_model[slug]
    if vision:
        m["input_modalities"] = ["text", "image"]
        m["supports_image_detail_original"] = True
    else:
        m["input_modalities"] = ["text"]
        m["supports_image_detail_original"] = False
    m["truncation_policy"] = {"mode": provider.truncation_mode, "limit": 10000}
    m["supports_parallel_tool_calls"] = provider.parallel_tool_calls
    m["tool_mode"] = None
    m["multi_agent_version"] = "v2"
    m["use_responses_lite"] = False
    m["include_skills_usage_instructions"] = False
    m["auto_review_model_override"] = None
    m["context_window"] = provider.context_window
    m["max_context_window"] = provider.context_window
    m["effective_context_window_percent"] = 95
    m["auto_compact_token_limit"] = None
    m["comp_hash"] = "3000"
    m["reasoning_summary_format"] = "experimental"
    m["default_reasoning_summary"] = "none"
    m["display_name"] = slug
    m["description"] = f"{provider.description} - {slug}"
    m["default_reasoning_level"] = "high"
    m["supported_reasoning_levels"] = levels
    m["shell_type"] = "shell_command"
    m["visibility"] = "list"
    m["minimal_client_version"] = "0.144.0"
    m["supported_in_api"] = True
    m["availability_nux"] = None
    m["upgrade"] = None
    m["priority"] = index + 1
    if provider.instructions_mode == "full":
        m["model_messages"] = {
            "instructions_template": load_codex_instructions(),
            "instructions_variables": {
                "personality_default": "",
                "personality_friendly": "",
                "personality_pragmatic": "",
            },
            "approvals": None,
        }
    m["experimental_supported_tools"] = []
    m["supports_search_tool"] = provider.search_support
    m["default_service_tier"] = None
    m["supports_reasoning_summaries"] = True
    m["base_instructions"] = provider.base_instructions

    overrides = provider.meta_overrides.get(slug)
    if overrides:
        for key, value in overrides.items():
            if value is None:
                continue
            if key == "context_window":
                m["context_window"] = value
                m["max_context_window"] = value
            elif key == "max_context_window":
                m["max_context_window"] = value
            elif key in m:
                m[key] = value
    return m


def merge_catalog(existing: list[dict], provider: Provider) -> tuple[list[dict], int]:
    owned = set(provider.models)
    kept = [item for item in existing if item.get("slug") not in owned]
    replaced = len(existing) - len(kept)
    merged = list(kept)
    for i in range(len(provider.models)):
        merged.append(build_model_metadata(provider, i))
    return merged, replaced


def catalog_text(models: list[dict], had_existing: bool) -> str:
    text = json.dumps({"models": models}, ensure_ascii=False)
    if had_existing:
        text += "\r\n"
    return text


def write_catalog(path: Path, models: list[dict], had_existing: bool) -> None:
    atomic_write(path, catalog_text(models, had_existing))
