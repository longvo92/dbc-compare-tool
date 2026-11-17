"""Value table (VAL_) and comment/description comparison."""

import tempfile
import unittest
from pathlib import Path

from dbc_compare_tool.dbc_compare.core.comparator import DbcComparator
from dbc_compare_tool.dbc_compare.core.parser import parse_dbc

_OLD_DBC = """VERSION ""

BO_ 100 Gear_Status: 8 TCU
 SG_ GearState : 0|4@1+ (1,0) [0|15] "" ECM
CM_ BO_ 100 "Gear status message.";
CM_ SG_ 100 GearState "Current gear state.";
VAL_ 100 GearState 0 "Park" 1 "Reverse" 2 "Neutral" ;
"""

_NEW_DBC = """VERSION ""

BO_ 100 Gear_Status: 8 TCU
 SG_ GearState : 0|4@1+ (1,0) [0|15] "" ECM
CM_ BO_ 100 "Gear status message, updated.";
CM_ SG_ 100 GearState "Current gear state, includes Park/Drive.";
VAL_ 100 GearState 0 "Park" 1 "Reverse" 2 "Neutral" 3 "Drive" ;
"""


class TestValueDescriptionsAndComments(unittest.TestCase):
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

    def test_message_comment_parsed(self):
        old_db = parse_dbc(Path(self._tmp_dir.name) / "old.dbc")
        self.assertEqual(old_db.messages["Gear_Status"].comment, "Gear status message.")

    def test_signal_value_descriptions_parsed(self):
        old_db = parse_dbc(Path(self._tmp_dir.name) / "old.dbc")
        signal = old_db.messages["Gear_Status"].signals["GearState"]
        self.assertEqual(signal.value_descriptions, ((0, "Park"), (1, "Reverse"), (2, "Neutral")))

    def test_message_description_change_detected(self):
        modified = [c for c in self.result.message_changes if c.change_type == "Modified"]
        self.assertEqual(len(modified), 1)
        property_names = {name for name, _, _ in modified[0].property_diffs}
        self.assertIn("Description", property_names)

    def test_signal_value_descriptions_change_detected(self):
        modified = [c for c in self.result.signal_changes if c.change_type == "Modified"]
        self.assertEqual(len(modified), 1)
        property_names = {name for name, _, _ in modified[0].property_diffs}
        self.assertIn("Value Descriptions", property_names)
        self.assertIn("Description", property_names)


if __name__ == "__main__":
    unittest.main()
