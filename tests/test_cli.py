"""CLI path and automatic output behavior."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from dbc_compare_tool.cli import main


_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _ROOT / "examples"


class TestCliPaths(unittest.TestCase):
    def test_unquoted_folder_parts_and_default_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_folder = root / "old baseline"
            new_folder = root / "new baseline"
            shutil.copytree(_EXAMPLES / "old", old_folder)
            shutil.copytree(_EXAMPLES / "new", new_folder)

            exit_code = main(
                [
                    "--old",
                    *str(old_folder).split(" "),
                    "--new",
                    *str(new_folder).split(" "),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "compared_new baseline.xlsx").is_file())


if __name__ == "__main__":
    unittest.main()
