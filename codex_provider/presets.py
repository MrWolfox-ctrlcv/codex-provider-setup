from __future__ import annotations

from codex_provider.provider import Provider
from codex_provider.prompts import load_codex_instructions


def deepseek_preset() -> Provider:
    return Provider(
        id="deepseek",
        name="DeepSeek 官方",
        base_url="https://api.deepseek.com/",
        key_prefix="sk-",
        env_var_name="DEEPSEEK_API_KEY",
        use_env_key=False,
        models=["deepseek-v4-flash", "deepseek-v4-pro"],
        wire_api="responses",
        context_window=1048576,
        vision=False,
        instructions_mode="full",
        reasoning_levels=["low", "high", "max"],
        base_instructions=load_codex_instructions(),
        description="DeepSeek API",
        apply_patch_tool_type="freeform",
        search_support=True,
        parallel_tool_calls=True,
        support_verbosity=True,
        truncation_mode="tokens",
    )


def wolfox_preset() -> Provider:
    return Provider(
        id="wolfox",
        name="Wolfox AI",
        base_url="https://api.wolfoxlabs.xyz/v1",
        key_prefix="sk-",
        env_var_name="WOLFOX_API_KEY",
        use_env_key=False,
        models=["spe/deepseek-v4-flash", "spe/deepseek-v4-pro"],
        wire_api="chat",
        context_window=1048576,
        vision=False,
        instructions_mode="full",
        reasoning_levels=["low", "high", "max"],
        base_instructions=load_codex_instructions(),
        description="Wolfox AI API",
        apply_patch_tool_type="freeform",
        search_support=False,
        disable_web_search=True,
        parallel_tool_calls=True,
        support_verbosity=False,
        truncation_mode="tokens",
    )
