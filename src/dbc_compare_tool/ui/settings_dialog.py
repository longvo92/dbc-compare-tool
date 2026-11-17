"""Preferences that are not part of a comparison: the two languages and the theme."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import theme as app_theme
from .widgets import NoWheelComboBox, TextBinder, dialog_buttons, section

THEME_KEY = "theme"


def theme_mode(settings: QSettings) -> str:
    mode = str(settings.value(THEME_KEY, "system", type=str))
    return mode if mode in app_theme.MODES else "system"


class SettingsDialog(QDialog):
    """GUI language, report language and the theme. Inputs stay on the window."""

    def __init__(
        self,
        parent: QWidget | None,
        binder: TextBinder,
        *,
        gui_language: str,
        report_language: str,
        mode: str,
    ) -> None:
        super().__init__(parent)
        self._binder = binder
        self._tr = binder.tr
        self.setWindowTitle(self._tr("Settings"))
        self.resize(480, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        language_card, language_form = section(binder, "Language")
        self.gui_input = self._combo(("English", "en"), ("Tiếng Việt", "vi"), current=gui_language)
        self.report_input = self._combo((self._tr("Follow GUI"), "gui"), ("English", "en"), ("Tiếng Việt", "vi"),
                                        current=report_language)
        self._row(language_form, 0, "GUI Language", self.gui_input)
        self._row(language_form, 1, "Report Language", self.report_input)
        layout.addWidget(language_card)

        appearance_card, appearance_form = section(binder, "Appearance")
        self.theme_input = self._combo(
            (self._tr("Follow Windows"), "system"), (self._tr("Light"), "light"), (self._tr("Dark"), "dark"),
            current=mode,
        )
        self._row(appearance_form, 0, "Theme", self.theme_input)
        layout.addWidget(appearance_card)

        buttons = dialog_buttons(binder.language, QDialogButtonBox.StandardButton.Save,
                                 QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- construction --------------------------------------------------------------

    def _combo(self, *choices: tuple[str, str], current: str) -> NoWheelComboBox:
        combo = NoWheelComboBox(self)
        for text, value in choices:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(combo.findData(current), 0))
        return combo

    def _row(self, form, row: int, key: str, widget: QWidget) -> QLabel:
        label = self._binder.widget(QLabel, key)
        label.setBuddy(widget)
        self._binder.bind(widget.setAccessibleName, key)
        form.addWidget(label, row, 0)
        form.addWidget(widget, row, 1)
        return label

    # -- values --------------------------------------------------------------------

    def values(self) -> dict[str, str]:
        return {
            "gui_language": str(self.gui_input.currentData()),
            "report_language": str(self.report_input.currentData()),
            "theme": str(self.theme_input.currentData()),
        }


def open_settings(
    parent: QWidget,
    binder: TextBinder,
    settings: QSettings,
    *,
    gui_language: str,
    report_language: str,
    apply: Callable[[str, str], None],
) -> bool:
    """Show the dialog and store what the user saved; ``apply`` takes the languages."""
    dialog = SettingsDialog(
        parent, binder, gui_language=gui_language, report_language=report_language,
        mode=theme_mode(settings),
    )
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        values = dialog.values()
    finally:
        dialog.deleteLater()
    settings.setValue(THEME_KEY, values["theme"])
    application = QApplication.instance()
    if application is not None:
        app_theme.configure_appearance(application, values["theme"])
    apply(values["gui_language"], values["report_language"])
    return True
