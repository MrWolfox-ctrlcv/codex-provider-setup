from __future__ import annotations

import re

_REASONING_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"gpt-5|gpt-4", ("none", "low", "high", "max", "xhigh")),
    (r"\bo[0-9](?![0-9])", ("low", "medium", "high")),
    (r"deepseek-r|reason|think|grok-?[0-9]|\br1\b", ("low", "high", "max")),
    (r"claude", ("low", "high")),
)

_FALLBACK_LEVELS: tuple[str, ...] = ("none", "high")

_VISION_RE = re.compile(r"vision|vl|omni|vlm|4o|gpt-4|gpt-5|\bo[0-9](?![0-9])", re.IGNORECASE)


def default_reasoning_levels(models: list[str]) -> list[str]:
    joined = " ".join(models)
    for pattern, levels in _REASONING_RULES:
        if re.search(pattern, joined, re.IGNORECASE):
            return list(levels)
    return list(_FALLBACK_LEVELS)


def likely_vision(models: list[str]) -> bool:
    return _VISION_RE.search(" ".join(models)) is not None
