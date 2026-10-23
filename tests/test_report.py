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
from dbc_compare_tool.core.models import ComparisonResult, FilePairSummary
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

    def test_workbook_has_the_four_documented_sheets_in_order(self):
        self.assertEqual(
            self.workbook.sheetnames,
            ["Summary", "DBC Overview", "Message Details", "Signal Details"],
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

    def test_changed_properties_combines_old_and_new_values(self):
        rows = _rows(self.workbook["Signal Details"])
        self.assertTrue(rows)
        factor_rows = [row for row in rows if row["New Signal Name"] == "EngineRPM"]
        self.assertTrue(factor_rows, "the EngineRPM factor change should appear")
        self.assertIn("Factor: 0.25->0.5", factor_rows[0]["Changed Properties"])

    def test_detail_columns_include_one_changed_properties_column(self):
        context = {"CAN ID", "ECU Node Tx", "ECU Node Rx"}
        shared = {
            "DBC File", "Change Type", "Confidence Score", "Confidence Level", "Match Reason", "Changed Properties",
        } | context
        expected = {
            "Message Details": shared | {"Old Message Name", "New Message Name"},
            "Signal Details": shared | {
                "Old Signal Name", "New Signal Name", "Parent Message (Old)", "Parent Message (New)",
            },
        }
        for name, headers in expected.items():
            with self.subTest(sheet=name):
                sheet = self.workbook[name]
                self.assertEqual(set(next(sheet.iter_rows(values_only=True))), headers)
                self.assertEqual(sheet.max_column, len(headers))
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

    def test_overview_combines_paths_and_counts_without_losing_zero(self):
        rows = _rows(self.workbook["DBC Overview"])
        for row, pair in zip(rows, self.result.file_pairs):
            with self.subTest(file=pair.dbc_file):
                self.assertEqual(row["Path"], pair.old_path if pair.old_path == pair.new_path
                                 else f"{pair.old_path}->{pair.new_path}")
                for label, old, new in (
                    ("Messages", pair.message_count_old, pair.message_count_new),
                    ("Signals", pair.signal_count_old, pair.signal_count_new),
                ):
                    self.assertEqual(row[label], old if old == new else f"{old}->{new}")

    def test_confidence_and_change_colors_follow_compacted_columns(self):
        for name in ("Message Details", "Signal Details"):
            sheet = self.workbook[name]
            headers = [cell.value for cell in sheet[1]]
            for row in sheet.iter_rows(min_row=2):
                if row[headers.index("Confidence Level")].value == "High":
                    self.assertEqual(row[headers.index("Confidence Level")].fill.fgColor.rgb, "00C6EFCE")
                    self.assertEqual(row[headers.index("Confidence Score")].alignment.horizontal, "center")
                properties = row[headers.index("Changed Properties")]
                self.assertTrue(properties.alignment.wrap_text)
                self.assertIsNone(sheet.row_dimensions[properties.row].height)
                if row[headers.index("Change Type")].value == "Modified":
                    self.assertEqual(properties.fill.fgColor.rgb, "00FFF2CC")

    def test_missing_parent_directory_is_created(self):
        nested = Path(self._tmp.name) / "a" / "b" / "report.xlsx"
        write_excel_report(self.result, nested)
        self.assertTrue(nested.is_file())


class OneSidedReportTests(unittest.TestCase):
    def test_added_removed_dbc_paths_and_counts_have_no_arrows_and_keep_zero(self):
        result = ComparisonResult(file_pairs=[
            FilePairSummary("added.dbc", "DBC Added", "", "new/added.dbc", None, 0, 2, 0, 0),
            FilePairSummary("removed.dbc", "DBC Removed", "old/removed.dbc", "", None, 1, 0, 0, 0),
            FilePairSummary("matched.dbc", "Matched", "same.dbc", "same.dbc", 1.0, 0, 1, 1, 0),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.xlsx"
            write_excel_report(result, output)
            workbook = load_workbook(output)
            try:
                added, removed, matched = _rows(workbook["DBC Overview"])
                self.assertEqual((added["Path"], added["Messages"], added["Signals"]), ("new/added.dbc", 2, 0))
                self.assertEqual((removed["Path"], removed["Messages"], removed["Signals"]), ("old/removed.dbc", 1, 0))
                for row in (added, removed):
                    self.assertTrue(all("->" not in str(value) for value in row.values()))
                self.assertEqual((matched["Messages"], matched["Signals"]), ("0->1", "1->0"))
            finally:
                workbook.close()


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
