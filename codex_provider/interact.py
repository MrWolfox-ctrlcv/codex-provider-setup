from __future__ import annotations

import os
import re
import sys
from getpass import getpass

from codex_provider import heuristics, paths, presets, registry, service, upstream
from codex_provider.io_utils import read_json, read_text
from codex_provider.provider import Provider

_active: Provider | None = None


def _paint(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def ok(m: str) -> None:
    print(_paint("32", "[OK] ") + m)


def warn(m: str) -> None:
    print(_paint("33", "[!]  ") + m)


def head(m: str) -> None:
    print("")
    print(_paint("37", m))


def dim(m: str) -> None:
    print(_paint("90", m))


def err(m: str) -> None:
    print(_paint("31", "[X] ") + m)


def confirm(prompt: str, default: bool = False) -> bool:
    if re.search(r"\[[yY]/", prompt):
        shown = prompt
    elif default:
        shown = f"{prompt} [Y/n]"
    else:
        shown = f"{prompt} [y/N]"
    v = input(f"  {shown} ").strip().lower()
    if not v:
        return default
    if v.startswith("y"):
        return True
    if v.startswith("n"):
        return False
    return default


def read_required(label: str, default: str = "", from_param: str = "") -> str:
    if from_param:
        dim(f"{label} : {from_param}（来自参数）")
        return from_param
    hint = f" [默认 {default}]" if default else ""
    v = input(f"  {label}{hint}: ").strip()
    if not v:
        return default
    return v


def read_choice_list(text: str, count: int) -> list[int] | None:
    if count <= 0:
        return []
    if text == "a" or text == "A":
        return list(range(count))
    if text == "q" or text == "Q":
        return None
    picked: list[int] = []
    for tok in re.split(r"[,，;、\s]+", text):
        if not tok:
            continue
        m = re.fullmatch(r"(\d+)-(\d+)", tok)
        if m:
            lo = int(m.group(1))
            hi = int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            for n in range(lo, hi + 1):
                if 1 <= n <= count and n - 1 not in picked:
                    picked.append(n - 1)
            continue
        if re.fullmatch(r"\d+", tok):
            n = int(tok)
            if 1 <= n <= count and n - 1 not in picked:
                picked.append(n - 1)
    return picked


def choose_provider(allow_custom: bool) -> Provider | None:
    head("选择 provider")
    preset = presets.deepseek_preset()
    installed = [p for p in service.installed_providers() if p.get("id") != "deepseek"]
    default_model = preset.models[0] if preset.models else "(无)"
    print(f"   1) {preset.name}  ({preset.base_url}, 默认模型 {default_model})")
    base = 1
    if installed:
        dim("   ── 已接入的 provider（可重新接入/切换/回退） ──")
        for j, rec in enumerate(installed):
            mdl = f", 模型: {' / '.join(rec.get('models') or [])}" if rec.get("models") else ""
            shown = rec.get("name") or rec.get("id") or ""
            print(f"   {base + j + 1}) {shown}  ({rec.get('base_url') or ''}{mdl})")
    n_custom = base + len(installed) + 1
    if allow_custom:
        print(f"   {n_custom}) 完全自定义")
    max_n = base + len(installed) + (1 if allow_custom else 0)
    raw = input(f"   请输入 [1-{max_n}] ")
    try:
        idx = int(raw.strip())
    except ValueError:
        idx = 0
    if idx < 1 or idx > max_n:
        warn("输入无效，已取消。")
        return None
    if idx <= base:
        return preset
    if idx <= base + len(installed):
        rec = installed[idx - base - 1]
        try:
            return service.provider_from_installed(rec)
        except ValueError as exc:
            warn(str(exc))
            return None
    return custom_provider_wizard()


def prompt_api_key(provider: Provider) -> str | None:
    print("")
    dim(f"Key 获取地址请查看你的 provider 控制台（一般以 {provider.key_prefix} 开头）")
    v = getpass("  请输入 API Key: ").strip()
    if not v:
        warn("未输入 Key，已取消。")
        return None
    return v


def select_fetched_models(model_ids: list[str]) -> list[str] | None:
    print("")
    dim(f"从 API 拉取到 {len(model_ids)} 个模型：")
    for i, mid in enumerate(model_ids, 1):
        print(f"    {i:3}) {mid}")
    print("")
    bad = 0
    while True:
        print("  1) 全部接入")
        print("  2) 按关键字过滤后选择")
        print("  3) 手动输入模型名")
        opt = input("  请选择 [1-3] ").strip()
        if opt == "1":
            return list(model_ids)
        if opt == "3":
            return None
        if opt == "2":
            break
        bad += 1
        if bad >= 3:
            warn("连续输入无效，已取消。")
            return None
        warn("输入无效。")
    bad = 0
    while True:
        kw = input("  关键字（直接回车=不过滤，列出全部） ").strip()
        filtered = [m for m in model_ids if not kw or kw.lower() in m.lower()]
        if not filtered:
            bad += 1
            if bad >= 3:
                warn("连续无匹配，已取消。")
                return None
            warn("无匹配模型，请重新输入关键字。")
            continue
        print(f"  匹配 {len(filtered)} 个：")
        for i, mid in enumerate(filtered, 1):
            print(f"    {i:3}) {mid}")
        sel_bad = 0
        while True:
            sel = read_choice_list(input("  选择编号（逗号分隔；a=全部匹配；q=重新过滤） "), len(filtered))
            if sel is None:
                break
            if sel:
                return [filtered[i] for i in sel]
            sel_bad += 1
            if sel_bad >= 3:
                warn("连续输入无效，已取消。")
                return None
            warn("没有有效的选择。")


def custom_provider_wizard() -> Provider | None:
    head("自定义 provider（填写你的接口信息）")
    pid = read_required("provider id（config.toml 段名，如 myapi，只能用小写字母数字-_）")
    if not pid or not re.fullmatch(r"[a-zA-Z0-9_-]+", pid):
        warn("provider id 不合法，已取消。")
        return None
    pid = pid.lower()
    name = read_required("显示名", pid)
    base_url = read_required("base_url（如 https://api.example.com/v1）")
    if not re.match(r"^https?://", base_url) or '"' in base_url or "'" in base_url:
        warn("base_url 不合法，已取消。")
        return None
    prefix = read_required("API Key 前缀（留空则不校验）", "sk-")

    provisional = Provider(id=pid, name=name, base_url=base_url, key_prefix=prefix)
    key = service.get_api_key(provisional, interactive_prompt=lambda: prompt_api_key(provisional))
    if not key:
        warn("未取得 API Key，已取消。")
        return None
    if prefix and not key.startswith(prefix):
        warn(f"Key 不是 {prefix} 开头，与常见格式不符。")
        if not confirm("仍要继续?"):
            warn("已取消。")
            return None

    models: list[str] = []
    detected_cw: int | None = None
    fetch = upstream.fetch_models(base_url, key)
    if fetch["ok"]:
        ok(f"API 连通，Key 有效，拉取到 {len(fetch['models'])} 个模型")
        detected_cw = upstream.detect_context_window(fetch["raw"])
        if detected_cw is None:
            dim("该 API 未提供 context_window 字段（newapi 等中转常见），上下文窗口将使用默认值")
        picked = select_fetched_models(list(fetch["models"]))
        if picked is None:
            warn("跳过拉取，改为手动输入模型。")
        else:
            models = picked
    else:
        warn(f"拉取模型列表失败（{fetch['error']}），改为手动输入。")
    if not models:
        raw = read_required("模型 slug（逗号分隔，第一个为默认）")
        models = [s.strip() for s in re.split(r"[,，]", raw) if s.strip()]
    if not models:
        warn("未提供模型，已取消。")
        return None
    for s in models:
        if '"' in s or "'" in s or re.search(r"\s", s):
            warn(f"模型 slug 不能含引号/空格: {s}，已取消。")
            return None

    cw = detected_cw if detected_cw is not None else 1048576
    if detected_cw is not None:
        dim(f"从 API 检测到上下文窗口: {detected_cw}")
    cw_raw = read_required("上下文窗口", str(cw))
    try:
        cw_val = int(cw_raw)
    except ValueError:
        cw_val = 0
    if cw_val < 1000 or cw_val > 16777216:
        warn("上下文窗口不合法，已取消。")
        return None

    levels = heuristics.default_reasoning_levels(models)
    v = read_required("支持的思考档位（逗号分隔；不支持思考填 none）", ",".join(levels))
    levels = [x.strip() for x in re.split(r"[,，]", v) if x.strip()]
    if not levels:
        levels = ["none"]
    def_effort = "high" if "high" in levels else ("low" if "low" in levels else "none")
    read_required("默认推理强度", def_effort)

    vision = confirm("支持图片输入?", default=heuristics.likely_vision(models))
    full_instr = confirm("使用 Codex 完整 agent 提示词?", default=True)
    search = confirm("支持联网搜索（web_search 工具）?", default=False)
    env_name = read_required("环境变量名（留空则把 Key 写入 config.toml 的 experimental_bearer_token）")
    wire_v = read_required("wire_api（responses 默认 / chat）", "responses")
    wire = "chat" if wire_v == "chat" else "responses"

    return Provider(
        id=pid,
        name=name,
        base_url=base_url,
        key_prefix=prefix,
        env_var_name=env_name,
        use_env_key=bool(env_name),
        models=models,
        wire_api=wire,
        context_window=cw_val,
        vision=vision,
        instructions_mode="full" if full_instr else "short",
        reasoning_levels=levels,
        base_instructions=f"You are {name}, an AI assistant provided via the {name} API. Today's date: {{date}} {{week}}.",
        description=f"{name} API",
        apply_patch_tool_type="",
        search_support=search,
        support_verbosity=False,
        parallel_tool_calls=False,
        disable_web_search=not search,
    )


def manage_models(record: dict) -> None:
    prov = service.provider_from_installed(record)
    current = [m for m in (record.get("models") or []) if m]

    key = service.get_api_key(prov, interactive_prompt=lambda: prompt_api_key(prov))
    if not key:
        warn("未取得 API Key，无法拉取上游候选，已取消。")
        return
    fetch = upstream.fetch_models(prov.base_url, key)
    if not fetch["ok"]:
        warn(f"拉取上游模型列表失败（{fetch['error']}），已取消。")
        return
    up_models = list(fetch["models"])
    kept = [s for s in current if s in up_models]
    added = [s for s in up_models if s not in current]
    stale = [s for s in current if s not in up_models]

    title = prov.name if prov.name else prov.id
    head(f"模型列表管理：{title}（{prov.base_url}）")
    if up_models:
        dim(f"上游 /models 共返回 {len(up_models)} 个候选")
    else:
        warn("上游返回空列表（网关可能限制该 Key 可见模型）。")
    print(f"  已接入（保留）: {' / '.join(kept) if kept else '(无)'}")
    if added:
        ok(f"上游新增候选: {' / '.join(added)}")
    if stale:
        warn(f"本地有、上游未列出: {' / '.join(stale)}（未自动移除；如下架可手动移除）")

    pending_add: list[str] = []
    pending_del: list[str] = []
    bad = 0
    while True:
        print("")
        print("  ── 待处理变更 ────────────────────────────")
        print(f"     待接入: {' / '.join(pending_add) if pending_add else '(无)'}")
        print(f"     待移除: {' / '.join(pending_del) if pending_del else '(无)'}")
        print("    1) 从上游候选勾选要接入的模型")
        print("    2) 手动输入要接入的模型名")
        print("    3) 移除已接入的模型")
        print("    4) 编辑模型参数（上下文窗口/有效百分比/自动压缩阈值）")
        print("    5) 探测并移除当前 Key 不可用的模型")
        print("    6) 清空所有待处理变更")
        print("    7) 应用变更并写盘")
        print("    8) 返回（不写盘）")
        opt = input("  请输入 [1-8] ").strip()

        if opt == "8":
            dim("已取消，未写盘。")
            return
        if opt == "6":
            pending_add.clear()
            pending_del.clear()
            dim("待处理变更已清空。")
            continue

        if opt == "1":
            cand = [s for s in added if s not in pending_add]
            if not cand:
                warn("没有可勾选的新候选（上游新模型均已接入或已列入待接入）。")
                continue
            print(f"  上游新候选 {len(cand)} 个：")
            for i, s in enumerate(cand, 1):
                print(f"     {i:2}) {s}")
            sel = read_choice_list(input("  输入编号（逗号/空格/区间；a=全部；q=返回） "), len(cand))
            if sel is None or not sel:
                continue
            for i in sel:
                if cand[i] not in pending_add:
                    pending_add.append(cand[i])
            ok(f"待接入: {' / '.join(pending_add)}")
            continue

        if opt == "2":
            raw = input("  输入要接入的模型名（逗号分隔，如 gpt-5.6-sol,qwen3-max） ")
            bad2 = 0
            for piece in re.split(r"[,，;、]", raw):
                nm = piece.strip()
                if not nm:
                    continue
                if nm in current or nm in pending_add:
                    dim(f"  跳过 {nm}（已在清单中）")
                    continue
                if nm not in up_models:
                    if bad2 >= 3:
                        warn("连续输入无效，放弃手动接入。")
                        break
                    if not confirm(f'上游候选里没有 "{nm}"（网关可能过滤或未开通该模型），仍要接入?'):
                        bad2 += 1
                        dim(f"  跳过 {nm}")
                        continue
                pending_add.append(nm)
            if pending_add:
                ok(f"待接入: {' / '.join(pending_add)}")
            continue

        if opt == "3":
            pool = list(current) + [s for s in pending_add if s not in current]
            st_model, st_prov = service.current_state()
            blocked_default = st_prov == prov.id and st_model != "(未设置)"
            available: list[str] = []
            for s in pool:
                if s in pending_del:
                    continue
                if blocked_default and s == st_model:
                    warn(f"  {s} 是当前默认模型，不能在此移除（请先在主菜单用「切换默认模型」改到其它模型）。")
                    continue
                available.append(s)
            if not available:
                warn("没有可移除的模型。")
                continue
            print(f"  已接入 {len(available)} 个（可移除）：")
            for i, s in enumerate(available, 1):
                tag = "（上游未列出，疑已下架）" if s not in up_models else ""
                print(f"     {i:2}) {s}{tag}")
            sel = read_choice_list(input("  输入要移除的编号（逗号/空格/区间；q=返回） "), len(available))
            if sel is None or not sel:
                continue
            for i in sel:
                if available[i] not in pending_del:
                    pending_del.append(available[i])
            ok(f"待移除: {' / '.join(pending_del)}")
            continue

        if opt == "4":
            avail = list(current)
            if not avail:
                warn("该 provider 还没有任何模型。")
                continue
            catalog_rows: dict[str, dict] = {}
            data = read_json(paths.models_path())
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                for row in data["models"]:
                    if isinstance(row, dict) and row.get("slug"):
                        catalog_rows[row["slug"]] = row
            print("  选择要编辑参数的模型（括号内为 models.json 当前值）：")
            for i, s in enumerate(avail, 1):
                row = catalog_rows.get(s)
                cw_cur = row.get("context_window") if row and row.get("context_window") else 1048576
                ep_cur = row.get("effective_context_window_percent") if row and row.get("effective_context_window_percent") else 95
                ac_cur = row.get("auto_compact_token_limit") if row and row.get("auto_compact_token_limit") is not None else "默认"
                print(f"     {i:2}) {s}  (窗口 {cw_cur} / 有效 {ep_cur}% / 压缩阈值 {ac_cur})")
            sel = read_choice_list(input("  编号（q=返回） "), len(avail))
            if sel is None or not sel:
                continue
            slug = avail[sel[0]]
            row = catalog_rows.get(slug)
            def_cw = row.get("context_window") if row and row.get("context_window") else 1048576
            def_ep = row.get("effective_context_window_percent") if row and row.get("effective_context_window_percent") else 95
            def_ac = row.get("auto_compact_token_limit") if row and row.get("auto_compact_token_limit") is not None else ""
            cw_in = input(f"  上下文窗口 [默认 {def_cw}] ").strip()
            ep_in = input(f"  有效上下文百分比 [默认 {def_ep}] ").strip()
            ac_in = input(f"  自动压缩 token 阈值（回车=默认，按百分比触发）[当前 {def_ac}] ").strip()
            try:
                cw_v = int(def_cw) if not cw_in else int(cw_in)
            except ValueError:
                warn("上下文窗口必须是整数，已取消。")
                continue
            try:
                ep_v = int(def_ep) if not ep_in else int(ep_in)
            except ValueError:
                warn("百分比必须是整数，已取消。")
                continue
            if cw_v < 1000 or cw_v > 16777216 or ep_v < 1 or ep_v > 100:
                warn("数值超出合理范围（窗口 1000~16777216，百分比 1~100），已取消。")
                continue
            ac_v: int | None = None
            if ac_in:
                try:
                    ac_v = int(ac_in)
                except ValueError:
                    warn("压缩阈值必须是整数，已取消。")
                    continue
                if ac_v < 1000 or ac_v > cw_v:
                    warn(f"压缩阈值需在 1000~{cw_v} 之间，已取消。")
                    continue
            ac_txt = "默认" if ac_v is None else str(ac_v)
            if not confirm(f"  应用 {slug}：窗口 {cw_v} / 有效 {ep_v}% / 压缩 {ac_txt}? [y/N]"):
                dim("已取消。")
                continue
            try:
                service.set_model_params(prov, slug, cw_v, ep_v, ac_v)
            except ValueError as exc:
                err(str(exc))
                continue
            ok(f"已更新 {slug} 的参数（models.json + registry，重装也会保留）。")
            continue

        if opt == "5":
            if not current:
                warn("该 provider 还没有模型。")
                continue
            print(f"  开始探测 {len(current)} 个模型（每个最多 20 秒）...")
            usable, unusable, unknown = upstream.probe_models(current, prov.base_url, key)
            print("")
            print(f"  可用   : {' / '.join(usable) if usable else '(无)'}")
            if unusable:
                err(f"不可用 : {' / '.join(unusable)}")
            if unknown:
                warn(f"不确定 : {' / '.join(unknown)}")
            to_remove: list[str] = []
            if unusable:
                if confirm(f"移除 {len(unusable)} 个不可用模型（{' / '.join(unusable)}）?"):
                    to_remove.extend(unusable)
            if unknown:
                if confirm(f"另有 {len(unknown)} 个探测结果不确定（{' / '.join(unknown)}）也一并移除?"):
                    to_remove.extend(unknown)
            if not to_remove:
                dim("没有要移除的模型。")
                continue
            final5 = [s for s in current if s not in to_remove]
            try:
                service.update_provider_models(prov, current, final5)
            except ValueError as exc:
                err(str(exc))
                continue
            ok(f"已移除 {len(to_remove)} 个模型。")
            continue

        if opt == "7":
            if not pending_add and not pending_del:
                warn("没有待处理的变更。")
                continue
            fin: list[str] = list(current)
            for s in pending_add:
                if s not in fin:
                    fin.append(s)
            fin = [s for s in fin if s not in pending_del]
            st_model, st_prov = service.current_state()
            is_def_prov = st_prov == prov.id and st_model != "(未设置)"
            if is_def_prov and st_model not in fin:
                warn(f"默认模型 {st_model} 在移除之列，需要先选一个新的默认模型。")
                if not fin:
                    warn("剩余清单为空，无法继续。已取消。")
                    continue
                print("  在剩余模型中选择新的默认模型：")
                for i, s in enumerate(fin, 1):
                    print(f"     {i:2}) {s}")
                sel = read_choice_list(input("  编号（q=取消本次应用） "), len(fin))
                if sel is None or not sel:
                    continue
                new_default = fin[sel[0]]
                service.switch_default_model(new_default)
                try:
                    service.update_provider_models(prov, current, fin)
                except ValueError as exc:
                    err(str(exc))
                    continue
                ok(f"默认模型已切换为 {new_default}")
                return
            try:
                service.update_provider_models(prov, current, fin)
            except ValueError as exc:
                err(str(exc))
                continue
            ok(f"应用完成。默认模型仍为 {st_model}（如要切换请回主菜单）。")
            return

        bad += 1
        if bad >= 3:
            warn("连续输入无效，返回主菜单。")
            return
        warn("输入无效，请重新选择。")


def show_status(provider: Provider | None = None) -> None:
    st_model, st_prov = service.current_state()
    print("")
    if provider is None:
        head("当前状态")
        print(f"  默认模型        : {st_model}")
        print(f"  默认 Provider    : {st_prov}")
        ids = [p.get("id") or "" for p in service.installed_providers() if p.get("id")]
        print(f"  已接入 provider  : {' / '.join(ids) if ids else '(无)'}")
        print("")
        return
    head(f"当前状态（provider: {provider.id}）")
    print(f"  默认模型        : {st_model}")
    print(f"  默认 Provider    : {st_prov}")
    in_cfg = False
    cfg_path = paths.config_path()
    if cfg_path.exists():
        text = read_text(cfg_path)
        in_cfg = re.search(rf"(?m)^\[\s*model_providers\.{re.escape(provider.id)}\s*\]", text) is not None
    print(f"  [model_providers.{provider.id}] : {'已配置' if in_cfg else '未配置'}")
    in_models: list[str] = []
    data = read_json(paths.models_path())
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        all_slugs = [m.get("slug") for m in data["models"] if isinstance(m, dict)]
        in_models = [s for s in provider.models if s in all_slugs]
    print(f"  models.json 模型 : {' / '.join(in_models) if in_models else '未接入'}")
    ids = [p.get("id") or "" for p in service.installed_providers() if p.get("id")]
    print(f"  已接入 provider  : {' / '.join(ids) if ids else '(无)'}")
    if provider.use_env_key and provider.env_var_name:
        env_set = bool(os.environ.get(provider.env_var_name))
        print(f"  环境变量 {provider.env_var_name}      : {'已设置' if env_set else '未设置'}")
    backup_dir = paths.backup_dir(provider.id)
    print(f"  备份目录         : {backup_dir if backup_dir.exists() else '(无)'}")
    print(f"  配置路径         : {cfg_path}")
    print("")


def main_menu() -> None:
    global _active
    print("")
    print(_paint("35", "  ╔══════════════════════════════════════════╗"))
    print(_paint("35", "  ║   任意 Provider × Codex 一键接入/管理脚本  ║"))
    print(_paint("35", "  ║   最小侵入 · 可合并 · 可一键回退           ║"))
    print(_paint("35", "  ╚══════════════════════════════════════════╝"))
    print("")

    if not paths.codex_home().exists():
        warn(f"未找到 Codex 配置目录: {paths.codex_home()}")
        warn("请先安装并运行一次 Codex CLI / ChatGPT 桌面端 / VS Code Codex 插件")
        warn("（首次运行会自动创建该目录），或设置 CODEX_HOME 环境变量后重试。")
        print("      npm install -g @openai/codex")
        return

    bad_menu = 0
    while True:
        st_model, st_prov = service.current_state()
        print(_paint("36", "  ── 主菜单 ──────────────────────────────"))
        print(f"   当前 provider: {st_prov}  /  默认模型: {st_model}")
        print("    1) 接入/更新 provider（写入 config.toml + models.json，切为默认）")
        print("    2) 管理模型列表（从上游拉取候选：勾选接入/移除/手动输入）")
        print("    3) 切换默认模型")
        print("    4) 回退（恢复运行前原状）")
        print("    5) 查看当前状态")
        print("    6) 自测")
        print("    7) 退出")
        choice = input("  请输入 [1-7] ").strip()
        if choice == "7":
            print("  再见。")
            return

        if choice == "1":
            prov = choose_provider(allow_custom=True)
            if prov is None:
                continue
            _active = prov
            key = service.get_api_key(prov, interactive_prompt=lambda: prompt_api_key(prov))
            if not key:
                continue
            reg = registry.load(paths.registry_path())
            reg_providers = reg.get("providers") if reg and isinstance(reg.get("providers"), list) else []
            entry = next((rp for rp in reg_providers if isinstance(rp, dict) and rp.get("id") == prov.id), None)
            if entry is not None:
                if entry.get("meta_overrides"):
                    prov.meta_overrides = dict(entry["meta_overrides"])
                if confirm("该 provider 之前接入过。先从上游拉取候选模型并合并新增?"):
                    merged = service.sync_from_upstream(prov, key)
                    if merged:
                        prov.models = list(merged)
            service.install_provider(prov, key)
            continue

        if choice == "2":
            records = [p for p in service.installed_providers() if p.get("base_url") and p.get("id")]
            if not records:
                warn("没有已接入的 provider（先用菜单 1 接入一个）。")
                continue
            head("管理模型列表：选择 provider")
            for i, rec in enumerate(records, 1):
                shown = rec.get("name") or rec.get("id")
                mdl = f"，模型: {' / '.join(rec.get('models') or [])}" if rec.get("models") else ""
                print(f"   {i}) {shown}  ({rec.get('base_url')}{mdl})")
            print(f"   {len(records) + 1}) 返回")
            raw = input(f"  请输入 [1-{len(records) + 1}] ").strip()
            try:
                idx = int(raw)
            except ValueError:
                warn("输入无效。")
                continue
            if idx < 1 or idx > len(records) + 1:
                warn("输入无效。")
                continue
            if idx == len(records) + 1:
                continue
            manage_models(records[idx - 1])
            continue

        if choice == "3":
            if _active is None:
                prov = choose_provider(allow_custom=False)
                if prov is None:
                    continue
                _active = prov
            prov = _active
            if not prov.models:
                slugs = service.all_catalog_slugs()
                if not slugs:
                    warn("models.json 中没有任何模型，无法切换。")
                    continue
                head("选择默认模型（该 provider 无模型记录，直接输入已注册模型名）")
                dim(f"   已注册: {' / '.join(slugs)}")
                slug_in = input("   模型名 ").strip()
                if not slug_in or slug_in not in slugs:
                    warn("模型未在 models.json 注册，已取消。")
                    continue
                service.switch_default_model(slug_in)
                ok(f'config.toml 已更新: model = "{slug_in}"（其余配置未动）')
                continue
            head("选择默认模型（只改 config.toml 顶部的 model 一行）")
            for i, slug in enumerate(prov.models, 1):
                print(f"   {i}) {slug}")
            raw = input(f"  请输入 [1-{len(prov.models)}] ").strip()
            try:
                idx = int(raw)
            except ValueError:
                idx = 0
            if idx < 1 or idx > len(prov.models):
                warn("输入无效。")
                continue
            service.switch_default_model(prov.models[idx - 1])
            ok(f'config.toml 已更新: model = "{prov.models[idx - 1]}"（其余配置未动）')
            continue

        if choice == "4":
            if _active is None:
                prov = choose_provider(allow_custom=False)
                if prov is None:
                    continue
                _active = prov
            service.restore_provider(_active, confirm=lambda: confirm("确认回退? [y/N]"))
            continue

        if choice == "5":
            if _active is None:
                prov = choose_provider(allow_custom=False)
                if prov is None:
                    continue
                _active = prov
            show_status(_active)
            continue

        if choice == "6":
            warn("内置自测已迁移为 pytest：请运行 .\\.venv\\Scripts\\python.exe -m pytest")
            continue

        bad_menu += 1
        if bad_menu >= 3:
            warn("连续输入无效，退出。")
            return
        warn("输入无效，请重新选择。")
