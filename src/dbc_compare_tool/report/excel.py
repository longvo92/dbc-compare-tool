from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from dbc_compare_tool.core.models import Change, ComparisonResult, FilePairSummary, Message, Signal
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

_OLD_VAL_FILL = "FCE4D6"   # light salmon — what it was
_NEW_VAL_FILL = "E2EFDA"   # light green  — what it became

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

# Append context columns to preserve the existing report columns and their order.
_CONTEXT_HEADERS = [
    f"{label} ({side})"
    for label in ("CAN ID", "ECU Node Tx", "ECU Node Rx")
    for side in ("Old", "New")
]
_MESSAGE_FIELDS = (
    ("DLC", "dlc"), ("Extended Frame", "is_extended_frame"),
    ("Cycle Time (ms)", "cycle_time_ms"), ("Signal Count", "signals"),
    ("Message Description", "comment"),
)
_SIGNAL_FIELDS = (
    ("Start Bit", "start_bit"), ("Length", "length"), ("Byte Order", "byte_order"),
    ("Value Type", "value_type"), ("Signed", "is_signed"), ("Factor", "factor"),
    ("Offset", "offset"), ("Minimum", "minimum"), ("Maximum", "maximum"),
    ("Unit", "unit"), ("Multiplexer", "is_multiplexer"),
    ("Multiplexer IDs", "multiplexer_ids"), ("Multiplexer Signal", "multiplexer_signal"),
    ("Value Descriptions", "value_descriptions"), ("Signal Description", "comment"),
)


def default_report_path(new_folder: Path) -> Path:
    """Place an automatically named report beside the new baseline folder."""
    return new_folder.parent / f"compared_{new_folder.name}.xlsx"


def write_excel_report(result: ComparisonResult, output_path: Path) -> Path:
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    overview_sheet = workbook.create_sheet("DBC Overview")
    message_sheet = workbook.create_sheet("Message Details")
    signal_sheet = workbook.create_sheet("Signal Details")
    diff_sheet = workbook.create_sheet("Property Diff")

    _write_summary(summary_sheet, result)
    _write_overview(overview_sheet, result.file_pairs)
    _write_message_details(message_sheet, result.message_changes)
    _write_signal_details(signal_sheet, result.signal_changes)
    _write_property_diff(diff_sheet, result.message_changes, result.signal_changes)

    _format_summary(summary_sheet)
    _format_overview_sheet(overview_sheet)
    _format_detail_sheet(message_sheet, change_col=2, conf_score_col=6, conf_level_col=7)
    _format_detail_sheet(signal_sheet, change_col=3, conf_score_col=6, conf_level_col=7)
    _format_property_diff_sheet(diff_sheet)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return output_path


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _write_summary(sheet, result: ComparisonResult) -> None:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheet.append(["DBC Compare Tool  —  Comparison Report", generated])
    sheet.append([])                                           # blank separator
    sheet.append(["Metric", "Count"])
    summary = result.summary()
    for metric in SUMMARY_ORDER:
        sheet.append([metric, summary.get(metric, 0)])
    for metric in summary:
        if metric not in SUMMARY_ORDER:
            sheet.append([metric, summary[metric]])
    sheet.append(["Report Mode", "Include Unchanged" if result.include_unchanged else "Changes only"])
    sheet.append(["Parse Errors (skipped DBCs)", sum(fp.status == "Parse Error" for fp in result.file_pairs)])


def _write_overview(sheet, file_pairs: list[FilePairSummary]) -> None:
    sheet.append([
        "DBC File",
        "Status",
        "Old Path",
        "New Path",
        "Pairing Confidence",
        "Messages (Old)",
        "Messages (New)",
        "Signals (Old)",
        "Signals (New)",
        "Pairing Reason",
    ])
    for fp in file_pairs:
        sheet.append([
            fp.dbc_file,
            fp.status,
            fp.old_path,
            fp.new_path,
            _fmt_confidence(fp.pairing_confidence),
            fp.message_count_old,
            fp.message_count_new,
            fp.signal_count_old,
            fp.signal_count_new,
            "; ".join(fp.pairing_reasons),
        ])


def _write_message_details(sheet, changes: list[Change]) -> None:
    sheet.append([
        "DBC File",
        "Change Type",
        "Old Message Name",
        "New Message Name",
        "CAN ID",
        "Confidence Score",
        "Confidence Level",
        "Change Description",
        *_CONTEXT_HEADERS,
        *_field_headers(_MESSAGE_FIELDS),
    ])
    for change in changes:
        sheet.append([
            change.dbc_file,
            change.change_type,
            change.old_name,
            change.new_name,
            _fmt_can_id(change.can_id),
            _fmt_confidence(change.confidence),
            change.confidence_level,
            change.description,
            *_context_values(change),
            *_field_values(change.old_message, change.new_message, _MESSAGE_FIELDS),
        ])


def _write_signal_details(sheet, changes: list[Change]) -> None:
    sheet.append([
        "DBC File",
        "Parent Message",
        "Change Type",
        "Old Signal Name",
        "New Signal Name",
        "Confidence Score",
        "Confidence Level",
        "Changed Properties",
        "Parent Message (Old)",
        "Parent Message (New)",
        *_CONTEXT_HEADERS,
        *_field_headers(_MESSAGE_FIELDS),
        *_field_headers(_SIGNAL_FIELDS),
    ])
    for change in changes:
        sheet.append([
            change.dbc_file,
            change.parent_message,
            change.change_type,
            change.old_name,
            change.new_name,
            _fmt_confidence(change.confidence),
            change.confidence_level,
            change.description,
            change.old_message.name if change.old_message else "",
            change.new_message.name if change.new_message else "",
            *_context_values(change, signal=True),
            *_field_values(change.old_message, change.new_message, _MESSAGE_FIELDS),
            *_field_values(change.old_signal, change.new_signal, _SIGNAL_FIELDS),
        ])


def _write_property_diff(
    sheet,
    message_changes: list[Change],
    signal_changes: list[Change],
) -> None:
    sheet.append([
        "DBC File",
        "Entity Type",
        "Old Name",
        "New Name",
        "Parent Message",
        "Change Type",
        "Property",
        "Old Value",
        "New Value",
        *_CONTEXT_HEADERS,
    ])
    for change in message_changes:
        for prop, old_val, new_val in change.property_diffs:
            sheet.append([
                change.dbc_file,
                "Message",
                change.old_name,
                change.new_name,
                "",
                change.change_type,
                prop,
                old_val,
                new_val,
                *_context_values(change),
            ])
    for change in signal_changes:
        for prop, old_val, new_val in change.property_diffs:
            sheet.append([
                change.dbc_file,
                "Signal",
                change.old_name,
                change.new_name,
                change.parent_message,
                change.change_type,
                prop,
                old_val,
                new_val,
                *_context_values(change, signal=True),
            ])


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_summary(sheet) -> None:
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
    for row_idx in range(4, sheet.max_row + 1):
        metric = sheet.cell(row_idx, 1).value
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
        sheet.row_dimensions[row_idx].height = 18

    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 24
    sheet.freeze_panes = "A4"


def _format_overview_sheet(sheet) -> None:
    header_fill = PatternFill("solid", fgColor=_HEADER_BG)
    header_font = Font(color=_HEADER_FG, bold=True, size=11)

    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
    sheet.row_dimensions[1].height = 26

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row_idx, row in enumerate(sheet.iter_rows(min_row=2), start=2):
        status = str(row[1].value or "")
        row_fill = PatternFill("solid", fgColor=_STATUS_FILL.get(status, "FFFFFF"))
        for cell in row:
            cell.fill = row_fill
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = _BORDER
        sheet.row_dimensions[row_idx].height = 18

    for col_cells in sheet.columns:
        max_len = max(len(str(cell.value or "")) for cell in col_cells)
        col_letter = get_column_letter(col_cells[0].column)
        sheet.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 60)


def _format_detail_sheet(
    sheet,
    change_col: int,
    conf_score_col: int,
    conf_level_col: int,
) -> None:
    header_fill = PatternFill("solid", fgColor=_HEADER_BG)
    header_font = Font(color=_HEADER_FG, bold=True, size=11)

    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
    sheet.row_dimensions[1].height = 26

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row_idx, row in enumerate(sheet.iter_rows(min_row=2), start=2):
        change_type = str(row[change_col - 1].value or "")
        row_bg = _CHANGE_ROW_FILL.get(change_type, "FFFFFF")
        row_fill = PatternFill("solid", fgColor=row_bg)

        for cell in row:
            cell.fill = row_fill
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = _BORDER

        # Highlight confidence level cell individually
        conf_cell = row[conf_level_col - 1]
        conf_level = str(conf_cell.value or "")
        if conf_level in _CONF_FILL:
            conf_cell.fill = PatternFill("solid", fgColor=_CONF_FILL[conf_level])
            conf_cell.font = Font(bold=True)
            conf_cell.alignment = Alignment(horizontal="center", vertical="top")

        # Center-align confidence score
        row[conf_score_col - 1].alignment = Alignment(horizontal="center", vertical="top")

        sheet.row_dimensions[row_idx].height = 18

    # Auto-width columns (capped at 60)
    for col_cells in sheet.columns:
        max_len = max(len(str(cell.value or "")) for cell in col_cells)
        col_letter = get_column_letter(col_cells[0].column)
        sheet.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 60)


def _format_property_diff_sheet(sheet) -> None:
    header_fill = PatternFill("solid", fgColor=_HEADER_BG)
    header_font = Font(color=_HEADER_FG, bold=True, size=11)

    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
    sheet.row_dimensions[1].height = 26

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row_idx, row in enumerate(sheet.iter_rows(min_row=2), start=2):
        change_type = str(row[5].value or "")  # column 6 = Change Type
        row_fill = PatternFill("solid", fgColor=_CHANGE_ROW_FILL.get(change_type, "FFFFFF"))

        for cell in row:
            cell.fill = row_fill
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = _BORDER

        row[7].fill = PatternFill("solid", fgColor=_OLD_VAL_FILL)  # Old Value — salmon
        row[8].fill = PatternFill("solid", fgColor=_NEW_VAL_FILL)  # New Value — green
        sheet.row_dimensions[row_idx].height = 18

    for col_cells in sheet.columns:
        max_len = max(len(str(cell.value or "")) for cell in col_cells)
        col_letter = get_column_letter(col_cells[0].column)
        sheet.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 50)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field_headers(fields: tuple[tuple[str, str], ...]) -> list[str]:
    return [f"{label} ({side})" for label, _ in fields for side in ("Old", "New")]


def _field_values(
    old: Message | Signal | None,
    new: Message | Signal | None,
    fields: tuple[tuple[str, str], ...],
) -> list[object]:
    values = []
    for _, attr in fields:
        for entity in (old, new):
            value = getattr(entity, attr) if entity is not None else None
            if attr == "signals" and value is not None:
                value = len(value)
            elif attr == "byte_order" and value is not None:
                value = "Intel/little-endian (1)" if value == 1 else "Motorola/big-endian (0)"
            elif attr == "value_descriptions" and value is not None:
                value = ", ".join(f"{raw}={label}" for raw, label in value)
            elif isinstance(value, tuple):
                value = ", ".join(str(item) for item in value)
            values.append(value)
    return values


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
        _fmt_can_id(old.can_id) if old else "",
        _fmt_can_id(new.can_id) if new else "",
        old.transmitter if old else "",
        new.transmitter if new else "",
        old_rx, new_rx,
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
