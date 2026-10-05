"""Tests for manual DBC file pairing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_OLD_FOLDER = _EXAMPLES / "old"
_NEW_FOLDER = _EXAMPLES / "new"

_MINIMAL_DBC = '''VERSION ""

BO_ 100 Status: 8 ECU
 SG_ Counter : 0|8@1+ (1,0) [0|255] "" ECM
'''


class TestCompareManual(unittest.TestCase):
    def test_explicit_pair_matches_auto_result(self):
        auto = DbcComparator().compare_folders(_OLD_FOLDER, _NEW_FOLDER)
        manual = DbcComparator().compare_manual(
            _OLD_FOLDER, _NEW_FOLDER, {"Bus_A.dbc": "Bus_A.dbc"}
        )
        self.assertEqual(manual.summary(), auto.summary())
        self.assertEqual(manual.file_pairs[0].status, "Matched")

    def test_unpaired_old_reported_removed(self):
        result = DbcComparator().compare_manual(
            _OLD_FOLDER, _NEW_FOLDER, {"Bus_A.dbc": None}
        )
        statuses = {fp.status for fp in result.file_pairs}
        self.assertEqual(statuses, {"DBC Removed", "DBC Added"})
        removed_msgs = [c for c in result.message_changes if c.change_type == "Removed"]
        added_msgs = [c for c in result.message_changes if c.change_type == "Added"]
        self.assertTrue(removed_msgs)
        self.assertTrue(added_msgs)

    def test_old_file_missing_from_map_treated_removed(self):
        result = DbcComparator().compare_manual(_OLD_FOLDER, _NEW_FOLDER, {})
        statuses = {fp.status for fp in result.file_pairs}
        self.assertEqual(statuses, {"DBC Removed", "DBC Added"})

    def test_unknown_pair_raises(self):
        with self.assertRaises(FileNotFoundError):
            DbcComparator().compare_manual(
                _OLD_FOLDER, _NEW_FOLDER, {"NoSuchFile.dbc": "Bus_A.dbc"}
            )

    def test_duplicate_new_pair_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_folder = root / "old"
            new_folder = root / "new"
            old_folder.mkdir()
            new_folder.mkdir()
            for name in ("first.dbc", "second.dbc"):
                (old_folder / name).write_text(_MINIMAL_DBC, encoding="utf-8")
            (new_folder / "current.dbc").write_text(_MINIMAL_DBC, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "paired more than once"):
                DbcComparator().compare_manual(
                    old_folder,
                    new_folder,
                    {"first.dbc": "current.dbc", "second.dbc": "current.dbc"},
                )

    def test_progress_callback_called(self):
        messages: list[str] = []
        DbcComparator().compare_manual(
            _OLD_FOLDER,
            _NEW_FOLDER,
            {"Bus_A.dbc": "Bus_A.dbc"},
            progress_callback=messages.append,
        )
        self.assertTrue(messages)


if __name__ == "__main__":
    unittest.main()
