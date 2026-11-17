from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import translate


class TextBinder:
    """Remember which widget text comes from which translation key.

    Each binding is applied immediately and replayed by :meth:`set_language`,
    so a whole tab can be retranslated without being rebuilt.
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language
        self._bindings: list[tuple[Callable[[str], object], str]] = []

    def tr(self, key: str, **parameters: object) -> str:
        return translate(self.language, key, **parameters)

    def bind(self, setter: Callable[[str], object], key: str) -> None:
        self._bindings.append((setter, key))
        setter(self.tr(key))

    def widget(self, widget_type, key: str):
        widget = widget_type()
        self.bind(widget.setText, key)
        return widget

    def set_language(self, language: str) -> None:
        self.language = language
        for setter, key in self._bindings:
            setter(self.tr(key))


def section(binder: TextBinder, key: str) -> tuple[QGroupBox, QGridLayout]:
    """Return a titled card and the grid that holds its rows."""
    card = QGroupBox()
    card.setObjectName("sectionCard")
    binder.bind(card.setAccessibleName, key)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(12)
    title = binder.widget(QLabel, key)
    title.setObjectName("sectionTitle")
    layout.addWidget(title)
    form = QGridLayout()
    form.setHorizontalSpacing(8)
    form.setVerticalSpacing(8)
    form.setColumnStretch(1, 1)
    layout.addLayout(form)
    return card, form


def scrollable(content: QWidget) -> QScrollArea:
    """Keep the workspace scrollable and give its backing surfaces the app background."""
    scroll = QScrollArea()
    scroll.setObjectName("workspaceScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.viewport().setObjectName("workspaceViewport")
    content.setObjectName("workspaceContent")
    scroll.setWidget(content)
    return scroll


def dialog_buttons(language: str, *buttons: QDialogButtonBox.StandardButton) -> QDialogButtonBox:
    labels = {
        QDialogButtonBox.StandardButton.Save: "Save",
        QDialogButtonBox.StandardButton.Cancel: "Cancel",
        QDialogButtonBox.StandardButton.Close: "Close",
    }
    box = QDialogButtonBox()
    for button in buttons:
        box.addButton(button).setText(translate(language, labels[button]))
    return box


class NoWheelComboBox(QComboBox):
    """QComboBox that ignores wheel events.

    Used inside tables: scrolling the table must not silently change a
    selection, and the ignored event lets the table scroll instead.
    """

    def wheelEvent(self, event) -> None:
        event.ignore()


class DropLineEdit(QLineEdit):
    """Path field that accepts dropped files and folders of the configured kinds."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self._directories = True
        self._suffixes: tuple[str, ...] = ()
        self._placeholder_key = ""
        self.set_files_mode(False)
        # Without this the field demands room for the placeholder, which pushes
        # a horizontal scrollbar onto every layout it sits in.
        self.setMinimumWidth(160)

    def set_accepts(
        self,
        *,
        directories: bool = False,
        suffixes: tuple[str, ...] = (),
        placeholder_key: str = "",
        language: str = "en",
    ) -> None:
        """Accept folders and/or files with ``suffixes`` (lowercase, with dot)."""
        self._directories = directories
        self._suffixes = tuple(suffix.lower() for suffix in suffixes)
        self._placeholder_key = placeholder_key
        self.set_language(language)

    def set_language(self, language: str) -> None:
        self.setPlaceholderText(translate(language, self._placeholder_key) if self._placeholder_key else "")

    def set_files_mode(self, enabled: bool, language: str = "en") -> None:
        """DBC baseline input: one ``.dbc`` file, or a baseline folder."""
        if enabled:
            self.set_accepts(suffixes=(".dbc",), placeholder_key="Browse or drag & drop a DBC file here",
                             language=language)
        else:
            self.set_accepts(directories=True, placeholder_key="Browse or drag & drop a folder here",
                             language=language)

    def _accepts_path(self, path: Path) -> bool:
        if path.is_dir():
            return self._directories
        return path.is_file() and path.suffix.lower() in self._suffixes

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if self._accepts_path(Path(url.toLocalFile())):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        path = Path(event.mimeData().urls()[0].toLocalFile())
        if self._accepts_path(path):
            self.setText(str(path))
            event.acceptProposedAction()
        else:
            event.ignore()
