"""The shell: preference migration, the engine boundary and the window's own state."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_PACKAGE = _SRC / "dbc_compare_tool"
_VENDORED = sorted(_PACKAGE.glob("dbc_compare/**/*.py")) + [
    _PACKAGE / "ui" / "compare_tab.py",
    _PACKAGE / "ui" / "ecu_focus.py",
]


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.append(node.module or "")
    return names


def test_the_comparison_code_only_uses_relative_imports():
    """These files are copied into can-toolbox, so they may not name a package."""
    assert _VENDORED
    offenders = {
        str(path.relative_to(_SRC)): [
            name for name in _imports(path) if name.split(".")[0] in {"dbc_compare_tool", "can_toolbox"}
        ]
        for path in _VENDORED
    }
    assert {path: names for path, names in offenders.items() if names} == {}


def test_the_engine_imports_no_gui_framework():
    gui = {"PySide6", "shiboken6", "tkinter", "PyQt5", "PyQt6"}
    offenders = {
        str(path.relative_to(_SRC)): sorted(gui.intersection(name.split(".")[0] for name in _imports(path)))
        for path in sorted(_PACKAGE.glob("dbc_compare/**/*.py"))
    }
    assert {path: names for path, names in offenders.items() if names} == {}


def test_the_shell_translations_extend_the_comparison_ones():
    from dbc_compare_tool.dbc_compare.i18n import VI as COMPARE_VI
    from dbc_compare_tool.i18n import VI, translate

    assert set(COMPARE_VI).issubset(VI)
    assert translate("vi", "Run Compare") == COMPARE_VI["Run Compare"]
    assert translate("vi", "Settings") == "Cài đặt"
    assert translate("en", "Settings") == "Settings"
    assert translate("vi", "Unable to open help file: {error}", error="x") == "Không mở được file trợ giúp: x"


def test_version_is_the_one_the_packaging_declares():
    import dbc_compare_tool

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{dbc_compare_tool.__version__}"' in pyproject


# -- the window ------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dbc_compare_tool.ui.main_window import MainWindow, migrate_legacy_keys  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_preferences_from_0_8_0_are_carried_over(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("input_mode", "files")
    settings.setValue("last_old_folder", r"C:\old")
    settings.setValue("report_path_is_explicit", True)
    settings.setValue("gui_language", "vi")
    migrate_legacy_keys(settings)

    assert settings.value("compare/input_mode") == "files"
    assert settings.value("compare/last_old_folder") == r"C:\old"
    assert settings.value("compare/report_path_is_explicit", False, type=bool) is True
    # The old keys stay, so 0.8.0 keeps working beside this version.
    assert settings.value("input_mode") == "files"

    # A second run keeps what the user has set since.
    settings.setValue("compare/input_mode", "folders")
    migrate_legacy_keys(settings)
    assert settings.value("compare/input_mode") == "folders"


@pytest.mark.gui
def test_the_window_hosts_the_comparison_and_remembers_its_languages(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    try:
        assert window.centralWidget() is window.compare
        assert [action.text() for action in window.menuBar().actions()] == ["Settings", "Help"]
        assert window.compare.run_button.text() == "Run Compare"
        window._set_languages("vi", "en")
        assert window.compare.run_button.text() == "Chạy so sánh"
        assert window.settings_menu.title() == "Cài đặt"
        window.close()
    finally:
        window.deleteLater()
        app.processEvents()

    restored = MainWindow(settings)
    try:
        assert restored.gui_language == "vi"
        assert restored._report_language == "en"
        assert restored.compare.run_button.text() == "Chạy so sánh"
        assert settings.value("window/geometry") is not None
    finally:
        restored.close()
        restored.deleteLater()
        app.processEvents()


@pytest.mark.gui
def test_a_running_comparison_locks_the_settings_menu(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    try:
        window.compare.busy_changed.emit(True)
        assert not window.settings_action.isEnabled()
        window.compare.busy_changed.emit(False)
        assert window.settings_action.isEnabled()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
