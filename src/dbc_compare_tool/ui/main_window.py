from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dbc_compare_tool import __version__
from dbc_compare_tool.core.comparator import DbcComparator, filter_result
from dbc_compare_tool.core.discovery import collect_dbc_files
from dbc_compare_tool.core.ecu import collect_ecu_nodes, validate_ecu_map
from dbc_compare_tool.core.models import ComparisonResult
from dbc_compare_tool.report.excel import default_report_path, write_excel_report
from dbc_compare_tool.ui.widgets import DropLineEdit, NoWheelComboBox


def _resource_path(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "resources" / filename
    return Path(__file__).resolve().parents[3] / "resources" / filename


def _changelog_path() -> Path:
    """CHANGELOG.md lives at the repository root, which no build ships.

    scripts/build.py copies it in beside the other resources, so a build finds
    it there; a source checkout falls back to the root copy itself.
    """
    bundled = _resource_path("CHANGELOG.md")
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parents[3] / "CHANGELOG.md"


_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #f4f6fb;
}
QWidget {
    font-family: 'Segoe UI', sans-serif;
    font-size: 10pt;
    color: #1f2430;
}
QLabel#appTitle {
    font-size: 17pt;
    font-weight: 700;
    color: #16213a;
}
QLabel#appSubtitle {
    color: #6b7280;
    font-size: 9pt;
}
QLabel#versionBadge {
    color: #2563eb;
    background: #e3ecfd;
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 8pt;
    font-weight: 600;
}
QLineEdit {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: #bfd3f8;
}
QLineEdit:focus {
    border: 1px solid #2563eb;
}
QLineEdit:disabled {
    background: #f1f5f9;
    color: #64748b;
    border-color: #e2e8f0;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 7px 16px;
}
QPushButton:hover { background: #eef2fb; }
QPushButton:pressed { background: #e0e7f7; }
QPushButton:disabled { color: #9aa2b1; background: #f0f1f5; }
QPushButton#primaryButton {
    background: #2563eb;
    border: none;
    color: #ffffff;
    font-weight: 600;
    padding: 8px 22px;
}
QPushButton#primaryButton:hover { background: #1d4fd7; }
QPushButton#primaryButton:pressed { background: #1a46bd; }
QPushButton#primaryButton:disabled { background: #a5bdf2; color: #eef2fb; }
QGroupBox {
    background: #ffffff;
    border: 1px solid #e1e5ee;
    border-radius: 8px;
    margin-top: 10px;
    padding: 12px 14px 10px 14px;
    font-weight: 600;
    color: #334155;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
QCheckBox {
    spacing: 6px;
    font-weight: 400;
}
QCheckBox:disabled { color: #64748b; }
QLabel#runStatus {
    color: #334155;
    font-weight: 600;
    font-size: 9pt;
}
QProgressBar {
    background: #e5e9f2;
    border: none;
    border-radius: 4px;
    max-height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 4px;
}
QTextEdit#logView {
    background: #ffffff;
    color: #334155;
    border: 1px solid #e1e5ee;
    border-radius: 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 9pt;
    padding: 10px;
}
QTextBrowser {
    background: #ffffff;
    border: 1px solid #e1e5ee;
    border-radius: 8px;
    padding: 10px;
}
QMenuBar {
    background: #f4f6fb;
}
QMenuBar::item {
    padding: 6px 10px;
    border-radius: 4px;
}
QMenuBar::item:selected { background: #e3ecfd; }
QMenu {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected { background: #e3ecfd; }
QStatusBar {
    background: #eef1f8;
    color: #4b5563;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #e1e5ee;
    border-radius: 6px;
    gridline-color: #edf0f7;
}
QHeaderView::section {
    background: #eef2fb;
    border: none;
    border-bottom: 1px solid #d4d9e4;
    padding: 6px 8px;
    font-weight: 600;
    color: #4b5563;
}
QComboBox {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 4px 8px;
}
QComboBox:focus { border: 1px solid #2563eb; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    selection-background-color: #e3ecfd;
    selection-color: #1f2430;
}
QLabel#hintLabel {
    color: #6b7280;
    font-size: 9pt;
}
QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 6px 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 9pt;
}
QPlainTextEdit:focus { border: 1px solid #2563eb; }
QScrollArea {
    background: transparent;
    border: none;
}
"""


def _read_resource_text(filename: str) -> str:
    return _resource_path(filename).read_text(encoding="utf-8")


def _scrollable(content: QWidget) -> QScrollArea:
    """Wrap a tab's content so a small window scrolls instead of crushing it."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.viewport().setAutoFillBackground(False)
    content.setAutoFillBackground(False)
    scroll.setWidget(content)
    return scroll


class CompareWorker(QThread):
    log = Signal(str)
    compared = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        old_folder: Path,
        new_folder: Path,
        pair_map: dict[str, str | None] | None = None,
        include_unchanged: bool = False,
        ecu_map: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.old_folder = old_folder
        self.new_folder = new_folder
        self.pair_map = pair_map
        self.include_unchanged = include_unchanged
        self.ecu_map = dict(ecu_map or {})

    def run(self) -> None:
        try:
            self.log.emit("Discovering and parsing DBC files...")
            comparator = DbcComparator(
                include_unchanged=self.include_unchanged, ecu_map=self.ecu_map
            )
            if self.pair_map is None:
                result = comparator.compare_paths(
                    self.old_folder,
                    self.new_folder,
                    progress_callback=lambda msg: self.log.emit(msg),
                )
            else:
                result = comparator.compare_manual(
                    self.old_folder,
                    self.new_folder,
                    self.pair_map,
                    progress_callback=lambda msg: self.log.emit(msg),
                )
            self.compared.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ExportWorker(QThread):
    log = Signal(str)
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, result: ComparisonResult, output_path: Path) -> None:
        super().__init__()
        self.result = result
        self.output_path = output_path

    def run(self) -> None:
        try:
            self.log.emit("Writing Excel report...")
            write_excel_report(self.result, self.output_path)
            self.completed.emit(self.output_path, dict(self.result.summary(),
                completeness=self.result.completeness, parse_error_count=len(self.result.diagnostics),
                review_count=self.result.review_count))
        except Exception as exc:
            self.failed.emit(str(exc))


class EcuDiscoveryWorker(QThread):
    loaded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, old_path: Path, new_path: Path) -> None:
        super().__init__()
        self.old_path = old_path
        self.new_path = new_path

    def run(self) -> None:
        try:
            self.loaded.emit(collect_ecu_nodes(self.old_path), collect_ecu_nodes(self.new_path))
        except Exception as exc:
            self.failed.emit(str(exc))


class EcuPairingDialog(QDialog):
    """Pair renamed ECU nodes while retaining original routing in the report."""

    def __init__(
        self,
        parent,
        old_nodes: list[str],
        new_nodes: list[str],
        previous: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ECU Node Pairing")
        self.resize(680, 460)
        self._pair_map: dict[str, str] = {}
        self._old_nodes = set(old_nodes)
        self._new_nodes = set(new_nodes)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Pair only the nodes you want to rename. Leave the rest at "
            "Keep original name. Selected renames must use different NEW nodes. "
            "Pairing applies across the selected baselines; original names remain in the report."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(len(old_nodes), 2)
        self.table.setHorizontalHeaderLabels(["OLD ECU Node", "NEW ECU Node"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, old_node in enumerate(old_nodes):
            self.table.setItem(row, 0, QTableWidgetItem(old_node))
            combo = NoWheelComboBox()
            combo.addItem("— Keep original name —", None)
            for new_node in new_nodes:
                combo.addItem(new_node, new_node)
            if previous and previous.get(old_node) in new_nodes:
                combo.setCurrentIndex(combo.findData(previous[old_node]))
            self.table.setCellWidget(row, 1, combo)
        layout.addWidget(self.table)
        counts = QLabel(f"{len(old_nodes)} OLD node(s) · {len(new_nodes)} NEW node(s)")
        counts.setObjectName("hintLabel")
        layout.addWidget(counts)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        pair_map: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            old_node = self.table.item(row, 0).text()
            new_node = self.table.cellWidget(row, 1).currentData()
            if new_node is not None and new_node != old_node:
                pair_map[old_node] = new_node
        try:
            validate_ecu_map(pair_map, self._old_nodes, self._new_nodes)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid ECU Pairing", str(exc))
            return
        self._pair_map = pair_map
        self.accept()

    def pair_map(self) -> dict[str, str]:
        return dict(self._pair_map)


class ManualPairingDialog(QDialog):
    """Lets the user choose which new-baseline file each old-baseline file pairs with.

    The chosen pairing is returned via pair_map() after Save.
    """

    def __init__(
        self,
        parent,
        old_folder: Path,
        new_folder: Path,
        previous: dict[str, str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual DBC Pairing")
        self.resize(780, 520)
        self._pair_map: dict[str, str | None] = {}

        old_files = sorted(collect_dbc_files(old_folder))
        new_files = sorted(collect_dbc_files(new_folder))

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Pick the new-baseline file for each old-baseline file. Old files set to "
            "\"— Removed (no pair) —\" are reported as removed; new files not selected "
            "in any pair are reported as added."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        counts = QLabel(f"{len(old_files)} old file(s)  ·  {len(new_files)} new file(s)")
        counts.setObjectName("hintLabel")
        layout.addWidget(counts)

        self.table = QTableWidget(len(old_files), 2)
        self.table.setHorizontalHeaderLabels(["Old Baseline DBC", "New Baseline DBC"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        for row, old_rel in enumerate(old_files):
            old_item = QTableWidgetItem(old_rel)
            old_item.setToolTip(old_rel)
            self.table.setItem(row, 0, old_item)

            combo = NoWheelComboBox()
            combo.addItem("— Removed (no pair) —", None)
            for new_rel in new_files:
                combo.addItem(new_rel, new_rel)
            # Restore the previously saved choice; otherwise default to the
            # same relative path, mirroring auto pairing.
            if previous is not None and old_rel in previous:
                target = previous[old_rel]
            elif old_rel in new_files:
                target = old_rel
            else:
                target = None
            if target is not None and target in new_files:
                combo.setCurrentIndex(1 + new_files.index(target))
            self.table.setCellWidget(row, 1, combo)

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        pair_map: dict[str, str | None] = {}
        used_new: dict[str, str] = {}
        duplicates: list[str] = []
        for row in range(self.table.rowCount()):
            old_rel = self.table.item(row, 0).text()
            new_rel = self.table.cellWidget(row, 1).currentData()
            pair_map[old_rel] = new_rel
            if new_rel:
                if new_rel in used_new:
                    duplicates.append(f"{new_rel} (paired with {used_new[new_rel]} and {old_rel})")
                else:
                    used_new[new_rel] = old_rel
        if duplicates:
            QMessageBox.warning(
                self,
                "Duplicate Pairing",
                "Each new DBC file can only be paired once:\n" + "\n".join(duplicates),
            )
            return
        self._pair_map = pair_map
        self.accept()

    def pair_map(self) -> dict[str, str | None]:
        return dict(self._pair_map)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DBC Compare Tool")
        self.resize(1000, 780)
        self.setMinimumSize(720, 520)
        self.worker: CompareWorker | None = None
        self.export_worker: ExportWorker | None = None
        self.ecu_worker: EcuDiscoveryWorker | None = None
        self._pending_output_path: Path | None = None
        self.last_report: Path | None = None
        self._settings = QSettings("DbcCompareTool", "DBCCompareTool")

        self.old_input = DropLineEdit()
        self.new_input = DropLineEdit()
        self.input_mode = NoWheelComboBox()
        self.input_mode.addItem("Folders", "folders")
        self.input_mode.addItem("Files", "files")
        self.input_mode.setAccessibleName("Input Type")
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText(
            "Automatic: beside New folder as compared_<folder>.xlsx"
        )
        self.run_button = QPushButton("Run Compare")
        self.manual_pair_button = QPushButton("Manual Pairing…")
        self.ecu_pair_button = QPushButton("ECU Pairing…")
        self.open_button = QPushButton("Open Report")
        self.progress = QProgressBar()
        self.log_view = QTextEdit()
        self.run_status = QLabel("Ready to compare")
        self.run_status.setObjectName("runStatus")
        self.run_status.setWordWrap(True)

        # Manual pairing saved from the Manual Pairing dialog, plus the folder
        # inputs it was built for; invalidated when either folder changes.
        self._saved_pair_map: dict[str, str | None] | None = None
        self._saved_pair_folders: tuple[str, str] | None = None
        self._saved_ecu_map: dict[str, str] = {}
        self._saved_ecu_inputs: tuple[str, str, str] | None = None
        self._ecu_load_inputs: tuple[str, str, str] | None = None

        # Filter checkboxes
        self.chk_added = QCheckBox("Added")
        self.chk_removed = QCheckBox("Removed")
        self.chk_modified = QCheckBox("Modified")
        self.chk_renamed = QCheckBox("Renamed")
        for chk in (self.chk_added, self.chk_removed, self.chk_modified, self.chk_renamed):
            chk.setChecked(True)
        self.chk_include_unchanged = QCheckBox("Include Unchanged")
        self.chk_include_unchanged.setToolTip(
            "Export every message and signal, including unchanged entries. "
            "Change-type filters are ignored in this mode."
        )

        self._build_menu()
        self._build_layout()
        self._wire_events()
        self._restore_paths()

    def _build_menu(self) -> None:
        help_menu = self.menuBar().addMenu("Help")
        user_guide_action = help_menu.addAction("User Guide")
        changelog_action = help_menu.addAction("Changelog")
        about_action = help_menu.addAction("About")
        user_guide_action.triggered.connect(
            lambda: self._show_help_document("User Guide", "help/user_guide.md")
        )
        changelog_action.triggered.connect(self._show_changelog)
        about_action.triggered.connect(lambda: self._show_help_document("About", "help/about.md"))

    def _build_layout(self) -> None:
        # Header
        title = QLabel("DBC Compare Tool")
        title.setObjectName("appTitle")

        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("versionBadge")

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(title)
        title_row.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch()

        subtitle = QLabel("Compare DBC baselines. Review message and signal changes in Excel.")
        subtitle.setObjectName("appSubtitle")

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addLayout(title_row)
        header.addWidget(subtitle)

        # Baselines and report settings follow the comparison workflow.
        input_group = QGroupBox("Baselines")
        form = QGridLayout(input_group)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        mode_label = QLabel("Input Type")
        mode_label.setBuddy(self.input_mode)
        form.addWidget(mode_label, 0, 0)
        form.addWidget(self.input_mode, 0, 1)

        old_label = self.old_label = QLabel("Old Baseline Folder")
        old_label.setBuddy(self.old_input)
        self.old_input.setAccessibleName("Old Baseline Folder")
        form.addWidget(old_label, 1, 0)
        form.addWidget(self.old_input, 1, 1)
        old_button = QPushButton("Browse")
        old_button.setAccessibleName("Browse old baseline folder")
        old_button.clicked.connect(lambda: self._choose_baseline(self.old_input))
        form.addWidget(old_button, 1, 2)

        new_label = self.new_label = QLabel("New Baseline Folder")
        new_label.setBuddy(self.new_input)
        self.new_input.setAccessibleName("New Baseline Folder")
        form.addWidget(new_label, 2, 0)
        form.addWidget(self.new_input, 2, 1)
        new_button = QPushButton("Browse")
        new_button.setAccessibleName("Browse new baseline folder")
        new_button.clicked.connect(lambda: self._choose_baseline(self.new_input))
        form.addWidget(new_button, 2, 2)

        pairing_row = QHBoxLayout()
        pairing_hint = self.pairing_hint = QLabel("Automatic DBC pairing by default.")
        pairing_hint.setObjectName("hintLabel")
        pairing_hint.setWordWrap(True)
        pairing_row.addWidget(pairing_hint, 1)
        pairing_row.addWidget(self.manual_pair_button)
        pairing_row.addWidget(self.ecu_pair_button)
        form.addLayout(pairing_row, 3, 0, 1, 3)
        form.setColumnStretch(1, 1)

        report_group = QGroupBox("Report")
        report_form = QGridLayout(report_group)
        report_form.setHorizontalSpacing(10)
        report_form.setVerticalSpacing(10)
        output_label = QLabel("Report Path (optional)")
        output_label.setBuddy(self.output_input)
        self.output_input.setAccessibleName("Report Path (optional)")
        report_form.addWidget(output_label, 0, 0)
        label_width = max(label.sizeHint().width() for label in (old_label, new_label, output_label))
        for label in (old_label, new_label, output_label):
            label.setFixedWidth(label_width)
        report_form.addWidget(self.output_input, 0, 1)
        output_button = QPushButton("Browse")
        output_button.setAccessibleName("Browse report output path")
        output_button.clicked.connect(self._choose_report)
        report_form.addWidget(output_button, 0, 2)
        report_form.setColumnStretch(1, 1)
        report_form.addWidget(self.chk_include_unchanged, 1, 0, 1, 3)
        self._browse_buttons = (old_button, new_button, output_button)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(16)
        filter_label = QLabel("Change types")
        filter_label.setObjectName("hintLabel")
        filter_layout.addWidget(filter_label)
        for chk in (self.chk_added, self.chk_removed, self.chk_modified, self.chk_renamed):
            filter_layout.addWidget(chk)
        filter_layout.addStretch()
        report_form.addLayout(filter_layout, 2, 0, 1, 3)
        self.report_hint = QLabel("Change-type filters are ignored.")
        self.report_hint.setObjectName("hintLabel")
        self.report_hint.setWordWrap(True)
        self.report_hint.setVisible(False)
        report_form.addWidget(self.report_hint, 3, 0, 1, 3)

        # Action buttons
        self.run_button.setObjectName("primaryButton")
        self.run_button.setToolTip(
            "Compare two DBC files directly in Files mode. In Folders mode, use saved manual "
            "mapping, including Removed rows; otherwise use automatic matching. "
            "Saved ECU pairing applies in either mode."
        )
        self.manual_pair_button.setToolTip(
            "Choose which new-baseline file each old-baseline file is compared against."
        )
        self.ecu_pair_button.setToolTip(
            "Pair renamed ECU nodes to avoid routing changes caused only by node renaming."
        )
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.run_status, 1)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.run_button)

        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.open_button.setEnabled(False)
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Comparison progress and results will appear here.")
        self.log_view.setMinimumHeight(140)

        log_label = QLabel("Execution Log")
        log_label.setObjectName("hintLabel")

        # Keep actions outside the scroll area, including at the minimum size.
        baseline_content = QWidget()
        baseline_layout = QVBoxLayout(baseline_content)
        baseline_layout.setContentsMargins(0, 0, 0, 0)
        baseline_layout.setSpacing(10)
        baseline_layout.addWidget(input_group)
        baseline_layout.addWidget(report_group)
        baseline_layout.addWidget(log_label)
        baseline_layout.addWidget(self.log_view)
        baseline_tab = _scrollable(baseline_content)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(16, 12, 16, 12)
        central_layout.setSpacing(10)
        central_layout.addLayout(header)
        central_layout.addWidget(baseline_tab)
        central_layout.addWidget(self.progress)
        central_layout.addLayout(buttons)

        self.setCentralWidget(central)
        focus_order = (
            self.input_mode, self.old_input, old_button, self.new_input, new_button,
            self.manual_pair_button, self.ecu_pair_button, self.output_input, output_button,
            self.chk_include_unchanged, self.chk_added, self.chk_removed,
            self.chk_modified, self.chk_renamed, self.run_button, self.open_button,
        )
        for first, second in zip(focus_order, focus_order[1:]):
            QWidget.setTabOrder(first, second)

    def _wire_events(self) -> None:
        self.chk_include_unchanged.toggled.connect(self._update_change_filters)
        self.run_button.clicked.connect(self._run_compare)
        self.manual_pair_button.clicked.connect(self._open_manual_pairing)
        self.ecu_pair_button.clicked.connect(self._open_ecu_pairing)
        self.input_mode.currentIndexChanged.connect(self._on_input_mode_changed)
        self.open_button.clicked.connect(self._open_report)
        self.old_input.textChanged.connect(self._invalidate_saved_pairing)
        self.new_input.textChanged.connect(self._invalidate_saved_pairing)
        self.new_input.textChanged.connect(self._update_output_hint)

    def _current_folder_inputs(self) -> tuple[str, str]:
        return (self.old_input.text().strip(), self.new_input.text().strip())

    def _current_inputs(self) -> tuple[str, str, str]:
        return (*self._current_folder_inputs(), self.input_mode.currentData())

    def _files_mode(self) -> bool:
        return self.input_mode.currentData() == "files"

    def _on_input_mode_changed(self) -> None:
        self._clear_saved_pairing()
        kind = "DBC" if self._files_mode() else "Folder"
        self.old_label.setText(f"Old Baseline {kind}")
        self.new_label.setText(f"New Baseline {kind}")
        self.old_input.setAccessibleName(self.old_label.text())
        self.new_input.setAccessibleName(self.new_label.text())
        for field in (self.old_input, self.new_input):
            field.set_files_mode(self._files_mode())
        for side, button in zip(("old", "new"), self._browse_buttons[:2]):
            button.setAccessibleName(f"Browse {side} baseline {kind.lower()}")
        self.manual_pair_button.setEnabled(self.run_button.isEnabled() and not self._files_mode())
        self.pairing_hint.setText(
            "The selected DBC files are compared directly."
            if self._files_mode() else "Automatic DBC pairing by default."
        )
        self._update_output_hint()

    def _clear_saved_pairing(self) -> None:
        had_pairing = self._saved_pair_map is not None or bool(self._saved_ecu_map)
        self._saved_pair_map = None
        self._saved_pair_folders = None
        self._saved_ecu_map = {}
        self._saved_ecu_inputs = None
        if had_pairing:
            self._log("Baseline input changed — saved DBC and ECU pairing discarded.")

    def _invalidate_saved_pairing(self) -> None:
        if (
            self._saved_pair_folders and self._saved_pair_folders != self._current_folder_inputs()
        ) or (
            self._saved_ecu_inputs and self._saved_ecu_inputs != self._current_inputs()
        ):
            self._clear_saved_pairing()

    def _open_manual_pairing(self) -> bool:
        """Open the pairing dialog; returns True if a pairing was saved."""
        if self._files_mode():
            return False
        old_text, new_text = self._current_folder_inputs()
        # Guard empty text explicitly: Path("") is ".", which is_dir() accepts.
        if not old_text or not new_text or not Path(old_text).is_dir() or not Path(new_text).is_dir():
            QMessageBox.warning(self, "Invalid Input", "Select valid old and new baseline folders first.")
            return False
        old_folder = Path(old_text)
        new_folder = Path(new_text)

        previous = self._saved_pair_map if self._saved_pair_folders == self._current_folder_inputs() else None
        try:
            dialog = ManualPairingDialog(self, old_folder, new_folder, previous=previous)
        except OSError as exc:
            QMessageBox.critical(self, "Load Failed", f"Unable to scan folders: {exc}")
            return False

        previous_status = self.run_status.text()
        self.run_status.setText("Editing DBC pairing…")
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self.run_status.setText(previous_status)
        if not accepted:
            return False

        self._saved_pair_map = dialog.pair_map()
        self._saved_pair_folders = self._current_folder_inputs()
        paired = sum(1 for new_rel in self._saved_pair_map.values() if new_rel)
        unpaired = len(self._saved_pair_map) - paired
        if unpaired:
            self._log(
                f"Manual pairing saved: {paired} pair(s), {unpaired} old file(s) marked Removed"
            )
        else:
            self._log(
                f"Manual pairing saved: {paired} pair(s) — Run Compare will use it"
            )
        return True

    def _validated_baselines(self) -> tuple[Path, Path] | None:
        old_text, new_text = self._current_folder_inputs()
        paths = (Path(old_text), Path(new_text))
        if self._files_mode():
            valid = all(path.is_file() and path.suffix.lower() == ".dbc" for path in paths)
            expected = "DBC files"
        else:
            valid = all(path.is_dir() for path in paths)
            expected = "baseline folders"
        # Empty text must not be accepted as Path(""), which points to cwd.
        if not old_text or not new_text or not valid:
            QMessageBox.warning(self, "Invalid Input", f"Select valid old and new {expected}.")
            return None
        return paths

    def _open_ecu_pairing(self) -> None:
        paths = self._validated_baselines()
        if paths is None:
            return
        self._ecu_load_inputs = self._current_inputs()
        self._set_actions_enabled(False)
        self.open_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.run_status.setText("Loading ECU nodes…")
        self.ecu_worker = EcuDiscoveryWorker(*paths)
        self.ecu_worker.loaded.connect(self._on_ecu_nodes_loaded)
        self.ecu_worker.failed.connect(self._ecu_load_failed)
        self.ecu_worker.start()

    def _finish_ecu_loading(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        self._set_actions_enabled(True)
        self.open_button.setEnabled(self.last_report is not None)
        self.run_status.setText("Ready to compare")

    def _on_ecu_nodes_loaded(self, old_nodes: list[str], new_nodes: list[str]) -> None:
        if self._ecu_load_inputs != self._current_inputs():
            self._finish_ecu_loading()
            return
        previous = (
            self._saved_ecu_map if self._saved_ecu_inputs == self._current_inputs() else None
        )
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        self.run_status.setText("Editing ECU pairing…")
        try:
            dialog = EcuPairingDialog(self, old_nodes, new_nodes, previous=previous)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._saved_ecu_map = dialog.pair_map()
                self._saved_ecu_inputs = self._current_inputs()
                self._log(f"ECU pairing saved: {len(self._saved_ecu_map)} renamed node pair(s).")
        finally:
            self._finish_ecu_loading()

    def _ecu_load_failed(self, message: str) -> None:
        self._finish_ecu_loading()
        self._log(f"Unable to load ECU nodes: {message}")
        QMessageBox.critical(self, "ECU Load Failed", message)

    def _choose_baseline(self, target: QLineEdit) -> None:
        if self._files_mode():
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Baseline DBC", target.text().strip(), "DBC files (*.dbc)"
            )
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Baseline Folder")
        if path:
            # Qt hands back forward slashes; normalize to the native separator so
            # every path field reads the same way.
            target.setText(str(Path(path)))

    def _choose_report(self) -> None:
        suggested_path = self.output_input.text().strip()
        if not suggested_path:
            new_text = self.new_input.text().strip()
            if new_text:
                suggested_path = str(default_report_path(Path(new_text)))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Excel Report", suggested_path, "Excel (*.xlsx)"
        )
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.output_input.setText(str(Path(path)))

    def _update_output_hint(self) -> None:
        new_text = self.new_input.text().strip()
        if new_text:
            automatic = default_report_path(Path(new_text))
            self.output_input.setPlaceholderText(f"Automatic: {automatic}")
        else:
            self.output_input.setPlaceholderText(
                "Automatic: beside New DBC as compared_<file>.xlsx"
                if self._files_mode() else "Automatic: beside New folder as compared_<folder>.xlsx"
            )

    def _selected_change_types(self) -> set[str]:
        types: set[str] = set()
        if self.chk_added.isChecked():
            types.add("Added")
        if self.chk_removed.isChecked():
            types.add("Removed")
        if self.chk_modified.isChecked():
            types.add("Modified")
        if self.chk_renamed.isChecked():
            types.add("Renamed")
        return types

    def _complete_manual_pairing(self) -> dict[str, str | None] | None:
        """Honor saved mappings for these inputs, including explicit Removed rows."""
        pair_map = self._saved_pair_map
        if (
            not self._files_mode()
            and pair_map is not None
            and self._saved_pair_folders == self._current_folder_inputs()
        ):
            return pair_map
        return None

    def _run_compare(self) -> None:
        # A saved manual DBC mapping overrides automatic file pairing.
        pair_map = self._complete_manual_pairing()
        self._start_compare(pair_map=pair_map)

    def _start_compare(self, pair_map: dict[str, str | None] | None) -> None:
        paths = self._validated_baselines()
        if paths is None:
            return
        old_folder, new_folder = paths
        if self._files_mode():
            pair_map = None
        output_text = self.output_input.text().strip()
        output_path = Path(output_text) if output_text else default_report_path(new_folder)
        if output_path.suffix.lower() != ".xlsx":
            QMessageBox.warning(self, "Invalid Output", "Report path must end with .xlsx.")
            return

        selected = self._selected_change_types()
        if not selected and not self.chk_include_unchanged.isChecked():
            QMessageBox.warning(self, "No Filter Selected", "Select at least one change type to include.")
            return

        self._pending_output_path = output_path
        self.log_view.clear()
        pairing = (
            "direct file comparison" if self._files_mode()
            else "manual pairing" if pair_map is not None else "auto pairing"
        )
        ecu_map = self._saved_ecu_map if self._saved_ecu_inputs == self._current_inputs() else {}
        mode = ", include unchanged" if self.chk_include_unchanged.isChecked() else ", changes only"
        self._log(f"Starting comparison ({pairing}{mode})...")
        if ecu_map:
            self._log(f"Using {len(ecu_map)} ECU node pair(s).")
        self.progress.setRange(0, 0)
        self.progress.show()
        self.run_status.setText("Comparing baselines…")
        self._set_actions_enabled(False)
        self.open_button.setEnabled(False)
        self.worker = CompareWorker(
            old_folder, new_folder, pair_map,
            include_unchanged=self.chk_include_unchanged.isChecked(),
            ecu_map=ecu_map,
        )
        self.worker.log.connect(self._log)
        self.worker.compared.connect(self._on_compared)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _set_actions_enabled(self, enabled: bool) -> None:
        self.run_button.setEnabled(enabled)
        self.manual_pair_button.setEnabled(enabled and not self._files_mode())
        self.ecu_pair_button.setEnabled(enabled)
        self.input_mode.setEnabled(enabled)
        self.chk_include_unchanged.setEnabled(enabled)
        for control in (self.old_input, self.new_input, self.output_input, *self._browse_buttons):
            control.setEnabled(enabled)
        self._update_change_filters()

    def _update_change_filters(self) -> None:
        enabled = self.run_button.isEnabled() and not self.chk_include_unchanged.isChecked()
        for chk in (self.chk_added, self.chk_removed, self.chk_modified, self.chk_renamed):
            chk.setEnabled(enabled)
        self.report_hint.setVisible(self.chk_include_unchanged.isChecked())

    def _on_compared(self, result: ComparisonResult) -> None:
        result = filter_result(result, self._selected_change_types())
        self.run_status.setText("Writing Excel report…")
        self.export_worker = ExportWorker(result, self._pending_output_path)
        self.export_worker.log.connect(self._log)
        self.export_worker.completed.connect(self._completed)
        self.export_worker.failed.connect(self._failed)
        self.export_worker.start()

    def _restore_paths(self) -> None:
        # Older sessions may have stored forward-slash paths; normalize on load
        # so all three fields use the native separator.
        mode_index = self.input_mode.findData(self._settings.value("input_mode", "folders"))
        self.input_mode.setCurrentIndex(max(0, mode_index))
        if val := self._settings.value("last_old_folder"):
            self.old_input.setText(str(Path(str(val))))
        if val := self._settings.value("last_new_folder"):
            self.new_input.setText(str(Path(str(val))))
        report_path_is_explicit = self._settings.value(
            "report_path_is_explicit", False, type=bool
        )
        if report_path_is_explicit and (val := self._settings.value("last_report_path")):
            self.output_input.setText(str(Path(str(val))))

    def _save_paths(self) -> None:
        self._settings.setValue("input_mode", self.input_mode.currentData())
        self._settings.setValue("last_old_folder", self.old_input.text())
        self._settings.setValue("last_new_folder", self.new_input.text())
        self._settings.setValue("last_report_path", self.output_input.text())
        self._settings.setValue(
            "report_path_is_explicit", bool(self.output_input.text().strip())
        )

    def _completed(self, report_path: Path, summary: dict) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.hide()
        self._set_actions_enabled(True)
        self.open_button.setEnabled(True)
        self.last_report = report_path
        status = "Report incomplete" if summary.get("completeness") == "Incomplete" else "Report ready"
        self.run_status.setText(f"{status} · {summary['Total Changes']} changes · "
                               f"{summary.get('parse_error_count', 0)} file errors · "
                               f"{summary.get('review_count', 0)} pairs require review")
        self._log(f"Report generated: {report_path}")
        self._log(f"Total changes: {summary['Total Changes']}")
        self._save_paths()

    def _failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        self._set_actions_enabled(True)
        self.run_status.setText("Comparison failed — see log")
        self._log(f"Failed: {message}")
        QMessageBox.critical(self, "Comparison Failed", message)

    def _open_report(self) -> None:
        if self.last_report and self.last_report.exists():
            os.startfile(self.last_report)
        else:
            QMessageBox.information(
                self, "Report Not Found", "The report file no longer exists. Run the comparison again."
            )

    def closeEvent(self, event) -> None:
        running = [
            w for w in (self.worker, self.export_worker, self.ecu_worker) if w and w.isRunning()
        ]
        if running:
            reply = QMessageBox.question(
                self,
                "Comparison Running",
                "A comparison is still running. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # Detach signals, then stop the threads before Qt destroys them,
            # otherwise the app crashes with "QThread destroyed while running".
            for worker in running:
                worker.disconnect()
                worker.terminate()
                worker.wait(3000)
        event.accept()

    def _show_help_document(self, title: str, filename: str) -> None:
        try:
            content = _read_resource_text(filename)
        except OSError as exc:
            QMessageBox.critical(self, title, f"Unable to open help file: {exc}")
            return
        self._show_markdown(title, content)

    def _show_changelog(self) -> None:
        try:
            content = _changelog_path().read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Changelog", f"Unable to open the changelog: {exc}")
            return
        self._show_markdown("Changelog", content)

    def _show_markdown(self, title: str, content: str) -> None:
        content = content.replace("{version}", __version__)

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        viewer = QTextBrowser()
        viewer.setOpenExternalLinks(True)
        viewer.setMarkdown(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(viewer)
        layout.addWidget(buttons)
        dialog.exec()

    def _log(self, message: str) -> None:
        self.log_view.append(message)


def main() -> int:
    app = QApplication(sys.argv)
    icon_path = _resource_path("app.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(_STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
