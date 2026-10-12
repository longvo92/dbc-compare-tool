from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLineEdit


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

    def set_files_mode(self, enabled: bool) -> None:
        self._files_mode = enabled
        kind = "DBC file" if enabled else "folder"
        self.setPlaceholderText(f"Browse or drag & drop a {kind} here")

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
