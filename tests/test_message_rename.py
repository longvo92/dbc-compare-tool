"""Message rename detection wired into compare_databases (CAN ID change + name change)."""

import tempfile
import unittest
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.core.parser import parse_dbc

_OLD_DBC = """VERSION ""

BO_ 100 WheelSpeeds: 8 ABS
 SG_ FL_Speed : 0|16@1+ (0.01,0) [0|250] "km/h" ECM
 SG_ FR_Speed : 16|16@1+ (0.01,0) [0|250] "km/h" ECM
BA_ "GenMsgCycleTime" BO_ 100 20;
"""

_NEW_DBC = """VERSION ""

BO_ 400 WhlSpeeds: 8 ABS
 SG_ FL_Speed : 0|16@1+ (0.01,0) [0|250] "km/h" ECM
 SG_ FR_Speed : 16|16@1+ (0.01,0) [0|250] "km/h" ECM
BA_ "GenMsgCycleTime" BO_ 400 20;
"""


class TestMessageRenameViaCanIdChange(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        tmp_dir = Path(self._tmp_dir.name)
        old_path = tmp_dir / "old.dbc"
        new_path = tmp_dir / "new.dbc"
        old_path.write_text(_OLD_DBC, encoding="utf-8")
        new_path.write_text(_NEW_DBC, encoding="utf-8")

        old_db = parse_dbc(old_path)
        new_db = parse_dbc(new_path)
        self.result = DbcComparator().compare_databases("test.dbc", old_db, new_db)

    def test_message_detected_as_renamed(self):
        renames = [c for c in self.result.message_changes if c.change_type == "Renamed"]
        self.assertEqual(len(renames), 1)
        self.assertEqual(renames[0].old_name, "WheelSpeeds")
        self.assertEqual(renames[0].new_name, "WhlSpeeds")

    def test_no_removed_or_added_messages(self):
        added = [c for c in self.result.message_changes if c.change_type == "Added"]
        removed = [c for c in self.result.message_changes if c.change_type == "Removed"]
        self.assertEqual(len(added), 0)
        self.assertEqual(len(removed), 0)

    def test_rename_has_confidence(self):
        renames = [c for c in self.result.message_changes if c.change_type == "Renamed"]
        self.assertIsNotNone(renames[0].confidence)
        self.assertIn(renames[0].confidence_level, {"High", "Medium", "Low"})

    def test_signals_compared_under_renamed_message(self):
        # Signals kept identical layout, so no spurious signal changes should appear.
        self.assertEqual(len(self.result.signal_changes), 0)


class TestMessageIdentityChanges(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.old = Path(temporary.name) / "old.dbc"
        self.new = Path(temporary.name) / "new.dbc"

    def _compare(self, old, new, include_unchanged=False):
        self.old.write_text(old, encoding="utf-8")
        self.new.write_text(new, encoding="utf-8")
        return DbcComparator(include_unchanged=include_unchanged).compare_files(self.old, self.new)

    def test_id_change_with_same_name_is_modified_with_or_without_cycle_time(self):
        for cycle in (False, True):
            for full in (False, True):
                with self.subTest(cycle=cycle, full=full):
                    old = _OLD_DBC if cycle else _OLD_DBC.split('BA_ "GenMsgCycleTime"')[0]
                    result = self._compare(old, old.replace("BO_ 100 ", "BO_ 400 "), full)
                    self.assertEqual(len(result.message_changes), 1)
                    change = result.message_changes[0]
                    self.assertEqual((change.change_type, change.old_name, change.new_name),
                                     ("Modified", "WheelSpeeds", "WheelSpeeds"))
                    self.assertEqual(change.property_diffs, (("CAN ID", "100", "400"),))
                    self.assertEqual((change.old_message.can_id, change.new_message.can_id), (100, 400))
                    self.assertEqual([c.change_type for c in result.signal_changes],
                                     ["Unchanged", "Unchanged"] if full else [])

    def test_same_name_pair_is_reserved_before_structural_rename_candidates(self):
        old = _OLD_DBC.split('BA_ "GenMsgCycleTime"')[0]
        replacement = old.replace("BO_ 100 ", "BO_ 400 ").replace("WheelSpeeds", "OtherSpeeds")
        same_name = old.replace("BO_ 100 WheelSpeeds: 8 ABS", "BO_ 500 WheelSpeeds: 4 ABS")
        result = self._compare(old, replacement + same_name)
        self.assertEqual({(c.change_type, c.old_name, c.new_name) for c in result.message_changes}, {
            ("Modified", "WheelSpeeds", "WheelSpeeds"), ("Added", "", "OtherSpeeds"),
        })
        modified = next(c for c in result.message_changes if c.change_type == "Modified")
        self.assertEqual(modified.new_message.can_id, 500)

    def test_frame_key_still_takes_priority_over_name(self):
        old = _OLD_DBC.split('BA_ "GenMsgCycleTime"')[0]
        renamed = old.replace("WheelSpeeds", "OtherSpeeds")
        moved = old.replace("BO_ 100 ", "BO_ 400 ")
        result = self._compare(old, renamed + moved)
        self.assertEqual({(c.change_type, c.old_name, c.new_name) for c in result.message_changes}, {
            ("Renamed", "WheelSpeeds", "OtherSpeeds"), ("Added", "", "WheelSpeeds"),
        })

    def test_frame_format_change_with_same_name_is_modified(self):
        old = _OLD_DBC.split('BA_ "GenMsgCycleTime"')[0]
        result = self._compare(old, old.replace("BO_ 100 ", f"BO_ {0x80000000 | 100} "))
        self.assertEqual(len(result.message_changes), 1)
        change = result.message_changes[0]
        self.assertEqual(change.change_type, "Modified")
        self.assertEqual(change.property_diffs, (("Extended Frame", "No", "Yes"),))
        self.assertEqual(result.signal_changes, [])


if __name__ == "__main__":
    unittest.main()
