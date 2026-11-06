"""Public release history for the app and its distributables."""
from __future__ import annotations

import re


_RELEASE_HEADING = re.compile(
    r"^##[ \t]+\[\d+\.\d+\.\d+\][ \t]*[-—][ \t]*\d{4}-\d{2}-\d{2}[ \t]*\r?$",
    re.MULTILINE,
)


def published_release_notes(changelog: str) -> str:
    """Keep the dated release history below the development section."""
    first_release = _RELEASE_HEADING.search(changelog)
    return changelog[first_release.start():] if first_release else ""
