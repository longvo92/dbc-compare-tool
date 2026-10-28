from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_pairing import CORPUS, evaluate_case


class CorpusTests(unittest.TestCase):
    def test_supported_renames_recover_gold_and_ambiguity_is_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for spec in json.loads(CORPUS.read_text(encoding="utf-8")):
                with self.subTest(case=spec["name"]):
                    measured = evaluate_case(Path(tmp) / spec["name"], spec)
                    self.assertTrue(measured["passed"], measured)
