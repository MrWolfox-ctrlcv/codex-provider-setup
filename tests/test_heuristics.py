from __future__ import annotations

import pytest

from codex_provider.heuristics import default_reasoning_levels, likely_vision

LEVEL_CASES: list[tuple[list[str], list[str]]] = [
    (["gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra"], ["none", "low", "high", "max", "xhigh"]),
    (["gpt-4"], ["none", "low", "high", "max", "xhigh"]),
    (["gpt-4o-mini"], ["none", "low", "high", "max", "xhigh"]),
    (["GPT-5.5"], ["none", "low", "high", "max", "xhigh"]),
    (["gpt-5.5", "deepseek-chat"], ["none", "low", "high", "max", "xhigh"]),
    (["deepseek-chat"], ["none", "high"]),
    (["qwen-max"], ["none", "high"]),
    (["deepseek-chat", "qwen-max"], ["none", "high"]),
    (["deepseek-r1"], ["low", "high", "max"]),
    (["deepseek-reasoner"], ["low", "high", "max"]),
    (["o4-mini"], ["low", "medium", "high"]),
    (["o1"], ["low", "medium", "high"]),
    (["o1-preview"], ["low", "medium", "high"]),
    ([], ["none", "high"]),
    (["grok-3"], ["low", "high", "max"]),
    (["grok3"], ["low", "high", "max"]),
    (["deepseek-v3.2-think"], ["low", "high", "max"]),
    (["claude-sonnet-4"], ["low", "high"]),
    (["claude-3-7-sonnet"], ["low", "high"]),
    (["claude-sonnet-4", "grok-3"], ["low", "high", "max"]),
]

VISION_CASES: list[tuple[list[str], bool]] = [
    (["gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra"], True),
    (["gpt-4o"], True),
    (["gpt-4"], True),
    (["gpt-5"], True),
    (["GPT-4O"], True),
    (["o4-mini"], True),
    (["o1"], True),
    (["qwen3-vl-plus"], True),
    (["gemini-2.5-vl"], True),
    (["claude-omni"], True),
    (["x-vlm-1"], True),
    ([], False),
    (["deepseek-chat"], False),
    (["qwen-max"], False),
    (["deepseek-r1"], False),
    (["grok-3"], False),
    (["grok3"], False),
    (["claude-sonnet-4"], False),
    (["deepseek-v3.2-think"], False),
]


@pytest.mark.parametrize(("models", "expected"), LEVEL_CASES)
def test_default_reasoning_levels(models: list[str], expected: list[str]) -> None:
    assert default_reasoning_levels(models) == expected


@pytest.mark.parametrize(("models", "expected"), VISION_CASES)
def test_likely_vision(models: list[str], expected: bool) -> None:
    assert likely_vision(models) is expected
