"""ECU rename equivalence, validation and preserved original report context."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from dbc_compare_tool.cli import main
from dbc_compare_tool.core.comparator import DbcComparator, filter_result
from dbc_compare_tool.core.ecu import collect_ecu_nodes, validate_ecu_map
from dbc_compare_tool.core.models import DbcDatabase, Message, Signal
from dbc_compare_tool.core.pairing import DatabaseCandidate, match_renamed_databases
from dbc_compare_tool.core.parser import parse_dbc
from dbc_compare_tool.core.rename import MessageRenameDetector, SignalRenameDetector


def _database(tx: str, rx: tuple[str, ...], *, factor: float = 1.0) -> DbcDatabase:
    signal = Signal("Speed", 0, 8, 1, "unsigned", False, factor, 0.0, 0, 255, "", rx)
    message = Message("Status", 100, 8, tx, signals={signal.name: signal}, cycle_time_ms=10)
    return DbcDatabase(Path("bus.dbc"), {message.name: message})


class TestEcuPairing(unittest.TestCase):
    def test_mapped_tx_rx_are_unchanged_and_original_context_is_preserved(self):
        old = _database("OLD", ("OLD", "OTHER"))
        new = _database("NEW", ("NEW", "OTHER"))
        result = DbcComparator(include_unchanged=True, ecu_map={"OLD": "NEW"}).compare_databases("bus", old, new)
        self.assertEqual(result.summary()["Total Changes"], 0)
        self.assertEqual(result.ecu_map, {"OLD": "NEW"})
        message, signal = result.message_changes[0], result.signal_changes[0]
        self.assertEqual((message.change_type, signal.change_type), ("Unchanged", "Unchanged"))
        self.assertEqual((message.property_diffs, signal.property_diffs), ((), ()))
        self.assertIs(message.old_message, old.messages["Status"])
        self.assertEqual(message.old_message.transmitter, "OLD")
        self.assertEqual(signal.old_signal.receivers, ("OLD", "OTHER"))
        self.assertEqual(signal.new_signal.receivers, ("NEW", "OTHER"))

    def test_mapping_is_opt_in(self):
        old, new = _database("OLD", ("OLD",)), _database("NEW", ("NEW",))
        plain = DbcComparator().compare_databases("bus", old, new)
        empty = DbcComparator(ecu_map={}).compare_databases("bus", old, new)
        self.assertEqual(plain, empty)
        self.assertEqual(plain.summary()["Total Changes"], 2)
        self.assertEqual(plain.message_changes[0].property_diffs, (("Transmitter", "OLD", "NEW"),))

    def test_real_routing_and_value_changes_keep_original_names(self):
        old = _database("OLD,OTHER", ("OLD", "OTHER"))
        new = _database("EXTRA,NEW", ("EXTRA", "NEW"), factor=2.0)
        result = DbcComparator(ecu_map={"OLD": "NEW"}).compare_databases("bus", old, new)
        self.assertIn(("Transmitter", "OLD,OTHER", "EXTRA,NEW"), result.message_changes[0].property_diffs)
        self.assertIn(("Receivers", "OLD, OTHER", "EXTRA, NEW"), result.signal_changes[0].property_diffs)
        self.assertIn(("Factor", "1", "2"), result.signal_changes[0].property_diffs)

    def test_multiple_senders_are_mapped_individually_and_reordered(self):
        old, new = _database("A,Z", ("A", "Z")), _database("B,C", ("B", "C"))
        result = DbcComparator(ecu_map={"A": "C", "Z": "B"}).compare_databases("bus", old, new)
        self.assertEqual(result.summary()["Total Changes"], 0)

    def test_mapping_does_not_replace_substrings(self):
        old, new = _database("ECU,ECU_EXTRA", ("ECU",)), _database("ECU_EXTRA,NEW", ("NEW",))
        result = DbcComparator(ecu_map={"ECU": "NEW"}).compare_databases("bus", old, new)
        self.assertEqual(result.summary()["Total Changes"], 0)

    def test_swaps_are_simultaneous_and_identity_is_allowed(self):
        old, new = _database("A", ("B",)), _database("B", ("A",))
        result = DbcComparator(ecu_map={"A": "B", "B": "A"}).compare_databases("bus", old, new)
        self.assertEqual(result.summary()["Total Changes"], 0)
        validate_ecu_map({"A": "A"}, {"A", "B"}, {"A", "B"})

    def test_same_literal_names_are_changed_when_swapped_identities_differ(self):
        old, new = _database("A", ("B",)), _database("A", ("B",))
        result = DbcComparator(ecu_map={"A": "B", "B": "A"}).compare_databases("bus", old, new)
        self.assertEqual(result.summary()["Total Changes"], 2)
        self.assertEqual(result.message_changes[0].property_diffs, (("Transmitter", "A", "A"),))
        self.assertEqual(result.signal_changes[0].property_diffs, (("Receivers", "B", "B"),))

    def test_same_literal_names_are_changed_when_old_name_is_reused_in_new(self):
        old, new = _database("A", ("A",)), _database("A", ("A",))
        new.nodes = ("A", "B")
        result = DbcComparator(ecu_map={"A": "B"}).compare_databases("bus", old, new)
        self.assertEqual(result.summary()["Total Changes"], 2)
        self.assertEqual(result.message_changes[0].property_diffs, (("Transmitter", "A", "A"),))
        self.assertEqual(result.signal_changes[0].property_diffs, (("Receivers", "A", "A"),))

    def test_partial_mapping_keeps_unselected_nodes_and_original_report_context(self):
        for mapping in ({"A": "B"}, {"A": "B", "C": "D"}, {"A": "B", "B": "B"}):
            with self.subTest(mapping=mapping):
                old = _database("A", ("C",))
                new = _database("B", (mapping.get("C", "C"),))
                stable = replace(_database("B", ("D", "E")).messages["Status"], name="Stable", can_id=200)
                old.messages["Stable"] = new.messages["Stable"] = stable
                result = DbcComparator(include_unchanged=True, ecu_map=mapping).compare_databases("bus", old, new)
                self.assertEqual(result.summary()["Total Changes"], 0)
                self.assertEqual(len(result.message_changes), 2)
                self.assertEqual(len(result.signal_changes), 2)
                self.assertTrue(all(change.change_type == "Unchanged" for change in result.message_changes + result.signal_changes))
                self.assertEqual(result.message_changes[0].old_message.transmitter, "A")
                self.assertEqual(result.message_changes[0].new_message.transmitter, "B")
                self.assertEqual(result.message_changes[1].old_message.transmitter, "B")
                self.assertEqual(result.message_changes[1].new_message.transmitter, "B")

    def test_duplicate_targets_and_unknown_nodes_are_rejected(self):
        cases = [
            ({"A": "C", "B": "C"}, {"A", "B"}, {"C"}, "more than once"),
            ({"MISSING": "C"}, {"A"}, {"C"}, "OLD: MISSING"),
            ({"A": "MISSING"}, {"A"}, {"C"}, "NEW: MISSING"),
            ({"": "B"}, {"A"}, {"B"}, "non-empty"),
        ]
        for mapping, old, new, message in cases:
            with self.subTest(mapping=mapping), self.assertRaisesRegex(ValueError, message):
                validate_ecu_map(mapping, old, new)

    def test_invalid_mapping_is_rejected_by_comparator(self):
        with self.assertRaisesRegex(ValueError, "OLD: MISSING"):
            DbcComparator(ecu_map={"MISSING": "NEW"}).compare_databases(
                "bus", _database("OLD", ()), _database("NEW", ()),
            )
        with self.assertRaisesRegex(ValueError, "more than once"):
            DbcComparator(ecu_map={"A": "NEW", "B": "NEW"})

    def test_mapping_is_copied_and_filter_retains_it(self):
        mapping = {"OLD": "NEW"}
        comparator = DbcComparator(ecu_map=mapping)
        mapping["OLD"] = "WRONG"
        result = comparator.compare_databases("bus", _database("OLD", ()), _database("NEW", (), factor=2))
        filtered = filter_result(result, {"Modified"})
        self.assertEqual(filtered.ecu_map, {"OLD": "NEW"})
        self.assertEqual(len(filtered.signal_changes), 1)

    def test_message_rename_crosses_threshold_with_mapped_transmitter(self):
        old, new = _database("OLD", ()), _database("NEW", ())
        renamed = replace(new.messages.pop("Status"), name="StatusNew", can_id=200)
        new.messages[renamed.name] = renamed
        plain = DbcComparator().compare_databases("bus", old, new)
        mapped = DbcComparator(ecu_map={"OLD": "NEW"}).compare_databases("bus", old, new)
        self.assertEqual({c.change_type for c in plain.message_changes}, {"Added", "Removed"})
        self.assertEqual([c.change_type for c in mapped.message_changes], ["Renamed"])
        self.assertNotIn("Transmitter", dict((key, before) for key, before, after in mapped.message_changes[0].property_diffs))

    def test_same_name_id_change_keeps_ecu_mapping_and_reports_only_real_deltas(self):
        old, new = _database("OLD", ()), _database("NEW", ())
        new.messages["Status"].can_id = 200
        result = DbcComparator(ecu_map={"OLD": "NEW"}).compare_databases("bus", old, new)
        self.assertEqual([c.change_type for c in result.message_changes], ["Modified"])
        self.assertEqual(result.message_changes[0].property_diffs, (("CAN ID", "100", "200"),))
        self.assertEqual(result.signal_changes, [])

    def test_signal_rename_scoring_honors_mapped_receivers(self):
        old = _database("OLD", ("OLD",)).messages["Status"].signals["Speed"]
        new = replace(old, name="Velocity", receivers=("NEW",), factor=2.0)
        self.assertFalse(SignalRenameDetector().match([old], [new]))
        matches = SignalRenameDetector(ecu_map={"OLD": "NEW"}).match([old], [new])
        self.assertEqual(len(matches), 1)
        self.assertIn("Receivers matched", matches[0].reasons)
        event_score = SignalRenameDetector(is_event_like=True, ecu_map={"OLD": "NEW"}).score(old, new)[0]
        plain_score = SignalRenameDetector(is_event_like=True).score(old, new)[0]
        self.assertAlmostEqual(event_score - plain_score, 0.06)

    def test_database_pairing_scoring_honors_mapping(self):
        old = DatabaseCandidate("alpha.dbc", _database("OLD", ()))
        new = DatabaseCandidate("beta.dbc", _database("NEW", ()))
        plain = match_renamed_databases([old], [new])[0]
        mapped = match_renamed_databases([old], [new], {"OLD": "NEW"})[0]
        self.assertGreater(mapped.confidence, plain.confidence)
        self.assertIn("Common CAN ID structures 100% matched", mapped.reasons)
        self.assertIn("Transmitter matched", MessageRenameDetector(ecu_map={"OLD": "NEW"}).score(
            old.database.messages["Status"], new.database.messages["Status"],
        )[1])


class TestEcuDiscoveryAndFolderMappings(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _write(self, path: Path, tx: str, rx: str, declared: str = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'VERSION ""\nBU_: {declared}\n\nBO_ 100 Status: 8 {tx}\n'
            f' SG_ Speed : 0|8@1+ (1,0) [0|255] "" {rx}\n', encoding="utf-8",
        )
        return path

    def test_discovery_includes_declared_unused_and_routing_only_nodes(self):
        file = self._write(self.root / "bus.DBC", "TX", "RX", "UNUSED")
        self.assertEqual(parse_dbc(file).nodes, ("UNUSED",))
        self.assertEqual(collect_ecu_nodes(file), ["RX", "TX", "UNUSED"])
        self._write(self.root / "nested" / "second.dbc", "EXTRA", "Vector__XXX")
        (self.root / "invalid.dbc").write_text("invalid DBC", encoding="utf-8")
        self.assertEqual(collect_ecu_nodes(self.root), ["EXTRA", "RX", "TX", "UNUSED"])

    def test_folder_mapping_is_validated_across_whole_inventory(self):
        for side, nodes in (("old", ("A", "B")), ("new", ("C", "D"))):
            for index, node in enumerate(nodes):
                self._write(self.root / side / f"{index}.dbc", node, node)
        comparator = DbcComparator(ecu_map={"A": "C", "B": "D"})
        result = comparator.compare_paths(self.root / "old", self.root / "new")
        self.assertEqual(result.summary()["Total Changes"], 0)
        manual = comparator.compare_manual(self.root / "old", self.root / "new", {"0.dbc": "0.dbc", "1.dbc": "1.dbc"})
        self.assertEqual(manual.summary()["Total Changes"], 0)
        with self.assertRaisesRegex(ValueError, "OLD: MISSING"):
            DbcComparator(ecu_map={"MISSING": "C"}).compare_paths(self.root / "old", self.root / "new")

    def test_partial_mapping_in_files_folders_manual_and_cli(self):
        for mapping in ({"A": "B"}, {"A": "B", "C": "D"}):
            with self.subTest(mapping=mapping):
                for index, node in enumerate(("A", "B", "C", "D", "E")):
                    self._write(self.root / "old" / f"{index}.dbc", node, node, "A B C D E")
                    target = mapping.get(node, node)
                    self._write(self.root / "new" / f"{index}.dbc", target, target, "B C D E")
                comparator = DbcComparator(ecu_map=mapping)
                results = [
                    comparator.compare_files(self.root / "old/0.dbc", self.root / "new/0.dbc"),
                    comparator.compare_paths(self.root / "old", self.root / "new"),
                    comparator.compare_manual(self.root / "old", self.root / "new",
                                              {f"{i}.dbc": f"{i}.dbc" for i in range(5)}),
                ]
                self.assertTrue(all(result.summary()["Total Changes"] == 0 for result in results))
                for mode in ("files", "folders"):
                    suffix = "0.dbc" if mode == "files" else ""
                    output = self.root / f"{mode}.xlsx"
                    args = ["--old", str(self.root / "old" / suffix), "--new", str(self.root / "new" / suffix),
                            "--out", str(output)]
                    for old, new in mapping.items():
                        args.extend(("--ecu-pair", f"{old}={new}"))
                    log = io.StringIO()
                    with contextlib.redirect_stdout(log):
                        self.assertEqual(main(args), 0)
                    self.assertIn("Total changes: 0", log.getvalue())
                    self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
