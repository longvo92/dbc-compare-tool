"""Desktop entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ..app_paths import resource_path
from .main_window import MainWindow
from .theme import configure_appearance

__all__ = ["configure_appearance", "main"]


def main() -> int:
    app = QApplication(sys.argv)
    icon_path = resource_path("app.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    configure_appearance(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
