"""Synthetic shifted-signal pairing through the engine, CLI and Excel report."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from dbc_compare_tool.cli import main
from dbc_compare_tool.core.comparator import DbcComparator


def shifted_dbc(event_like: bool) -> tuple[str, str, dict[str, str]]:
    header = 'VERSION ""\nBU_: ECU Receiver\nBO_ 100 Status: 8 ECU\n'
    old, new, pairs = header, header.replace("Status:", "StatusNew:"), {}
    for index in range(8 if event_like else 3):
        name = f"Event_Door_{index}" if event_like else f"BatteryValue_{index}"
        start, length = (index, 1) if event_like else (index * 16, 8)
        unit = "" if event_like else f"Unit{index}"
        for is_new in (False, True):
            signal_name = name + "_New" if is_new else name
            line = (f' SG_ {signal_name} : {start + is_new}|{length}@1+ '
                    f'(1,0) [0|{2 ** length - 1}] "{unit}" Receiver\n')
            if is_new:
                new += line
            else:
                old += line
        pairs[name] = name + "_New"
    alive = ' SG_ Alive : 56|8@1+ (1,0) [0|255] "" Receiver\n'
    return old + alive, new + alive, pairs


class TestShiftedSignalPairing(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old_folder, self.new_folder = self.root / "old", self.root / "new"
        self.old_folder.mkdir()
        self.new_folder.mkdir()
        self.old, self.new = self.old_folder / "bus.dbc", self.new_folder / "bus.dbc"

    def _inputs(self, event_like):
        old, new, pairs = shifted_dbc(event_like)
        self.old.write_text(old, encoding="utf-8")
        self.new.write_text(new, encoding="utf-8")
        return pairs

    def test_shifted_renames_preserve_deltas_in_files_folders_and_manual_pairing(self):
        for event_like in (False, True):
            pairs = self._inputs(event_like)
            for include_unchanged in (False, True):
                comparator = DbcComparator(include_unchanged=include_unchanged)
                for mode, result in (
                    ("files", comparator.compare_files(self.old, self.new)),
                    ("folders", comparator.compare_folders(self.old_folder, self.new_folder)),
                    ("manual", comparator.compare_manual(self.old_folder, self.new_folder, {"bus.dbc": "bus.dbc"})),
                ):
                    with self.subTest(event_like=event_like, full=include_unchanged, mode=mode):
                        renames = [change for change in result.signal_changes if change.change_type == "Renamed"]
                        self.assertEqual({change.old_name: change.new_name for change in renames}, pairs)
                        self.assertFalse(any(change.change_type in {"Added", "Removed"} for change in result.signal_changes))
                        for change in renames:
                            self.assertEqual(change.confidence_level, "Low" if event_like else "Medium")
                            self.assertEqual(change.property_diffs, (("Start Bit", str(change.old_signal.start_bit),
                                                                     str(change.new_signal.start_bit)),))
                            self.assertEqual(change.old_message.name, "Status")
                            self.assertEqual(change.new_message.name, "StatusNew")
                        self.assertEqual(sum(change.change_type == "Unchanged" for change in result.signal_changes),
                                         int(include_unchanged))

    def test_cli_exports_review_confidence_and_start_bit_changes(self):
        for event_like in (False, True):
            with self.subTest(event_like=event_like):
                pairs = self._inputs(event_like)
                report = self.root / "report.xlsx"
                with contextlib.redirect_stdout(io.StringIO()):
                    status = main(["--old", str(self.old), "--new", str(self.new), "--out", str(report)])
                self.assertEqual(status, 0)
                workbook = load_workbook(report)
                try:
                    values = list(workbook["Signal Details"].values)
                    rows = [dict(zip(values[0], row)) for row in values[1:]]
                    self.assertEqual({row["Old Signal Name"]: row["New Signal Name"] for row in rows}, pairs)
                    self.assertTrue(all(row["Change Type"] == "Renamed" for row in rows))
                    self.assertTrue(all(row["Confidence Level"] == ("Low" if event_like else "Medium") for row in rows))
                    self.assertTrue(all(0.0 <= float(row["Confidence Score"]) < 0.90 for row in rows))
                    self.assertTrue(all("review recommended" in row["Match Reason"] for row in rows))
                    deltas = list(workbook["Changed Properties"].values)[1:]
                    self.assertEqual(len(deltas), len(pairs))
                    self.assertTrue(all(row[6] == "Start Bit" and int(row[8]) - int(row[7]) == 1 for row in deltas))
                finally:
                    workbook.close()
