"""Tests for manual file pairing and user rejection of signal renames."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator, reject_signal_renames
from dbc_compare_tool.core.models import Change, ComparisonResult

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


class TestRejectSignalRenames(unittest.TestCase):
    def _result_with_renames(self) -> ComparisonResult:
        return ComparisonResult(
            signal_changes=[
                Change("a.dbc", "Modified", "Sig0", "Sig0", None, "Factor: 1 -> 2", parent_message="Msg"),
                Change("a.dbc", "Renamed", "OldSig1", "NewSig1", 0.9, "", parent_message="Msg"),
                Change("a.dbc", "Renamed", "OldSig2", "NewSig2", 0.85, "", parent_message="Msg"),
            ]
        )

    def test_no_rejections_returns_same_result(self):
        result = self._result_with_renames()
        self.assertIs(reject_signal_renames(result, set()), result)

    def test_rejected_rename_becomes_removed_plus_added(self):
        result = reject_signal_renames(self._result_with_renames(), {0})
        types = [c.change_type for c in result.signal_changes]
        self.assertEqual(types, ["Modified", "Removed", "Added", "Renamed"])
        removed = result.signal_changes[1]
        added = result.signal_changes[2]
        self.assertEqual(removed.old_name, "OldSig1")
        self.assertEqual(removed.new_name, "")
        self.assertEqual(added.old_name, "")
        self.assertEqual(added.new_name, "NewSig1")
        self.assertEqual(removed.parent_message, "Msg")
        self.assertIn("rejected by user", removed.description)

    def test_accepted_rename_untouched(self):
        result = reject_signal_renames(self._result_with_renames(), {0})
        kept = result.signal_changes[3]
        self.assertEqual(kept.change_type, "Renamed")
        self.assertEqual(kept.old_name, "OldSig2")

    def test_reject_all(self):
        result = reject_signal_renames(self._result_with_renames(), {0, 1})
        types = [c.change_type for c in result.signal_changes]
        self.assertEqual(types, ["Modified", "Removed", "Added", "Removed", "Added"])

    def test_summary_reflects_rejection(self):
        result = reject_signal_renames(self._result_with_renames(), {0, 1})
        summary = result.summary()
        self.assertEqual(summary["Signals Renamed"], 0)
        self.assertEqual(summary["Signals Removed"], 2)
        self.assertEqual(summary["Signals Added"], 2)


if __name__ == "__main__":
    unittest.main()
