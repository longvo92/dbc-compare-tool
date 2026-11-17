"""Locations of bundled resources and the release history, frozen or from source."""

from __future__ import annotations

import sys
from pathlib import Path

# Repository root in a source checkout.
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(filename: str) -> Path:
    """Return a file under ``resources/`` in the PyInstaller bundle or the checkout."""
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "resources" / filename
    return _SOURCE_ROOT / "resources" / filename


def changelog_path() -> Path:
    """Use packaged release history, or the full changelog in a source checkout."""
    bundled = resource_path("CHANGELOG.md")
    if bundled.is_file():
        return bundled
    return _SOURCE_ROOT / "CHANGELOG.md"
