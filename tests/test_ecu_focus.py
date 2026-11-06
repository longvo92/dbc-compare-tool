from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import load_workbook

from dbc_compare_tool.cli import main
from dbc_compare_tool.core.comparator import DbcComparator, filter_result
from dbc_compare_tool.core.focus import apply_ecu_focus
from dbc_compare_tool.core.models import DbcDatabase, Message, Signal
from dbc_compare_tool.report.excel import write_excel_report


def signal(name, start, *receivers):
    return Signal(name, start, 8, 1, "unsigned", False, 1, 0, 0, 255, "", receivers)


def database(*messages, nodes=()):
    return DbcDatabase(Path("bus.dbc"), {message.name: message for message in messages}, nodes)


def rows(sheet):
    headers = next(sheet.values)
    return [dict(zip(headers, row)) for row in sheet.iter_rows(min_row=2, values_only=True)]


DBC = """VERSION ""
BU_: Tx Rx Spare
BO_ 100 Status: 8 Tx
 SG_ Speed : 0|8@1+ (1,0) [0|255] "" Rx
 SG_ Other : 8|8@1+ (1,0) [0|255] "" SomeoneElse
"""


class EcuFocusTests(unittest.TestCase):
    def test_rx_is_per_signal_and_respects_old_or_new_routes(self):
        signals = [
            signal("LostRx", 0, "Rx"),
            signal("GainedRx", 8, "Other"),
            signal("Unrelated", 16, "Other"),
            signal("StillRx", 24, "Rx"),
        ]
        old = Message("Status", 100, 8, "Tx,SecondTx", signals={item.name: item for item in signals})
        new = replace(old, dlc=7, signals={
            "LostRx": replace(signals[0], receivers=("Other",)),
            "GainedRx": replace(signals[1], receivers=("Rx",)),
            "Unrelated": replace(signals[2], factor=2),
            "StillRx": signals[3],
        })
        result = DbcComparator(include_unchanged=True).compare_databases(
            "bus.dbc", database(old), database(new, nodes=("Spare",)),
        )
        rx = apply_ecu_focus(result, ["Rx"])
        self.assertEqual([change.old_name for change in rx.message_changes], ["Status"])
        self.assertEqual({change.old_name for change in rx.signal_changes}, {"LostRx", "GainedRx", "StillRx"})
        self.assertEqual(rx.summary()["Signals Unchanged"], 1)
        self.assertEqual(len(apply_ecu_focus(result, ["Rx", "SecondTx"]).signal_changes), 4)
        self.assertEqual(apply_ecu_focus(result, ["Spare"]).summary()["Total Changes"], 0)
        self.assertEqual(len(result.signal_changes), 4)
        self.assertEqual(rx.coverage, result.coverage)
        with self.assertRaisesRegex(ValueError, "Missing"):
            apply_ecu_focus(result, ["Missing"])

    def test_added_and_removed_signals_check_only_side_with_signal(self):
        old = Message("Status", 100, 8, "OldTx", signals={"Gone": signal("Gone", 0, "A")})
        new = replace(old, transmitter="NewTx", signals={
            "Added": replace(signal("Added", 48, "B"), length=16, factor=5, unit="V"),
        })
        result = DbcComparator().compare_databases("bus.dbc", database(old), database(new))
        self.assertEqual(
            [change.change_type for change in apply_ecu_focus(result, ["OldTx"]).signal_changes], ["Removed"],
        )
        self.assertEqual(
            [change.change_type for change in apply_ecu_focus(result, ["NewTx"]).signal_changes], ["Added"],
        )

    def test_renamed_ecu_expands_only_direct_pair_and_uses_correct_side(self):
        old = Message("Paired", 100, 8, "A", signals={"Speed": signal("Speed", 0, "Receiver")})
        new = replace(old, transmitter="B", signals={
            "Speed": replace(old.signals["Speed"], factor=2),
        })
        other = Message("Other", 101, 8, "B")
        result = DbcComparator(ecu_map={"A": "B", "B": "C"}).compare_databases(
            "bus.dbc", database(old, other), database(new, replace(other, transmitter="C", dlc=7)),
        )
        focus = apply_ecu_focus(result, ["A"])
        self.assertEqual(focus.focus_pairs, (("A", "B"),))
        self.assertEqual([c.new_name for c in focus.signal_changes], ["Speed"])
        self.assertEqual(focus.message_changes, [])
        self.assertEqual(apply_ecu_focus(result, ["B"]).focus_pairs, (("A", "B"), ("B", "C")))

    def test_folder_overview_uses_final_rows_and_incomplete_coverage_is_global(self):
        with TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "old", Path(tmp) / "new"
            for path in (old, new):
                (path / "nested").mkdir(parents=True)
                (path / "other").mkdir()
                (path / "other" / "bus.dbc").write_text(DBC, encoding="utf-8")
            (old / "nested" / "bus.dbc").write_text(DBC, encoding="utf-8")
            (new / "nested" / "bus.dbc").write_text(DBC.replace("(1,0)", "(2,0)"), encoding="utf-8")
            (old / "bad.dbc").write_text("invalid DBC", encoding="utf-8")
            result = DbcComparator().compare_paths(old, new)
            focus = apply_ecu_focus(result, ["Rx"])
            self.assertEqual([pair.old_path for pair in focus.file_pairs], ["nested/bus.dbc"])
            self.assertEqual([change.old_name for change in focus.signal_changes], ["Speed"])
            self.assertEqual(focus.completeness, "Incomplete")
            self.assertEqual(focus.diagnostics, result.diagnostics)
            self.assertEqual(focus.coverage, result.coverage)
            self.assertEqual(filter_result(focus, {"Added"}).file_pairs, [])
            self.assertIn("SomeoneElse", result.new_nodes)
            self.assertIn("Spare", result.old_nodes)

    def test_vietnamese_rename_reasons_keep_dynamic_evidence_and_confidence_style(self):
        old_signal = signal("Speed_Previous", 0, "Rx")
        new_signal = replace(old_signal, name="Speed_Current", start_bit=1)
        old = Message("Status", 100, 8, "Tx", signals={old_signal.name: old_signal})
        new = replace(old, signals={new_signal.name: new_signal})
        result = apply_ecu_focus(
            DbcComparator().compare_databases("bus.dbc", database(old), database(new)), ["Rx"],
        )
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.xlsx"
            write_excel_report(result, output, language="vi")
            workbook = load_workbook(output)
            try:
                sheet = workbook["Chi tiết signal"]
                row, = rows(sheet)
                self.assertEqual(row["Loại thay đổi"], "Đổi tên")
                self.assertIn("Start Bit dịch 1 bit", row["Lý do matching"])
                self.assertEqual(row["Tên signal mới"], "Speed_Current")
                self.assertEqual(sheet["D2"].fill.fgColor.rgb, "00DDEBF7")
                self.assertEqual(sheet["H2"].fill.fgColor.rgb, {
                    "Cao": "00C6EFCE", "Trung bình": "00FFEB9C", "Thấp": "00FFC7CE",
                }[row["Mức tin cậy"]])
            finally:
                workbook.close()

    def test_cli_list_and_vietnamese_focus_report(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / "Baseline cũ.dbc", root / "Baseline mới.dbc"
            old.write_text(DBC, encoding="utf-8")
            new.write_text(DBC.replace("(1,0)", "(2,0)"), encoding="utf-8")
            args = ["--old", str(old), "--new", str(new)]
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(StringIO()):
                self.assertEqual(main([*args, "--list-ecus"]), 0)
            self.assertIn("SomeoneElse", output.getvalue())
            self.assertIn("Spare", output.getvalue())
            self.assertNotIn("Vector__XXX", output.getvalue())
            self.assertEqual(list(root.glob("*.xlsx")), [])
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main([*args, "--ecu-focus", "missing"]), 2)
                self.assertEqual(main([*args, "--ecu-focus", "Rx", "--ecu-focus", "Spare",
                                       "--report-language", "vi"]), 0)
            output_path = root / "compared_Baseline cũ_vs_Baseline mới.xlsx"
            workbook = load_workbook(output_path)
            try:
                self.assertEqual(workbook.sheetnames, ["Tổng quan", "Chi tiết message", "Chi tiết signal"])
                summary = dict(workbook["Tổng quan"].values)
                self.assertEqual(summary["Tổng số thay đổi"], 1)
                self.assertEqual(summary["ECU focus"], "Rx, Spare")
                self.assertEqual(summary["Baseline cũ"], str(old.resolve()))
                self.assertEqual(summary["Baseline mới"], str(new.resolve()))
                sheet = workbook["Chi tiết signal"]
                self.assertEqual(sheet.auto_filter.ref, sheet.dimensions)
                self.assertEqual(sheet["D2"].fill.fgColor.rgb, "00FFF2CC")
                row, = rows(sheet)
                self.assertEqual(row["Tên signal mới"], "Speed")
                self.assertEqual(row["Loại thay đổi"], "Đã sửa")
                self.assertEqual(row["Thuộc tính thay đổi"], "Factor: 1->2")
                self.assertEqual(row["Node ECU Rx"], "Rx")
            finally:
                workbook.close()
