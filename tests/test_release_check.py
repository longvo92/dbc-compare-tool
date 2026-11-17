"""Tests for the release gate.

scripts/release_check.py is what stands between a typo and a tag that cannot be
taken back, so its parsing is tested like engine code. The last test runs it
against the real project files, which is what keeps the gate honest as those
files change.
"""

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "release_check.py"

_spec = importlib.util.spec_from_file_location("release_check", _SCRIPT)
release_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_check)


_NOTES = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-08-02

### Added

- Hexadecimal CAN IDs.

---

## [0.1.8] - 2026-07-16

### Added

- Manual DBC pairing.
"""


class VersionSourceTests(unittest.TestCase):
    def test_reads_the_version_from_init(self):
        text = '"""Doc."""\n\n__version__ = "1.2.3"\n'
        self.assertEqual(release_check.read_init_version(text), "1.2.3")

    def test_missing_init_version_is_an_error(self):
        with self.assertRaises(release_check.ReleaseCheckError):
            release_check.read_init_version("__ver__ = 'nope'")

    def test_reads_the_version_from_pyproject(self):
        text = '[project]\nname = "dbc-compare-tool"\nversion = "1.2.3"\n'
        self.assertEqual(release_check.read_pyproject_version(text), "1.2.3")

    def test_rejects_a_version_that_is_not_x_y_z(self):
        for bad in ("0.2", "v0.2.0", "0.2.0-rc1", "latest"):
            with self.subTest(version=bad):
                self.assertIsNone(release_check.VERSION_PATTERN.match(bad))


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_only_the_newest_section(self):
        notes = release_check.extract_release_notes(_NOTES, "0.2.0")
        self.assertIn("Hexadecimal CAN IDs", notes)
        self.assertNotIn("Manual DBC pairing", notes)
        self.assertNotIn("Unreleased", notes)
        self.assertFalse(notes.endswith("-"), "the --- separator must not leak into the notes")

    def test_an_older_section_is_refused(self):
        # Releasing 0.1.8 while 0.2.0 sits on top means the bump PR was not merged.
        with self.assertRaises(release_check.ReleaseCheckError):
            release_check.extract_release_notes(_NOTES, "0.1.8")

    def test_entries_left_under_unreleased_are_refused(self):
        pending = _NOTES.replace(
            "## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- Something unannounced.\n"
        )
        with self.assertRaises(release_check.ReleaseCheckError) as caught:
            release_check.extract_release_notes(pending, "0.2.0")
        self.assertIn("Unreleased", str(caught.exception))

    def test_an_empty_section_is_refused(self):
        with self.assertRaises(release_check.ReleaseCheckError):
            release_check.extract_release_notes("# Notes\n\n## [0.3.0] - 2026-01-01\n\n", "0.3.0")

    def test_a_section_without_a_date_is_refused(self):
        with self.assertRaises(release_check.ReleaseCheckError):
            release_check.extract_release_notes("# Notes\n\n## [0.3.0]\n\n- One thing.\n", "0.3.0")

    def test_a_file_without_sections_is_refused(self):
        with self.assertRaises(release_check.ReleaseCheckError):
            release_check.extract_release_notes("# Notes\n\nnothing here\n", "0.3.0")

    def test_the_last_section_runs_to_the_end_of_the_file(self):
        single = "# Notes\n\n## [0.3.0] - 2026-01-01\n\n### Added\n\n- One thing.\n"
        self.assertIn("One thing", release_check.extract_release_notes(single, "0.3.0"))

    def test_an_em_dash_date_separator_is_accepted(self):
        single = "# Notes\n\n## [0.3.0] — 2026-01-01\n\n- One thing.\n"
        self.assertIn("One thing", release_check.extract_release_notes(single, "0.3.0"))


class RealRepositoryTests(unittest.TestCase):
    """The gate has to parse this repository's real files correctly.

    Deliberately does *not* assert that `check(self.version)` succeeds: between
    releases, [Unreleased] normally holds pending entries while __init__.py
    still declares the last released version, and `check()` is right to refuse
    that. What must always hold, in every commit, is that the version
    currently declared has a real, non-empty, dated changelog section — that
    is the fact a version bump PR is responsible for keeping true.
    """

    def setUp(self):
        init_text = (_REPO_ROOT / "src" / "dbc_compare_tool" / "__init__.py").read_text(encoding="utf-8")
        self.version = release_check.read_init_version(init_text)
        self.changelog_text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_pyproject_agrees_with_the_package(self):
        pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(release_check.read_pyproject_version(pyproject), self.version)

    def test_the_declared_version_has_a_dated_non_empty_section(self):
        headings = list(release_check._CHANGELOG_HEADING.finditer(self.changelog_text))
        index = 1 if headings and headings[0].group(1) == release_check.UNRELEASED else 0
        self.assertGreater(len(headings), index, "no dated section follows [Unreleased]")
        self.assertEqual(headings[index].group(1), self.version)
        self.assertIsNotNone(headings[index].group(2), "the section has no date")
        body = release_check._section_body(self.changelog_text, headings, index)
        self.assertTrue(body.strip())

    def test_a_version_the_repository_does_not_declare_is_refused(self):
        with self.assertRaises(release_check.ReleaseCheckError):
            release_check.check("99.99.99")

    def test_check_succeeds_once_unreleased_is_emptied(self):
        """What `check()` will see on the commit that actually cuts the release:
        simulate the version-bump PR by dropping everything under [Unreleased]."""
        headings = list(release_check._CHANGELOG_HEADING.finditer(self.changelog_text))
        if not headings or headings[0].group(1) != release_check.UNRELEASED:
            self.skipTest("CHANGELOG.md has no [Unreleased] section to empty")
        next_start = headings[1].start() if len(headings) > 1 else len(self.changelog_text)
        released = self.changelog_text[: headings[0].end()] + "\n" + self.changelog_text[next_start:]

        notes = release_check.extract_release_notes(released, self.version)
        self.assertTrue(notes.strip())


class CommandLineTests(unittest.TestCase):
    """`--notes` is what feeds `gh release create --notes-file`, so the file the
    script writes is part of the release contract, not an implementation detail."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)

        init_file = root / "__init__.py"
        init_file.write_text('__version__ = "0.2.0"\n', encoding="utf-8")
        pyproject = root / "pyproject.toml"
        pyproject.write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")
        changelog = root / "CHANGELOG.md"
        changelog.write_text(_NOTES, encoding="utf-8")

        for name, value in (
            ("INIT_FILE", init_file),
            ("PYPROJECT", pyproject),
            ("CHANGELOG", changelog),
        ):
            original = getattr(release_check, name)
            setattr(release_check, name, value)
            self.addCleanup(setattr, release_check, name, original)

        self.notes_path = root / "RELEASE_NOTES.md"

    def _run(self, *argv: str) -> int:
        original_argv = sys.argv
        sys.argv = ["release_check.py", *argv]
        self.addCleanup(setattr, sys, "argv", original_argv)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return release_check.main()

    def test_notes_file_holds_the_section_for_the_released_version(self):
        self.assertEqual(self._run("0.2.0", "--notes", str(self.notes_path)), 0)
        written = self.notes_path.read_text(encoding="utf-8")
        self.assertIn("Hexadecimal CAN IDs", written)
        self.assertNotIn("Manual DBC pairing", written, "older sections must not leak in")
        self.assertNotIn("Unreleased", written)

    def test_no_notes_file_is_written_without_the_flag(self):
        self.assertEqual(self._run("0.2.0"), 0)
        self.assertFalse(self.notes_path.exists())

    def test_a_mismatched_version_exits_non_zero_and_writes_nothing(self):
        self.assertEqual(self._run("0.3.0", "--notes", str(self.notes_path)), 1)
        self.assertFalse(self.notes_path.exists())


if __name__ == "__main__":
    unittest.main()
