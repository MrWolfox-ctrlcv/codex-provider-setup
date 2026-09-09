from __future__ import annotations

import argparse
import sys

from codex_provider import interact, paths, presets, registry, service, upstream
from codex_provider.heuristics import default_reasoning_levels, likely_vision
from codex_provider.provider import Provider


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="codex-provider-setup", description="任意 Provider × Codex 一键接入/管理（跨平台）")
    sub = p.add_subparsers(dest="command")

    install = sub.add_parser("install", help="接入/更新 provider")
    install.add_argument("--provider-id")
    install.add_argument("--provider-name")
    install.add_argument("--base-url")
    install.add_argument("--api-key")
    install.add_argument("--model-slugs")
    install.add_argument("--env-key-name")
    install.add_argument("--wire-api", choices=["responses", "chat"], default="responses")
    install.add_argument("--reasoning-effort", default="high")
    install.add_argument("--vision", action="store_true")
    install.add_argument("--short-instructions", action="store_true")
    install.add_argument("--enable-search", action="store_true")
    install.add_argument("--preset", type=int, help="1 = DeepSeek 官方")

    switch = sub.add_parser("switch", help="切换默认模型（只改 config.toml 顶部 model 一行）")
    switch.add_argument("model")

    sub.add_parser("status", help="查看当前状态")

    restore = sub.add_parser("restore", help="回退到接入前的状态")
    restore.add_argument("--provider-id", required=True)

    sync = sub.add_parser("sync", help="免交互：把上游 /models 新模型并入已接入的 provider")
    sync.add_argument("--provider-id", required=True)

    prune = sub.add_parser("prune", help="免交互：探测并移除当前 Key 不可用的模型")
    prune.add_argument("--provider-id", required=True)

    sub.add_parser("selftest", help="运行内置自测")
    return p


def _registry_rec(provider_id: str) -> dict | None:
    reg = registry.load(paths.registry_path())
    if reg and isinstance(reg.get("providers"), list):
        for rp in reg["providers"]:
            if rp.get("id") == provider_id:
                return rp
    return None


def _apply_registry_overrides(prov: Provider) -> None:
    rec = _registry_rec(prov.id)
    if rec and isinstance(rec.get("meta_overrides"), dict):
        prov.meta_overrides = rec["meta_overrides"]


def _build_param_provider(args) -> Provider:
    models = [s.strip() for s in (args.model_slugs or "").replace("，", ",").split(",") if s.strip()] if args.model_slugs else []
    cw = 1048576
    if not models:
        if not args.api_key:
            raise SystemExit("缺少模型列表：请提供 --model-slugs，或提供 --api-key 以便自动拉取。")
        fetch = upstream.fetch_models(args.base_url, args.api_key)
        if not fetch["ok"]:
            raise SystemExit(f"拉取模型列表失败（{fetch['error']}），请改用 --model-slugs 显式指定。")
        models = fetch["models"]
        if not models:
            raise SystemExit("API 返回的模型列表为空。")
        det = upstream.detect_context_window(fetch["raw"])
        if det:
            cw = det
        interact.ok(f"已从 API 自动拉取 {len(models)} 个模型（上下文窗口: {cw}）")
    vision = args.vision or (len(models) > 0 and likely_vision(models))
    return Provider(
        id=args.provider_id,
        name=args.provider_name or args.provider_id,
        base_url=args.base_url,
        key_prefix="sk-",
        env_var_name=args.env_key_name or "",
        use_env_key=bool(args.env_key_name),
        models=models,
        wire_api=args.wire_api,
        context_window=cw,
        vision=vision,
        instructions_mode="short" if args.short_instructions else "full",
        reasoning_levels=default_reasoning_levels(models),
        base_instructions=f"You are {args.provider_id}, an AI assistant. Today's date: {{date}} {{week}}.",
        description=args.provider_id,
        apply_patch_tool_type="",
        search_support=args.enable_search,
        support_verbosity=False,
        parallel_tool_calls=False,
        disable_web_search=not args.enable_search,
    )


def _cmd_install(args) -> int:
    reasoning_effort = getattr(args, "reasoning_effort", "high")
    param_key = getattr(args, "api_key", "") or ""
    if args.preset:
        if args.preset == 1:
            prov = presets.deepseek_preset()
        else:
            raise SystemExit("预设仅支持 1 = DeepSeek 官方；其它请走完全自定义（--provider-id + --base-url）。")
        _apply_registry_overrides(prov)
    elif args.provider_id and args.base_url:
        prov = _build_param_provider(args)
    else:
        prov = interact.choose_provider(allow_custom=True)
        if prov is None:
            return 0
        _apply_registry_overrides(prov)
    key = service.get_api_key(prov, param_key=param_key, interactive_prompt=lambda: interact.prompt_api_key(prov))
    if not key:
        raise SystemExit("未取得 API Key，已中止（未改动任何文件）。")
    service.install_provider(prov, key, reasoning_effort=reasoning_effort)
    return 0


def _cmd_restore(args) -> int:
    rec = next((r for r in service.installed_providers() if r.get("id") == args.provider_id), None)
    if rec is None:
        raise SystemExit(f"provider '{args.provider_id}' 未接入，请先用 install 接入。")
    prov = service.provider_from_installed(rec)
    service.restore_provider(prov)
    return 0


def _cmd_provider_op(args, op) -> int:
    rec = next((r for r in service.installed_providers() if r.get("id") == args.provider_id), None)
    if rec is None:
        raise SystemExit(f"provider '{args.provider_id}' 未接入，请先用 install 接入。")
    prov = service.provider_from_installed(rec)
    key = service.get_api_key(prov, interactive_prompt=lambda: interact.prompt_api_key(prov))
    if not key:
        raise SystemExit("未取得 API Key，已中止（未改动任何文件）。")
    op(prov, key)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command is None:
        interact.main_menu()
        return 0
    if args.command == "install":
        return _cmd_install(args)
    if args.command == "switch":
        service.switch_default_model(args.model)
        interact.ok(f'config.toml 已更新: model = "{args.model}"（其余配置未动）')
        interact.warn("请新开终端运行 codex 生效。")
        return 0
    if args.command == "status":
        interact.show_status(None)
        return 0
    if args.command == "restore":
        return _cmd_restore(args)
    if args.command == "sync":
        return _cmd_provider_op(args, lambda prov, key: service.sync_from_upstream(prov, key))
    if args.command == "prune":
        return _cmd_provider_op(args, lambda prov, key: service.prune_unusable(prov, key))
    if args.command == "selftest":
        interact.warn("内置自测已迁移为 pytest：请运行 .\\.venv\\Scripts\\python.exe -m pytest")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
