from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from codex_provider import interact, paths, presets, registry, service, upstream
from codex_provider.heuristics import default_reasoning_levels, likely_vision
from codex_provider.interact import err
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
    install.add_argument("--preset", type=int, help="1 = DeepSeek 官方，2 = Wolfox AI（https://api.wolfoxlabs.xyz）")

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

    doc = sub.add_parser("doctor", help="诊断 Codex 为何不显示新接入的 provider/模型")
    doc.add_argument("--fix", action="store_true", help="清理桌面端 UI 状态缓存（备份后清除）")
    doc.add_argument("--include-web", action="store_true", help="连同桌面端 Chromium 数据目录一起清理")
    doc.add_argument("--json", action="store_true", help="以 JSON 输出诊断结果")
    doc.add_argument("--restore-ui", action="store_true", help="从最近的备份恢复桌面端 UI 状态")
    doc.add_argument("--from", dest="restore_from", help="指定 backup-ui-state-* 目录（配合 --restore-ui）")
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
        elif args.preset == 2:
            prov = presets.wolfox_preset()
        else:
            raise SystemExit("预设支持 1 = DeepSeek 官方、2 = Wolfox AI；其它请走完全自定义（--provider-id + --base-url）。")
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


def _log_crash(exc: BaseException) -> None:
    """Write the full traceback to a log file next to the user's codex home."""
    import traceback
    from codex_provider.service import SCRIPT_VERSION

    try:
        log_path = paths.codex_home() / "codex-provider-setup-crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write("=" * 60 + "\n")
            fh.write(f"codex-provider-setup crash log (version {SCRIPT_VERSION})\n")
            traceback.print_exc(file=fh)
        return log_path
    except Exception:
        return None


def _pause_before_exit() -> None:
    """Keep the console window open on Windows so users can read errors.

    Must never raise: this runs while an error is already being reported, and a
    failure here would hide the real message.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, True)
    except Exception:
        pass
    try:
        input("  按回车键退出...")
    except (EOFError, OSError, KeyboardInterrupt):
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except interact.AbortError as exc:
        print("")
        err(str(exc))
        err("没有写入或修改任何文件。")
        print("")
        _pause_before_exit()
        return 2
    except KeyboardInterrupt:
        print("")
        warn("已中断。")
        _pause_before_exit()
        return 130
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - last-resort guard: never flash-crash
        print("")
        err(f"程序发生未预期的错误：{exc}")
        err("已将详细错误写入日志，请把下面日志发给开发者排查：")
        log_path = _log_crash(exc)
        if log_path:
            err(f"  日志文件：{log_path}")
        print("")
        traceback.print_exc()
        print("")
        _pause_before_exit()
        return 1


def _cmd_doctor(args) -> int:
    import json as _json

    from codex_provider import doctor

    as_json = bool(getattr(args, "json", False))

    def say(kind: str, msg: str) -> None:
        """Suppress prose in JSON mode so stdout stays machine-readable."""
        if as_json:
            return
        {"ok": interact.ok, "warn": interact.warn, "err": interact.err}[kind](msg)

    diag = doctor.diagnose()
    payload: dict = {
        "ok": diag.ok,
        "codex_home": str(paths.codex_home()),
        "findings": [
            {"level": f.level, "title": f.title, "detail": f.detail, "fix": f.fix}
            for f in diag.findings
        ],
    }

    if not as_json:
        print("")
        print(f"Codex 配置目录: {paths.codex_home()}")
        print("")
        for f in diag.findings:
            tag = {"ok": "[OK]", "warn": "[!] ", "bad": "[X] "}[f.level]
            line = f"  {tag} {f.title}"
            if f.detail:
                line += f"  ({f.detail})"
            print(line)
            if f.fix and f.level in ("warn", "bad"):
                print(f"        → {f.fix}")
        print("")

    if getattr(args, "restore_ui", False):
        procs = doctor.find_codex_processes()
        if procs:
            say("warn", "检测到 Codex / ChatGPT 正在运行：" + " / ".join(procs))
            say("warn", "请先完全退出（含托盘）再恢复，否则会被应用覆盖。")
            if as_json:
                payload["restore_ui"] = {"errors": ["Codex 正在运行，已跳过"], "restored_keys": []}
                print(_json.dumps(payload, ensure_ascii=True, indent=2))
            return 2
        src = Path(args.restore_from) if getattr(args, "restore_from", None) else None
        result = doctor.restore_ui_state(src)
        for e in result["errors"]:
            say("err", f"  {e}")
        if result["restored_keys"]:
            say("ok", f"已从 {result['source'].parent.name} 恢复 {len(result['restored_keys'])} 个键：")
            for k in result["restored_keys"]:
                print(f"      - {k}")
            if result["backup_of_current"]:
                print(f"      当前状态已先备份到：{result['backup_of_current']}")
            say("warn", "请重新打开 Codex 查看。")
        elif not result["errors"]:
            say("ok", "没有需要恢复的键（当前状态已包含备份内容）。")
        if as_json:
            payload["restore_ui"] = {
                "restored_keys": result["restored_keys"],
                "source": str(result["source"]) if result["source"] else None,
                "backup_of_current": str(result["backup_of_current"]) if result["backup_of_current"] else None,
                "errors": result["errors"],
            }
            print(_json.dumps(payload, ensure_ascii=True, indent=2))
        return 0 if not result["errors"] else 1

    if not getattr(args, "fix", False):
        if as_json:
            # JSON mode stays machine-readable: no prose on stdout.
            print(_json.dumps(payload, ensure_ascii=True, indent=2))
            return 0 if diag.ok else 1
        if not diag.ok:
            interact.warn("发现问题。可加 --fix 清理桌面端缓存（会先备份），然后完全退出 Codex 再打开。")
            return 1
        interact.ok("未发现明显问题。若 Codex 里仍不对，请完全退出应用后重开并新建对话。")
        return 0

    procs = doctor.find_codex_processes()
    if procs:
        say("warn", "检测到 Codex / ChatGPT 正在运行：" + " / ".join(procs))
        say("warn", "请先完全退出（含托盘）再清理，否则可能被覆盖。")
        if as_json:
            payload["fix"] = {"errors": ["Codex 正在运行，已跳过"], "moved": []}
            print(_json.dumps(payload, ensure_ascii=True, indent=2))
        return 2

    result = doctor.reset_ui_state(include_web=getattr(args, "include_web", False))
    if result["moved"]:
        say("ok", f"已备份并清除 {len(result['moved'])} 项：{' / '.join(result['moved'])}")
        if not as_json:
            print(f"      备份目录：{result['backup_dir']}")
    else:
        say("warn", "没有可清理的桌面端缓存。")
    for e in result["errors"]:
        say("err", f"  {e}")
    say("ok", "请完全退出 Codex（含托盘）后重新打开，并新建一个对话验证模型列表。")
    if as_json:
        payload["fix"] = {
            "moved": result["moved"],
            "backup_dir": str(result["backup_dir"]) if result["backup_dir"] else None,
            "errors": result["errors"],
        }
        print(_json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


def _main(argv: list[str] | None = None) -> int:
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
    if args.command == "doctor":
        return _cmd_doctor(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
