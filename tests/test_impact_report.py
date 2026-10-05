"""Full inventory coverage and ECU context in impact-review reports (no Qt)."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from openpyxl import load_workbook

from dbc_compare_tool.cli import main
from dbc_compare_tool.core.comparator import DbcComparator, filter_result, reject_signal_renames
from dbc_compare_tool.core.models import DbcDatabase, Message, Signal
from dbc_compare_tool.report.excel import write_excel_report


def _signal(name: str, start: int = 0, receivers: tuple[str, ...] = ("ECM",)) -> Signal:
    return Signal(name, start, 8, 1, "unsigned", False, 1.0, 0.0, 0, 255, "km/h", receivers)


def _database(*messages: Message) -> DbcDatabase:
    return DbcDatabase(Path("bus.dbc"), {message.name: message for message in messages})


def _rows(sheet) -> list[dict]:
    header = next(sheet.iter_rows(values_only=True))
    return [dict(zip(header, row)) for row in sheet.iter_rows(min_row=2, values_only=True)]


_DBC = '''VERSION ""
BO_ 100 Status: 8 BCM
 SG_ Speed : 0|8@1+ (1,0) [0|255] "km/h" ECM,IC
 SG_ State : 8|8@1+ (1,0) [0|255] "" ECM
'''


class ImpactReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.message = Message(
            "Status", 100, 8, "BCM", signals={
                "Speed": _signal("Speed", receivers=("ECM", "IC")),
                "State": _signal("State", start=8),
            }, cycle_time_ms=10, comment="Vehicle status",
        )

    def _compare(self, old=None, new=None, full=True):
        return DbcComparator(include_unchanged=full).compare_databases(
            "bus.dbc", old or _database(self.message), new or _database(self.message)
        )

    def _report(self, result):
        output = self.root / "report.xlsx"
        write_excel_report(result, output)
        workbook = load_workbook(output)
        self.addCleanup(workbook.close)
        return workbook

    def test_identical_baselines_default_empty_full_inventory_and_zero_changes(self):
        default = self._compare(full=False)
        self.assertEqual(default.message_changes, [])
        self.assertEqual(default.signal_changes, [])
        full = self._compare()
        self.assertEqual([c.change_type for c in full.message_changes], ["Unchanged"])
        self.assertEqual([c.change_type for c in full.signal_changes], ["Unchanged", "Unchanged"])
        self.assertEqual(full.summary()["Total Changes"], 0)
        self.assertEqual(full.summary()["Messages Unchanged"], 1)
        self.assertEqual(full.summary()["Signals Unchanged"], 2)
        workbook = self._report(full)
        self.assertEqual(workbook["Property Diff"].max_row, 1)
        self.assertEqual(workbook["Message Details"]["B2"].fill.fgColor.rgb, "00F2F2F2")

    def test_signal_only_change_retains_message_and_unchanged_siblings(self):
        signals = dict(self.message.signals)
        signals["Speed"] = replace(signals["Speed"], factor=2)
        new = _database(replace(self.message, signals=signals))
        full = self._compare(new=new)
        default = self._compare(new=new, full=False)
        self.assertEqual(full.message_changes[0].change_type, "Unchanged")
        self.assertEqual({c.change_type for c in full.signal_changes}, {"Modified", "Unchanged"})
        self.assertEqual(full.summary()["Total Changes"], default.summary()["Total Changes"])
        self.assertEqual(full.summary()["Total Changes"], 1)

    def test_full_mode_cannot_drop_rows_through_change_filter(self):
        full = self._compare()
        self.assertIs(filter_result(full, {"Added"}), full)

    def test_ecu_receivers_and_technical_snapshots_survive_excel_roundtrip(self):
        workbook = self._report(self._compare())
        message = _rows(workbook["Message Details"])[0]
        signals = {row["New Signal Name"]: row for row in _rows(workbook["Signal Details"])}
        self.assertEqual(message["ECU Node Tx (Old)"], "BCM")
        self.assertEqual(message["ECU Node Rx (New)"], "ECM, IC")
        self.assertEqual(message["Cycle Time (ms) (New)"], 10)
        self.assertEqual(message["DLC (Old)"], 8)
        self.assertEqual(message["Signal Count (New)"], 2)
        self.assertEqual(signals["State"]["ECU Node Rx (Old)"], "ECM")
        self.assertEqual(signals["Speed"]["ECU Node Rx (New)"], "ECM, IC")
        self.assertEqual(signals["Speed"]["CAN ID (New)"], "0x64")
        self.assertEqual(signals["Speed"]["Start Bit (Old)"], 0)
        self.assertEqual(signals["Speed"]["Factor (New)"], 1)
        self.assertEqual(signals["Speed"]["Byte Order (New)"], "Intel/little-endian (1)")
        for name in ("Message Details", "Signal Details", "Property Diff"):
            self.assertEqual(workbook[name].auto_filter.ref, workbook[name].dimensions)

    def test_changed_routing_is_available_in_default_report_and_property_diff(self):
        signals = {name: replace(signal, receivers=("VCU",)) for name, signal in self.message.signals.items()}
        new = _database(replace(self.message, transmitter="Gateway", signals=signals))
        workbook = self._report(self._compare(new=new, full=False))
        message = _rows(workbook["Message Details"])[0]
        signal = _rows(workbook["Signal Details"])[0]
        self.assertEqual(message["ECU Node Tx (Old)"], "BCM")
        self.assertEqual(message["ECU Node Tx (New)"], "Gateway")
        self.assertEqual(message["ECU Node Rx (Old)"], "ECM, IC")
        self.assertEqual(signal["ECU Node Rx (New)"], "VCU")
        diff = next(row for row in _rows(workbook["Property Diff"]) if row["Property"] == "Receivers")
        self.assertEqual(diff["ECU Node Rx (New)"], "VCU")
        self.assertEqual(diff["ECU Node Tx (Old)"], "BCM")

    def test_unchanged_signals_under_renamed_message_keep_both_parent_ids(self):
        new = _database(replace(self.message, name="StatusV2", can_id=400))
        result = self._compare(new=new)
        self.assertEqual(result.message_changes[0].change_type, "Renamed")
        self.assertEqual(len(result.signal_changes), 2)
        signal = _rows(self._report(result)["Signal Details"])[0]
        self.assertEqual(signal["Change Type"], "Unchanged")
        self.assertEqual(signal["Parent Message (Old)"], "Status")
        self.assertEqual(signal["Parent Message (New)"], "StatusV2")
        self.assertEqual(signal["CAN ID (Old)"], "0x64")
        self.assertEqual(signal["CAN ID (New)"], "0x190")

    def test_added_removed_entities_keep_only_available_signal_snapshot(self):
        for old, new, kind, side, missing in (
            (_database(), _database(self.message), "Added", "New", "Old"),
            (_database(self.message), _database(), "Removed", "Old", "New"),
        ):
            with self.subTest(kind=kind):
                workbook = self._report(self._compare(old, new))
                for sheet in ("Message Details", "Signal Details"):
                    row = _rows(workbook[sheet])[0]
                    self.assertEqual(row["Change Type"], kind)
                    self.assertEqual(row[f"ECU Node Tx ({side})"], "BCM")
                    self.assertIsNone(row[f"ECU Node Tx ({missing})"])
                    self.assertIsNone(row[f"CAN ID ({missing})"])

    def test_signal_added_removed_inside_matched_parent(self):
        new_signals = {"Speed": self.message.signals["Speed"], "Temperature": _signal("Temperature", 32)}
        result = self._compare(new=_database(replace(self.message, signals=new_signals)))
        rows = _rows(self._report(result)["Signal Details"])
        removed = next(row for row in rows if row["Change Type"] == "Removed")
        added = next(row for row in rows if row["Change Type"] == "Added")
        self.assertEqual(removed["Start Bit (Old)"], 8)
        self.assertIsNone(removed["Start Bit (New)"])
        self.assertEqual(added["Start Bit (New)"], 32)
        self.assertIsNone(added["Start Bit (Old)"])

    def test_rejected_rename_keeps_ecu_context_and_full_mode(self):
        renamed = replace(self.message.signals["Speed"], name="VehicleSpeed")
        new = _database(replace(self.message, signals={"VehicleSpeed": renamed, "State": self.message.signals["State"]}))
        result = reject_signal_renames(self._compare(new=new), {0})
        self.assertTrue(result.include_unchanged)
        rows = _rows(self._report(result)["Signal Details"])
        removed = next(row for row in rows if row["Change Type"] == "Removed")
        added = next(row for row in rows if row["Change Type"] == "Added")
        self.assertEqual(removed["ECU Node Rx (Old)"], "ECM, IC")
        self.assertIsNone(removed["ECU Node Rx (New)"])
        self.assertEqual(added["ECU Node Rx (New)"], "ECM, IC")
        self.assertIsNone(added["ECU Node Rx (Old)"])
        self.assertEqual(result.summary()["Total Changes"], 2)

    def test_extended_and_standard_twins_are_both_in_inventory(self):
        extended = replace(self.message, name="ExtendedStatus", is_extended_frame=True)
        result = self._compare(_database(self.message, extended), _database(self.message, extended))
        self.assertEqual(len(result.message_changes), 2)
        self.assertEqual(len(result.signal_changes), 4)
        rows = _rows(self._report(result)["Message Details"])
        self.assertEqual({row["Extended Frame (New)"] for row in rows}, {True, False})

    def test_signal_value_table_multiplexing_and_comments_exported(self):
        speed = replace(self.message.signals["Speed"], is_multiplexer=True,
                        value_descriptions=((0, "Off"), (1, "On")), comment="Speed state")
        state = replace(self.message.signals["State"], multiplexer_ids=(0, 1), multiplexer_signal="Speed")
        message = replace(self.message, signals={"Speed": speed, "State": state})
        rows = _rows(self._report(self._compare(_database(message), _database(message)))["Signal Details"])
        speed_row = next(row for row in rows if row["New Signal Name"] == "Speed")
        state_row = next(row for row in rows if row["New Signal Name"] == "State")
        self.assertTrue(speed_row["Multiplexer (New)"])
        self.assertEqual(speed_row["Value Descriptions (New)"], "0=Off, 1=On")
        self.assertEqual(speed_row["Signal Description (New)"], "Speed state")
        self.assertEqual(state_row["Multiplexer IDs (Old)"], "0, 1")
        self.assertEqual(state_row["Multiplexer Signal (New)"], "Speed")

    def test_automatic_renamed_file_and_manual_pairing_preserve_full_inventory(self):
        old, new = self.root / "old", self.root / "new"
        old.mkdir()
        new.mkdir()
        (old / "bus.dbc").write_text(_DBC, encoding="utf-8")
        (new / "bus_v2.dbc").write_text(_DBC, encoding="utf-8")
        comparator = DbcComparator(include_unchanged=True)
        auto = comparator.compare_folders(old, new)
        manual = comparator.compare_manual(old, new, {"bus.dbc": "bus_v2.dbc"})
        for result in (auto, manual):
            self.assertEqual(len(result.message_changes), 1)
            self.assertEqual(len(result.signal_changes), 2)
            self.assertEqual(result.summary()["Total Changes"], 0)
        self.assertEqual(auto.file_pairs[0].status, "DBC Renamed")
        self.assertEqual(manual.file_pairs[0].status, "Manually Paired")

    def test_cli_full_mode_and_parse_error_coverage_are_recorded(self):
        old, new = self.root / "old", self.root / "new"
        old.mkdir()
        new.mkdir()
        for folder in (old, new):
            (folder / "bus.dbc").write_text(_DBC, encoding="utf-8")
            (folder / "bad.dbc").write_text("invalid dbc {{{", encoding="utf-8")
        output = self.root / "full.xlsx"
        self.assertEqual(main(["--old", str(old), "--new", str(new), "--out", str(output), "--include-unchanged"]), 0)
        workbook = load_workbook(output)
        self.addCleanup(workbook.close)
        summary = dict(workbook["Summary"].iter_rows(min_row=4, values_only=True))
        self.assertEqual(summary["Report Mode"], "Full impact review")
        self.assertEqual(summary["Total Changes"], 0)
        self.assertEqual(summary["Parse Errors (skipped DBCs)"], 1)
        self.assertEqual(workbook["Signal Details"].max_row, 3)
