# Architecture

The CLI and PySide6 GUI share a comparison engine and Excel writer. `core/` and `report/` run without Qt. Python 3.9+ is required.

## Components

Paths below are relative to `src/dbc_compare_tool/`.

| Module | Responsibility |
|---|---|
| `core/models.py` | Databases, messages, signals and comparison results |
| `core/parser.py` | Read DBCs with cantools; extract layout, routing, multiplexing, values and comments |
| `core/discovery.py`, `core/pairing.py` | Find files and select one-to-one DBC pairs |
| `core/ecu.py` | Discover ECU nodes and validate identity mappings |
| `core/comparator.py` | Compare file pairs and filter results |
| `core/rename.py` | Detect message and signal renames |
| `report/excel.py`, `report/_style.py` | Write and format the Excel workbook |
| `ui/main_window.py`, `ui/widgets.py` | GUI, pairing dialogs, workers and path settings |
| `cli.py` | Command-line arguments, comparison and export |

## Data Flow

1. Validate two folders or two `.dbc` files and any ECU mapping.
2. Parse the selected files, or discover and pair files from both folders.
3. Match messages, compare their signals and collect property changes.
4. Apply report filters and write the workbook.

Added or removed DBCs are compared against an empty database so their messages and signals appear in the detail sheets. Folder parse errors are recorded per file; other files continue. Direct file parse errors stop the run. ECU discovery skips unreadable files in folder mode.

## Comparison Contracts

- `compare_paths` accepts matching input types. `compare_files` treats the two selected files as one explicit pair.
- `compare_manual` accepts a DBC pairing map. The GUI uses saved manual pairs only when every OLD file is paired; otherwise it uses automatic pairing.
- A message's frame key is `(can_id, is_extended_frame)`, keeping standard and extended frames distinct.
- Signals are matched within their paired parent messages.
- ECU mappings are one-to-one, reference existing nodes and cannot collide with unmapped OLD names. Original names remain in report data.
- `include_unchanged=True` retains unchanged entries and bypasses change-type filters. `Total Changes` excludes unchanged entries.
- `filter_result` preserves file pairs and ECU mappings.

## Matching Rules

| Item | Matching order | Fallback threshold |
|---|---|---|
| DBC files | Equal relative path, then global keyword/content assignment | 0.55 |
| Messages | Equal frame key, then structural similarity | 0.60 |
| Signals | Exact name, unique complete-property match, then similarity | 0.82; 0.65 for event-like messages |

A renamed message with the same frame key has confidence 1.0. A unique complete-property signal match also has confidence 1.0, after applying ECU mappings to receivers. Duplicate signatures use fallback scoring.

Remaining message and signal candidates use greedy one-to-one matching with ambiguity penalties. Confidence levels are **High** ≥ 0.90, **Medium** ≥ 0.70 and **Low** below 0.70. Event-like fallback signal matches cannot reach High.

DBC pairing can match files through shared keywords even when their contents differ. Pairing reasons are recorded in DBC Overview.

Scoring constants and formulas are defined in [pairing.py](../src/dbc_compare_tool/core/pairing.py) and [rename.py](../src/dbc_compare_tool/core/rename.py).

## Report

The workbook contains `Summary`, `DBC Overview`, `Message Details`, `Signal Details` and `Changed Properties`.

Detail sheets contain identity, CAN IDs, ECU Tx/Rx and match confidence/reasons. Property deltas appear in Changed Properties. Summary records report mode, ECU mappings and skipped parse errors. DBC Overview retains file paths; detail display labels use basenames.

## GUI and Entry Points

Comparison, ECU discovery and export use workers. Input changes invalidate saved DBC and ECU pairing. Input type and paths are stored through `QSettings("DbcCompareTool", "DBCCompareTool")`.

| Entry point | Target |
|---|---|
| `dbc-compare-tool-gui`, `python -m dbc_compare_tool` | `ui.main_window:main` |
| `dbc-compare-tool`, `python -m dbc_compare_tool.cli` | `cli:main` |

CLI exit codes: `0` completed, `1` parse/write failure, `2` invalid input or mapping. A folder comparison can complete with skipped parse errors.

## Verification

After [source installation](../README.md#install-from-source), run from the repository folder:

```powershell
.\.venv\Scripts\python.exe -m pip install ruff pyinstaller
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m dbc_compare_tool.cli --old examples/old --new examples/new --out "$env:TEMP\dbc-smoke.xlsx"
```

Tests cover parsing, comparison, pairing, renames, reports, GUI and release checks. GUI tests skip without Qt. CI runs engine tests on Linux/Windows with Python 3.9, 3.10 and 3.12, plus a Windows/Python 3.12 GUI job.

## Build and Release

```powershell
.\.venv\Scripts\python.exe scripts/build.py
```

| Output | Resources |
|---|---|
| `dist/DbcCompareTool-<version>.exe` | Bundled; no Python installation needed |
| `dist/DbcCompareTool-<version>.pyzw` | Ship with `dist/resources/`; requires Python and runtime dependencies |

The build copies CHANGELOG.md into resources for the Help menu. Windows packaging restricts DLL search paths to Python and Windows system directories; Qt hooks add package DLLs. Verify the main window opens when checking a build.

`scripts/release_check.py` requires matching versions in `pyproject.toml` and `__init__.py`, a dated changelog section and an empty `[Unreleased]`. It can extract release notes with `--notes`.

`.github/workflows/release.yml` runs manually from `main`, builds and starts both artifacts, then uploads them. Publishing requires `publish=true`.

## Constraints

- Custom `BA_` attributes other than `GenMsgCycleTime` are not compared.
- Rename detection is heuristic; unmatched items are reported as Removed or Added.
- Manual pairing applies to DBC files and ECU nodes. Message/signal pairing remains automatic.
- Duplicate basenames can share a detail-sheet display label; use DBC Overview to identify paths.
