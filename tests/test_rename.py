"""Unit tests for rename detection logic."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from dbc_compare_tool.core.models import Message, Signal
from dbc_compare_tool.core.rename import (
    EventMessageDetector,
    MessageRenameDetector,
    RenameMatch,
    SignalRenameDetector,
)


def _make_signal(name: str, start_bit: int = 0, length: int = 8, **kwargs) -> Signal:
    defaults = dict(
        byte_order=1, value_type="unsigned", is_signed=False,
        factor=1.0, offset=0.0, minimum=0.0, maximum=255.0,
        unit="", receivers=(),
    )
    defaults.update(kwargs)
    return Signal(name=name, start_bit=start_bit, length=length, **defaults)


def _make_message(name: str, can_id: int, signals: dict[str, Signal] | None = None) -> Message:
    return Message(name=name, can_id=can_id, dlc=8, transmitter="ECU", signals=signals or {})


class TestSignalRenameDetector(unittest.TestCase):
    def setUp(self):
        self.detector = SignalRenameDetector()

    def test_identical_layout_matches(self):
        old = _make_signal("EngineTemp", start_bit=16, length=8)
        new = _make_signal("CoolantTemp", start_bit=16, length=8)
        matches = self.detector.match([old], [new])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].old.name, "EngineTemp")
        self.assertEqual(matches[0].new.name, "CoolantTemp")

    def test_different_layout_no_match(self):
        old = _make_signal("SigA", start_bit=0, length=8)
        new = _make_signal("SigB", start_bit=24, length=16)
        matches = self.detector.match([old], [new])
        self.assertEqual(len(matches), 0)

    def test_exact_same_signal_high_confidence(self):
        old = _make_signal("Speed", start_bit=0, length=16, factor=0.01, unit="km/h")
        new = _make_signal("VehicleSpeed", start_bit=0, length=16, factor=0.01, unit="km/h")
        matches = self.detector.match([old], [new])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].confidence_level, "High")

    def test_one_to_one_pairing(self):
        old1 = _make_signal("A", start_bit=0, length=8)
        old2 = _make_signal("B", start_bit=8, length=8)
        new1 = _make_signal("X", start_bit=0, length=8)
        new2 = _make_signal("Y", start_bit=8, length=8)
        matches = self.detector.match([old1, old2], [new1, new2])
        self.assertEqual(len(matches), 2)

    def test_confidence_levels(self):
        self.assertEqual(self.detector.get_confidence_level(0.95), "High")
        self.assertEqual(self.detector.get_confidence_level(0.80), "Medium")
        self.assertEqual(self.detector.get_confidence_level(0.65), "Low")

    def test_bulk_prefix_rename_keeps_unique_exact_pairs(self):
        old = [_make_signal(f"VCU_Value_{i}", start_bit=i * 8) for i in range(8)]
        new = [replace(signal, name=signal.name.replace("VCU_", "IVC_")) for signal in old]
        for event_like in (False, True):
            for targets in (new, list(reversed(new))):
                with self.subTest(event_like=event_like, reversed=targets != new):
                    matches = SignalRenameDetector(is_event_like=event_like).match(old, targets)
                    self.assertEqual({(m.old.name, m.new.name) for m in matches},
                                     {(a.name, b.name) for a, b in zip(old, new)})
                    self.assertTrue(all(m.confidence == 1.0 for m in matches))

    def test_exact_pairs_distinguish_multiplex_branches(self):
        old = [_make_signal(f"VCU_Size_{i}", start_bit=8, length=16,
                            multiplexer_ids=(i,), multiplexer_signal="Mode") for i in range(5)]
        new = [replace(signal, name=signal.name.replace("VCU_", "IVC_")) for signal in old]
        matches = self.detector.match(old, list(reversed(new)))
        self.assertEqual(len(matches), 5)
        self.assertTrue(all(m.old.multiplexer_ids == m.new.multiplexer_ids for m in matches))

    def test_all_properties_disambiguate_exact_pairs(self):
        variants = [
            {"minimum": 1.0}, {"maximum": 100.0}, {"value_type": "float"},
            {"comment": "Different meaning"}, {"value_descriptions": ((0, "Off"),)},
            {"is_multiplexer": True}, {"multiplexer_signal": "Other"},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                old = [_make_signal("VCU_A"), _make_signal("VCU_B", **variant)]
                new = [replace(signal, name=signal.name.replace("VCU_", "IVC_")) for signal in old]
                matches = self.detector.match(old, list(reversed(new)))
                self.assertEqual({(m.old.name, m.new.name) for m in matches},
                                 {("VCU_A", "IVC_A"), ("VCU_B", "IVC_B")})
                self.assertTrue(all(m.confidence == 1.0 for m in matches))

    def test_exact_pairs_use_ecu_mapping_without_changing_models(self):
        old = [_make_signal(f"VCU_Value_{i}", start_bit=i * 8, receivers=("OLD",)) for i in range(5)]
        new = [replace(s, name=s.name.replace("VCU_", "IVC_"), receivers=("NEW",)) for s in old]
        matches = SignalRenameDetector(ecu_map={"OLD": "NEW"}).match(old, new)
        self.assertEqual(len(matches), 5)
        self.assertTrue(all(m.confidence == 1.0 for m in matches))
        self.assertEqual(matches[0].old.receivers, ("OLD",))

    def test_property_change_is_not_reported_as_exact(self):
        old = _make_signal("VCU_Size")
        new = replace(old, name="IVC_Size", maximum=100.0)
        matches = self.detector.match([old], [new])
        self.assertEqual(len(matches), 1)
        self.assertLess(matches[0].confidence, 1.0)

    def test_slight_name_and_start_bit_changes_are_medium_confidence(self):
        old = _make_signal("BatteryVoltage", start_bit=16, length=16, factor=0.01, unit="V")
        for event_like in (False, True):
            for shift in (-8, -1, 1, 4, 8):
                with self.subTest(event_like=event_like, shift=shift):
                    new = replace(old, name="BatteryVoltageRaw", start_bit=old.start_bit + shift)
                    match, = SignalRenameDetector(is_event_like=event_like).match([old], [new])
                    self.assertEqual(match.confidence_level, "Medium")
                    self.assertLess(match.confidence, 0.90)
                    self.assertTrue(any("Start bit shifted" in reason for reason in match.reasons))

    def test_confidence_falls_with_weaker_names_and_position_evidence(self):
        old = _make_signal("BatteryVoltage", start_bit=16)
        close = replace(old, name="BatteryVoltageRaw", start_bit=17)
        distant = replace(close, start_bit=40)
        weaker_name = replace(close, name="Voltage")
        close_match, = self.detector.match([old], [close])
        distant_match, = self.detector.match([old], [distant])
        weak_match, = self.detector.match([old], [weaker_name])
        self.assertGreater(close_match.confidence, distant_match.confidence)
        self.assertGreater(close_match.confidence, weak_match.confidence)

    def test_weak_but_eligible_pair_is_retained_with_low_confidence(self):
        old = _make_signal("State", start_bit=8)
        new = replace(old, name="Temperature", start_bit=32)
        match, = self.detector.match([old], [new])
        self.assertEqual(match.confidence_level, "Low")
        self.assertTrue(any("review recommended" in reason for reason in match.reasons))

    def test_confidence_level_agrees_with_displayed_score_at_medium_boundary(self):
        old, new = _make_signal("Old", 0), _make_signal("New", 1)
        for score, expected_level in ((0.694, "Low"), (0.699, "Medium"), (0.704, "Medium")):
            with self.subTest(score=score):
                with patch.object(self.detector, "score", return_value=(score / 0.89, ())):
                    match, = self.detector.match([old], [new])
                self.assertEqual(match.confidence_level, expected_level)
                self.assertEqual(match.confidence, float(f"{match.confidence:.2f}"))

    def test_bulk_shift_does_not_lock_renames_to_a_neighboring_old_layout(self):
        old = [_make_signal(f"Event_Door_{i}", start_bit=i, length=1) for i in range(8)]
        new = [replace(signal, name=signal.name + "_New", start_bit=signal.start_bit + 1) for signal in old]
        for event_like in (False, True):
            for targets in (new, list(reversed(new))):
                with self.subTest(event_like=event_like, reversed=targets != new):
                    matches = SignalRenameDetector(is_event_like=event_like).match(old, targets)
                    self.assertEqual({(m.old.name, m.new.name) for m in matches},
                                     {(signal.name, signal.name + "_New") for signal in old})
                    self.assertTrue(all(m.confidence < 0.90 for m in matches))

    def test_global_assignment_prioritizes_coverage_over_strongest_pair(self):
        old = [_make_signal("A", 0), _make_signal("B", 8)]
        new = [_make_signal("X", 1), _make_signal("Y", 9)]
        scores = {("A", "X"): 0.95, ("A", "Y"): 0.70,
                  ("B", "X"): 0.80, ("B", "Y"): 0.10}
        with patch.object(self.detector, "score", side_effect=lambda a, b: (scores[a.name, b.name], ())):
            matches = self.detector.match(old, new)
        self.assertEqual({(m.old.name, m.new.name) for m in matches}, {("A", "Y"), ("B", "X")})
        self.assertTrue(all(m.confidence_level == "Low" for m in matches))

    def test_unequal_inventories_and_ties_are_deterministic(self):
        old = [_make_signal("A", 0), _make_signal("B", 8), _make_signal("C", 16)]
        new = [_make_signal("X", 1), _make_signal("Y", 9)]
        with patch.object(self.detector, "score", return_value=(0.75, ())):
            first = self.detector.match(old, new)
            second = self.detector.match(reversed(old), reversed(new))
        self.assertEqual([(m.old.name, m.new.name) for m in first], [(m.old.name, m.new.name) for m in second])
        self.assertEqual(len(first), 2)
        self.assertEqual(len({id(m.old) for m in first}), 2)
        self.assertEqual(len({id(m.new) for m in first}), 2)

    def test_empty_inventory_has_no_pairs(self):
        self.assertEqual(self.detector.match([], [_make_signal("New")]), [])
        self.assertEqual(self.detector.match([_make_signal("Old")], []), [])

    def test_duplicate_event_properties_remain_pairable_with_low_confidence(self):
        old = [_make_signal("AB"), _make_signal("CD")]
        new = [_make_signal("XY"), _make_signal("ZW")]
        matches = SignalRenameDetector(is_event_like=True).match(old, new)
        self.assertEqual(len(matches), 2)
        self.assertTrue(all(match.confidence_level == "Low" for match in matches))

    def test_deferred_exact_pairs_stay_eligible_when_names_are_unrelated(self):
        old = [_make_signal("AB", 0), _make_signal("CD", 1)]
        new = [_make_signal("EF", 0), _make_signal("AG", 1)]
        matches = SignalRenameDetector(is_event_like=True).match(old, new)
        self.assertEqual(len(matches), 2)
        self.assertEqual({(match.old.start_bit, match.new.start_bit) for match in matches}, {(0, 0), (1, 1)})


class TestSignalRenameDetectorEventMode(unittest.TestCase):
    def test_event_mode_uses_lower_threshold(self):
        detector = SignalRenameDetector(is_event_like=True)
        self.assertEqual(detector.threshold, detector.event_threshold)

    def test_event_mode_name_similarity_drives_match(self):
        detector = SignalRenameDetector(is_event_like=True)
        old = _make_signal("Event_Door_Open", start_bit=0, length=1)
        new = _make_signal("Door_Opened", start_bit=0, length=1)
        matches = detector.match([old], [new])
        self.assertEqual(len(matches), 1)


class TestAmbiguityAdjustment(unittest.TestCase):
    def test_two_old_rivals_for_one_new_keep_a_low_confidence_pair(self):
        detector = SignalRenameDetector()
        old1 = _make_signal("A", start_bit=0, length=8)
        old2 = _make_signal("B", start_bit=0, length=8)  # same layout as old1
        new = _make_signal("X", start_bit=0, length=8)
        matches = detector.match([old1, old2], [new])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].confidence_level, "Low")
        self.assertTrue(any("Ambiguous" in reason for reason in matches[0].reasons))

    def test_one_old_rival_for_two_new_keeps_a_low_confidence_pair(self):
        detector = SignalRenameDetector()
        old = _make_signal("A", start_bit=0, length=8)
        new1 = _make_signal("X", start_bit=0, length=8)
        new2 = _make_signal("Y", start_bit=0, length=8)
        matches = detector.match([old], [new1, new2])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].confidence_level, "Low")
        self.assertTrue(any("Ambiguous" in reason for reason in matches[0].reasons))

    def test_strong_ambiguous_candidate_remains_flagged(self):
        detector = SignalRenameDetector()
        old1 = _make_signal("VehicleSpeed", start_bit=0, length=8)
        old2 = _make_signal("VehicleSpeeds", start_bit=0, length=8)
        new = _make_signal("VehicleSpeedNew", start_bit=0, length=8)
        matches = detector.match([old1, old2], [new])
        self.assertEqual(len(matches), 1)
        self.assertTrue(any("Ambiguous" in r for r in matches[0].reasons))

    def test_adjustment_never_raises_confidence(self):
        # Regression: the fixed 0.70 floor used to raise event-like scores
        # (threshold 0.65) above their unadjusted value.
        detector = SignalRenameDetector(is_event_like=True)
        old1 = _make_signal("a")
        old2 = _make_signal("b")
        new = _make_signal("x")
        base = 0.66  # below the old fixed 0.70 floor
        candidates = [
            RenameMatch(old1, new, base, "Low", ()),
            RenameMatch(old2, new, base, "Low", ()),
        ]
        adjusted = detector._adjust_for_ambiguity(candidates)
        for match in adjusted:
            self.assertLessEqual(match.confidence, base)
            self.assertTrue(any("Ambiguous" in r for r in match.reasons))


class TestMessageRenameDetector(unittest.TestCase):
    def setUp(self):
        self.detector = MessageRenameDetector()

    def test_same_can_id_matches(self):
        old = _make_message("BCM_Status", can_id=100)
        new = _make_message("Body_Status", can_id=100)
        matches = self.detector.match([old], [new])
        self.assertEqual(len(matches), 1)

    def test_different_can_id_no_match(self):
        old = _make_message("MsgA", can_id=100)
        new = _make_message("MsgB", can_id=999)
        matches = self.detector.match([old], [new])
        self.assertEqual(len(matches), 0)


class TestEventMessageDetector(unittest.TestCase):
    def _make_event_signals(self, count: int) -> dict[str, Signal]:
        return {
            f"Event_{i}": _make_signal(f"Event_{i}", start_bit=i, length=1)
            for i in range(count)
        }

    def test_event_like_with_many_short_signals(self):
        msg = _make_message("EventMatrix", can_id=200, signals=self._make_event_signals(8))
        self.assertTrue(EventMessageDetector.is_event_like(msg))

    def test_not_event_like_with_few_signals(self):
        msg = _make_message("Normal", can_id=100, signals={
            "Speed": _make_signal("Speed", length=16),
        })
        self.assertFalse(EventMessageDetector.is_event_like(msg))

    def test_warning_message_is_string(self):
        self.assertIsInstance(EventMessageDetector.get_warning(), str)
        self.assertGreater(len(EventMessageDetector.get_warning()), 0)


if __name__ == "__main__":
    unittest.main()
