"""Direct DBC file comparisons and shared pipeline input validation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from dbc_compare_tool.dbc_compare.core.comparator import DbcComparator
from dbc_compare_tool.dbc_compare.core.parser import DbcParseError
from dbc_compare_tool.dbc_compare.pipeline import run_comparison


class TestFileInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = self.root / "alpha input.dbc"
        self.new = self.root / "omega input.DBC"
        self.old.write_text('VERSION ""\n\nBO_ 100 Status: 8 OLD\n SG_ Speed : 0|8@1+ (1,0) [0|255] "" OLD\n', encoding="utf-8")
        self.new.write_text(self.old.read_text(encoding="utf-8").replace("OLD", "NEW"), encoding="utf-8")

    def _run(self, output: Path | None = None, *, new: Path | None = None, **options):
        return run_comparison(self.old, new or self.new, output, **options)

    def test_explicit_files_pair_even_with_unrelated_content(self):
        self.new.write_text('VERSION ""\n\nBO_ 900 Other: 3 ECU\n', encoding="utf-8")
        progress = []
        result = DbcComparator().compare_paths(self.old, self.new, progress.append)
        self.assertEqual(len(result.file_pairs), 1)
        self.assertTrue(result.is_file_comparison)
        pair = result.file_pairs[0]
        self.assertEqual((pair.old_path, pair.new_path), (str(self.old.resolve()), str(self.new.resolve())))
        self.assertEqual(pair.status, "Manually Paired")
        self.assertIn("Explicit file selection", pair.pairing_reasons)
        self.assertEqual({c.change_type for c in result.message_changes}, {"Added", "Removed"})
        self.assertTrue(progress)

    def test_direct_file_mapping_and_include_unchanged(self):
        result = DbcComparator(include_unchanged=True, ecu_map={"OLD": "NEW"}).compare_files(self.old, self.new)
        self.assertEqual(result.summary()["Total Changes"], 0)
        self.assertEqual(result.summary()["Messages Unchanged"], 1)
        self.assertEqual(result.summary()["Signals Unchanged"], 1)

    def test_invalid_input_modes_and_missing_paths(self):
        text = self.root / "not-dbc.txt"
        text.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            DbcComparator().compare_paths(self.old, self.root)
        with self.assertRaisesRegex(ValueError, "folder or a .dbc file"):
            DbcComparator().compare_paths(text, self.new)
        with self.assertRaisesRegex(ValueError, "requires a .dbc file"):
            DbcComparator().compare_files(self.root, self.new)
        with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
            DbcComparator().compare_paths(self.root / "missing.dbc", self.new)

    def test_invalid_selected_file_is_a_parse_error(self):
        self.new.write_text("not a DBC", encoding="utf-8")
        with self.assertRaises(DbcParseError):
            DbcComparator().compare_files(self.old, self.new)
        with self.assertRaisesRegex(DbcParseError, "Unable to parse DBC"):
            self._run()
        self.assertFalse(list(self.root.glob("*.xlsx")))

    def test_duplicate_message_name_is_a_parse_error_without_report(self):
        old = self.old.read_text(encoding="utf-8")
        self.old.write_text(old + old.replace("BO_ 100 ", "BO_ 200 "), encoding="utf-8")
        with self.assertRaisesRegex(DbcParseError, "Duplicate message name 'Status'"):
            self._run()
        self.assertFalse(list(self.root.glob("*.xlsx")))

    def test_pipeline_exports_same_name_id_change_and_precise_factor_delta(self):
        old = self.old.read_text(encoding="utf-8").replace("(1,0)", "(0.1234567,0)")
        self.old.write_text(old, encoding="utf-8")
        self.new.write_text(old.replace("BO_ 100 ", "BO_ 400 ").replace("0.1234567", "0.1234568"),
                            encoding="utf-8")
        result, report = self._run(self.root / "precise.xlsx")
        self.assertEqual(result.completeness, "Complete")
        workbook = load_workbook(report)
        self.addCleanup(workbook.close)
        for name, expected in (("Message Details", "CAN ID: 100->400"),
                               ("Signal Details", "Factor: 0.1234567->0.1234568")):
            values = list(workbook[name].values)
            self.assertEqual(len(values), 2)
            row = dict(zip(values[0], values[1]))
            self.assertEqual(row["Change Type"], "Modified")
            self.assertEqual(row["Changed Properties"], expected)

    def test_files_mapping_and_default_report_name(self):
        result, report = self._run(ecu_map={"OLD": "NEW"}, include_unchanged=True)
        self.assertEqual(result.summary()["Total Changes"], 0)
        self.assertEqual(report, self.root / "compared_alpha input_vs_omega input.xlsx")
        self.assertTrue(report.is_file())
        workbook = load_workbook(report)
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.sheetnames, ["Summary", "Message Details", "Signal Details"])
        for name in ("Message Details", "Signal Details"):
            self.assertIn("Changed Properties", next(workbook[name].values))

    def test_multiple_ecu_pairs(self):
        self.old.write_text(self.old.read_text(encoding="utf-8").replace('"" OLD', '"" OLD_RX'), encoding="utf-8")
        self.new.write_text(self.new.read_text(encoding="utf-8").replace('"" NEW', '"" NEW_RX'), encoding="utf-8")
        result, _ = self._run(ecu_map={"OLD": "NEW", "OLD_RX": "NEW_RX"})
        self.assertEqual(result.summary()["Total Changes"], 0)

    def test_mapping_errors_are_actionable_and_do_not_create_reports(self):
        cases = [
            ({"OLD": "NEW", "OTHER": "NEW"}, "NEW ECU nodes paired more than once"),
            ({"OLD": "MISSING"}, "NEW: MISSING"),
        ]
        for ecu_map, message in cases:
            with self.subTest(ecu_map=ecu_map):
                with self.assertRaisesRegex(ValueError, message):
                    self._run(ecu_map=ecu_map)
        self.assertFalse(list(self.root.glob("*.xlsx")))

    def test_mixed_mode_and_non_excel_output_are_input_errors(self):
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            self._run(new=self.root)
        with self.assertRaisesRegex(ValueError, "must end with .xlsx"):
            self._run(self.root / "report.csv")
        self.assertFalse(list(self.root.glob("*.xlsx")))


if __name__ == "__main__":
    unittest.main()
