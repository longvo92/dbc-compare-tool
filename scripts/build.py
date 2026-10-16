"""Build distributables for dbc-compare-tool.

Usage (run from anywhere, uses the project venv's Python):
    python scripts/build.py            # build both pyz and exe
    python scripts/build.py pyz        # thin zipapp (needs Python + deps on target)
    python scripts/build.py exe        # standalone one-file exe (PyInstaller)

Outputs go to dist/:
    DbcCompareTool-<version>.pyzw      # + dist/resources/ must ship next to it
    DbcCompareTool-<version>.exe       # resources bundled inside, ships alone
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PKG = REPO_ROOT / "src" / "dbc_compare_tool"
RESOURCES = REPO_ROOT / "resources"
# Help > Changelog reads this; it lives at the repo root, so every build has to
# copy it in beside the other resources.
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
DIST = REPO_ROOT / "dist"
APP_NAME = "DbcCompareTool"
_ADD_DATA_SEP = ";" if sys.platform == "win32" else ":"


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
            "    .venv\\Scripts\\pip install -e . pyinstaller",
            file=sys.stderr,
        )
        raise SystemExit(1)


def read_version() -> str:
    text = (SRC_PKG / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("__version__ not found in src/dbc_compare_tool/__init__.py")
    return match.group(1)


def build_pyz(version: str) -> Path:
    target = DIST / f"{APP_NAME}-{version}.pyzw"
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        shutil.copytree(
            SRC_PKG,
            staging / "dbc_compare_tool",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        zipapp.create_archive(
            staging,
            target,
            main="dbc_compare_tool.ui.main_window:main",
            compressed=True,
        )
    # _resource_path() resolves to the folder containing the .pyzw,
    # so resources/ must sit next to it.
    shutil.copytree(RESOURCES, DIST / "resources", dirs_exist_ok=True)
    shutil.copy2(CHANGELOG, DIST / "resources" / CHANGELOG.name)
    return target


def build_exe(version: str) -> Path:
    python = find_python()
    check_build_env(python)
    build_dir = REPO_ROOT / "build" / "pyinstaller"
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
        f"{CHANGELOG}{_ADD_DATA_SEP}resources",
        "--distpath",
        str(DIST),
        "--workpath",
        str(build_dir / "work"),
        "--specpath",
        str(build_dir),
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
    targets = sys.argv[1:] or ["pyz", "exe"]
    unknown = set(targets) - {"pyz", "exe"}
    if unknown:
        print(f"Unknown target(s): {', '.join(sorted(unknown))}. Use: pyz, exe", file=sys.stderr)
        return 2

    version = read_version()
    DIST.mkdir(exist_ok=True)

    built: list[Path] = []
    if "pyz" in targets:
        built.append(build_pyz(version))
    if "exe" in targets:
        built.append(build_exe(version))

    print()
    for path in built:
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"Built: {path.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")
    if any(p.suffix == ".pyzw" for p in built):
        print("Note: ship dist/resources/ alongside the .pyzw; target machine needs")
        print("      Python >=3.9 with: pip install PySide6 cantools openpyxl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
