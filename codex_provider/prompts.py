from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from codex_provider.io_utils import read_text


@lru_cache(maxsize=1)
def load_codex_instructions() -> str:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is not None:
        path = Path(bundle) / "codex_provider" / "prompts" / "codex_instructions.txt"
    else:
        path = Path(__file__).parent / "prompts" / "codex_instructions.txt"
    return read_text(path)
