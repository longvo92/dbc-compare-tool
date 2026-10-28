"""Recall-v1 regressions and inventory invariants, independent of Qt."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from dbc_compare_tool.cli import main
from dbc_compare_tool.core.comparator import DbcComparator, filter_result
from dbc_compare_tool.core.matching import identity, match_entities
from dbc_compare_tool.core.models import DbcDatabase, Message
from dbc_compare_tool.core.parser import DbcParseError, parse_dbc
from dbc_compare_tool.core.policy import (
    RECALL_V1,
    Evidence,
    database_evidence,
    database_profile,
    message_evidence,
    message_profile,
    name_similarity,
    overlap,
    signal_evidence,
)
from dbc_compare_tool.report.excel import ReportExportError, write_excel_report

from tests.pairing_fixtures import database, message, signal, write_dbc


class EvidenceTests(unittest.TestCase):
    def test_missing_cycle_time_is_unavailable_not_matching_evidence(self):
        old, new = message(signals=[signal()]), message(signals=[signal()])
        absent = message_evidence(old, new, {}, RECALL_V1)
        old.cycle_time_ms, new.cycle_time_ms = 10, 10
        equal = message_evidence(old, new, {}, RECALL_V1)
        self.assertEqual(absent.similarity, equal.similarity)
        new.cycle_time_ms = 20
        self.assertLess(
            message_evidence(old, new, {}, RECALL_V1).similarity, absent.similarity
        )
        old.cycle_time_ms = None
        self.assertEqual(
            message_evidence(old, new, {}, RECALL_V1).similarity, absent.similarity
        )

    def test_empty_collections_do_not_supply_evidence_and_multisets_keep_mux(self):
        self.assertIsNone(overlap(set(), set()))
        a = message(signals=[signal("A"), signal("B")])
        b = message(signals=[signal("X"), signal("Y", 16)])
        self.assertEqual(
            overlap(message_profile(a).layouts, message_profile(b).layouts), 0.5
        )
        c = message(
            signals=[signal("X", multiplexer_ids=(1,), multiplexer_signal="Mux")]
        )
        self.assertEqual(
            overlap(message_profile(a).layouts, message_profile(c).layouts), 0
        )
        x = database_profile("alpha.dbc", database("alpha", [message("A", 1)]))
        y = database_profile("beta.dbc", database("beta", [message("Z", 2)]))
        self.assertIsNone(database_evidence(x, y, RECALL_V1))

    def test_structure_ignores_message_name_id_cycle_and_keeps_multiplicity(self):
        old = message(signals=[signal("A"), signal("B")])
        new = message("Renamed", 200, [signal("X"), signal("Y")], cycle_time_ms=10)
        self.assertEqual(message_profile(old).structure, message_profile(new).structure)
        self.assertNotEqual(
            message_profile(old).structure,
            message_profile(message(signals=[signal("A")])).structure,
        )

    def test_unrelated_signals_and_messages_stay_unmatched(self):
        a = signal("aaa", 0)
        b = signal(
            "zzz",
            60,
            length=3,
            byte_order=0,
            factor=7,
            offset=9,
            unit="other",
            is_signed=True,
        )
        self.assertIsNone(signal_evidence(a, b, {}, RECALL_V1))
        x = message("aaa", 100, [a])
        y = Message("zzz", 200, 7, "OTHER", signals={b.name: b})
        self.assertIsNone(message_evidence(x, y, {}, RECALL_V1))

    def test_position_similarity_has_no_eight_bit_cliff(self):
        old = signal()
        scores = [
            signal_evidence(
                old, replace(old, name="SpeedNew", start_bit=i), {}, RECALL_V1
            ).similarity
            for i in (7, 8, 9, 10)
        ]
        self.assertTrue(all(a > b for a, b in zip(scores, scores[1:])))
        self.assertLess(abs(scores[1] - scores[2]), 0.01)
        self.assertEqual(name_similarity("Straße", "STRASSE"), 1.0)

    def test_ecu_mapping_affects_evidence_without_mutating_inputs(self):
        old = signal(receivers=("OLD",))
        new = replace(old, receivers=("NEW",), name="Velocity")
        plain = signal_evidence(old, new, {}, RECALL_V1)
        mapped = signal_evidence(old, new, {"OLD": "NEW"}, RECALL_V1)
        self.assertGreater(mapped.similarity, plain.similarity)
        self.assertEqual(old.receivers, ("OLD",))


class RecallRegressions(unittest.TestCase):
    def test_actual_message_graph_finds_two_pairs_instead_of_greedy_one(self):
        a = message("aaaa", 1, [signal("A")])
        b = Message("zzzz", 2, 7, "OTHER", signals={"B": signal("B", 32)})
        x = message("zzzz", 1, [signal("B", 32)])
        y = message("aaaa_new", 99, [signal("C", 60, length=3, factor=7)])
        self.assertIsNone(message_evidence(b, y, {}, RECALL_V1))
        result = DbcComparator().compare_databases(
            "bus", database("old", [a, b]), database("new", [x, y])
        )
        self.assertEqual(
            {(c.old_name, c.new_name) for c in result.message_changes},
            {("aaaa", "aaaa_new"), ("zzzz", "zzzz")},
        )
        self.assertEqual(result.coverage["OLD message"], {"paired": 2})

    def test_actual_dbc_graph_prioritizes_count_over_total_similarity_and_same_path(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_dbc(root / "old/alpha.dbc", name="A", frame=1, sig="SA")
            write_dbc(root / "old/beta.dbc", name="B", frame=2, sig="SB", start=32)
            x = write_dbc(root / "new/alpha.dbc", name="A", frame=1, sig="SA")
            y = write_dbc(
                root / "new/gamma.dbc",
                name="Z",
                frame=999,
                sig="SA",
                start=60,
                length=3,
            )
            x.write_text(
                x.read_text()
                + 'BO_ 2 B: 4 OTHER\n SG_ SB : 48|3@1+ (7,9) [0|7] "other" OTHER\n'
            )
            self.assertTrue(y.exists())
            result = DbcComparator().compare_folders(root / "old", root / "new")
            self.assertEqual(
                {(p.old_path, p.new_path) for p in result.file_pairs},
                {("alpha.dbc", "gamma.dbc"), ("beta.dbc", "alpha.dbc")},
            )
            self.assertEqual(result.coverage["OLD dbc"], {"paired": 2})

    def test_greedy_message_and_exact_signal_do_not_reserve_edges(self):
        # The strong exact edge loses to two eligible pairs at BOTH hierarchy levels.
        for kind in ("message", "signal", "dbc"):
            old = [
                identity(
                    "OLD",
                    "a" if kind == "dbc" else "bus",
                    None if kind == "dbc" else message("A", 1),
                ),
                identity(
                    "OLD",
                    "b" if kind == "dbc" else "bus",
                    None if kind == "dbc" else message("B", 2),
                ),
            ]
            new = [
                identity(
                    "NEW",
                    "x" if kind == "dbc" else "bus",
                    None if kind == "dbc" else message("X", 3),
                ),
                identity(
                    "NEW",
                    "y" if kind == "dbc" else "bus",
                    None if kind == "dbc" else message("Y", 4),
                ),
            ]
            edges = {
                (old[0], new[0]): Evidence(1.0, ("complete",), True),
                (old[0], new[1]): Evidence(0.1, ("weak",)),
                (old[1], new[0]): Evidence(0.1, ("weak",)),
            }
            pairs, candidates = match_entities(
                old, new, lambda a, b: edges.get((a, b)), RECALL_V1
            )
            self.assertEqual(
                {(p.old, p.new) for p in pairs}, {(old[0], new[1]), (old[1], new[0])}
            )
            self.assertTrue(
                all(p.requires_review and p.confidence < 0.9 for p in pairs)
            )
            self.assertEqual(len(candidates), 3)

    def test_dbc_and_message_same_identity_are_evidence_not_constraints(self):
        old = database(
            "bus",
            [message("A", 1, [signal("A", 0)]), message("B", 2, [signal("B", 32)])],
        )
        new = database(
            "bus",
            [message("B", 1, [signal("B", 32)]), message("A", 2, [signal("A", 0)])],
        )
        result = DbcComparator(True).compare_databases("bus", old, new)
        self.assertEqual(
            {(c.old_name, c.new_name) for c in result.message_changes},
            {("A", "A"), ("B", "B")},
        )
        self.assertTrue(
            all(c.change_type == "Modified" for c in result.message_changes)
        )

    def test_unique_complete_match_only_gets_one_without_competitors(self):
        a, b = signal("A"), signal("B")
        x, y = (
            identity("OLD", "bus", a, message()),
            identity("NEW", "bus", b, message()),
        )
        pairs, _ = match_entities(
            [x], [y], lambda a, b: Evidence(0.1, (), True), RECALL_V1
        )
        self.assertEqual(pairs[0].confidence, 1.0)
        z = identity("NEW", "bus", signal("C"), message())
        pairs, _ = match_entities(
            [x], [y, z], lambda a, b: Evidence(0.99, (), True), RECALL_V1
        )
        self.assertLess(pairs[0].confidence, 0.9)

    def test_file_and_can_id_rename_use_signal_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_dbc(root / "old" / "alpha.dbc", name="aaa", frame=100)
            write_dbc(root / "new" / "zeta.dbc", name="zzz", frame=200)
            result = DbcComparator().compare_folders(root / "old", root / "new")
            self.assertEqual([p.status for p in result.file_pairs], ["DBC Renamed"])
            self.assertEqual(
                [c.change_type for c in result.message_changes], ["Renamed"]
            )
            parent = result.file_pairs[0].pairing
            self.assertTrue(parent.requires_review)
            self.assertLessEqual(
                result.message_changes[0].confidence, parent.confidence
            )
            self.assertTrue(result.message_changes[0].pairing.requires_review)
            self.assertEqual(sum(result.coverage["OLD signal"].values()), 1)
            # The unchanged child has no detail row but still needs a review row.
            self.assertEqual(result.signal_changes, [])
            out = write_excel_report(result, root / "review.xlsx")
            wb = load_workbook(out)
            try:
                self.assertTrue(
                    any(
                        row[2] == "signal" and row[12] == "Yes"
                        for row in list(wb["Pairing Review"].values)[1:]
                    )
                )
            finally:
                wb.close()

    def test_permutation_and_unrelated_component_preserve_pair_mapping_and_scores(self):
        old = database("bus", [message("A", 1, [signal("aa"), signal("bb", 32)])])
        new = database(
            "bus", [message("A", 1, [signal("aa_new"), signal("bb_new", 32)])]
        )
        first = DbcComparator(True).compare_databases("bus", old, new)
        new.messages["A"].signals = dict(
            reversed(list(new.messages["A"].signals.items()))
        )
        second = DbcComparator(True).compare_databases("bus", old, new)

        def signature(r):
            return [
                (p.old, p.new, p.similarity, p.confidence, p.pair_id)
                for p in r.pairings
            ]

        self.assertEqual(signature(first), signature(second))
        x, y = identity("OLD", "a"), identity("NEW", "a")
        a = database_profile("a", old)
        b = database_profile("a", new)

        def ev(i, j):
            return database_evidence(a, b, RECALL_V1) if (i, j) == (x, y) else None

        p, _ = match_entities([x], [y], ev, RECALL_V1)
        q, _ = match_entities(
            [x, identity("OLD", "z")], [y, identity("NEW", "z")], ev, RECALL_V1
        )
        self.assertEqual(
            (p[0].similarity, p[0].confidence), (q[0].similarity, q[0].confidence)
        )


class InputAndReportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.old, self.new = self.root / "old", self.root / "new"
        self.old.mkdir()
        self.new.mkdir()

    def test_reject_duplicate_signal_and_frame_keys_in_parser_and_api(self):
        for duplicate in ("signal", "frame", "message"):
            path = write_dbc(self.old / "bad.dbc")
            text = path.read_text()
            if duplicate == "signal":
                text += ' SG_ Speed : 8|8@1+ (1,0) [0|255] "" ECU\n'
            else:
                text += f"BO_ {100 if duplicate == 'frame' else 200} {'Other' if duplicate == 'frame' else 'Status'}: 8 ECU\n"
            path.write_text(text)
            with self.subTest(duplicate=duplicate), self.assertRaises(DbcParseError):
                parse_dbc(path)
        for db in (
            DbcDatabase(Path("api"), {"A": message("A"), "B": message("B")}),
            DbcDatabase(Path("api"), {"alias": message()}),
            database("api", [message(signals=[signal()])]),
        ):
            if "Status" in db.messages:
                db.messages["Status"].signals["alias"] = signal()
            with self.assertRaises(DbcParseError):
                DbcComparator().compare_databases("api", db, database("new", []))

    def test_fixed_bad_counterpart_is_not_compared_unknown_counts_and_no_changes(self):
        (self.old / "bus.dbc").write_text("not a dbc")
        write_dbc(self.new / "bus.dbc")
        result = DbcComparator().compare_manual(
            self.old, self.new, {"bus.dbc": "bus.dbc"}
        )
        self.assertEqual(result.completeness, "Incomplete")
        self.assertEqual(result.diagnostics[0].side, "OLD")
        self.assertEqual(result.summary()["Total Changes"], 0)
        self.assertEqual(result.coverage["NEW signal"], {"not compared": 1})
        self.assertIsNone(result.coverage["OLD signal"]["unknown"])
        self.assertIsNone(result.file_pairs[0].message_count_old)
        self.assertEqual(result.file_pairs[0].message_count_new, 1)
        filtered = filter_result(result, {"Renamed"})
        self.assertEqual(filtered.diagnostics, result.diagnostics)
        self.assertEqual(filtered.coverage, result.coverage)
        out = write_excel_report(filtered, self.root / "report.xlsx")
        wb = load_workbook(out)
        self.addCleanup(wb.close)
        overview = list(wb["DBC Overview"].values)
        self.assertEqual(overview[1][3], "Unknown->1")
        status = next(row for row in wb["Summary"] if row[0].value == "Completeness")
        self.assertEqual(status[1].value, "Incomplete")
        self.assertEqual(status[1].fill.fgColor.rgb, "00FFC7CE")

    def test_direct_file_failure_never_exports_and_folder_cli_returns_three(self):
        bad, good = self.old / "bus.dbc", write_dbc(self.new / "bus.dbc")
        bad.write_text("invalid")
        out = self.root / "report.xlsx"
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                main(["--old", str(bad), "--new", str(good), "--out", str(out)]), 1
            )
            self.assertFalse(out.exists())
            self.assertEqual(
                main(
                    ["--old", str(self.old), "--new", str(self.new), "--out", str(out)]
                ),
                3,
            )
        self.assertTrue(out.exists())

    def test_unreadable_side_defers_only_unknown_ecu_node_validation(self):
        (self.old / "bus.dbc").write_text("invalid", encoding="utf-8")
        write_dbc(self.new / "bus.dbc")
        result = DbcComparator(ecu_map={"UNKNOWN_OLD": "ECU"}).compare_manual(
            self.old, self.new, {"bus.dbc": "bus.dbc"}
        )
        self.assertEqual(result.completeness, "Incomplete")
        with self.assertRaises(ValueError):
            DbcComparator(ecu_map={"UNKNOWN_OLD": "MISSING_NEW"}).compare_folders(
                self.old, self.new
            )
        for mapping in ({"bus.dbc": ""}, {None: "bus.dbc"}, {"bus.dbc": 1}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                DbcComparator().compare_manual(self.old, self.new, mapping)

    def test_export_error_keeps_existing_report_and_cli_uses_failure_code(self):
        a, b = write_dbc(self.old / "bus.dbc"), write_dbc(self.new / "bus.dbc")
        result = DbcComparator().compare_files(a, b)
        output = self.root / "existing.xlsx"
        output.write_bytes(b"existing report")
        with patch(
            "dbc_compare_tool.report.excel.Workbook.save",
            side_effect=OSError("write failed"),
        ):
            with self.assertRaises(OSError):
                write_excel_report(result, output)
        self.assertEqual(output.read_bytes(), b"existing report")
        self.assertEqual(list(self.root.glob("*.xlsx")), [output])
        with patch(
            "dbc_compare_tool.cli.write_excel_report",
            side_effect=ReportExportError("limit"),
        ):
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    main(["--old", str(a), "--new", str(b), "--out", str(output)]), 1
                )

    def test_move_suggestions_leave_main_changes_unchanged_and_respect_manual_exclusion(
        self,
    ):
        # Force different parents; moved messages/signals remain Added/Removed.
        a = write_dbc(self.old / "a.dbc", name="Moved", frame=1, sig="Target")
        b = write_dbc(
            self.old / "b.dbc", name="Anchor", frame=2, sig="Other", start=32, length=3
        )
        c = write_dbc(
            self.new / "a.dbc", name="Anchor", frame=2, sig="Other", start=32, length=3
        )
        d = write_dbc(self.new / "b.dbc", name="Moved", frame=1, sig="Target")
        # Empty counterpart parent is intentional to expose unmatched entities.
        c.write_text('VERSION ""\nBU_: ECU\n')
        b.write_text('VERSION ""\nBU_: ECU\n')
        result = DbcComparator().compare_manual(
            self.old, self.new, {"a.dbc": "a.dbc", "b.dbc": "b.dbc"}
        )
        self.assertEqual(
            {c.change_type for c in result.message_changes}, {"Added", "Removed"}
        )
        self.assertTrue(any(p.old.kind == "message" for p in result.move_suggestions))
        self.assertTrue(any(p.old.kind == "signal" for p in result.move_suggestions))
        before = result.summary()
        self.assertEqual(
            filter_result(result, {"Renamed"}).move_suggestions, result.move_suggestions
        )
        self.assertEqual(result.summary(), before)
        excluded = DbcComparator().compare_manual(
            self.old, self.new, {"a.dbc": None, "b.dbc": "a.dbc"}
        )
        self.assertFalse(excluded.move_suggestions)
        self.assertTrue(a.exists() and d.exists())

    def test_review_exports_every_candidate_and_pair_ids_survive_filtering(self):
        old = database("old", [message(signals=[signal("A"), signal("B")])])
        new = database("new", [message(signals=[signal("X"), signal("Y")])])
        result = DbcComparator().compare_databases("bus", old, new)
        self.assertEqual(
            len([p for p in result.pairing_candidates if p.old.kind == "signal"]), 4
        )
        filtered = filter_result(result, {"Added"})
        self.assertEqual(filtered.review_count, result.review_count)
        out = write_excel_report(filtered, self.root / "review.xlsx")
        wb = load_workbook(out)
        self.addCleanup(wb.close)
        rows = list(wb["Pairing Review"].values)
        self.assertEqual(len([r for r in rows[1:] if r[2] == "signal"]), 4)
        self.assertTrue(all(r[3].startswith('["OLD",') for r in rows[1:]))
        ids = [
            p.pair_id
            for p in result.pairings
            + [p for p in result.pairing_candidates if not p.selected]
        ]
        self.assertEqual(len(ids), len(set(ids)))
        with (
            patch("dbc_compare_tool.report.excel.EXCEL_MAX_ROWS", 3),
            self.assertRaises(ReportExportError),
        ):
            write_excel_report(result, self.root / "limited.xlsx")
        self.assertFalse((self.root / "limited.xlsx").exists())
        with (
            patch("dbc_compare_tool.report.excel.EXCEL_MAX_CELL_LENGTH", 10),
            self.assertRaises(ReportExportError),
        ):
            write_excel_report(result, self.root / "limited.xlsx")

    def test_same_basename_in_different_folders_has_distinct_identities(self):
        for prefix, frame in (("one", 1), ("two", 2)):
            write_dbc(self.old / prefix / "bus.dbc", frame=frame)
            write_dbc(self.new / prefix / "bus.dbc", frame=frame)
        result = DbcComparator(True).compare_folders(self.old, self.new)
        self.assertEqual(len(result.inventory), 12)
        self.assertEqual(len({p.pair_id for p in result.pairings}), 6)
        self.assertEqual(result.coverage["OLD signal"], {"paired": 2})

    def test_discovery_and_message_order_and_unrelated_component_do_not_change_scores(
        self,
    ):
        from dbc_compare_tool.core.discovery import collect_dbc_files

        for parent, frame in (("alpha", 1), ("beta", 2)):
            write_dbc(
                self.old / parent / "bus.dbc",
                frame=frame,
                name=f"Msg{frame}",
                sig=f"S{frame}",
            )
            write_dbc(
                self.new / parent / "bus.dbc",
                frame=frame,
                name=f"Msg{frame}",
                sig=f"S{frame}",
            )
        first = DbcComparator(True).compare_folders(self.old, self.new)

        def reverse(folder):
            return dict(reversed(list(collect_dbc_files(folder).items())))

        with patch(
            "dbc_compare_tool.core.comparator.collect_dbc_files", side_effect=reverse
        ):
            second = DbcComparator(True).compare_folders(self.old, self.new)

        def selected(result):
            return [(p.old, p.new, p.similarity, p.confidence) for p in result.pairings]

        self.assertEqual(selected(first), selected(second))
        self.assertEqual(
            [p.pair_id for p in first.pairings], [p.pair_id for p in second.pairings]
        )
        for side in (self.old, self.new):
            path = write_dbc(
                side / "unrelated.dbc",
                frame=900,
                name="ZZZZ",
                sig="Other",
                start=60,
                length=3,
            )
            path.write_text(
                path.read_text()
                .replace('"km/h"', '"different"')
                .replace("(1,0)", "(7,9)")
            )
        third = DbcComparator(True).compare_folders(self.old, self.new)
        retained = [
            p
            for p in third.pairings
            if "unrelated.dbc"
            not in {p.old.dbc_path if p.old else "", p.new.dbc_path if p.new else ""}
        ]
        self.assertEqual(
            selected(first),
            [(p.old, p.new, p.similarity, p.confidence) for p in retained],
        )
        old = database(
            "old", [message("A", 1, [signal("A")]), message("B", 2, [signal("B", 32)])]
        )
        new = database("new", list(reversed(list(old.messages.values()))))
        a = DbcComparator(True).compare_databases("bus", old, new)
        old.messages = dict(reversed(list(old.messages.items())))
        b = DbcComparator(True).compare_databases("bus", old, new)
        self.assertEqual(selected(a), selected(b))
