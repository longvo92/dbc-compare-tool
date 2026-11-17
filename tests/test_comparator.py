"""Comparator integration tests using example DBC folders."""

import unittest
from pathlib import Path

from dbc_compare_tool.dbc_compare.core.comparator import DbcComparator
from dbc_compare_tool.dbc_compare.core.models import ComparisonResult

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_OLD_FOLDER = _EXAMPLES / "old"
_NEW_FOLDER = _EXAMPLES / "new"


class TestCompareFolders(unittest.TestCase):
    def setUp(self):
        self.result: ComparisonResult = DbcComparator().compare_folders(_OLD_FOLDER, _NEW_FOLDER)

    # --- file pairs ---

    def test_file_pairs_populated(self):
        self.assertEqual(len(self.result.file_pairs), 1)

    def test_file_pair_status_matched(self):
        self.assertEqual(self.result.file_pairs[0].status, "Matched")

    def test_file_pair_message_counts(self):
        fp = self.result.file_pairs[0]
        self.assertEqual(fp.message_count_old, 3)
        self.assertEqual(fp.message_count_new, 3)

    # --- message changes ---

    def test_three_message_renames(self):
        renames = [c for c in self.result.message_changes if c.change_type == "Renamed"]
        self.assertEqual(len(renames), 3)

    def test_bcm_renamed_to_body_status(self):
        renames = [c for c in self.result.message_changes if c.change_type == "Renamed"]
        names = {(c.old_name, c.new_name) for c in renames}
        self.assertIn(("BCM_Status", "Body_Status"), names)

    def test_engine_status_renamed(self):
        renames = [c for c in self.result.message_changes if c.change_type == "Renamed"]
        names = {(c.old_name, c.new_name) for c in renames}
        self.assertIn(("Engine_Status", "Engine_Info"), names)

    def test_no_message_added_or_removed(self):
        added = [c for c in self.result.message_changes if c.change_type == "Added"]
        removed = [c for c in self.result.message_changes if c.change_type == "Removed"]
        self.assertEqual(len(added), 0)
        self.assertEqual(len(removed), 0)

    # --- signal changes ---

    def test_engine_rpm_modified(self):
        modified = [c for c in self.result.signal_changes if c.change_type == "Modified"]
        self.assertTrue(any(c.old_name == "EngineRPM" for c in modified))

    def test_diag_state_added(self):
        added = [c for c in self.result.signal_changes if c.change_type == "Added"]
        self.assertTrue(any(c.new_name == "DiagState" for c in added))

    def test_vehicle_speed_renamed(self):
        renames = [c for c in self.result.signal_changes if c.change_type == "Renamed"]
        self.assertTrue(any(c.old_name == "VehicleSpeed" and c.new_name == "VehSpd" for c in renames))

    # --- summary ---

    def test_summary_total_changes_positive(self):
        self.assertGreater(self.result.summary()["Total Changes"], 0)

    def test_summary_messages_renamed(self):
        self.assertEqual(self.result.summary()["Messages Renamed"], 3)

    # --- progress callback ---

    def test_progress_callback_called(self):
        messages: list[str] = []
        DbcComparator().compare_folders(
            _OLD_FOLDER, _NEW_FOLDER,
            progress_callback=messages.append,
        )
        self.assertTrue(any("Bus_A.dbc" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
