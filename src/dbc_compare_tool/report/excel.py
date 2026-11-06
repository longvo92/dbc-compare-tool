from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime
from functools import partial
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from dbc_compare_tool.core.models import Change, ComparisonResult, FilePairSummary, Message
from dbc_compare_tool.i18n import LANGUAGES, reason_text, translate
from dbc_compare_tool.report._style import BORDER, HEADER_BG, HEADER_FG


SUMMARY_ORDER = [
    "Messages Added",
    "Messages Removed",
    "Messages Modified",
    "Messages Renamed",
    "Signals Added",
    "Signals Removed",
    "Signals Modified",
    "Signals Renamed",
    "Total Changes",
]

_HEADER_BG = HEADER_BG
_HEADER_FG = HEADER_FG

# Row background color keyed by change_type
_CHANGE_ROW_FILL: dict[str, str] = {
    "Added":    "E2EFDA",   # light green
    "Removed":  "FCE4D6",   # light salmon
    "Modified": "FFF2CC",   # light yellow
    "Renamed":  "DDEBF7",   # light blue
    "Unchanged": "F2F2F2",  # light gray
}

# Confidence level cell highlight
_CONF_FILL: dict[str, str] = {
    "High":   "C6EFCE",   # green
    "Medium": "FFEB9C",   # yellow
    "Low":    "FFC7CE",   # pink-red
}

# Summary metric row colors (matches grouping)
_SUMMARY_METRIC_FILL: dict[str, str] = {
    "Messages Added":    "E8F8F5",
    "Messages Removed":  "FDEDEC",
    "Messages Modified": "FEF9E7",
    "Messages Renamed":  "EBF5FB",
    "Signals Added":     "E9F7EF",
    "Signals Removed":   "FDEDEC",
    "Signals Modified":  "FEF9E7",
    "Signals Renamed":   "EBF5FB",
    "Total Changes":     "F0F0F0",
}

# Overview sheet status row colors
_STATUS_FILL: dict[str, str] = {
    "Matched":         "F2F2F2",   # light gray
    "DBC Added":       "E2EFDA",   # light green
    "DBC Removed":     "FCE4D6",   # light salmon
    "DBC Renamed":     "DDEBF7",   # light blue
    "Manually Paired": "E4DFEC",   # light purple
    "Parse Error":     "FFC7CE",   # pink-red
}

_BORDER = BORDER

# Keep identity and routing context available for impact-review filtering.
_CONTEXT_HEADERS = ["CAN ID", "ECU Node Tx", "ECU Node Rx"]
EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_CELL_LENGTH = 32_767


class ReportExportError(ValueError):
    pass


def _append(sheet, values):
    if any(isinstance(value, str) and len(value) > EXCEL_MAX_CELL_LENGTH for value in values):
        raise ReportExportError(f"Excel cell text limit exceeded in {sheet.title}")
    # Bulk row counts are prevalidated; every sheet is checked before saving.
    # Worksheet.max_row scans existing cells, so querying it here is quadratic.
    sheet.append(values)


def _safe_baseline_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "root"


def _shorten_baseline_name(name: str) -> str:
    encoded = name.encode("utf-8", errors="replace")
    if len(encoded) <= 100:
        return name
    digest = hashlib.sha256(encoded).hexdigest()[:10]
    return encoded[:89].decode("utf-8", errors="ignore") + "_" + digest


def default_report_path(old_path: Path, new_path: Path) -> Path:
    """Use both baseline names and place the report beside NEW."""
    old_path, new_path = Path(old_path), Path(new_path)
    paths = [Path(os.path.abspath(path)) for path in (old_path, new_path)]
    labels = [
        _safe_baseline_name(path.stem if not path.is_dir() and path.suffix.lower() == ".dbc" else path.name)
        for path in paths
    ]
    if labels[0].casefold() == labels[1].casefold() and paths[0] != paths[1]:
        qualified = labels[:]
        for old_parent, new_parent in zip(paths[0].parents, paths[1].parents):
            qualified = [
                f"{_safe_baseline_name(parent.name or parent.anchor)}_{label}"
                for parent, label in zip((old_parent, new_parent), qualified)
            ]
            if qualified[0].casefold() != qualified[1].casefold():
                break
        if qualified[0].casefold() == qualified[1].casefold():
            qualified = [
                f"{label}_{hashlib.sha256(os.fsencode(path)).hexdigest()[:10]}"
                for label, path in zip(labels, paths)
            ]
        labels = qualified
    old_name, new_name = map(_shorten_baseline_name, labels)
    return new_path.parent / f"compared_{old_name}_vs_{new_name}.xlsx"


def write_excel_report(result: ComparisonResult, output_path: Path, *, language: str = "en") -> Path:
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported report language: {language}")
    tr = partial(translate, language)
    render_reason = partial(reason_text, language)
    for count in (len(result.message_changes), len(result.signal_changes), len(result.file_pairs)):
        if count + 1 > EXCEL_MAX_ROWS:
            raise ReportExportError("Excel row limit exceeded")
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = tr("Summary")
    if not result.is_file_comparison:
        overview_sheet = workbook.create_sheet(tr("DBC Overview"))
        _write_overview(overview_sheet, result.file_pairs, tr, render_reason, bool(result.focus_nodes))
        _format_overview_sheet(overview_sheet, result.file_pairs)
    message_sheet = workbook.create_sheet(tr("Message Details"))
    signal_sheet = workbook.create_sheet(tr("Signal Details"))

    summary_keys = _write_summary(summary_sheet, result, tr)
    _write_message_details(message_sheet, result.message_changes, tr, render_reason)
    _write_signal_details(signal_sheet, result.signal_changes, tr, render_reason)

    _format_summary(summary_sheet, summary_keys, result.completeness)
    _format_detail_sheet(message_sheet, result.message_changes, conf_score_col=6, conf_level_col=7)
    _format_detail_sheet(signal_sheet, result.signal_changes, conf_score_col=7, conf_level_col=8)

    for sheet in workbook:
        if sheet.max_row > EXCEL_MAX_ROWS:
            raise ReportExportError("Excel row limit exceeded")
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    if len(cell.value) > EXCEL_MAX_CELL_LENGTH:
                        raise ReportExportError(f"Excel cell text limit exceeded in {sheet.title}")
                    cell.data_type = "s"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(suffix=".xlsx", dir=output_path.parent)
    os.close(descriptor)
    try:
        workbook.save(temporary)
        os.replace(temporary, output_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
        workbook.close()
    return output_path


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _write_summary(sheet, result: ComparisonResult, tr) -> list[str]:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    _append(sheet, [tr("DBC Compare Tool  —  Comparison Report"), generated])
    _append(sheet, [])
    _append(sheet, [tr("Metric"), tr("Count")])
    keys: list[str] = []

    def row(key: str, value=None, *, caption: str | None = None) -> None:
        keys.append(key)
        _append(sheet, [tr(key) if caption is None else caption, value])

    summary = result.summary()
    for metric in SUMMARY_ORDER:
        row(metric, summary.get(metric, 0))
    for metric in summary:
        if metric not in SUMMARY_ORDER:
            row(metric, summary[metric])
    row("Report Mode", tr("Include Unchanged" if result.include_unchanged else "Changes only"))
    row("Parse Errors (skipped DBCs)", len(result.diagnostics))
    row("Completeness", tr(result.completeness))
    row("Matching Policy", result.policy_version)
    if result.old_path is not None:
        row("Old Baseline", str(result.old_path))
    if result.new_path is not None:
        row("New Baseline", str(result.new_path))
    if result.focus_nodes:
        row("ECU Focus", ", ".join(result.focus_nodes))
        row("Focus Scope", tr("Tx/Rx on either baseline"))
        for old, new in result.focus_pairs:
            row("Focus ECU Pair", _fmt_transition(old, new))
        if not summary["Total Changes"]:
            row("No changes in focus")
        row("Coverage Scope", tr("Entire input"))
    for group, counts in result.coverage.items():
        details = [f"{tr(key)}: {counts.get(key, 0)}" for key in ("paired", "unmatched", "not compared")]
        if "unknown" in counts:
            details.append(tr("unreadable entities: Unknown"))
        row("Coverage", "; ".join(details), caption=tr("Coverage {group}", group=group))
    for diagnostic in result.diagnostics:
        row("Parse Error", diagnostic.reason, caption=f"{tr('Parse Error')} {diagnostic.side} {diagnostic.path}")
    if result.ecu_map and not result.focus_nodes:
        row("")
        row("ECU Node")
        for old_node, new_node in sorted(result.ecu_map.items()):
            row("", caption=str(_fmt_transition(old_node, new_node)))
    return keys


def _write_overview(sheet, file_pairs: list[FilePairSummary], tr, render_reason, focused: bool) -> None:
    _append(sheet, [tr(key) for key in (
        "Status",
        "Path",
        "Pairing Confidence",
        "Messages (whole DBC)" if focused else "Messages",
        "Signals (whole DBC)" if focused else "Signals",
        "Pairing Reason",
    )])
    for fp in file_pairs:
        _append(sheet, [
            tr(fp.status),
            _fmt_transition(fp.old_path, fp.new_path, change_type=fp.status),
            _fmt_confidence(fp.pairing_confidence),
            _fmt_transition(fp.message_count_old if fp.message_count_old is not None else tr("Unknown"),
                            fp.message_count_new if fp.message_count_new is not None else tr("Unknown"), change_type=fp.status),
            _fmt_transition(fp.signal_count_old if fp.signal_count_old is not None else tr("Unknown"),
                            fp.signal_count_new if fp.signal_count_new is not None else tr("Unknown"), change_type=fp.status),
            "; ".join(map(render_reason, fp.pairing_reasons)),
        ])


def _write_message_details(sheet, changes: list[Change], tr, render_reason) -> None:
    _append(sheet, [tr(key) for key in (
        "DBC File",
        "Change Type",
        "Old Message Name",
        "New Message Name",
        "CAN ID",
        "Confidence Score",
        "Confidence Level",
        "Match Reason",
        *_CONTEXT_HEADERS[1:],
        "Changed Properties",
    )])
    for change in changes:
        can_id, transmitter, receivers = _context_values(change)
        _append(sheet, [
            _dbc_label(change.dbc_file),
            tr(change.change_type),
            change.old_name,
            change.new_name,
            can_id or _fmt_can_id(change.can_id),
            _fmt_confidence(change.confidence),
            tr(change.confidence_level),
            _match_reason(change, render_reason),
            transmitter,
            receivers,
            _changed_properties(change),
        ])


def _write_signal_details(sheet, changes: list[Change], tr, render_reason) -> None:
    _append(sheet, [tr(key) for key in (
        "DBC File",
        "Parent Message (Old)",
        "Parent Message (New)",
        "Change Type",
        "Old Signal Name",
        "New Signal Name",
        "Confidence Score",
        "Confidence Level",
        "Match Reason",
        *_CONTEXT_HEADERS,
        "Changed Properties",
    )])
    for change in changes:
        _append(sheet, [
            _dbc_label(change.dbc_file),
            *_parent_message_names(change),
            tr(change.change_type),
            change.old_name,
            change.new_name,
            _fmt_confidence(change.confidence),
            tr(change.confidence_level),
            _match_reason(change, render_reason),
            *_context_values(change, signal=True),
            _changed_properties(change),
        ])


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_summary(sheet, keys: list[str], completeness: str) -> None:
    # Row 1 — report title
    title_cell = sheet.cell(row=1, column=1)
    title_cell.font = Font(bold=True, size=13, color="1F4E78")
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    sheet.row_dimensions[1].height = 26

    date_cell = sheet.cell(row=1, column=2)
    date_cell.font = Font(italic=True, size=10, color="595959")
    date_cell.alignment = Alignment(horizontal="right", vertical="center")

    # Row 3 — column headers
    header_fill = PatternFill("solid", fgColor=_HEADER_BG)
    header_font = Font(color=_HEADER_FG, bold=True, size=11)
    for cell in sheet[3]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER
    sheet.row_dimensions[3].height = 22

    # Rows 4+ — metric data
    for row_idx, metric in enumerate(keys, start=4):
        row = sheet[row_idx]
        bg = _SUMMARY_METRIC_FILL.get(metric, "FFFFFF")
        fill = PatternFill("solid", fgColor=bg)
        for cell in row:
            cell.fill = fill
            cell.border = _BORDER
            cell.alignment = Alignment(vertical="center")
        if metric == "Total Changes":
            for cell in row:
                cell.font = Font(bold=True, size=11)
        elif metric == "ECU Node":
            for cell in row:
                cell.fill = header_fill
                cell.font = header_font
        if metric == "Completeness" and completeness == "Incomplete":
            for cell in row:
                cell.fill = PatternFill("solid", fgColor="FFC7CE")
                cell.font = Font(bold=True, color="9C0006")
        sheet.row_dimensions[row_idx].height = 18

    for column, default_width in (("A", 30), ("B", 24)):
        max_len = max(len(str(cell.value or "")) for cell in sheet[column][2:])
        sheet.column_dimensions[column].width = min(max(default_width, max_len + 2), 60)
    sheet.freeze_panes = "A4"


def _format_overview_sheet(sheet, pairs: list[FilePairSummary]) -> None:
    header_fill = PatternFill("solid", fgColor=_HEADER_BG)
    header_font = Font(color=_HEADER_FG, bold=True, size=11)
    status_fills = {status: PatternFill("solid", fgColor=color)
                    for status, color in _STATUS_FILL.items()}
    default_fill = PatternFill("solid", fgColor="FFFFFF")
    body_alignment = Alignment(wrap_text=True, vertical="top")

    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
    sheet.row_dimensions[1].height = 26

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row_idx, (row, pair) in enumerate(zip(sheet.iter_rows(min_row=2), pairs), start=2):
        row_fill = status_fills.get(pair.status, default_fill)
        for cell in row:
            cell.fill = row_fill
            cell.alignment = body_alignment
            cell.border = _BORDER
        sheet.row_dimensions[row_idx].height = 18

    for col_cells in sheet.columns:
        max_len = max(len(str(cell.value or "")) for cell in col_cells)
        col_letter = get_column_letter(col_cells[0].column)
        sheet.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 60)


def _format_detail_sheet(
    sheet,
    changes: list[Change],
    conf_score_col: int,
    conf_level_col: int,
) -> None:
    header_fill = PatternFill("solid", fgColor=_HEADER_BG)
    header_font = Font(color=_HEADER_FG, bold=True, size=11)
    row_fills = {kind: PatternFill("solid", fgColor=color)
                 for kind, color in _CHANGE_ROW_FILL.items()}
    default_fill = PatternFill("solid", fgColor="FFFFFF")
    confidence_fills = {level: PatternFill("solid", fgColor=color)
                        for level, color in _CONF_FILL.items()}
    body_alignment = Alignment(wrap_text=True, vertical="top")
    centered_alignment = Alignment(horizontal="center", vertical="top")
    bold_font = Font(bold=True)

    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
    sheet.row_dimensions[1].height = 26

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row, change in zip(sheet.iter_rows(min_row=2), changes):
        row_fill = row_fills.get(change.change_type, default_fill)

        for cell in row:
            cell.fill = row_fill
            cell.alignment = body_alignment
            cell.border = _BORDER

        # Highlight confidence level cell individually
        conf_cell = row[conf_level_col - 1]
        conf_level = change.confidence_level
        if conf_level in _CONF_FILL:
            conf_cell.fill = confidence_fills[conf_level]
            conf_cell.font = bold_font
            conf_cell.alignment = centered_alignment

        # Center-align confidence score
        row[conf_score_col - 1].alignment = centered_alignment

    # Auto-width columns (capped at 60)
    for col_cells in sheet.columns:
        max_len = max(len(str(cell.value or "")) for cell in col_cells)
        col_letter = get_column_letter(col_cells[0].column)
        sheet.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 60)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _changed_properties(change: Change) -> str:
    """Keep all property deltas in the entity's detail row."""
    return "; ".join(
        f"{prop}: {_fmt_transition(old, new, change_type=change.change_type)}"
        for prop, old, new in change.property_diffs
    )


def _fmt_transition(
    old: str | int | None, new: str | int | None, *, change_type: str = "",
) -> str | int:
    """Show only the existing side for additions/removals; retain other deltas."""
    old = "" if old is None else old
    new = "" if new is None else new
    if change_type in {"Added", "DBC Added"}:
        return new
    if change_type in {"Removed", "DBC Removed"}:
        return old
    return old if old == new else f"{old}->{new}"


def _dbc_label(label: str) -> str:
    old, separator, new = label.partition(" -> ")
    return _fmt_transition(old, new) if separator else label


def _parent_message_names(change: Change) -> tuple[str, str]:
    if change.old_message is None and change.new_message is None:
        return (
            change.parent_message if change.change_type != "Added" else "",
            change.parent_message if change.change_type != "Removed" else "",
        )
    return (
        change.old_message.name if change.old_message else "",
        change.new_message.name if change.new_message else "",
    )


def _match_reason(change: Change, render_reason) -> str:
    """Retain rename evidence without copying technical property changes."""
    if change.change_type != "Renamed":
        return ""
    if change.match_reasons:
        return ", ".join(map(render_reason, change.match_reasons))
    # Results constructed by external callers may still provide only description.
    marker = "Matched by: "
    for line in reversed(change.description.splitlines()):
        if line.startswith(marker):
            return line[len(marker):]
    return ""


def _message_receivers(message: Message | None) -> str:
    if message is None:
        return ""
    return ", ".join(sorted({node for signal in message.signals.values() for node in signal.receivers}))


def _context_values(change: Change, signal: bool = False) -> list[str]:
    old, new = change.old_message, change.new_message
    if signal:
        old_rx = ", ".join(change.old_signal.receivers) if change.old_signal else ""
        new_rx = ", ".join(change.new_signal.receivers) if change.new_signal else ""
    else:
        old_rx, new_rx = _message_receivers(old), _message_receivers(new)
    return [
        _fmt_transition(
            _fmt_can_id(old.can_id) if old else "", _fmt_can_id(new.can_id) if new else "",
            change_type=change.change_type,
        ),
        _fmt_transition(old.transmitter if old else "", new.transmitter if new else "", change_type=change.change_type),
        _fmt_transition(old_rx, new_rx, change_type=change.change_type),
    ]


def _fmt_confidence(confidence: float | None) -> str:
    return "" if confidence is None else f"{confidence:.2f}"


def _fmt_can_id(can_id: int | None) -> str:
    if can_id is None:
        return ""
    try:
        return f"0x{int(can_id):X}"
    except (TypeError, ValueError):
        return str(can_id)
