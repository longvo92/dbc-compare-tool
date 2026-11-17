"""Colour tokens: both themes are complete, and nothing paints colours of its own."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dbc_compare_tool.ui import theme as app_theme  # noqa: E402
from dbc_compare_tool.ui.settings_dialog import theme_mode  # noqa: E402

pytestmark = pytest.mark.gui

_UI = Path(__file__).resolve().parents[1] / "src" / "dbc_compare_tool" / "ui"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def light_again(app):
    yield
    app_theme.configure_appearance(app, "light")


def test_both_themes_fill_every_token_in_the_stylesheet(app):
    placeholders = set(re.findall(r"\$([a-z_]+)", app_theme.STYLESHEET.template))
    assert placeholders, "the stylesheet lost its tokens"
    for theme in (app_theme.LIGHT, app_theme.DARK):
        tokens = theme.tokens()
        assert placeholders <= set(tokens), f"{theme.name} is missing {placeholders - set(tokens)}"
        sheet = app_theme.stylesheet(theme)
        assert "$" not in sheet
        assert theme.window in sheet and theme.accent in sheet


def test_the_two_themes_are_not_the_same_palette():
    assert app_theme.LIGHT.window != app_theme.DARK.window
    assert app_theme.LIGHT.tokens().keys() == app_theme.DARK.tokens().keys()


def _luminance(color: str) -> float:
    channels = []
    for index in (1, 3, 5):
        value = int(color[index:index + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio, 1 (identical) to 21 (black on white)."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("theme", [app_theme.LIGHT, app_theme.DARK], ids=lambda t: t.name)
def test_text_stays_readable_in_both_themes(theme):
    """Body text needs 4.5:1, large or secondary text and lines 3:1 (WCAG AA)."""
    for token, background, minimum in (
        ("text", "window", 4.5), ("text", "surface", 4.5), ("heading", "window", 4.5),
        ("subtle", "chrome", 4.5), ("muted", "window", 3.0), ("muted_strong", "window", 4.5),
        ("accent", "window", 3.0), ("error", "surface", 4.0), ("text", "alternate", 4.5),
        ("text", "accent_soft", 4.5), ("accent_text", "accent", 4.5), ("link", "surface", 4.0),
        ("chevron", "surface", 3.0),
    ):
        ratio = contrast(getattr(theme, token), getattr(theme, background))
        assert ratio >= minimum, f"{theme.name}: {token} on {background} is {ratio:.2f}:1"


def test_only_the_theme_module_holds_colours():
    """A hard-coded hex in a widget would survive the theme switch unchanged."""
    offenders = []
    for path in _UI.rglob("*.py"):
        if path.name == "theme.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"#[0-9a-fA-F]{6}\b", line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"colours outside theme.py: {offenders}"


def test_applying_a_theme_repaints_the_application(app):
    light = app_theme.configure_appearance(app, "light")
    assert light is app_theme.LIGHT and app_theme.manager.mode == "light"
    assert app.palette().window().color().name() == app_theme.LIGHT.window

    seen = []
    app_theme.manager.changed.connect(seen.append)
    try:
        dark = app_theme.configure_appearance(app, "dark")
    finally:
        app_theme.manager.changed.disconnect(seen.append)
    assert dark is app_theme.DARK and seen == [app_theme.DARK]
    assert app.palette().window().color().name() == app_theme.DARK.window
    assert app_theme.DARK.surface in app.styleSheet()

    app_theme.configure_appearance(app, "nonsense")  # unknown modes follow the system
    assert app_theme.manager.mode == "system"
    assert app_theme.manager.theme in (app_theme.LIGHT, app_theme.DARK)


def test_tinted_assets_are_written_once_per_colour():
    first = app_theme.tinted_asset("chevron-down.svg", app_theme.DARK.chevron)
    assert first is not None and first.is_file()
    assert app_theme.DARK.chevron in first.read_text(encoding="utf-8")
    assert app_theme.tinted_asset("chevron-down.svg", app_theme.DARK.chevron) == first
    assert app_theme.tinted_asset("chevron-down.svg", app_theme.LIGHT.chevron) != first
    assert app_theme.tinted_asset("not-a-file.svg", "#000000") is None


def test_the_stored_theme_is_the_one_the_window_applies(app, tmp_path):
    from dbc_compare_tool.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert theme_mode(settings) == "system"
    settings.setValue("theme", "neon")
    assert theme_mode(settings) == "system"
    settings.setValue("theme", "dark")
    assert theme_mode(settings) == "dark"

    window = MainWindow(settings)
    assert app_theme.manager.theme is app_theme.DARK
    try:
        viewer = window.markdown_viewer("# Title\n\n[link](https://example.test)\n")
        styles = viewer.document().defaultStyleSheet()
        assert app_theme.DARK.link in styles and app_theme.DARK.code_bg in styles
        assert "link" in viewer.toPlainText()
        app_theme.configure_appearance(app, "light")
        viewer = window.markdown_viewer("# Title")
        assert app_theme.LIGHT.link in viewer.document().defaultStyleSheet()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
