from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from codex_provider import paths
from codex_provider.io_utils import read_json, read_text

# Desktop Codex is an Electron app: it caches the model list / provider display
# in these files and only re-derives them on a clean start.  After this script
# rewrites config.toml the app can keep showing the old model, so diagnosing
# and clearing this state is the documented fix.
UI_STATE_NAME = ".codex-global-state.json"
UI_STATE_SUFFIX = ".codex-global-state.json"

CODEX_PROCESS_HINTS = ("codex", "chatgpt")

# Small state-bearing entries inside the Electron user-data dir.  Everything
# else there (Cache, GPUCache, Code Cache, ...) is regenerated automatically and
# is far too large to relocate into a backup folder.
WEB_STATE_NAMES = (
    "Local Storage",
    "Session Storage",
    "Preferences",
    "Local State",
    "Network Persistent State",
)


@dataclass
class Finding:
    level: str  # "ok" | "warn" | "bad"
    title: str
    detail: str = ""
    fix: str = ""


@dataclass
class Diagnosis:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, title: str, detail: str = "", fix: str = "") -> None:
        self.findings.append(Finding(level, title, detail, fix))

    @property
    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.level in ("warn", "bad")]

    @property
    def ok(self) -> bool:
        return not any(f.level == "bad" for f in self.findings)


def ui_state_files() -> list[Path]:
    """Files the desktop app caches its UI/model state in (existing ones only)."""
    home = paths.codex_home()
    out: list[Path] = []
    if not home.exists():
        return out
    for entry in sorted(home.iterdir()):
        name = entry.name
        if not entry.is_file():
            continue
        if name == UI_STATE_NAME or name == UI_STATE_NAME + ".bak":
            out.append(entry)
        elif UI_STATE_SUFFIX in name and ".tmp-" in name:
            # stray temp files left behind by the app, e.g.
            # "..codex-global-state.json.tmp-1788...-<uuid>"
            out.append(entry)
    return out


def desktop_web_dir() -> Path:
    """Chromium (Electron) user-data dir of the desktop app."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Codex" / "web"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Codex" / "web"
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "Codex" / "web"


def find_codex_processes() -> list[str]:
    """Names of running Codex/ChatGPT processes (best effort, never raises)."""
    try:
        if sys.platform == "win32":
            proc = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            names = re.findall(r'^"([^"]+)"', proc.stdout, re.MULTILINE)
        else:
            proc = subprocess.run(
                ["ps", "-A", "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=15,
            )
            names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except Exception:
        return []
    seen: list[str] = []
    for name in names:
        low = name.lower()
        if any(hint in low for hint in CODEX_PROCESS_HINTS):
            # never report this diagnostic tool itself
            if "provider-setup" in low:
                continue
            if name not in seen:
                seen.append(name)
    return seen


def process_check_available() -> bool:
    """Whether the process probe actually ran.

    ``find_codex_processes`` returns an empty list both when nothing is running
    and when the probe could not run at all (missing tasklist/ps).  Callers that
    move live state files must tell those apart.
    """
    try:
        if sys.platform == "win32":
            proc = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15
            )
        else:
            proc = subprocess.run(
                ["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=15
            )
        return proc.returncode == 0
    except Exception:
        return False


def _parse_config() -> tuple[dict | None, str | None]:
    path = paths.config_path()
    if not path.exists():
        return None, f"找不到 {path}"
    try:
        return tomllib.loads(read_text(path)), None
    except Exception as exc:  # noqa: BLE001 - report parse failure as a finding
        return None, str(exc)


def diagnose(provider_id: str | None = None) -> Diagnosis:
    """Check everything that can stop Codex from showing a freshly added provider."""
    d = Diagnosis()
    home = paths.codex_home()

    if not home.exists():
        d.add("bad", "找不到 Codex 配置目录", str(home), "先安装并运行一次 Codex（CLI 或桌面端）")
        return d

    cfg, cfg_err = _parse_config()
    if cfg is None:
        d.add("bad", "config.toml 无法解析", cfg_err or "", "检查 config.toml 语法，或从备份恢复")
        return d

    model = str(cfg.get("model") or "")
    provider = str(cfg.get("model_provider") or "")
    d.add("ok", "config.toml 解析正常", str(paths.config_path()))
    if model:
        d.add("ok", f"当前默认模型: {model}")
    else:
        d.add("bad", "config.toml 顶部缺少 model", f"provider={provider or '(未设置)'}")
    if provider:
        d.add("ok", f"当前默认 provider: {provider}")
    else:
        d.add("bad", "config.toml 顶部缺少 model_provider")

    target = provider_id or provider
    providers = cfg.get("model_providers")
    providers = providers if isinstance(providers, dict) else {}
    if target:
        section = providers.get(target)
        if not isinstance(section, dict):
            d.add(
                "bad",
                f"config.toml 里没有 [model_providers.{target}]",
                "",
                "重新运行本程序接入一次",
            )
        else:
            base_url = str(section.get("base_url") or "")
            wire = str(section.get("wire_api") or "")
            has_key = bool(section.get("experimental_bearer_token") or section.get("env_key"))
            d.add("ok", f"[model_providers.{target}] 已配置", f"base_url={base_url} wire_api={wire or '(缺省)'}")
            if not has_key:
                d.add("warn", f"[model_providers.{target}] 没有凭据", "", "重新运行本程序并输入 API Key")
            if section.get("env_key"):
                env_name = str(section.get("env_key"))
                if not os.environ.get(env_name):
                    d.add(
                        "warn",
                        f"环境变量 {env_name} 在当前会话未设置",
                        "新终端才会读到；Codex 桌面端需要重启",
                    )

    catalog_raw = str(cfg.get("model_catalog_json") or "")
    if not catalog_raw:
        d.add("warn", "config.toml 未设置 model_catalog_json", "", "重新运行本程序接入一次")
    else:
        catalog_path = Path(catalog_raw)
        if not catalog_path.is_absolute():
            d.add(
                "bad",
                "model_catalog_json 是相对路径",
                catalog_raw,
                "桌面端按自己的 CWD 解析相对路径会读不到模型列表，需改成绝对路径（本程序会写绝对路径）",
            )
        elif not catalog_path.exists():
            d.add("bad", "model_catalog_json 指向的文件不存在", catalog_raw)
        else:
            d.add("ok", "model_catalog_json 是绝对路径且存在", catalog_raw)
            data = read_json(catalog_path)
            if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                d.add("bad", "模型目录文件解析失败", catalog_raw)
            else:
                slugs = [m.get("slug") for m in data["models"] if isinstance(m, dict)]
                named = [s for s in slugs if s]
                d.add("ok", f"模型目录内有 {len(named)} 个模型条目")
                if model and model not in slugs:
                    d.add(
                        "bad",
                        f"模型目录里没有默认模型 {model}",
                        "Codex 会因此回退到内置模型列表",
                        "重新运行本程序接入一次，或检查模型名是否正确",
                    )
                elif model:
                    d.add("ok", f"模型目录包含默认模型 {model}")

    procs = find_codex_processes()
    if procs:
        d.add(
            "warn",
            "Codex / ChatGPT 正在运行",
            " / ".join(procs),
            "接入前后请完全退出（含托盘图标），否则应用退出时可能把 config.toml 覆盖回去",
        )
    else:
        d.add("ok", "没有检测到运行中的 Codex 进程")

    ui_files = ui_state_files()
    if ui_files:
        d.add(
            "warn",
            "检测到桌面端 UI 状态缓存",
            " / ".join(p.name for p in ui_files),
            "桌面端会把模型列表/provider 显示缓存在这里，改完配置需清缓存后重启才会刷新（本程序可自动清）",
        )
    else:
        d.add("ok", "没有桌面端 UI 状态缓存")

    web = desktop_web_dir()
    if web.exists():
        d.add(
            "warn",
            "检测到桌面端 Chromium 数据目录",
            str(web),
            "若清缓存+重启后仍不刷新，可让本程序把它改名备份后重启应用",
        )

    return d


def ui_state_backups() -> list[Path]:
    """Existing backup-ui-state-* folders, newest first."""
    home = paths.codex_home()
    if not home.exists():
        return []
    found = [p for p in home.glob("backup-ui-state-*") if p.is_dir()]
    return sorted(found, key=lambda p: p.name, reverse=True)


def restore_ui_state(
    backup_dir: Path | None = None,
    *,
    stamp: str | None = None,
) -> dict:
    """Merge a previous UI-state backup back into the live state file.

    Only keys that are missing from the current file are added back, so
    anything Codex wrote after the reset wins.  The current file is backed up
    first, which keeps this operation reversible.
    """
    home = paths.codex_home()
    live = home / UI_STATE_NAME
    backups = ui_state_backups()
    if backup_dir is None:
        if not backups:
            return {"restored_keys": [], "backup_of_current": None, "source": None, "errors": ["没有可用的 backup-ui-state-* 备份"]}
        backup_dir = backups[0]

    src = backup_dir / UI_STATE_NAME
    if not src.exists():
        return {
            "restored_keys": [],
            "backup_of_current": None,
            "source": None,
            "errors": [f"{backup_dir} 里没有 {UI_STATE_NAME}"],
        }

    try:
        backup_data = json.loads(src.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        return {"restored_keys": [], "backup_of_current": None, "source": None, "errors": [f"备份无法解析: {exc}"]}
    if not isinstance(backup_data, dict):
        return {"restored_keys": [], "backup_of_current": None, "source": None, "errors": ["备份内容不是 JSON 对象"]}

    current: dict = {}
    if live.exists():
        try:
            loaded = json.loads(live.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                current = loaded
        except Exception:
            current = {}

    restored = [k for k in backup_data if k not in current]
    merged = dict(current)
    for k in restored:
        merged[k] = backup_data[k]

    ts = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    saved_current: Path | None = None
    if live.exists():
        saved_current = home / f"backup-ui-state-{ts}-prerestore"
        try:
            saved_current.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, saved_current / UI_STATE_NAME)
        except Exception as exc:  # noqa: BLE001
            return {
                "restored_keys": [],
                "backup_of_current": None,
                "source": src,
                "errors": [f"无法备份当前状态，已中止: {exc}"],
            }

    try:
        live.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"restored_keys": [], "backup_of_current": saved_current, "source": src, "errors": [f"写入失败: {exc}"]}

    return {
        "restored_keys": restored,
        "backup_of_current": saved_current,
        "source": src,
        "errors": [],
    }


def reset_ui_state(*, include_web: bool = False, stamp: str | None = None) -> dict:
    """Move cached desktop UI state aside so Codex re-derives model list/provider.

    Everything is renamed into a backup folder (never deleted), so the operation
    is reversible.  For the Chromium user-data directory only the small state
    databases are moved: relocating the whole profile used to drag tens of
    gigabytes of Cache/GPUCache into the backup folder, and ``--restore-ui``
    could not put it back.
    """
    home = paths.codex_home()
    ts = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = home / f"backup-ui-state-{ts}"
    moved: list[str] = []
    errors: list[str] = []

    targets = [p for p in ui_state_files() if p.is_file()]
    web_state_files: list[Path] = []
    web = desktop_web_dir()
    if include_web and web.exists():
        for name in WEB_STATE_NAMES:
            candidate = web / name
            if candidate.exists():
                web_state_files.append(candidate)
        for pattern in ("Local Storage", "Session Storage"):
            sub = web / pattern
            if sub.is_dir():
                web_state_files.append(sub)

    if not targets and not web_state_files:
        return {"backup_dir": None, "moved": [], "errors": []}

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {"backup_dir": None, "moved": [], "errors": [f"无法创建备份目录: {exc}"]}

    for path in targets + web_state_files:
        # Keep the web files in a subfolder so a restore can tell them apart.
        try:
            is_web = web in path.parents or path.parent == web
        except (TypeError, ValueError):
            is_web = False
        dest_dir = (backup_dir / "web") if is_web else backup_dir
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: {exc}")
            continue
        dest = dest_dir / path.name
        try:
            if path.is_dir():
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(path), str(dest))
            else:
                if dest.exists():
                    dest.unlink()
                shutil.move(str(path), str(dest))
            moved.append(path.name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: {exc}")

    return {"backup_dir": backup_dir, "moved": moved, "errors": errors}
