from __future__ import annotations

from pathlib import Path


def collect_dbc_files(folder: Path) -> dict[str, Path]:
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Folder does not exist: {folder}")
    # Match the extension case-insensitively so *.DBC is found on
    # case-sensitive filesystems too (rglob("*.dbc") would miss it there).
    return {
        path.relative_to(folder).as_posix(): path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() == ".dbc"
    }

