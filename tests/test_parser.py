"""Parser tests using example DBC files."""

import tempfile
import unittest
from pathlib import Path

from dbc_compare_tool.core.parser import DbcParseError, parse_dbc, validate_database

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_OLD_BUS_A = _EXAMPLES / "old" / "Bus_A.dbc"
_NEW_BUS_A = _EXAMPLES / "new" / "Bus_A.dbc"

# The example baselines are Intel-only, so byte order needs its own fixture:
# @1 is little-endian (Intel), @0 is big-endian (Motorola).
_MIXED_ENDIAN_DBC = """VERSION ""

BO_ 100 Mixed: 8 ECU
 SG_ IntelSignal : 0|16@1+ (1,0) [0|65535] "" ECM
 SG_ MotorolaSignal : 23|16@0+ (1,0) [0|65535] "" ECM
 SG_ SignedSignal : 40|8@1- (1,0) [-128|127] "" ECM
"""


class TestParseOldBusA(unittest.TestCase):
    def setUp(self):
        self.db = parse_dbc(_OLD_BUS_A)

    def test_message_count(self):
        self.assertEqual(len(self.db.messages), 3)

    def test_message_names(self):
        self.assertIn("BCM_Status", self.db.messages)
        self.assertIn("EventMatrix_Old", self.db.messages)
        self.assertIn("Engine_Status", self.db.messages)

    def test_bcm_status_attributes(self):
        msg = self.db.messages["BCM_Status"]
        self.assertEqual(msg.can_id, 100)
        self.assertEqual(msg.dlc, 8)
        self.assertEqual(msg.transmitter, "BCM")
        self.assertEqual(msg.cycle_time_ms, 10)

    def test_bcm_status_signals(self):
        signals = self.db.messages["BCM_Status"].signals
        self.assertEqual(len(signals), 2)
        self.assertIn("VehicleSpeed", signals)
        self.assertIn("IgnitionState", signals)

    def test_vehicle_speed_properties(self):
        sig = self.db.messages["BCM_Status"].signals["VehicleSpeed"]
        self.assertEqual(sig.start_bit, 0)
        self.assertEqual(sig.length, 16)
        self.assertAlmostEqual(sig.factor, 0.01)
        self.assertEqual(sig.unit, "km/h")
        self.assertFalse(sig.is_signed)

    def test_engine_status_signal_count(self):
        self.assertEqual(len(self.db.messages["Engine_Status"].signals), 2)

    def test_event_matrix_signal_count(self):
        self.assertEqual(len(self.db.messages["EventMatrix_Old"].signals), 8)

    def test_db_path(self):
        self.assertEqual(self.db.path, _OLD_BUS_A)


class TestParseNewBusA(unittest.TestCase):
    def setUp(self):
        self.db = parse_dbc(_NEW_BUS_A)

    def test_message_count(self):
        self.assertEqual(len(self.db.messages), 3)

    def test_message_names(self):
        self.assertIn("Body_Status", self.db.messages)
        self.assertIn("EventMatrix_New", self.db.messages)
        self.assertIn("Engine_Info", self.db.messages)

    def test_engine_info_has_three_signals(self):
        self.assertEqual(len(self.db.messages["Engine_Info"].signals), 3)

    def test_veh_spd_max_updated(self):
        sig = self.db.messages["Body_Status"].signals["VehSpd"]
        self.assertEqual(sig.maximum, 220.0)


class TestByteOrderAndValueType(unittest.TestCase):
    """The report prints byte order as "Intel/little-endian (1)" or
    "Motorola/big-endian (0)", so the mapping direction is part of the output."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "mixed.dbc"
        path.write_text(_MIXED_ENDIAN_DBC, encoding="utf-8")
        self.signals = parse_dbc(path).messages["Mixed"].signals

    def test_intel_signal_maps_to_one(self):
        self.assertEqual(self.signals["IntelSignal"].byte_order, 1)

    def test_motorola_signal_maps_to_zero(self):
        self.assertEqual(self.signals["MotorolaSignal"].byte_order, 0)

    def test_value_type_follows_the_sign_flag(self):
        self.assertEqual(self.signals["IntelSignal"].value_type, "unsigned")
        self.assertFalse(self.signals["IntelSignal"].is_signed)
        self.assertEqual(self.signals["SignedSignal"].value_type, "signed")
        self.assertTrue(self.signals["SignedSignal"].is_signed)


class TestInventoryValidation(unittest.TestCase):
    def test_repeated_signal_and_frame_are_rejected_with_file_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.dbc"
            for line in (' SG_ IntelSignal : 56|8@1+ (1,0) [0|255] "" ECM\n',
                         'BO_ 100 Another: 8 ECU\n'):
                path.write_text(_MIXED_ENDIAN_DBC + line, encoding="utf-8")
                with self.subTest(line=line), self.assertRaises(DbcParseError) as error:
                    parse_dbc(path)
                self.assertIn(str(path), str(error.exception))

    def test_api_inventory_cannot_hide_repeated_signal_or_frame_with_alias_keys(self):
        from dataclasses import replace

        for kind in ("message", "signal", "frame"):
            db = parse_dbc(_OLD_BUS_A)
            msg = next(iter(db.messages.values()))
            if kind == "message":
                db.messages["Alias"] = msg
            elif kind == "signal":
                msg.signals["Alias"] = next(iter(msg.signals.values()))
            else:
                db.messages["Another"] = replace(msg, name="Another")
            with self.subTest(kind=kind), self.assertRaises(DbcParseError):
                validate_database(db)


if __name__ == "__main__":
    unittest.main()
