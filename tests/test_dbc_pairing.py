"""DBC inventory pairing: filename keywords, global assignment and report evidence."""
from __future__ import annotations

import itertools
import random
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.core.models import DbcDatabase, Message
from dbc_compare_tool.core.pairing import DatabaseCandidate, _maximum_assignment, match_renamed_databases
from dbc_compare_tool.report.excel import write_excel_report


def _candidate(path: str, frame: int | None = None, name: str = "Status") -> DatabaseCandidate:
    messages = {} if frame is None else {name: Message(name, frame, 8, "ECU")}
    return DatabaseCandidate(path, DbcDatabase(Path(path), messages))


def _pairs(old, new):
    return {(match.old.relative_path, match.new.relative_path) for match in match_renamed_databases(old, new)}


class TestDbcPairing(unittest.TestCase):
    def test_shared_keyword_matches_completely_different_content(self):
        matches = match_renamed_databases(
            [_candidate("OEM_Powertrain_2024_v1.dbc", 100, "Engine")],
            [_candidate("Vehicle_Powertrain_2026_Release.dbc", 500, "Battery")],
        )
        self.assertEqual(len(matches), 1)
        self.assertIn("powertrain", " ".join(matches[0].reasons))

    def test_case_camel_case_version_and_separators(self):
        self.assertEqual(_pairs([_candidate("VehiclePowertrainRev2.dbc")],
                                [_candidate("vehicle-powertrain-v3.DBC")]),
                         {("VehiclePowertrainRev2.dbc", "vehicle-powertrain-v3.DBC")})

    def test_channel_numbers_choose_correct_counterparts(self):
        old = [_candidate("Gateway_CAN_1_v1.dbc"), _candidate("Gateway_CAN_2_v1.dbc")]
        new = [_candidate("CAN2_Gateway_v3.dbc"), _candidate("CAN1_Gateway_v3.dbc")]
        self.assertEqual(_pairs(old, new), {
            ("Gateway_CAN_1_v1.dbc", "CAN1_Gateway_v3.dbc"),
            ("Gateway_CAN_2_v1.dbc", "CAN2_Gateway_v3.dbc"),
        })

    def test_channel_number_survives_inside_a_filename(self):
        self.assertEqual(_pairs([_candidate("Gateway_CAN_2_v1.dbc")],
                                [_candidate("CAN1_Gateway_v3.dbc"), _candidate("CAN2_Gateway_v3.dbc")]),
                         {("Gateway_CAN_2_v1.dbc", "CAN2_Gateway_v3.dbc")})

    def test_attached_dates_and_revision_suffixes_are_ignored(self):
        self.assertEqual(len(_pairs([_candidate("Powertrain20241005.dbc")],
                                   [_candidate("Powertrain20261005.dbc")])), 1)
        self.assertEqual(len(_pairs([_candidate("BCMv1.dbc")], [_candidate("BCMv2.dbc")])), 1)

    def test_parent_folder_keyword_supports_renamed_generic_file(self):
        self.assertEqual(len(_pairs([_candidate("Powertrain/release.dbc")],
                                   [_candidate("Powertrain/current.dbc")])), 1)

    def test_revision_and_generic_keywords_do_not_force_pair(self):
        self.assertFalse(_pairs([_candidate("old/CAN_release_v1_2024.dbc")],
                                [_candidate("new/CAN_release_v2_2026.dbc")]))

    def test_content_still_matches_without_shared_filename_keyword(self):
        self.assertEqual(len(_pairs([_candidate("Engine.dbc", 100)],
                                   [_candidate("Vehicle.dbc", 100)])), 1)

    def test_unrelated_files_remain_added_removed(self):
        self.assertFalse(_pairs([_candidate("Engine.dbc", 100, "EngineStatus")],
                                [_candidate("Battery.dbc", 200, "BatteryStatus")]))

    def test_global_assignment_keeps_restricted_counterpart_available(self):
        # A greedy matcher consumes Alpha_Beta for the strongest first pair,
        # leaving Alpha unpaired. The inventory has a better two-pair solution.
        old = [_candidate("Alpha_Beta_v1.dbc"), _candidate("Alpha_v1.dbc")]
        new = [_candidate("Alpha_Beta_v2.dbc"), _candidate("Beta_v2.dbc")]
        expected = {("Alpha_Beta_v1.dbc", "Beta_v2.dbc"), ("Alpha_v1.dbc", "Alpha_Beta_v2.dbc")}
        self.assertEqual(_pairs(old, new), expected)
        self.assertEqual(_pairs(list(reversed(old)), list(reversed(new))), expected)

    def test_unequal_inventories_and_ties_are_deterministic(self):
        old = [_candidate("Powertrain_A.dbc"), _candidate("Powertrain_B.dbc"), _candidate("Chassis.dbc")]
        new = [_candidate("Powertrain_C.dbc")]
        matches = match_renamed_databases(old, new)
        self.assertEqual(len(matches), 1)
        self.assertEqual(_pairs(old, new), _pairs(list(reversed(old)), new))
        self.assertEqual(len({match.new.relative_path for match in matches}), len(matches))

    def test_empty_inventory(self):
        self.assertFalse(_pairs([], [_candidate("Powertrain.dbc")]))
        self.assertFalse(_pairs([_candidate("Powertrain.dbc")], []))

    def test_global_optimizer_agrees_with_exhaustive_small_inventories(self):
        rng = random.Random(42)
        for rows in range(1, 5):
            for _ in range(20):
                scores = [[rng.randint(0, 100) / 100 for _ in range(rows + 1)] for _ in range(rows)]
                assignment = _maximum_assignment(scores)
                actual = sum(scores[row][column] for row, column in enumerate(assignment))
                expected = max(sum(scores[row][column] for row, column in enumerate(columns))
                               for columns in itertools.permutations(range(rows + 1), rows))
                self.assertAlmostEqual(actual, expected)
                self.assertEqual(len(set(assignment)), rows)

    def test_keyword_pairing_flows_through_comparison_and_excel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / "old", root / "new"
            old.mkdir()
            new.mkdir()
            (old / "OEM_Powertrain_v1.dbc").write_text('VERSION ""\nBO_ 100 Engine: 8 ECU\n', encoding="utf-8")
            (new / "Vehicle_Powertrain_v2.dbc").write_text('VERSION ""\nBO_ 500 Battery: 4 BMS\n', encoding="utf-8")
            log = []
            result = DbcComparator(include_unchanged=True).compare_folders(old, new, log.append)
            self.assertEqual([pair.status for pair in result.file_pairs], ["DBC Renamed"])
            self.assertIn("powertrain", " ".join(log))
            self.assertEqual({change.change_type for change in result.message_changes}, {"Removed", "Added"})
            report = write_excel_report(result, root / "report.xlsx")
            workbook = load_workbook(report)
            try:
                overview = workbook["DBC Overview"]
                row = dict(zip(next(overview.values), list(overview.values)[1]))
                self.assertIn("powertrain", row["Pairing Reason"])
                self.assertGreaterEqual(float(row["Pairing Confidence"]), 0.55)
            finally:
                workbook.close()

    def test_exact_relative_path_remains_first_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / "old", root / "new"
            old.mkdir()
            new.mkdir()
            for folder, frame in ((old, 100), (new, 200)):
                (folder / "Powertrain.dbc").write_text(f'VERSION ""\nBO_ {frame} Status: 8 ECU\n', encoding="utf-8")
            result = DbcComparator().compare_folders(old, new)
            self.assertEqual(result.file_pairs[0].status, "Matched")


if __name__ == "__main__":
    unittest.main()
