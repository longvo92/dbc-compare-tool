from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

from dbc_compare_tool.i18n import translate
from dbc_compare_tool.ui.widgets import dialog_buttons


class EcuFocusDialog(QDialog):
    def __init__(
        self, parent, old_nodes: list[str], new_nodes: list[str],
        ecu_map: dict[str, str], previous: set[str], *, language: str = "en",
    ) -> None:
        super().__init__(parent)
        tr = partial(translate, language)
        self.setWindowTitle(tr("Select Focus ECUs"))
        self.resize(560, 450)
        layout = QVBoxLayout(self)
        hint = QLabel(tr("Select ECU nodes to include their Tx/Rx changes across both baselines."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        search = QLineEdit()
        search.setPlaceholderText(tr("Search ECU nodes…"))
        search.setAccessibleName(tr("Search ECU nodes…"))
        layout.addWidget(search)

        self.nodes = QListWidget()
        self.nodes.setAccessibleName(tr("Select Focus ECUs"))
        old_set, new_set = set(old_nodes), set(new_nodes)
        pairs: dict[str, list[str]] = {}
        for old, new in sorted(ecu_map.items()):
            if old != new:
                label = f"OLD {old} → NEW {new}"
                pairs.setdefault(old, []).append(label)
                pairs.setdefault(new, []).append(label)
        for name in sorted(old_set | new_set, key=lambda name: (name.casefold(), name)):
            sides = "/".join(side for side, names in (("OLD", old_set), ("NEW", new_set)) if name in names)
            text = f"{name}  [{sides}]"
            if name in pairs:
                text += "  ·  " + "; ".join(pairs[name])
            item = QListWidgetItem(text, self.nodes)
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setCheckState(Qt.CheckState.Checked if name in previous else Qt.CheckState.Unchecked)
        layout.addWidget(self.nodes)
        if not self.nodes.count():
            layout.addWidget(QLabel(tr("No ECU nodes found in the readable DBC files.")))

        select = QPushButton(tr("Select All Visible"))
        clear = QPushButton(tr("Clear Selection"))
        actions = QHBoxLayout()
        actions.addWidget(select)
        actions.addWidget(clear)
        actions.addStretch()
        layout.addLayout(actions)
        select.clicked.connect(self._select_visible)
        clear.clicked.connect(self._clear)
        search.textChanged.connect(self._search)

        buttons = dialog_buttons(language, QDialogButtonBox.StandardButton.Save, QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        search.setFocus()

    def _items(self):
        return (self.nodes.item(row) for row in range(self.nodes.count()))

    def _select_visible(self) -> None:
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)

    def _clear(self) -> None:
        for item in self._items():
            item.setCheckState(Qt.CheckState.Unchecked)

    def _search(self, query: str) -> None:
        query = query.strip().casefold()
        for item in self._items():
            item.setHidden(query not in item.text().casefold())

    def selected_nodes(self) -> set[str]:
        return {
            item.data(Qt.ItemDataRole.UserRole) for item in self._items()
            if item.checkState() == Qt.CheckState.Checked
        }
