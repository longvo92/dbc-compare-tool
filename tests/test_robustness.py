"""Regression tests for robustness fixes: frame-key collisions, parse-error
resilience, case-insensitive discovery, and encoding fallback."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.core.discovery import discover_dbc_pairs
from dbc_compare_tool.core.models import DbcDatabase, Message, Signal
from dbc_compare_tool.core.parser import DbcParseError, parse_dbc

_GOOD_DBC = """VERSION ""

BO_ 100 Node_Status: 8 ECU
 SG_ Counter : 0|8@1+ (1,0) [0|255] "" ECM
"""

_NODE_ORDER_DBC = '''VERSION ""
NS_ :
BS_:
BU_: ECU A B
BO_ 100 Status: 8 ECU
 SG_ Value : 0|8@1+ (1,0) [0|255] "" {receivers}
BO_TX_BU_ 100 : {senders};
'''


def _make_signal(name: str = "Counter") -> Signal:
    return Signal(
        name=name,
        start_bit=0,
        length=8,
        byte_order=1,
        value_type="unsigned",
        is_signed=False,
        factor=1.0,
        offset=0.0,
        minimum=None,
        maximum=None,
        unit="",
        receivers=(),
    )


def _make_db(*messages: Message) -> DbcDatabase:
    db = DbcDatabase(path=Path("test.dbc"))
    for message in messages:
        db.messages[message.name] = message
    return db


class TestExtendedStandardFrameCollision(unittest.TestCase):
    """A standard frame and an extended frame with the same numeric ID are
    distinct CAN frames and must not shadow each other during comparison."""

    def test_modified_standard_frame_not_hidden_by_extended_twin(self):
        std_old = Message(name="MsgStd", can_id=0x100, dlc=8, transmitter="ECU", is_extended_frame=False)
        ext_old = Message(name="MsgExt", can_id=0x100, dlc=8, transmitter="ECU", is_extended_frame=True)
        std_new = Message(name="MsgStd", can_id=0x100, dlc=4, transmitter="ECU", is_extended_frame=False)
        ext_new = Message(name="MsgExt", can_id=0x100, dlc=8, transmitter="ECU", is_extended_frame=True)

        result = DbcComparator().compare_databases(
            "test.dbc", _make_db(std_old, ext_old), _make_db(std_new, ext_new)
        )

        modified = [c for c in result.message_changes if c.change_type == "Modified"]
        self.assertEqual(len(modified), 1)
        self.assertEqual(modified[0].old_name, "MsgStd")
        added = [c for c in result.message_changes if c.change_type in ("Added", "Removed")]
        self.assertEqual(added, [])


class TestParseErrorResilience(unittest.TestCase):
    """One unparsable DBC must not abort the whole folder comparison."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.old_folder = root / "old"
        self.new_folder = root / "new"
        self.old_folder.mkdir()
        self.new_folder.mkdir()

        (self.old_folder / "good.dbc").write_text(_GOOD_DBC, encoding="utf-8")
        (self.new_folder / "good.dbc").write_text(_GOOD_DBC, encoding="utf-8")
        (self.old_folder / "bad.dbc").write_text("this is not a dbc file {{{", encoding="utf-8")
        (self.new_folder / "bad.dbc").write_text("also not a dbc file }}}", encoding="utf-8")

    def test_bad_file_reported_and_good_file_still_compared(self):
        result = DbcComparator().compare_folders(self.old_folder, self.new_folder)
        statuses = {fp.dbc_file: fp.status for fp in result.file_pairs}
        self.assertEqual(statuses.get("good.dbc"), "Matched")
        self.assertEqual(statuses.get("bad.dbc"), "Parse Error")

    def test_progress_callback_reports_parse_error(self):
        logs: list[str] = []
        DbcComparator().compare_folders(self.old_folder, self.new_folder, progress_callback=logs.append)
        self.assertTrue(any("Parse error" in msg and "bad.dbc" in msg for msg in logs))


class TestDiscoveryCaseInsensitive(unittest.TestCase):
    def test_uppercase_extension_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "old"
            new = root / "new"
            old.mkdir()
            new.mkdir()
            (old / "BUS.DBC").write_text(_GOOD_DBC, encoding="utf-8")
            (new / "BUS.DBC").write_text(_GOOD_DBC, encoding="utf-8")
            pairs = discover_dbc_pairs(old, new)
            self.assertEqual(len(pairs), 1)
            self.assertIsNotNone(pairs[0].old_path)
            self.assertIsNotNone(pairs[0].new_path)


class TestEncodingFallback(unittest.TestCase):
    def test_cp1252_file_parses(self):
        dbc_text = _GOOD_DBC + 'CM_ BO_ 100 "Temperature in \xb0C";\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.dbc"
            path.write_bytes(dbc_text.encode("cp1252"))  # 0xB0 is invalid UTF-8 here
            db = parse_dbc(path)
            self.assertIn("Node_Status", db.messages)
            self.assertIn("\xb0C", db.messages["Node_Status"].comment)

    def test_utf8_bom_file_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bom.dbc"
            path.write_bytes(b"\xef\xbb\xbf" + _GOOD_DBC.encode("utf-8"))
            db = parse_dbc(path)
            self.assertIn("Node_Status", db.messages)

    def test_garbage_raises_dbc_parse_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "garbage.dbc"
            path.write_text("not a dbc {{{", encoding="utf-8")
            with self.assertRaises(DbcParseError):
                parse_dbc(path)


class TestNodeOrderNormalization(unittest.TestCase):
    def test_reordered_nodes_do_not_create_property_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_folder = root / "old"
            new_folder = root / "new"
            old_folder.mkdir()
            new_folder.mkdir()
            (old_folder / "network.dbc").write_text(
                _NODE_ORDER_DBC.format(receivers="A,B", senders="A,B"),
                encoding="utf-8",
            )
            (new_folder / "network.dbc").write_text(
                _NODE_ORDER_DBC.format(receivers="B,A", senders="B,A"),
                encoding="utf-8",
            )

            result = DbcComparator().compare_folders(old_folder, new_folder)

            self.assertEqual(result.summary()["Total Changes"], 0)


if __name__ == "__main__":
    unittest.main()
