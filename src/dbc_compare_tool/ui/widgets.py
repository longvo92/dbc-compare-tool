from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLineEdit

from dbc_compare_tool.i18n import translate


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
    """QLineEdit that accepts the currently selected baseline input type."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.set_files_mode(False)
        # Without this the field demands room for the placeholder, which pushes
        # a horizontal scrollbar onto every layout it sits in.
        self.setMinimumWidth(160)

    def set_files_mode(self, enabled: bool, language: str = "en") -> None:
        self._files_mode = enabled
        key = "Browse or drag & drop a DBC file here" if enabled else "Browse or drag & drop a folder here"
        self.setPlaceholderText(translate(language, key))

    def _accepts_path(self, path: Path) -> bool:
        if self._files_mode:
            return path.is_file() and path.suffix.lower() == ".dbc"
        return path.is_dir()

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
