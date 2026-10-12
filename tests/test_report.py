"""Excel report tests.

The writer is exercised end to end — written to disk, reopened with openpyxl,
and read back. Without this the report layer can crash or drop a sheet while
the whole suite stays green, which is exactly what a release build would then
ship.
"""

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.report.excel import default_report_path, write_excel_report

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_OLD_FOLDER = _EXAMPLES / "old"
_NEW_FOLDER = _EXAMPLES / "new"


def _rows(sheet) -> list[dict]:
    header = next(sheet.iter_rows(values_only=True))
    return [dict(zip(header, row)) for row in sheet.iter_rows(min_row=2, values_only=True)]


class BaselineReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = DbcComparator().compare_folders(_OLD_FOLDER, _NEW_FOLDER)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name) / "report.xlsx"
        write_excel_report(self.result, self.output)
        self.workbook = load_workbook(self.output)
        self.addCleanup(self.workbook.close)

    def test_workbook_has_the_five_documented_sheets_in_order(self):
        self.assertEqual(
            self.workbook.sheetnames,
            ["Summary", "DBC Overview", "Message Details", "Signal Details", "Changed Properties"],
        )

    def test_summary_total_matches_the_result(self):
        sheet = self.workbook["Summary"]
        totals = {row[0]: row[1] for row in sheet.iter_rows(min_row=4, values_only=True)}
        self.assertEqual(totals["Total Changes"], self.result.summary()["Total Changes"])
        self.assertEqual(totals["Messages Renamed"], self.result.summary()["Messages Renamed"])

    def test_every_signal_change_reaches_the_signal_sheet(self):
        rows = _rows(self.workbook["Signal Details"])
        self.assertEqual(len(rows), len(self.result.signal_changes))
        renamed = {(row["Old Signal Name"], row["New Signal Name"])
                   for row in rows if row["Change Type"] == "Renamed"}
        self.assertIn(("VehicleSpeed", "VehSpd"), renamed)

    def test_can_id_is_written_in_hexadecimal(self):
        rows = _rows(self.workbook["Message Details"])
        self.assertTrue(rows)
        self.assertTrue(all(str(row["CAN ID"]).startswith("0x") for row in rows if row["CAN ID"]))

    def test_changed_properties_carries_old_and_new_values(self):
        rows = _rows(self.workbook["Changed Properties"])
        self.assertTrue(rows)
        factor_rows = [row for row in rows if row["Property"] == "Factor"]
        self.assertTrue(factor_rows, "the EngineRPM factor change should appear")
        self.assertNotEqual(factor_rows[0]["Old Value"], factor_rows[0]["New Value"])

    def test_detail_columns_contain_only_identity_pairing_and_routing(self):
        context = {f"{label} ({side})" for label in ("CAN ID", "ECU Node Tx", "ECU Node Rx")
                   for side in ("Old", "New")}
        shared = {"DBC File", "Change Type", "Confidence Score", "Confidence Level", "Match Reason"} | context
        expected = {
            "Message Details": shared | {"Old Message Name", "New Message Name", "CAN ID"},
            "Signal Details": shared | {"Old Signal Name", "New Signal Name", "Parent Message",
                                         "Parent Message (Old)", "Parent Message (New)"},
        }
        for name, headers in expected.items():
            with self.subTest(sheet=name):
                sheet = self.workbook[name]
                self.assertEqual(set(next(sheet.iter_rows(values_only=True))), headers)
                self.assertEqual(sheet.auto_filter.ref, sheet.dimensions)

    def test_rename_evidence_does_not_repeat_changed_property_values(self):
        for sheet in ("Message Details", "Signal Details"):
            rows = _rows(self.workbook[sheet])
            for row in rows:
                if row["Change Type"] == "Renamed":
                    self.assertTrue(row["Match Reason"])
                    self.assertNotIn(" -> ", row["Match Reason"])
                else:
                    self.assertIsNone(row["Match Reason"])

    def test_overview_lists_every_file_pair(self):
        rows = _rows(self.workbook["DBC Overview"])
        self.assertEqual(len(rows), len(self.result.file_pairs))
        self.assertEqual(rows[0]["Status"], "Matched")

    def test_missing_parent_directory_is_created(self):
        nested = Path(self._tmp.name) / "a" / "b" / "report.xlsx"
        write_excel_report(self.result, nested)
        self.assertTrue(nested.is_file())


class DefaultReportPathTests(unittest.TestCase):
    def test_file_report_uses_stem_beside_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_file = Path(tmp) / "CAN network.v2.DBC"
            new_file.touch()
            self.assertEqual(default_report_path(new_file), Path(tmp) / "compared_CAN network.v2.xlsx")

    def test_folder_report_preserves_full_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_folder = Path(tmp) / "baseline.v2.dbc"
            new_folder.mkdir()
            self.assertEqual(default_report_path(new_folder), Path(tmp) / "compared_baseline.v2.dbc.xlsx")


if __name__ == "__main__":
    unittest.main()
