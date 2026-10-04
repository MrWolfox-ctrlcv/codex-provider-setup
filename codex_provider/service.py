from __future__ import annotations

import json
import os
import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Callable

from codex_provider import backup, catalog, env_os, paths, registry, toml_edit, upstream
from codex_provider import __version__ as SCRIPT_VERSION
from codex_provider.io_utils import (
    atomic_write,
    is_legal_model_slug,
    read_json,
    read_text,
    sanitize_ctrl,
)
from codex_provider.provider import Provider

Echo = Callable[[str], None]


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def current_state() -> tuple[str, str]:
    path = paths.config_path()
    model = "(未设置)"
    provider = "(未设置)"
    if path.exists():
        text = read_text(path)
        m = re.search(r'(?m)^model\s*=\s*"([^"]*)"', text)
        p = re.search(r'(?m)^model_provider\s*=\s*"([^"]*)"', text)
        if m:
            model = m.group(1)
        if p:
            provider = p.group(1)
    return model, provider


def all_catalog_slugs() -> list[str]:
    if not paths.models_path().exists():
        return []
    data = read_json(paths.models_path())
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        return [m.get("slug") for m in data["models"] if m.get("slug")]
    return []


def _scan_config_providers(config_path: Path) -> list[dict]:
    if not config_path.exists():
        return []
    text = read_text(config_path)
    pattern = re.compile(r"(?m)^\[\s*model_providers\.([^\]]+?)\s*\]")
    out: list[dict] = []
    for mm in pattern.finditer(text):
        pid = mm.group(1).strip()
        if not pid:
            continue
        block = text[mm.end() : pattern.search(text, mm.end()).start() if pattern.search(text, mm.end()) else len(text)]
        rec = {
            "id": pid,
            "name": "",
            "base_url": "",
            "wire_api": "",
            "env_key": "",
            "models": [],
            "vision": False,
            "reasoning_levels": [],
            "truncation_mode": "tokens",
            "apply_patch": False,
            "search": False,
            "disable_web_search": False,
            "meta_overrides": {},
        }
        for key, attr in (("name", "name"), ("base_url", "base_url"), ("wire_api", "wire_api"), ("env_key", "env_key")):
            m = re.search(rf'(?m)^{key}\s*=\s*"([^"]*)"', block)
            if m:
                rec[attr] = m.group(1)
        out.append(rec)
    return out


def installed_providers() -> list[dict]:
    merged = {p["id"]: p for p in _scan_config_providers(paths.config_path())}
    reg = registry.load(paths.registry_path())
    reg_providers = reg.get("providers") if reg and isinstance(reg.get("providers"), list) else []
    for rp in reg_providers:
        if not isinstance(rp, dict) or not rp.get("id"):
            continue
        pid = rp["id"]
        if pid in merged:
            for k in ("models", "vision", "reasoning_levels", "truncation_mode",
                      "apply_patch", "search", "disable_web_search", "meta_overrides"):
                if k in rp:
                    merged[pid][k] = rp[k]
        else:
            merged[pid] = dict(rp)
    return sorted(merged.values(), key=lambda p: p.get("id", ""))


def provider_from_installed(rec: dict) -> Provider:
    if not rec.get("base_url"):
        raise ValueError(f"已安装 provider '{rec['id']}' 在 config.toml 中缺少 base_url，无法重建")
    env_key = rec.get("env_key") or ""
    return Provider(
        id=rec["id"],
        name=rec.get("name") or rec["id"],
        base_url=rec["base_url"],
        key_prefix="sk-",
        env_var_name=env_key,
        use_env_key=bool(env_key),
        models=list(rec.get("models") or []),
        wire_api=rec.get("wire_api") or "responses",
        context_window=1048576,
        vision=bool(rec.get("vision")),
        instructions_mode="short",
        reasoning_levels=list(rec.get("reasoning_levels") or []),
        base_instructions=f"You are {rec['id']}, an AI assistant. Today's date: {{date}} {{week}}.",
        description=rec["id"],
        apply_patch_tool_type="freeform" if rec.get("apply_patch") else "",
        search_support=bool(rec.get("search")),
        support_verbosity=False,
        parallel_tool_calls=False,
        truncation_mode=rec.get("truncation_mode") or "tokens",
        disable_web_search=bool(rec.get("disable_web_search")),
        meta_overrides=dict(rec.get("meta_overrides") or {}),
    )


def get_api_key(provider: Provider, param_key: str = "", interactive_prompt: Callable[[], str] | None = None) -> str | None:
    if param_key:
        return param_key
    env_names = [provider.env_var_name] if provider.env_var_name else []
    env_names.append(provider.id.upper() + "_API_KEY")
    for name in env_names:
        v = os.environ.get(name)
        if v:
            return v.strip()
    if not provider.use_env_key and paths.config_path().exists():
        text = read_text(paths.config_path())
        body = toml_edit.provider_section_body(text, provider.id)
        if body:
            tk = re.search(r'(?m)^experimental_bearer_token\s*=\s*"([^"]*)"', body)
            if tk:
                return tk.group(1)
    if interactive_prompt is None:
        return None
    return interactive_prompt()


def stored_api_key(provider_id: str) -> str | None:
    """The bearer token currently persisted for ``provider_id``, if any."""
    path = paths.config_path()
    if not path.exists():
        return None
    body = toml_edit.provider_section_body(read_text(path), provider_id)
    if not body:
        return None
    tk = re.search(r'(?m)^experimental_bearer_token\s*=\s*"([^"]*)"', body)
    return tk.group(1) if tk else None


def prompt_new_api_key(provider: Provider, prompt: Callable[[], str]) -> str | None:
    """Always ask for a key, ignoring whatever is already stored.

    ``get_api_key`` intentionally prefers an existing credential so that
    re-installs stay non-interactive; that made it impossible to replace a
    revoked key.  Key rotation must bypass it entirely.
    """
    return prompt()


def update_api_key(provider: Provider, new_key: str, *, echo: Echo = print) -> None:
    """Replace a channel's credential in place, leaving everything else alone.

    Only the credential is touched: other providers, the user's own config
    sections and the model catalog are all preserved.
    """
    config_path = paths.config_path()
    if not config_path.exists():
        raise ValueError(f"找不到 {config_path}，无法更新 Key。")
    source = read_text(config_path)
    body = toml_edit.provider_section_body(source, provider.id)
    if not body:
        raise ValueError(f"config.toml 里没有 [model_providers.{provider.id}]，无法更新 Key。")

    new_key = sanitize_ctrl(new_key).strip()
    if not new_key:
        raise ValueError("新 Key 为空，未做任何修改。")

    if provider.use_env_key and provider.env_var_name:
        env_os.persist_env(provider.env_var_name, new_key)
        echo(f"[OK] 已更新环境变量 {provider.env_var_name}（新开终端生效）")
        echo("[i]  该渠道使用 env_key，config.toml 中不保存 Key，无需改写。")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.snapshot_files(
        paths.codex_home() / f"safety-{stamp}-key",
        [config_path],
        stamp=stamp,
    )

    new_text = toml_edit.set_bearer_token(source, provider.id, new_key)
    try:
        tomllib.loads(new_text)
    except Exception as exc:
        raise ValueError(f"改写后的 config.toml 未通过校验，已中止（原文件未改动）\n{exc}") from exc
    atomic_write(config_path, new_text, tmp_suffix=f".{provider.id}-key-tmp")
    echo("[OK] 已更新 config.toml 中的 experimental_bearer_token")
    echo(f"[i]  改动前副本：{paths.codex_home() / f'safety-{stamp}-key' / 'config.toml'}")


def remove_channel(provider_id: str, *, echo: Echo = print, confirm: Callable[[], bool] | None = None) -> None:
    """Remove exactly one channel and everything this tool registered for it.

    Unlike ``restore_provider`` (which rolls the whole config back to a
    pre-install snapshot and therefore also reverts unrelated providers and any
    later hand edits), this touches only the named channel.  The models it owns
    are dropped from the catalog, but models still referenced by another
    provider are kept.
    """
    config_path = paths.config_path()
    if not config_path.exists():
        raise ValueError(f"找不到 {config_path}，没有可删除的渠道。")
    source = read_text(config_path)
    if not toml_edit.provider_section_body(source, provider_id):
        raise ValueError(f"config.toml 里没有 [model_providers.{provider_id}]，无需删除。")

    rec = next((r for r in installed_providers() if r.get("id") == provider_id), None)
    own_models = list((rec or {}).get("models") or [])

    others_use: set[str] = set()
    for pr in installed_providers():
        if pr.get("id") != provider_id:
            others_use.update(pr.get("models") or [])
    removable = [s for s in own_models if s not in others_use]

    st_model, st_prov = current_state()
    is_default = st_prov == provider_id

    echo(f"将删除渠道 {provider_id}：")
    echo(f"  - 从 config.toml 移除 [model_providers.{provider_id}]")
    echo(f"  - 从 models.json 移除其独占模型 {len(removable)} 个"
         + (f"：{' / '.join(removable)}" if removable else "（无）"))
    if own_models and len(removable) < len(own_models):
        echo(f"  - 保留 {len(own_models) - len(removable)} 个被其它渠道共用的模型")
    echo(f"  - 从 providers-registry.json 移除该条目")
    if is_default:
        echo("  [!] 该渠道当前是默认 provider，删除后将回退到配置里的其它设置")
    if confirm is not None and not confirm():
        echo("[!] 已取消。")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safety = paths.codex_home() / f"safety-{stamp}-remove-{provider_id}"
    backup.snapshot_files(safety, [config_path, paths.models_path(), paths.registry_path()], stamp=stamp)
    echo(f"[i] 改动前副本：{safety}")

    new_text, removed = toml_edit.remove_provider_section(source, provider_id)
    if not removed:
        raise ValueError(f"未能定位 [model_providers.{provider_id}]，已中止（原文件未改动）。")
    try:
        tomllib.loads(new_text)
    except Exception as exc:
        raise ValueError(f"移除后的 config.toml 未通过校验，已中止（原文件未改动）\n{exc}") from exc
    atomic_write(config_path, new_text, tmp_suffix=f".{provider_id}-rm-tmp")

    if removable and paths.models_path().exists():
        data = read_json(paths.models_path())
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            keep = [m for m in data["models"] if m.get("slug") not in set(removable)]
            atomic_write(paths.models_path(), catalog.catalog_text(keep, True), tmp_suffix=".rm-tmp")

    reg = registry.load(paths.registry_path())
    if reg and isinstance(reg.get("providers"), list):
        kept = [p for p in reg["providers"] if p.get("id") != provider_id]
        if len(kept) != len(reg["providers"]):
            registry.dump(paths.registry_path(), kept)

    echo("[OK] 已删除该渠道（其它渠道与你的其它配置均未改动）。")


def merge_stale_models(provider: Provider, current: list[str], upstream_models: list[str]) -> list[str]:
    """Models this channel has registered but upstream no longer offers."""
    up = set(upstream_models)
    return [s for s in current if s not in up]


def _registry_entry(provider: Provider, models: list[str] | None = None) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "wire_api": provider.wire_api,
        "env_key": provider.env_var_name,
        "models": list(provider.models if models is None else models),
        "vision": provider.vision,
        "reasoning_levels": list(provider.reasoning_levels),
        "truncation_mode": provider.truncation_mode,
        "apply_patch": provider.apply_patch_tool_type == "freeform",
        "search": provider.search_support,
        "disable_web_search": provider.disable_web_search,
        "meta_overrides": provider.meta_overrides,
    }


def install_provider(
    provider: Provider,
    api_key: str,
    *,
    reasoning_effort: str | None = None,
    in_selftest: bool = False,
    echo: Echo = print,
) -> None:
    # An explicit argument wins; otherwise honour the value collected by the
    # wizard/CLI on the provider itself. Previously this defaulted to "high"
    # unconditionally, silently discarding the user's answer.
    if reasoning_effort is None:
        reasoning_effort = provider.reasoning_effort or "high"
    if not paths.codex_home().exists():
        raise SystemExit(
            f"未找到 Codex 配置目录: {paths.codex_home()}\n"
            "请先安装并运行一次 Codex CLI / ChatGPT 桌面端 / VS Code Codex 插件"
            "（首次运行会自动创建该目录），或设置 CODEX_HOME 环境变量后重试。"
        )
    config_path = paths.config_path()
    models_path = paths.models_path()
    backup_dir = paths.backup_dir(provider.id)

    # Keys copied from a web console can carry invisible control characters;
    # clean once so the TOML value and the persisted env var stay identical.
    api_key = sanitize_ctrl(api_key)

    orig_config_existed = config_path.exists()
    orig_models_existed = models_path.exists()
    backed_cfg, backed_mdl = backup.backup_config_and_models(backup_dir, config_path, models_path)
    if backed_cfg:
        echo(f"[OK] 已备份 config.toml -> {backup_dir / 'config.toml'}")
    elif not orig_config_existed:
        echo("[!]  config.toml 不存在，将新建")
    if backed_mdl:
        echo(f"[OK] 已备份 models.json -> {backup_dir / 'models.json'}")

    model_slug = provider.models[0]
    existing: list[dict] = []
    had_existing = False
    if models_path.exists():
        data = read_json(models_path)
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            existing = data["models"]
            had_existing = True
        else:
            raise ValueError(f"已有 {models_path} 但解析失败，为保护你的数据已中止")
    merged, replaced = catalog.merge_catalog(existing, provider)
    if replaced:
        echo(f"已用最新预设刷新 {replaced} 个同名模型条目")

    cfg = toml_edit.edit_config(
        source=read_text(config_path) if config_path.exists() else "",
        provider_id=provider.id,
        base_url=provider.base_url,
        wire_api=provider.wire_api,
        use_env_key=provider.use_env_key,
        env_var_name=provider.env_var_name,
        api_key_value=api_key,
        model_slug=model_slug,
        reasoning_effort=reasoning_effort,
        catalog_value=paths.catalog_value(),
        disable_web_search=provider.disable_web_search,
    )

    try:
        parsed = json.loads(catalog.catalog_text(merged, had_existing))
        slugs = [m.get("slug") for m in parsed["models"]]
        if model_slug not in slugs:
            raise ValueError(f"models.json 必须包含 {model_slug}")
    except Exception as exc:
        raise ValueError(f"生成的 models.json 未通过校验，已中止（原文件未改动）\n{exc}") from exc
    try:
        tomllib.loads(cfg.text)
    except Exception as exc:
        raise ValueError(f"生成的 config.toml 未通过校验，已中止（原文件未改动）\n{exc}") from exc

    atomic_write(models_path, catalog.catalog_text(merged, had_existing), tmp_suffix=f".{provider.id}-tmp")
    atomic_write(config_path, cfg.text, tmp_suffix=f".{provider.id}-tmp")

    if provider.use_env_key and not in_selftest:
        env_os.persist_env(provider.env_var_name, api_key)
        echo(f"[OK] 已设置用户环境变量 {provider.env_var_name}（新开终端生效）")

    backup.write_manifest(
        backup_dir,
        {
            "script_version": SCRIPT_VERSION,
            "provider_id": provider.id,
            "installed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "original_config_existed": "1" if orig_config_existed else "0",
            "models_json_existed": "1" if orig_models_existed else "0",
            "env_key_used": "1" if provider.use_env_key else "0",
            "env_var_name": provider.env_var_name,
            "default_model": model_slug,
            "base_url": provider.base_url,
            "catalog_value": paths.catalog_value(),
        },
        cfg.report,
    )

    reg = registry.load(paths.registry_path())
    providers = reg.get("providers") if reg and isinstance(reg.get("providers"), list) else []
    providers = registry.upsert(providers, _registry_entry(provider))
    registry.dump(paths.registry_path(), providers)

    echo(f"[OK] 已写入 {models_path}（追加模型: {' / '.join(provider.models)}）")
    echo(f"[OK] 已更新 {config_path}")
    if cfg.report:
        echo(f"对既有配置的改动（共 {len(cfg.report)} 项）")
        for r in cfg.report:
            echo(f"  - {r}")
    echo("已写入配置")
    echo(f"  model                  = \"{model_slug}\"")
    echo(f"  model_provider         = \"{provider.id}\"")
    echo('  preferred_auth_method  = "apikey"')
    echo('  forced_login_method    = "api"')
    echo(f"  model_reasoning_effort = \"{reasoning_effort}\"")
    echo(f"  model_catalog_json     = \"{paths.catalog_value()}\"")
    echo(f"  [model_providers.{provider.id}]")
    echo(f"  base_url  = \"{provider.base_url}\"")
    echo(f"  wire_api  = \"{provider.wire_api}\"")
    echo("[OK] 接入完成。")
    echo("[!]  请新开一个终端后运行 codex 生效（环境变量需新会话读取）。")


def switch_default_model(slug: str) -> None:
    slug = (slug or "").strip()
    if not is_legal_model_slug(slug):
        raise ValueError(f"模型名不合法：{slug!r}（不能含引号或空白字符）")
    path = paths.config_path()
    source = read_text(path) if path.exists() else ""
    new_text = toml_edit.switch_model(source, slug)
    try:
        tomllib.loads(new_text)
    except Exception as exc:
        raise ValueError(f"改写后的 config.toml 未通过校验，已中止（原文件未改动）\n{exc}") from exc
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup.snapshot_files(
            paths.codex_home() / f"safety-{stamp}-switch",
            [path],
            stamp=stamp,
        )
    atomic_write(path, new_text, tmp_suffix=".switch-tmp")


def restore_impact(provider_id: str) -> list[str]:
    """Other channels a full snapshot restore would also roll back."""
    config_path = paths.config_path()
    if not config_path.exists():
        return []
    source = read_text(config_path)
    affected: list[str] = []
    for rec in installed_providers():
        pid = rec.get("id")
        if not pid or pid == provider_id:
            continue
        if toml_edit.provider_section_body(source, pid):
            affected.append(pid)
    return affected


def restore_provider(provider: Provider, *, echo: Echo = print, confirm: Callable[[], bool] | None = None) -> None:
    backup_dir = paths.backup_dir(provider.id)
    if not backup_dir.exists():
        echo(f"[!] 未找到备份目录 {backup_dir}，没有可回退的内容。")
        echo("    如需只移除该渠道，请改用「删除渠道」。")
        return
    has_bak_config = (backup_dir / "config.toml").exists()
    has_bak_models = (backup_dir / "models.json").exists()
    others = restore_impact(provider.id)
    echo(f"回退到运行本脚本前的状态（provider: {provider.id}）")
    echo(f"  - {'恢复 config.toml' if has_bak_config else '删除 config.toml'}")
    echo(f"  - {'恢复 models.json' if has_bak_models else '删除 models.json'}")
    echo("  - 删除备份目录")
    if others:
        echo("")
        echo("[!]  注意：该快照早于其它渠道的接入，本次回退会一并影响：")
        echo(f"     {' / '.join(others)}")
        echo("     以及安装之后你对 config.toml 的任何手改。")
        echo("     若只想移除这一个渠道，请改用「删除渠道」（不动其它渠道）。")
    if confirm is not None and not confirm():
        echo("[!] 已取消。")
        return
    if others:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = paths.codex_home() / f"safety-{stamp}-restore-{provider.id}"
        backup.snapshot_files(
            safety,
            [paths.config_path(), paths.models_path(), paths.registry_path()],
            stamp=stamp,
        )
        echo(f"[i] 回退前副本：{safety}")
    backup.restore(
        backup_dir,
        paths.config_path(),
        paths.models_path(),
        remove_env=env_os.remove_env,
    )
    echo("[OK] 已回退：config.toml / models.json 恢复为运行本脚本前的状态，备份目录已清理。")


def update_provider_models(provider: Provider, current: list[str], final: list[str], *, echo: Echo = print) -> None:
    cur = _uniq(current)
    fin = _uniq(final)
    add = [x for x in fin if x not in cur]
    del_ = [x for x in cur if x not in fin]
    if not add and not del_:
        echo("模型清单无变化，跳过写盘。")
        return

    st_model, st_provider = current_state()
    is_def = st_provider == provider.id and st_model != "(未设置)"
    if is_def and st_model in del_:
        raise ValueError(
            f"默认模型 \"{st_model}\" 正在被移除，但它仍被 config.toml 的 model_provider={provider.id} 引用。"
            "请先改默认模型再移除。"
        )
    if is_def and not fin:
        raise ValueError("不能把当前默认 provider 的模型清单清空：config.toml 需要一个可用的默认模型。")

    others_use: set[str] = set()
    for pr in installed_providers():
        if pr.get("id") != provider.id:
            others_use.update(pr.get("models") or [])
    removable = [s for s in del_ if s not in others_use]

    had_file = paths.models_path().exists()
    catalog_list: list[dict] = []
    if had_file:
        data = read_json(paths.models_path())
        if not (isinstance(data, dict) and isinstance(data.get("models"), list)):
            raise ValueError(f"读取 {paths.models_path()} 失败，已中止（未改动任何文件）")
        catalog_list = data["models"]
    existing_slugs = [m.get("slug") for m in catalog_list]
    keep = [m for m in catalog_list if m.get("slug") not in removable]

    max_p = 0
    for m in keep:
        pv = m.get("priority")
        if isinstance(pv, (int, float)) and not isinstance(pv, bool) and int(pv) > max_p:
            max_p = int(pv)

    created = 0
    existed = 0
    for s in add:
        if s in existing_slugs:
            existed += 1
            continue
        clone = provider.clone([s])
        if not clone.reasoning_levels:
            clone.reasoning_levels = ["none", "high"]
        meta = catalog.build_model_metadata(clone, 0)
        max_p += 1
        meta["priority"] = max_p
        keep.append(meta)
        created += 1

    text = json.dumps({"models": keep}, ensure_ascii=False)
    if had_file:
        text += "\r\n"
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise ValueError("生成的 models.json 未通过校验，已中止（未改动任何文件）") from exc
    if fin and not any(m.get("slug") == fin[0] for m in parsed["models"]):
        raise ValueError(f"生成的 models.json 缺少模型 {fin[0]}，已中止（未改动任何文件）")
    atomic_write(paths.models_path(), text, tmp_suffix=".mng-tmp")

    reg = registry.load(paths.registry_path())
    providers = reg.get("providers") if reg and isinstance(reg.get("providers"), list) else []
    providers = registry.upsert(providers, _registry_entry(provider, models=fin))
    registry.dump(paths.registry_path(), providers)

    echo("模型列表变更已写盘")
    echo(f"[OK] 新增接入: {' / '.join(add) if add else '(无)'}")
    echo(f"[OK] 移除: {' / '.join(del_) if del_ else '(无)'}")
    if created:
        echo(f"已为 {created} 个新模型生成目录条目（元数据沿用该 provider 的设置）")
    if existed:
        echo(f"{existed} 个新模型在 models.json 中已有条目，保留原条目未覆盖。")
    if len(removable) < len(del_):
        echo("部分被移除的模型仍被其它 provider 使用，目录条目予以保留。")
    echo(f"registry 现记录 {len(fin)} 个模型：{' / '.join(fin)}")


def set_model_params(provider: Provider, slug: str, context_window: int, eff_percent: int, compact_limit: int | None) -> None:
    mpath = paths.models_path()
    if not mpath.exists():
        raise ValueError("models.json 不存在，无法设置模型参数。")
    data = read_json(mpath)
    if not (isinstance(data, dict) and isinstance(data.get("models"), list)):
        raise ValueError("读取 models.json 失败，已中止（未改动任何文件）")
    found = False
    for m in data["models"]:
        if m.get("slug") == slug:
            m["context_window"] = context_window
            m["max_context_window"] = context_window
            m["effective_context_window_percent"] = eff_percent
            m["auto_compact_token_limit"] = compact_limit
            found = True
    if not found:
        raise ValueError(f"models.json 中没有模型 {slug}，无法设置参数（未改动任何文件）。")
    text = json.dumps({"models": data["models"]}, ensure_ascii=False) + "\r\n"
    try:
        json.loads(text)
    except ValueError as exc:
        raise ValueError("生成的 models.json 未通过校验，已中止（未改动任何文件）") from exc
    atomic_write(mpath, text, tmp_suffix=".prm-tmp")

    reg = registry.load(paths.registry_path())
    providers = reg.get("providers") if reg and isinstance(reg.get("providers"), list) else []
    overrides = {slug: {"context_window": context_window, "effective_context_window_percent": eff_percent}}
    if compact_limit is not None:
        overrides[slug]["auto_compact_token_limit"] = compact_limit
    providers = registry.set_meta_override(providers, provider.id, slug, overrides[slug])
    registry.dump(paths.registry_path(), providers)


def sync_from_upstream(provider: Provider, api_key: str, *, echo: Echo = print) -> list[str] | None:
    reg = registry.load(paths.registry_path())
    base: list[str] = []
    if reg and isinstance(reg.get("providers"), list):
        for rp in reg["providers"]:
            if rp.get("id") == provider.id and isinstance(rp.get("models"), list) and rp["models"]:
                base = list(rp["models"])
                break
    if not base:
        base = list(provider.models)
    fetch = upstream.fetch_models(provider.base_url, api_key)
    if not fetch["ok"]:
        echo(f"[!] 拉取上游模型列表失败（{fetch['error']}）。")
        return None
    up = fetch["models"]
    if not up:
        echo("[!] 上游返回了空模型列表，已放弃同步。")
        return None
    added = [s for s in up if s not in base]
    if not added:
        echo(f"[OK] 上游候选与本地清单一致，无新增模型（共 {len(up)} 个）。")
        return None
    echo(f"[OK] 上游有 {len(added)} 个本地未接入的新模型：{' / '.join(added)}")
    final = base + added
    update_provider_models(provider, base, final, echo=echo)
    echo(f"[OK] 模型清单已更新为 {len(final)} 个（默认模型未变）。")
    return final


def prune_unusable(provider: Provider, api_key: str, *, echo: Echo = print) -> None:
    cur = _uniq(provider.models)
    if not cur:
        raise ValueError(f"provider '{provider.id}' 没有已注册模型，无需清理。")
    echo(f"开始探测 {len(cur)} 个模型（每个最多 20 秒，端点按 wire_api={provider.wire_api}）...")
    usable, unusable, unknown = upstream.probe_models(
        cur,
        provider.base_url,
        api_key,
        on_result=lambda slug, ok, cat, detail: echo(
            f"  探测 {slug}: {'可用' if ok else ('[X] 不可用' if cat == 'unusable' else '[?] 不确定')}（{detail}）"
        ),
        wire_api=provider.wire_api,
    )
    echo(f"  可用   : {' / '.join(usable) if usable else '(无)'}")
    if unusable:
        echo(f"  不可用 : {' / '.join(unusable)}")
    if unknown:
        echo(f"  不确定 : {' / '.join(unknown)}")
    if not unusable:
        echo("[OK] 没有发现不可用模型，无需清理。")
        return
    final = [s for s in cur if s not in unusable]
    update_provider_models(provider, cur, final, echo=echo)
    echo(f"[OK] 已移除 {len(unusable)} 个不可用模型（不确定的模型未自动删除）。")
