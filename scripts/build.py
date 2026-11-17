"""Build the standalone DBC Compare Tool executable.

Usage (run from anywhere, uses the project venv's Python):
    python scripts/build.py

Output: dist/DbcCompareTool-<version>.exe, a one-file PyInstaller bundle with every
dependency and resource inside; it is the only distributed artifact.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
from dbc_compare_tool.release_notes import published_release_notes  # noqa: E402

SRC_PKG = REPO_ROOT / "src" / "dbc_compare_tool"
RESOURCES = REPO_ROOT / "resources"
# Keep development notes in the repository and bundle only the release history.
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
DIST = REPO_ROOT / "dist"
APP_NAME = "DbcCompareTool"
_ADD_DATA_SEP = ";" if sys.platform == "win32" else ":"
# Reachable only through optional code paths the app never takes (Qt Quick,
# WebEngine); bundling them would add hundreds of megabytes.
_EXCLUDED_MODULES = (
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "matplotlib",
    "IPython",
)


def find_python() -> str:
    """Prefer the project venv's Python so PyInstaller bundles the right deps,
    regardless of which Python was used to invoke this script."""
    for candidate in (
        REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        REPO_ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def check_build_env(python: str) -> None:
    probe = subprocess.run(
        [python, "-c", "import PySide6, PyInstaller"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        print(
            f"Build environment is missing dependencies ({python}):\n"
            f"{probe.stderr.strip()}\n"
            "Fix: create the project venv and install deps:\n"
            "    python -m venv .venv\n"
            '    .venv\\Scripts\\pip install -e ".[dev]"',
            file=sys.stderr,
        )
        raise SystemExit(1)


def read_version() -> str:
    text = (SRC_PKG / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("__version__ not found in src/dbc_compare_tool/__init__.py")
    return match.group(1)


def _write_release_history(destination: Path) -> None:
    history = published_release_notes(CHANGELOG.read_text(encoding="utf-8"))
    destination.write_text(history, encoding="utf-8")


def build_exe(version: str) -> Path:
    python = find_python()
    check_build_env(python)
    build_dir = REPO_ROOT / "build" / "pyinstaller"
    build_dir.mkdir(parents=True, exist_ok=True)
    release_history = build_dir / CHANGELOG.name
    _write_release_history(release_history)
    cmd = [
        python,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--name",
        APP_NAME,
        "--icon",
        str(RESOURCES / "app.ico"),
        "--paths",
        str(REPO_ROOT / "src"),
        "--add-data",
        f"{RESOURCES}{_ADD_DATA_SEP}resources",
        "--add-data",
        f"{release_history}{_ADD_DATA_SEP}resources",
        "--distpath",
        str(DIST),
        "--workpath",
        str(build_dir / "work"),
        "--specpath",
        str(build_dir),
        *(argument for module in _EXCLUDED_MODULES for argument in ("--exclude-module", module)),
        str(SRC_PKG / "__main__.py"),
    ]
    env = os.environ.copy()
    if sys.platform == "win32":
        # Do not collect unrelated DLLs from development-tool PATH entries.
        # For example, Poppler's icuuc.dll lacks the Windows ICU exports Qt uses.
        # PyInstaller's hooks add package-specific Qt DLL directories separately.
        windows = Path(env.get("SystemRoot", r"C:\Windows"))
        env["PATH"] = os.pathsep.join((str(Path(python).parent), str(windows / "System32"), str(windows)))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, env=env)
    exe = DIST / f"{APP_NAME}.exe"
    versioned = DIST / f"{APP_NAME}-{version}.exe"
    versioned.unlink(missing_ok=True)
    exe.rename(versioned)
    return versioned


def main() -> int:
    if sys.argv[1:]:
        print("build.py takes no arguments; it builds the executable.", file=sys.stderr)
        return 2
    DIST.mkdir(exist_ok=True)
    exe = build_exe(read_version())
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"Built: {exe.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
