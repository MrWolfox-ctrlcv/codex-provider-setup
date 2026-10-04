from __future__ import annotations

import re
from dataclasses import dataclass

from codex_provider.io_utils import toml_quote

TARGET_KEYS = (
    "model",
    "model_provider",
    "preferred_auth_method",
    "forced_login_method",
    "model_reasoning_effort",
    "model_catalog_json",
)

DEL_A = {
    "profile": "masks model / model_provider / model_catalog_json, rejected by this version",
    "oss_provider": "alternate provider selector that would redirect requests",
    "openai_base_url": "global base_url override that would hijack requests",
}

DEL_B = {
    "model_context_window": "overrides the 1M window from models.json",
    "model_auto_compact_token_limit": "overrides auto-compaction trigger",
    "model_auto_compact_token_limit_scope": "overrides auto-compaction trigger",
    "base_instructions": "overrides base_instructions from models.json",
    "model_instructions_file": "overrides base_instructions from models.json",
    "compact_prompt": "overrides the compaction prompt",
    "experimental_compact_prompt_file": "overrides the compaction prompt",
    "service_tier": "stale value may cause a 400",
    "model_verbosity": "stale value may be unsupported",
    "model_reasoning_summary": "stale value would send reasoning.summary",
    "plan_mode_reasoning_effort": "may be unsupported by this model",
    "experimental_use_unified_exec_tool": "conflicts with shell_type=shell_command",
}

WARN_KEYS = (
    "review_model",
    "experimental_thread_config_endpoint",
    "experimental_thread_store_endpoint",
    "experimental_thread_store",
)


class _ScanState:
    __slots__ = ("depth", "mlstate")

    def __init__(self) -> None:
        self.depth = 0
        self.mlstate = ""

    def scan(self, line: str) -> None:
        n = len(line)
        i = 0
        instr = ""
        while i < n:
            c = line[i]
            c3 = line[i : i + 3]
            if self.mlstate:
                if self.mlstate == "basic" and c3 == '"""':
                    self.mlstate = ""
                    i += 3
                    continue
                if self.mlstate == "literal" and c3 == "'''":
                    self.mlstate = ""
                    i += 3
                    continue
                if self.mlstate == "basic" and c == "\\":
                    i += 2
                    continue
                i += 1
                continue
            if instr:
                if instr == "basic":
                    if c == "\\":
                        i += 2
                        continue
                    if c == '"':
                        instr = ""
                else:
                    if c == "'":
                        instr = ""
                i += 1
                continue
            if c3 == '"""':
                self.mlstate = "basic"
                i += 3
                continue
            if c3 == "'''":
                self.mlstate = "literal"
                i += 3
                continue
            if c == "#":
                return
            if c == '"':
                instr = "basic"
            elif c == "'":
                instr = "literal"
            elif c == "[":
                self.depth += 1
            elif c == "]":
                if self.depth > 0:
                    self.depth -= 1
            i += 1


def _key_of(line: str) -> str:
    l = line.strip()
    if not l or l.startswith("#"):
        return ""
    eq = l.find("=")
    if eq < 1:
        return ""
    return l[:eq].strip().strip('"').strip("'")


def _value_of(line: str) -> str:
    l = line.strip()
    eq = l.find("=")
    if eq < 0:
        return ""
    return l[eq + 1 :].strip()


def _format_val(v: str) -> str:
    return v[:58] + "..." if len(v) > 58 else v


def _target_value(key: str, model_slug: str, provider_id: str, reasoning_effort: str, catalog_value: str) -> str:
    if key == "model":
        return toml_quote(model_slug)
    if key == "model_provider":
        return toml_quote(provider_id)
    if key == "preferred_auth_method":
        return '"apikey"'
    if key == "forced_login_method":
        return '"api"'
    if key == "model_reasoning_effort":
        return toml_quote(reasoning_effort)
    if key == "model_catalog_json":
        return toml_quote(catalog_value)
    if key == "web_search":
        return '"disabled"'
    return '""'


@dataclass
class EditResult:
    text: str
    report: list[str]
    lines: list[str]


def edit_config(
    source: str,
    provider_id: str,
    base_url: str,
    wire_api: str,
    use_env_key: bool,
    env_var_name: str,
    api_key_value: str,
    model_slug: str,
    reasoning_effort: str,
    catalog_value: str,
    disable_web_search: bool = False,
) -> EditResult:
    raw = source.replace("\r\n", "\n").rstrip("\n")
    lines = raw.split("\n") if raw else []

    out: list[str] = []
    report: list[str] = []
    seen: set[str] = set()
    ins_at = 0
    st = _ScanState()
    idx = 0
    cur_section = ""
    skip_section = False
    prov_hdr = f"model_providers.{provider_id}"

    def consume_block() -> None:
        nonlocal idx
        while idx < len(lines):
            st.scan(lines[idx])
            idx += 1
            if not st.mlstate and st.depth == 0:
                break

    while idx < len(lines):
        line = lines[idx]
        trimmed = line.strip()
        is_header = (not st.mlstate) and st.depth == 0 and trimmed.startswith("[")

        if is_header:
            hdr = trimmed
            close = hdr.find("]")
            if close > 0:
                hdr = hdr[: close + 1]
            hdr = hdr.strip("[").strip("]").strip().replace('"', "").replace("'", "")
            cur_section = hdr
            skip_section = False
            if hdr == prov_hdr or hdr.startswith(prov_hdr + "."):
                skip_section = True
                report.append(f"Removed old [{hdr}] (rewritten with new settings)")
            elif hdr == "profiles" or hdr.startswith("profiles."):
                skip_section = True
                report.append(f"Removed [{hdr}] <- profile masks model settings")
            elif hdr == "auto_review":
                report.append(f"Kept [{hdr}] (may use fallback metadata for gpt-5.x models)")
            elif hdr == "tui.model_availability_nux":
                report.append(f"Kept [{hdr}] (harmless NUX counters)")
            st.scan(line)
            idx += 1
            if not skip_section:
                out.append(line)
            continue

        if cur_section:
            if skip_section:
                st.scan(line)
                idx += 1
                continue
            # NOTE: wire_api of *other* providers is intentionally left untouched.
            # Rewriting "chat" -> "responses" here silently broke unrelated
            # OpenAI-compatible relays (many only support chat completions).
            # The section we install is rewritten wholesale at the end of this
            # function with the provider's own wire_api value.
            out.append(line)
            st.scan(line)
            idx += 1
            continue

        k = _key_of(line)

        if k == "web_search":
            oldv = _value_of(trimmed)
            if disable_web_search:
                consume_block()
                out.append('web_search = "disabled"')
                ins_at = len(out)
                seen.add("web_search")
                if oldv != '"disabled"':
                    report.append(f"Rewrote web_search = {_format_val(oldv)} -> \"disabled\"")
            else:
                consume_block()
                report.append(f"Removed web_search = {_format_val(oldv)} (restore default auto)")
            continue

        if k in TARGET_KEYS:
            oldv = _value_of(trimmed)
            newv = _target_value(k, model_slug, provider_id, reasoning_effort, catalog_value)
            consume_block()
            out.append(f"{k} = {newv}")
            ins_at = len(out)
            seen.add(k)
            if oldv != newv:
                report.append(f"Rewrote {k}: {_format_val(oldv)} -> {newv}")
            continue

        if k in DEL_A:
            oldv = _value_of(trimmed)
            consume_block()
            report.append(f"Removed {k} = {_format_val(oldv)}  <- {DEL_A[k]}")
            continue

        if k in DEL_B:
            oldv = _value_of(trimmed)
            consume_block()
            report.append(f"Removed {k} = {_format_val(oldv)}  <- {DEL_B[k]}")
            continue

        if k in WARN_KEYS:
            report.append(f"Kept {k} (may cause fallback metadata or be overridden remotely)")

        out.append(line)
        if k:
            ins_at = len(out)
        st.scan(line)
        idx += 1

    missing = [k for k in TARGET_KEYS if k not in seen]
    if disable_web_search and "web_search" not in seen:
        missing.append("web_search")

    final: list[str] = []
    for i, line in enumerate(out):
        if i == ins_at and missing:
            for k in missing:
                final.append(f"{k} = {_target_value(k, model_slug, provider_id, reasoning_effort, catalog_value)}")
            missing = []
            if out[i].strip().startswith("["):
                final.append("")
        final.append(line)
    for k in missing:
        final.append(f"{k} = {_target_value(k, model_slug, provider_id, reasoning_effort, catalog_value)}")

    final.append("")
    final.append(f"[model_providers.{provider_id}]")
    final.append(f"name = {toml_quote(provider_id)}")
    final.append(f"base_url = {toml_quote(base_url)}")
    final.append(f"wire_api = {toml_quote(wire_api)}")
    if use_env_key:
        final.append(f"env_key = {toml_quote(env_var_name)}")
    else:
        final.append(f"experimental_bearer_token = {toml_quote(api_key_value)}")

    return EditResult(text="\n".join(final) + "\n", report=report, lines=final)


def switch_model(source: str, slug: str) -> str:
    quoted = toml_quote(slug)
    raw = source.replace("\r\n", "\n").rstrip("\n")
    lines = raw.split("\n") if raw else []

    out: list[str] = []
    st = _ScanState()
    i = 0
    replaced = False
    in_leading = True

    while i < len(lines):
        line = lines[i]
        if not in_leading:
            out.append(line)
            i += 1
            continue
        if st.mlstate or st.depth != 0:
            st.scan(line)
            out.append(line)
            i += 1
            continue
        trimmed = line.strip()
        if trimmed.startswith("["):
            if not replaced:
                out.append(f"model = {quoted}")
                out.append("")
                replaced = True
            in_leading = False
            out.append(line)
            i += 1
            continue
        k = _key_of(line)
        if k == "model":
            st.scan(line)
            i += 1
            while (st.mlstate or st.depth != 0) and i < len(lines):
                st.scan(lines[i])
                i += 1
            out.append(f"model = {quoted}")
            replaced = True
            continue
        st.scan(line)
        out.append(line)
        i += 1

    if not replaced:
        out.append(f"model = {quoted}")

    return "\n".join(out) + "\n"


def remove_provider_section(source: str, provider_id: str) -> tuple[str, bool]:
    """Delete ``[model_providers.<id>]`` (and any ``<id>.*`` sub-tables).

    Used when removing a single channel: unlike a full ``restore`` this leaves
    every other provider section, the user's MCP/projects/skills config and any
    hand-edits made after install completely untouched.
    """
    prov_hdr = f"model_providers.{provider_id}"
    raw = source.replace("\r\n", "\n").rstrip("\n")
    lines = raw.split("\n") if raw else []

    st = _ScanState()
    out: list[str] = []
    removed = False
    skip = False
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        trimmed = line.strip()
        if (not st.mlstate) and st.depth == 0 and trimmed.startswith("["):
            close = trimmed.find("]")
            hdr = trimmed[: close + 1] if close > 0 else trimmed
            hdr = hdr.strip("[").strip("]").strip().replace('"', "").replace("'", "")
            skip = hdr == prov_hdr or hdr.startswith(prov_hdr + ".")
            if skip:
                removed = True
        if skip:
            st.scan(line)
            idx += 1
            continue
        out.append(line)
        st.scan(line)
        idx += 1

    # Collapse a trailing run of blank lines left behind by the excision.
    while out and not out[-1].strip():
        out.pop()
    text = "\n".join(out)
    return (text + "\n" if text else ""), removed


def provider_section_body(source: str, provider_id: str) -> str:
    """Return the text of ``[model_providers.<id>]`` for inspection/validation."""
    pattern = re.compile(
        rf"(?m)^\[\s*model_providers\.{re.escape(provider_id)}\s*\](?P<body>.*?)(?=^\[\s*|\Z)",
        re.S,
    )
    m = pattern.search(source.replace("\r\n", "\n"))
    return m.group("body") if m else ""


def _section_header_of(line: str) -> str:
    """Section name for a table header line, or "" if it is not a header."""
    trimmed = line.strip()
    if not trimmed.startswith("["):
        return ""
    close = trimmed.find("]")
    hdr = trimmed[: close + 1] if close > 0 else trimmed
    return hdr.strip("[").strip("]").strip().replace('"', "").replace("'", "")


def set_bearer_token(source: str, provider_id: str, new_key: str) -> str:
    """Rewrite only ``experimental_bearer_token`` inside one provider section.

    This is the key-rotation primitive: it substitutes the single credential
    line and leaves every other byte of the user's config untouched.  If the
    section exists but has no bearer line (it used ``env_key``), one is appended
    at the end of that section.
    """
    quoted = f"experimental_bearer_token = {toml_quote(new_key)}"
    raw = source.replace("\r\n", "\n").rstrip("\n")
    lines = raw.split("\n") if raw else []

    prov_hdr = f"model_providers.{provider_id}"
    st = _ScanState()
    out: list[str] = []
    in_target = False
    seen_target = False
    replaced = False
    # Index in `out` just before which to insert when the section has no bearer.
    section_end: int | None = None

    for line in lines:
        is_header = (not st.mlstate) and st.depth == 0 and _section_header_of(line) != ""
        if is_header:
            if in_target and not replaced:
                # Leaving the target section without having found a bearer line.
                section_end = len(out)
            hdr = _section_header_of(line)
            in_target = hdr == prov_hdr
            seen_target = seen_target or in_target
            out.append(line)
            st.scan(line)
            continue

        if in_target and not st.mlstate and st.depth == 0 and _key_of(line) == "experimental_bearer_token":
            out.append(quoted)
            replaced = True
            st.scan(line)
            continue

        out.append(line)
        st.scan(line)

    if not replaced:
        if not seen_target:
            # No such provider section: leave the document exactly as it was.
            return source.replace("\r\n", "\n").rstrip("\n") + "\n"
        if in_target:
            # Target section was the last one in the file.
            section_end = len(out)
        at = len(out) if section_end is None else section_end
        # Trim trailing blank lines so the new key lands inside the section.
        while at > 0 and not out[at - 1].strip():
            at -= 1
        out[at:at] = ["", quoted] if at < len(out) else ["", quoted]

    return "\n".join(out) + "\n"
