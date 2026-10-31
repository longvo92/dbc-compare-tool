# Architecture

The CLI and optional PySide6 GUI share a Qt-independent comparison engine and Excel writer. Python 3.9+ is supported; `cantools` and `openpyxl` are core dependencies.

## Components and flow

| Module | Responsibility |
|---|---|
| `core/parser.py` | Parse DBCs and reject duplicate message names, signal names and frame keys before dictionary loss |
| `core/discovery.py`, `core/pairing.py` | Discover DBC files and select renamed file pairs |
| `core/rename.py` | Score message and signal renames using the 0.6.7 detectors |
| `core/comparator.py`, `core/models.py` | Compare entities, account for known inventory, record file diagnostics and filter changes |
| `report/excel.py` | Export a formatted workbook atomically |
| `ui/main_window.py`, `cli.py` | Shared engine/report entry points |

The `classic-v067` pipeline matches same-relative-path files first, then considers remaining files for rename pairing. Within each file pair it reserves equal frame keys, then equal message names, then applies the message rename detector. Within each message pair it reserves equal signal names and applies the signal rename detector to the remainder. The original 0.6.7 scores and thresholds are retained: DBC 0.55, message 0.60, signal 0.65 and event-like signal 0.55. A uniquely matching full signal-property set can be reserved before heuristic matching; ambiguity lowers heuristic confidence. Unmatched entities become Added/Removed. Cross-parent moves are not paired.

`compare_paths`, `compare_files`, `compare_folders`, `compare_manual` and `compare_databases` remain the public comparison entry points. Direct file selection pairs the chosen files and aborts on a parse error. Saved manual DBC mappings are fixed constraints, including `None` for Removed and unreferenced NEW files for Added. Valid peers of failed fixed pairs are Not compared. Folder parse failures yield Incomplete reports with side/path/reason and Unknown inventory counts. Known entities are counted as paired, unmatched or not compared. ECU mapping is validated against every readable side; an unreadable side cannot establish whether its node exists.

`DbcComparator(policy=...)`, `PairingMetadata`, competitor lists, move suggestions, Pair IDs, Review Required and the Pairing Review sheet were specific to the 0.7.0 recall-first engine and have been removed. Call `DbcComparator(...)` without `policy`; use detail changes and confidence fields for selected rename results. Both CLI and GUI use this engine. CLI status codes are 0 for complete export, 1 for processing/export failure, 2 for invalid input and 3 for exported Incomplete.

## Report

Direct-file reports contain Summary, Message Details and Signal Details. Folder reports add DBC Overview. Include Unchanged emits unchanged detail rows; normal mode emits only changes. Summary includes completeness, inventory coverage and parse diagnostics. Excel row/text limits fail explicitly. Export writes a sibling temporary workbook and replaces the destination only after a successful save, preserving an existing report on failure. String cells are written literally.

## Verification

```powershell
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -v
ruff check .
python scripts/evaluate_pairing.py --benchmark
python -m dbc_compare_tool.cli --old examples/old --new examples/new --out "$env:TEMP\\dbc-smoke.xlsx"
```

The benchmark prints median parse/compare and export times for 32, 128, 256 and 1,024 messages, with eight signals per message, for unchanged and one-property-change fixtures in both report modes. It is synthetic and does not claim production-data accuracy or machine-independent timing.

## Build and release

Run `python scripts/build.py` to create the Windows executable and zipapp in `dist/`. `scripts/release_check.py` checks release metadata and changelog consistency. The release workflow builds and smoke-tests artifacts from `main`; publishing requires an explicit release action. Python source GUI use requires the `gui` extra. Maintain matching-policy migration guidance in README and the user guide when changing report semantics.
