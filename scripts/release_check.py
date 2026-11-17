"""Check that the repository is ready to be released as a given version.

    python scripts/release_check.py 0.2.0
    python scripts/release_check.py 0.2.0 --notes RELEASE_NOTES.md

Run it before triggering the release workflow; the workflow runs the same
script, so a failure there is never a surprise. It only reads — bumping the
version and writing the release notes stays a reviewed pull request.

Verified:
  * the version is a plain X.Y.Z
  * src/dbc_compare_tool/__init__.py and pyproject.toml agree with it
  * CHANGELOG.md documents it as the newest released version, with a non-empty
    body, and nothing is left sitting under [Unreleased]

With --notes, that section is written out for `gh release create --notes-file`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_FILE = REPO_ROOT / "src" / "dbc_compare_tool" / "__init__.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_INIT_VERSION = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
_PYPROJECT_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
# "## [0.2.0] - 2026-08-02" and "## [Unreleased]"; the date separator may be a
# hyphen or an em dash, and the date itself is optional.
_CHANGELOG_HEADING = re.compile(r"^## \[([^\]]+)\](?:\s*[-—]\s*(\S+))?\s*$", re.MULTILINE)
UNRELEASED = "Unreleased"


class ReleaseCheckError(Exception):
    pass


def read_init_version(text: str) -> str:
    match = _INIT_VERSION.search(text)
    if not match:
        raise ReleaseCheckError("__version__ not found in src/dbc_compare_tool/__init__.py")
    return match.group(1)


def read_pyproject_version(text: str) -> str:
    match = _PYPROJECT_VERSION.search(text)
    if not match:
        raise ReleaseCheckError("version not found in pyproject.toml")
    return match.group(1)


def _section_body(text: str, headings: list[re.Match], index: int) -> str:
    start = headings[index].end()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
    # Sections are separated by a --- rule that belongs to neither of them.
    return text[start:end].strip().strip("-").strip()


def extract_release_notes(text: str, version: str) -> str:
    """The body of the "## [<version>]" section, which must be the newest release.

    An [Unreleased] section is allowed above it but has to be empty: anything
    still sitting there is a change that would ship without being announced.
    """
    headings = list(_CHANGELOG_HEADING.finditer(text))
    if not headings:
        raise ReleaseCheckError("no '## [X.Y.Z]' section found in CHANGELOG.md")

    index = 0
    if headings[0].group(1) == UNRELEASED:
        if _section_body(text, headings, 0):
            raise ReleaseCheckError(
                "CHANGELOG.md still has entries under [Unreleased] — move them under "
                f"'## [{version}]' before releasing"
            )
        index = 1

    if index >= len(headings):
        raise ReleaseCheckError("CHANGELOG.md has no released version section")

    newest = headings[index].group(1)
    if newest != version:
        raise ReleaseCheckError(
            f"the newest CHANGELOG.md section is {newest}, not {version} — "
            "releases are cut from the top of the file"
        )
    if not headings[index].group(2):
        raise ReleaseCheckError(f"the CHANGELOG.md section for {version} has no date")

    body = _section_body(text, headings, index)
    if not body:
        raise ReleaseCheckError(f"the CHANGELOG.md section for {version} is empty")
    return body


def check(version: str) -> str:
    if not VERSION_PATTERN.match(version):
        raise ReleaseCheckError(f"'{version}' is not a plain X.Y.Z version")

    init_version = read_init_version(INIT_FILE.read_text(encoding="utf-8"))
    if init_version != version:
        raise ReleaseCheckError(
            f"__init__.py says {init_version}, the release asks for {version}"
        )

    pyproject_version = read_pyproject_version(PYPROJECT.read_text(encoding="utf-8"))
    if pyproject_version != version:
        raise ReleaseCheckError(
            f"pyproject.toml says {pyproject_version}, the release asks for {version}"
        )

    return extract_release_notes(CHANGELOG.read_text(encoding="utf-8"), version)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the repository is ready to release.")
    parser.add_argument("version", help="Version to release, e.g. 0.2.0")
    parser.add_argument("--notes", type=Path, help="Write the release-notes section here")
    args = parser.parse_args()

    try:
        notes = check(args.version)
    except ReleaseCheckError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: unable to read a project file: {exc}", file=sys.stderr)
        return 1

    if args.notes:
        args.notes.write_text(f"{notes}\n", encoding="utf-8")
        print(f"Release notes written: {args.notes}")

    print(f"Ready to release {args.version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
