from __future__ import annotations

from codex_provider.io_utils import sanitize_ctrl


def test_sanitize_ctrl_keeps_legal_chars():
    text = "model = \"x\"\r\nbase_url = \"https://a/\t1\"\n"
    assert sanitize_ctrl(text) == text


def test_sanitize_ctrl_strips_illegal_control_chars():
    text = "model = \"a\x16b\"\nkey = \"c\x01d\"\r\n"
    out = sanitize_ctrl(text)
    assert "\x16" not in out
    assert "\x01" not in out
    assert 'model = "ab"' in out
    assert 'key = "cd"' in out


def test_sanitize_ctrl_strips_c0_and_del():
    # 0x00-0x08, 0x0b, 0x0c, 0x0e-0x1f and 0x7f are illegal; tab/lf/cr are kept
    illegal = [c for c in range(0x00, 0x20) if c not in (0x09, 0x0A, 0x0D)] + [0x7F]
    polluted = "".join(chr(c) for c in illegal) + "abc"
    out = sanitize_ctrl(polluted)
    assert out == "abc"
    # tab / lf / cr survive
    assert sanitize_ctrl("\t\n\r") == "\t\n\r"


def test_sanitize_ctrl_unicode_untouched():
    text = "name = \"Wolfox AI\" 显示名\n"
    assert sanitize_ctrl(text) == text


def test_sanitize_ctrl_strips_leading_bom():
    text = "\ufeffmodel = \"x\"\n"
    out = sanitize_ctrl(text)
    assert not out.startswith("\ufeff")
    assert out == "model = \"x\"\n"


def test_sanitize_ctrl_strips_bom_even_with_controls():
    text = "\ufeffmodel = \"a\x16b\"\n"
    out = sanitize_ctrl(text)
    assert out == "model = \"ab\"\n"
