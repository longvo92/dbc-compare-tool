"""Application shell: the comparison workspace plus the Settings and Help menus."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTextBrowser,
    QVBoxLayout,
)

from .. import __version__
from ..app_paths import changelog_path, resource_path
from ..i18n import LANGUAGES
from ..release_notes import published_release_notes
from .compare_tab import CompareTab
from .settings_dialog import open_settings, theme_mode
from .theme import configure_appearance, current_theme
from .widgets import TextBinder, dialog_buttons

APP_NAME = "DBC Compare Tool"

# 0.8.0 stored these keys unprefixed; the tab reads them under "compare/".
_LEGACY_KEYS = {
    "input_mode": "compare/input_mode",
    "last_old_folder": "compare/last_old_folder",
    "last_new_folder": "compare/last_new_folder",
    "last_report_path": "compare/last_report_path",
    "report_path_is_explicit": "compare/report_path_is_explicit",
}
_MIGRATED_KEY = "migrated_to_prefixed_keys"


def _read_resource_text(filename: str) -> str:
    return resource_path(filename).read_text(encoding="utf-8")


# Kept as a module attribute so tests can point Help → Release note at a fixture.
_changelog_path = changelog_path


def migrate_legacy_keys(settings: QSettings) -> None:
    """Carry 0.8.0 preferences over to the keys this version reads.

    The old keys are left in place so 0.8.0 keeps working side by side; values
    already stored under the new keys win.
    """
    if settings.value(_MIGRATED_KEY, False, type=bool):
        return
    for old_key, new_key in _LEGACY_KEYS.items():
        if settings.contains(old_key) and not settings.contains(new_key):
            settings.setValue(new_key, settings.value(old_key))
    settings.setValue(_MIGRATED_KEY, True)
    settings.sync()


def _language_preference(settings: QSettings, key: str, choices: tuple[str, ...], default: str) -> str:
    value = settings.value(key, default, type=str)
    return value if value in choices else default


class MainWindow(QMainWindow):
    """One window: the comparison workspace, with Settings and Help."""

    def __init__(self, settings: QSettings | None = None) -> None:
        """``settings`` defaults to the store of the installed app.

        Tests pass their own so a run never reads or writes the user's preferences.
        """
        super().__init__()
        # The namespace DBC Compare Tool 0.8.0 used, so its preferences carry over.
        self._settings = settings if settings is not None else QSettings("DbcCompareTool", "DBCCompareTool")
        migrate_legacy_keys(self._settings)
        gui_language = _language_preference(self._settings, "gui_language", LANGUAGES, "en")
        self._report_language = _language_preference(
            self._settings, "report_language", ("gui", *LANGUAGES), "gui",
        )
        self._binder = TextBinder(gui_language)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1024, 760)

        self.compare = CompareTab(self._settings, gui_language=gui_language,
                                  report_language=self._report_language)
        self.setCentralWidget(self.compare)
        self._subtitle = QLabel()
        self._subtitle.setObjectName("appSubtitle")
        self._binder.bind(self._subtitle.setText, self.compare.subtitle_key)
        self.statusBar().addWidget(self._subtitle, 1)
        self._build_menus()
        self.compare.busy_changed.connect(self._on_busy)
        self._restore_geometry()

        application = QApplication.instance()
        if application is not None:
            configure_appearance(application, theme_mode(self._settings))

    # -- menus ---------------------------------------------------------------------

    def _build_menus(self) -> None:
        self.settings_menu = self.menuBar().addMenu("")
        self._binder.bind(self.settings_menu.setTitle, "Settings")
        self.settings_action = self.settings_menu.addAction("")
        self._binder.bind(self.settings_action.setText, "Settings…")
        self.settings_action.triggered.connect(self._show_settings)
        self.settings_menu.addSeparator()
        quit_action = self.settings_menu.addAction("")
        self._binder.bind(quit_action.setText, "Quit")
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        help_menu = self.menuBar().addMenu("")
        self._binder.bind(help_menu.setTitle, "Help")
        user_guide_action = help_menu.addAction("")
        release_note_action = help_menu.addAction("")
        about_action = help_menu.addAction("")
        for action, key in ((user_guide_action, "User Guide"), (release_note_action, "Release note"),
                            (about_action, "About")):
            self._binder.bind(action.setText, key)
        user_guide_action.triggered.connect(
            lambda: self._show_help_document(
                "User Guide", "help/user_guide_vi.md" if self.gui_language == "vi" else "help/user_guide.md",
            )
        )
        release_note_action.triggered.connect(self._show_release_note)
        about_action.triggered.connect(lambda: self._show_help_document(
            "About", "help/about_vi.md" if self.gui_language == "vi" else "help/about.md",
        ))

    # -- languages -----------------------------------------------------------------

    @property
    def gui_language(self) -> str:
        return self._binder.language

    def _tr(self, key: str, **parameters: object) -> str:
        return self._binder.tr(key, **parameters)

    def _set_languages(self, gui_language: str, report_language: str) -> None:
        self._report_language = report_language
        self._settings.setValue("gui_language", gui_language)
        self._settings.setValue("report_language", report_language)
        self._binder.set_language(gui_language)
        self.compare.set_languages(gui_language, report_language)

    def _show_settings(self) -> None:
        open_settings(
            self, self._binder, self._settings,
            gui_language=self.gui_language, report_language=self._report_language,
            apply=self._set_languages,
        )

    # -- busy state ----------------------------------------------------------------

    def _on_busy(self, busy: bool) -> None:
        """Language and theme stay put while a comparison runs."""
        self.settings_menu.setEnabled(not busy)
        self.settings_action.setEnabled(not busy)

    # -- geometry ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        state = self._settings.value("window/geometry")
        if state is not None:
            self.restoreGeometry(state)

    # -- shutdown ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self.compare.is_busy():
            reply = QMessageBox.question(
                self,
                self._tr("Task Running"),
                self._tr("A task is still running. Quit anyway?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.compare.stop_workers()
        self._settings.setValue("window/geometry", self.saveGeometry())
        super().closeEvent(event)

    # -- help ----------------------------------------------------------------------

    def _show_help_document(self, title: str, filename: str) -> None:
        title = self._tr(title)
        try:
            content = _read_resource_text(filename)
        except OSError as exc:
            QMessageBox.critical(self, title, self._tr("Unable to open help file: {error}", error=exc))
            return
        self._show_markdown(title, content)

    def _show_release_note(self) -> None:
        title = self._tr("Release note")
        try:
            content = published_release_notes(_changelog_path().read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            QMessageBox.critical(self, title, self._tr("Unable to open the release notes: {error}", error=exc))
            return
        self._show_markdown(title, content or self._tr("No release notes available."))

    def markdown_viewer(self, content: str) -> QTextBrowser:
        """Help text in the current theme; QTextBrowser styles its document itself."""
        theme = current_theme()
        viewer = QTextBrowser()
        viewer.setOpenExternalLinks(True)
        viewer.document().setDefaultStyleSheet(
            f"a {{ color: {theme.link}; }}"
            f"code, pre {{ background-color: {theme.code_bg}; color: {theme.text}; }}"
            f"h1, h2, h3 {{ color: {theme.heading}; }}"
            f"table, td, th {{ border: 1px solid {theme.border}; }}"
        )
        viewer.setMarkdown(content.replace("{version}", __version__))
        return viewer

    def _show_markdown(self, title: str, content: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        viewer = self.markdown_viewer(content)
        buttons = dialog_buttons(self.gui_language, QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(viewer)
        layout.addWidget(buttons)
        dialog.exec()
