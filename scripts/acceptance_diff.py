#!/usr/bin/env python3
"""P6 新旧并行验收：在隔离的临时 CODEX_HOME 上分别运行新 Python CLI 与旧 PowerShell 脚本，对比产物。

只使用 tempfile 临时目录，绝不触碰真实 ~/.codex，不持久化任何环境变量。
退出码：全 PASS=0，任一 DIFF=1（子进程失败也视为 1）。
"""
from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(r"E:\aiPic\codex-provider-setup")
PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"
PS1 = Path(r"E:\aiPic\setup-codex-provider.ps1")
PS1_TIMEOUT_S = 120

FILES = ("config.toml", "models.json", "providers-registry.json")

PASS = "PASS"
DIFF = "DIFF"
FAIL = "FAIL"


def decode_out(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def run_subprocess(cmd: list[str], env: dict[str, str], cwd: Path, timeout: int | None) -> tuple[int | None, str, str, str | None]:
    try:
        proc = subprocess.run(cmd, capture_output=True, env=env, cwd=str(cwd), timeout=timeout)
        return proc.returncode, decode_out(proc.stdout), decode_out(proc.stderr), None
    except subprocess.TimeoutExpired as exc:
        return None, decode_out(exc.stdout or b""), decode_out(exc.stderr or b""), f"超时 {timeout}s"


def build_env(tmp_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["CODEX_HOME"] = str(tmp_home)
    return env


def norm_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def compare_config(a: Path, b: Path, tmp_a: Path, tmp_b: Path) -> tuple[str, list[str]]:
    notes: list[str] = []
    ra = a.read_bytes()
    rb = b.read_bytes()
    if b"\r\n" in ra or b"\r\n" in rb:
        notes.append("检测到 CRLF，已归一化为 LF 再比")
    na, nb = norm_lf(ra), norm_lf(rb)
    if na == nb:
        return PASS, notes
    paths_a = {str(tmp_a), str(tmp_a).replace("\\", "/")}
    paths_b = {str(tmp_b), str(tmp_b).replace("\\", "/")}
    na2 = na
    nb2 = nb
    for p in paths_a:
        na2 = na2.replace(p.encode(), b"<CODEX_HOME>")
    for p in paths_b:
        nb2 = nb2.replace(p.encode(), b"<CODEX_HOME>")
    if na2 == nb2:
        notes.append("原始字节差异仅来自 model_catalog_json 中各自的 CODEX_HOME 绝对路径（tmpA/tmpB 不同属预期）；"
                     "将该路径归一化为 <CODEX_HOME> 后字节级一致")
        return PASS, notes
    return DIFF, notes


def _norm_meta_overrides(obj: object) -> object:
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for k, v in obj.items():
            if k == "meta_overrides" and (v is None or v == {}):
                out[k] = {}
            else:
                out[k] = _norm_meta_overrides(v)
        return out
    if isinstance(obj, list):
        return [_norm_meta_overrides(x) for x in obj]
    return obj


def semantic_json(path: Path) -> object:
    raw = path.read_bytes().decode("utf-8-sig", errors="replace")
    return _norm_meta_overrides(json.loads(raw))


def canonical_json_text(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def unified_diff(a_text: str, b_text: str, label_a: str, label_b: str, max_lines: int = 200) -> str:
    diff = difflib.unified_diff(
        a_text.splitlines(keepends=True),
        b_text.splitlines(keepends=True),
        fromfile=label_a,
        tofile=label_b,
    )
    lines = list(diff)
    if len(lines) > max_lines:
        return "".join(lines[:max_lines]) + f"\n...（diff 共 {len(lines)} 行，仅显示前 {max_lines} 行）\n"
    return "".join(lines)


def field_level_diff(label_a: str, va: object, label_b: str, vb: object) -> str:
    """对 JSON 做字段级摘要：定位哪些字段不同、两侧取值（截断显示）。"""
    out: list[str] = []

    def walk(path: str, va: object, vb: object, depth: int) -> None:
        if depth > 4:
            return
        if isinstance(va, dict) and isinstance(vb, dict):
            for k in sorted(set(va) | set(vb)):
                if k not in va:
                    out.append(f"{path}.{k}: 仅 {label_b} 侧有（{label_a} 无此项）")
                elif k not in vb:
                    out.append(f"{path}.{k}: 仅 {label_a} 侧有（{label_b} 无此项）")
                else:
                    walk(f"{path}.{k}", va[k], vb[k], depth + 1)
            return
        if isinstance(va, list) and isinstance(vb, list) and len(va) == len(vb):
            for i, (x, y) in enumerate(zip(va, vb)):
                walk(f"{path}[{i}]", x, y, depth + 1)
            return
        if va != vb:
            sa = json.dumps(va, ensure_ascii=False)
            sb = json.dumps(vb, ensure_ascii=False)
            out.append(f"{path}:\n    {label_a}: {sa[:200]}{'...' if len(sa) > 200 else ''}\n    {label_b}: {sb[:200]}{'...' if len(sb) > 200 else ''}")

    walk("$", va, vb, 0)
    return "\n".join(out)


def compare_json(name: str, a: Path, b: Path, tmp_a: Path, tmp_b: Path) -> tuple[str, str]:
    ja = semantic_json(a)
    jb = semantic_json(b)
    if ja == jb:
        return PASS, ""
    detail = field_level_diff(f"Python({tmp_a})", ja, f"PS1({tmp_b})", jb)
    diff = unified_diff(
        canonical_json_text(ja),
        canonical_json_text(jb),
        f"{name} (Python {tmp_a})",
        f"{name} (PS1 {tmp_b})",
    )
    return DIFF, detail + "\n\n--- difflib 全量差异 ---\n" + diff


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    print("=" * 70)
    print("P6 新旧并行验收：新 Python CLI vs 旧 PowerShell 脚本（隔离 CODEX_HOME）")
    print("=" * 70)

    tmp_root = tempfile.mkdtemp(prefix="codex-accept-")
    tmp_a = Path(tmp_root) / "tmpA"
    tmp_b = Path(tmp_root) / "tmpB"
    tmp_a.mkdir(exist_ok=True)
    tmp_b.mkdir(exist_ok=True)
    print(f"tmpA (新 Python CLI): {tmp_a}")
    print(f"tmpB (旧 PS1 脚本)  : {tmp_b}")

    # ---- 1) 新 Python CLI ----
    py_cmd = [
        str(PYTHON), "-m", "codex_provider", "install",
        "--provider-id", "deepseek",
        "--base-url", "https://api.deepseek.com/",
        "--api-key", "sk-x",
        "--model-slugs", "deepseek-v4-flash,deepseek-v4-pro",
    ]
    print("\n[1/2] 运行新 Python CLI ...")
    py_rc, py_out, py_err, py_tmo = run_subprocess(py_cmd, build_env(tmp_a), PROJECT, None)
    print(f"      返回码: {py_rc}（{py_tmo or '正常结束'}）")
    if py_tmo:
        print(f"      [X] {py_tmo}")
    if py_rc != 0:
        print(f"      [X] Python CLI 失败（rc={py_rc}）")
        print("      --- stdout ---")
        print(py_out)
        print("      --- stderr ---")
        print(py_err)
    else:
        print("      --- stdout（关键片段）---")
        for line in py_out.splitlines():
            if "[OK]" in line or "[!]" in line or "model" in line or "写入" in line or "接入完成" in line:
                print("      " + line)

    # ---- 2) 旧 PowerShell 脚本 ----
    ps_cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(PS1),
        "-ProviderId", "deepseek",
        "-BaseUrl", "https://api.deepseek.com/",
        "-ApiKey", "sk-x",
        "-ModelSlugs", "deepseek-v4-flash,deepseek-v4-pro",
    ]
    print(f"\n[2/2] 运行旧 PowerShell 脚本（超时 {PS1_TIMEOUT_S}s）...")
    ps_rc, ps_out, ps_err, ps_tmo = run_subprocess(ps_cmd, build_env(tmp_b), PROJECT, PS1_TIMEOUT_S)
    print(f"      返回码: {ps_rc}（{ps_tmo or '正常结束'}）")
    if ps_tmo:
        print(f"      [X] {ps_tmo}")
    if ps_rc != 0:
        print(f"      [X] PS1 失败（rc={ps_rc}）")
        print("      --- stdout ---")
        print(ps_out)
        print("      --- stderr ---")
        print(ps_err)
    else:
        print("      --- stdout（关键片段）---")
        for line in ps_out.splitlines():
            if "[OK]" in line or "[!]" in line or "model" in line or "写入" in line or "接入完成" in line:
                print("      " + line)

    if py_rc != 0 or ps_rc != 0:
        print("\n子进程失败，中止对比（以上 stdout/stderr 帮助定位）。")
        return 1

    # ---- 3) 产物对比 ----
    print("\n" + "=" * 70)
    print("产物对比")
    print("=" * 70)
    results: dict[str, tuple[str, str]] = {}
    for name in FILES:
        fa = tmp_a / name
        fb = tmp_b / name
        print(f"\n[{name}]")
        if not fa.exists() or not fb.exists():
            print(f"      [X] 产物缺失: tmpA={'存在' if fa.exists() else '缺失'} / tmpB={'存在' if fb.exists() else '缺失'}")
            results[name] = (FAIL, f"文件缺失: tmpA={'存在' if fa.exists() else '缺失'} / tmpB={'存在' if fb.exists() else '缺失'}")
            continue
        if name == "config.toml":
            status, notes = compare_config(fa, fb, tmp_a, tmp_b)
            for note in notes:
                print(f"      [i] {note}")
            if status == PASS:
                print(f"      [PASS] 字节级一致（LF + 末尾换行）")
            else:
                print(f"      [DIFF] 字节级不一致")
                print(unified_diff(fa.read_text(encoding="utf-8-sig"), fb.read_text(encoding="utf-8-sig"), f"config.toml (Python {tmp_a})", f"config.toml (PS1 {tmp_b})"))
            results[name] = (status, "\n".join(notes))
        else:
            try:
                status, detail = compare_json(name, fa, fb, tmp_a, tmp_b)
            except (ValueError, KeyError) as exc:
                print(f"      [FAIL] JSON 解析失败: {exc}")
                results[name] = (FAIL, str(exc))
                continue
            if status == PASS:
                print(f"      [PASS] 语义一致（json.loads 深度相等）")
            else:
                print(f"      [DIFF] 语义不一致，字段级定位：")
                print(detail)
            results[name] = (status, detail)

    # ---- 4) 汇总 ----
    print("\n" + "=" * 70)
    print("验收汇总")
    print("=" * 70)
    all_pass = True
    for name in FILES:
        status, _ = results[name]
        mark = "[PASS]" if status == PASS else "[DIFF]" if status == DIFF else "[FAIL]"
        print(f"  {mark} {name}")
        if status != PASS:
            all_pass = False
    print()
    if all_pass:
        print("结论: PASS —— 新 Python CLI 与旧 PowerShell 脚本产物一致。")
        print(f"临时目录保留以供查验: {tmp_root}")
        return 0
    print("结论: DIFF —— 存在差异，根因见上方报告（未修改任何共享代码，由主 agent 决策修复）。")
    print(f"临时目录保留以供查验: {tmp_root}")
    return 1


if __name__ == "__main__":
    sys.exit(main())