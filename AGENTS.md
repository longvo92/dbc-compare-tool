# DBC Compare Tool

## Constraints
- Python >=3.9 (pyproject.toml). Keep syntax and runtime compatible; use postponed annotations where needed.
- Engine/report must run without Qt. Import PySide6 only in ui/.
- Packages live in src/dbc_compare_tool/. Existing dependencies: cantools, openpyxl and optional PySide6; choose additions autonomously and explain them.
- Keep shared CLI/GUI comparison and report behavior consistent.

## Verification
Set PYTHONPATH=src in the shell.
For code changes: python -m unittest discover -s tests -v
Lint: python -m ruff check .
Engine smoke: python -m dbc_compare_tool.cli --old examples/old --new examples/new --out <temporary-report.xlsx>
Packaging: python scripts/build.py
Windows launchers: run_gui.bat and run_cli.bat.
Verify affected GUI behavior; use the existing release preflight for an authorized release.
## Delivery
Follow global Git autonomy: commit scoped changes, push the task branch and create/update a PR without another approval after relevant checks. Use a draft when verification is incomplete. Merge, release and deploy require a request. Preserve unrelated work and private data.
