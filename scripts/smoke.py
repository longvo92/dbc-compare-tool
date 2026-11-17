"""Headless smoke test of DBC Compare Tool.

The app is GUI-only; this developer script exercises the Qt-free engine entry
point the window calls, so CI and release builds prove a comparison works
without driving the widgets.

Usage:
    python scripts/smoke.py              # compare the bundled baselines
    python scripts/smoke.py --gui        # also open the window offscreen
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

EXAMPLES = REPO_ROOT / "examples"


def _assert_sheets(path: Path, expected: list[str]) -> None:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True)
    try:
        if workbook.sheetnames != expected:
            raise AssertionError(f"{path.name}: sheets {workbook.sheetnames}, expected {expected}")
    finally:
        workbook.close()


def stage_compare(workdir: Path) -> None:
    from dbc_compare_tool.dbc_compare.pipeline import run_comparison

    folders = ["Summary", "DBC Overview", "Message Details", "Signal Details"]
    files = ["Summary", "Message Details", "Signal Details"]
    cases = (
        ("folders", EXAMPLES / "old", EXAMPLES / "new", {}, folders),
        ("unchanged", EXAMPLES / "old", EXAMPLES / "new", {"include_unchanged": True}, folders),
        ("files", EXAMPLES / "old" / "Bus_A.dbc", EXAMPLES / "new" / "Bus_A.dbc", {}, files),
        ("vietnamese", EXAMPLES / "old", EXAMPLES / "new", {"language": "vi"}, folders),
    )
    for name, old, new, options, sheets in cases:
        result, report = run_comparison(old, new, workdir / f"{name}.xlsx", **options)
        if name != "vietnamese":
            _assert_sheets(report, sheets)
        print(f"compare/{name}: {result.completeness}, {result.summary()['Total Changes']} changes")


def stage_gui(workdir: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from dbc_compare_tool.ui.app import configure_appearance
    from dbc_compare_tool.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    configure_appearance(app)
    # A store of its own: a smoke run never reads or writes the user's preferences.
    settings = QSettings(str(workdir / "smoke.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    try:
        if window.centralWidget() is not window.compare:
            raise AssertionError("the comparison workspace is not the central widget")
        titles = [action.text() for action in window.menuBar().actions()]
        if titles != ["Settings", "Help"]:
            raise AssertionError(f"unexpected menus: {titles}")
        window.show()
        app.processEvents()
        print(f"gui: {window.windowTitle()}, menus {titles}")
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def main() -> int:
    # Windows consoles often use cp1252; translated output must not crash the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gui", action="store_true", help="Also open the window offscreen")
    args = parser.parse_args()
    stages = [("compare", stage_compare)]
    if args.gui:
        stages.append(("gui", stage_gui))
    with tempfile.TemporaryDirectory(prefix="dbc_compare_smoke_") as tmp:
        for name, stage in stages:
            try:
                stage(Path(tmp))
            except Exception as exc:  # report the failing stage by name
                print(f"FAILED {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
