from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Provider:
    id: str
    name: str
    base_url: str
    key_prefix: str = "sk-"
    env_var_name: str = ""
    use_env_key: bool = False
    models: list[str] = field(default_factory=list)
    wire_api: str = "responses"
    context_window: int = 1048576
    vision: bool = False
    instructions_mode: str = "short"
    reasoning_levels: list[str] = field(default_factory=list)
    base_instructions: str = ""
    description: str = ""
    apply_patch_tool_type: str = ""
    search_support: bool = True
    parallel_tool_calls: bool = True
    support_verbosity: bool = True
    truncation_mode: str = "tokens"
    vision_by_model: dict[str, bool] = field(default_factory=dict)
    disable_web_search: bool = False
    meta_overrides: dict[str, dict] = field(default_factory=dict)
    reasoning_effort: str = "high"

    def clone(self, models: list[str] | None = None) -> "Provider":
        from dataclasses import replace

        return replace(self, models=models if models is not None else list(self.models))
