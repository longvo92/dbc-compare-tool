"""Signal regressions against the single shared matching implementation."""

from __future__ import annotations

import unittest
from dataclasses import replace

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.core.matching import identity, match_entities
from dbc_compare_tool.core.policy import RECALL_V1, signal_evidence
from tests.pairing_fixtures import database, message, signal


def pairs(old, new, ecu_map=None):
    parent = message()
    a = {identity("OLD", "bus", s, parent): s for s in old}
    b = {identity("NEW", "bus", s, parent): s for s in new}
    selected, _ = match_entities(
        a,
        b,
        lambda x, y: signal_evidence(a[x], b[y], ecu_map or {}, RECALL_V1),
        RECALL_V1,
    )
    return selected


class SignalPolicyTests(unittest.TestCase):
    def test_actual_complete_signal_edge_does_not_block_maximum_cardinality(self):
        a, b = signal("aaaa"), signal("zzzz", factor=9)
        x, y = signal("qqqq"), signal("aaaa_new", 40, factor=2)
        evidence = signal_evidence(a, x, {}, RECALL_V1)
        self.assertTrue(evidence.complete)
        self.assertIsNone(signal_evidence(b, y, {}, RECALL_V1))
        result = DbcComparator().compare_databases(
            "bus",
            database("old", [message(signals=[a, b])]),
            database("new", [message(signals=[x, y])]),
        )
        self.assertEqual(
            {(c.old_name, c.new_name) for c in result.signal_changes},
            {("aaaa", "aaaa_new"), ("zzzz", "qqqq")},
        )

    def test_bulk_prefix_and_shift_find_names_in_both_inventory_orders(self):
        for shift in (0, 1):
            old = [signal(f"VCU_Value_{i}", i * 8) for i in range(8)]
            new = [
                replace(
                    s,
                    name=s.name.replace("VCU_", "IVC_"),
                    start_bit=s.start_bit + shift,
                )
                for s in old
            ]
            expected = {(a.name, b.name) for a, b in zip(old, new)}
            for targets in (new, list(reversed(new))):
                result = pairs(old, targets)
                self.assertEqual(
                    {(p.old.signal_name, p.new.signal_name) for p in result}, expected
                )
                self.assertTrue(all(p.confidence < 1 for p in result))

    def test_multiplex_branches_and_full_properties_disambiguate(self):
        old = [
            signal("A", multiplexer_ids=(1,), multiplexer_signal="Mux"),
            signal("B", multiplexer_ids=(2,), multiplexer_signal="Mux"),
        ]
        new = [replace(s, name=f"{s.name}_new") for s in old]
        selected = pairs(old, new)
        self.assertEqual(
            {(p.old.signal_name, p.new.signal_name) for p in selected},
            {("A", "A_new"), ("B", "B_new")},
        )
        self.assertTrue(all(p.requires_review for p in selected))
        old = [
            signal("A", comment="first"),
            signal("B", value_descriptions=((1, "second"),)),
        ]
        new = [replace(s, name=f"{s.name}_new") for s in old]
        self.assertEqual(len(pairs(old, new)), 2)

    def test_equal_layout_rivals_are_retained_and_confidence_stays_below_high(self):
        old = [signal("A"), signal("B")]
        new = [signal("X"), signal("Y")]
        selected = pairs(old, new)
        self.assertEqual(len(selected), 2)
        self.assertTrue(
            all(
                p.requires_review and p.competitors and p.confidence < 0.9
                for p in selected
            )
        )
        self.assertEqual(pairs([], new), [])
        self.assertEqual(pairs(old, []), [])

    def test_unique_complete_with_ecu_mapping_and_changed_property(self):
        old, new = signal("Old", receivers=("OLD",)), signal("New", receivers=("NEW",))
        selected = pairs([old], [new], {"OLD": "NEW"})
        self.assertEqual(selected[0].confidence, 1.0)
        changed = pairs([old], [replace(new, maximum=128)], {"OLD": "NEW"})
        self.assertLess(changed[0].confidence, 1.0)
