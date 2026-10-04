from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import pytest

from codex_provider.presets import deepseek_preset, load_codex_instructions, wolfox_preset

# The legacy PowerShell script this project was ported from.  It lives outside
# the repository (it was the migration source, not a shipped artifact), so the
# comparison test can only run where a developer actually has it.  Overridable
# so other checkouts do not need this exact path.
PS1 = Path(os.environ.get("CODEX_SETUP_PS1", r"E:\aiPic\setup-codex-provider.ps1"))
PROMPT_FILE = Path(__file__).resolve().parent.parent / "codex_provider" / "prompts" / "codex_instructions.txt"


def _ps1_instructions() -> str:
    text = PS1.read_text(encoding="utf-8-sig")
    m = re.search(r"FromBase64String\('([^']+)'\)", text)
    assert m is not None
    return base64.b64decode(m.group(1)).decode("utf-8")


def test_deepseek_preset_fields():
    p = deepseek_preset()
    assert p.id == "deepseek"
    assert p.name == "DeepSeek 官方"
    assert p.base_url == "https://api.deepseek.com/"
    assert p.key_prefix == "sk-"
    assert p.env_var_name == "DEEPSEEK_API_KEY"
    assert p.use_env_key is False
    assert p.models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert p.wire_api == "responses"
    assert p.context_window == 1048576
    assert p.vision is False
    assert p.instructions_mode == "full"
    assert p.reasoning_levels == ["low", "high", "max"]
    assert p.apply_patch_tool_type == "freeform"
    assert p.search_support is True
    assert p.parallel_tool_calls is True
    assert p.support_verbosity is True
    assert p.truncation_mode == "tokens"
    assert p.description == "DeepSeek API"
    assert p.base_instructions == load_codex_instructions()


def test_wolfox_preset_fields():
    p = wolfox_preset()
    assert p.id == "wolfox"
    assert p.name == "Wolfox AI"
    assert p.base_url == "https://api.wolfoxlabs.xyz/v1"
    assert p.key_prefix == "sk-"
    assert p.env_var_name == "WOLFOX_API_KEY"
    assert p.use_env_key is False
    assert p.models == ["spe/deepseek-v4-flash", "spe/deepseek-v4-pro"]
    assert p.wire_api == "chat"
    assert p.context_window == 1048576
    assert p.vision is False
    assert p.instructions_mode == "full"
    assert p.reasoning_levels == ["low", "high", "max"]
    assert p.apply_patch_tool_type == "freeform"
    assert p.search_support is False
    assert p.disable_web_search is True
    assert p.parallel_tool_calls is True
    assert p.support_verbosity is False
    assert p.truncation_mode == "tokens"
    assert p.description == "Wolfox AI API"
    assert p.base_instructions == load_codex_instructions()


def test_deepseek_preset_instances_are_independent():
    a = deepseek_preset()
    b = deepseek_preset()
    assert a is not b
    assert a.models is not b.models
    assert a.reasoning_levels is not b.reasoning_levels
    assert a.vision_by_model is not b.vision_by_model
    assert a.meta_overrides is not b.meta_overrides
    a.models.append("extra")
    a.reasoning_levels.append("ultra")
    a.vision_by_model["x"] = True
    a.meta_overrides["y"] = {"context_window": 1}
    assert b.models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert b.reasoning_levels == ["low", "high", "max"]
    assert b.vision_by_model == {}
    assert b.meta_overrides == {}


def test_wolfox_preset_instances_are_independent():
    a = wolfox_preset()
    b = wolfox_preset()
    assert a is not b
    assert a.models is not b.models
    assert a.reasoning_levels is not b.reasoning_levels
    assert a.vision_by_model is not b.vision_by_model
    assert a.meta_overrides is not b.meta_overrides
    a.models.append("extra")
    a.reasoning_levels.append("ultra")
    a.vision_by_model["x"] = True
    a.meta_overrides["y"] = {"context_window": 1}
    assert b.models == ["spe/deepseek-v4-flash", "spe/deepseek-v4-pro"]
    assert b.reasoning_levels == ["low", "high", "max"]
    assert b.vision_by_model == {}
    assert b.meta_overrides == {}


def test_load_codex_instructions_content():
    text = load_codex_instructions()
    assert len(text) > 15000
    assert text.startswith("You are Codex")
    assert text.endswith("\n")


def test_prompt_file_utf8_no_bom_readable():
    assert PROMPT_FILE.is_file()
    raw = PROMPT_FILE.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    assert text.startswith("You are Codex")
    assert len(text) > 15000


@pytest.mark.skipif(
    not PS1.is_file(),
    reason="legacy setup-codex-provider.ps1 not present (lives outside the repo)",
)
def test_prompt_file_matches_ps1_decoded():
    expected = _ps1_instructions()
    raw = PROMPT_FILE.read_bytes()
    assert raw == expected.encode("utf-8")
    assert load_codex_instructions() == expected
