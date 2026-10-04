"""Codex provider setup/manager.

``__version__`` is the single source of truth for the release version: it is
read by hatchling when building the package and by ``service.SCRIPT_VERSION``
for the crash log and manifest, so the two can no longer disagree.
"""

__version__ = "0.2.1"
