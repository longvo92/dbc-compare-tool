# Architecture

The CLI and PySide6 GUI share a Qt-independent core and Excel writer. Python 3.9+ remains supported. Core dependencies are cantools/openpyxl; install `.[gui]` for the optional PySide6 UI. No solver dependency is required.

## Components

Paths are relative to `src/dbc_compare_tool/`.

| Module | Responsibility |
|---|---|
| `core/models.py` | Input entities, full identities, pairing metadata, inventory, diagnostics and results |
| `core/parser.py` | Parse DBCs; reject duplicate names/frame keys before dictionary loss; validate API inventories |
| `core/discovery.py` | Discover case-insensitive `.dbc` extensions with relative paths |
| `core/policy.py` | Versioned `recall-v1` eligibility, profiles, scoring weights and confidence constants |
| `core/assignment.py` | Component decomposition and rectangular Hungarian assignment |
| `core/matching.py`, `core/pairing.py` | Shared entity matching/confidence and DBC candidate convenience API |
| `core/ecu.py` | Node discovery, mapping validation and routing equivalence |
| `core/comparator.py` | Hierarchical comparison, inventory accounting, moves and filtering |
| `report/excel.py`, `report/_style.py` | Shared atomic Excel export and formatting |
| `ui/main_window.py`, `ui/widgets.py` | Inputs, workers, DBC/ECU mapping dialogs and settings |
| `cli.py` | Arguments, status codes and export |

## Pipeline and contracts

Parse/validate inventory → apply manual mapping → generate eligible edges → assign → assess confidence → compare properties → suggest parent moves → verify inventory → filter details → export.

`compare_paths`, `compare_files`, `compare_folders`, `compare_manual` and `compare_databases` remain available. `DbcComparator(..., *, policy="recall-v1")` accepts the policy version or an internal `MatchingPolicy` object. There is one engine and no legacy mode.

Identity consists of side, full relative DBC path (absolute selected path in direct-file mode), entity kind, frame ID/extended flag, message name and signal name. Basenames are display labels only. Pair IDs are assigned in identity order and preserved by filtering; they identify one pair throughout a report rather than a globally permanent record.

Direct-file selection and manual DBC targets are fixed constraints. For `compare_manual`, `None` and omitted OLD paths mean Removed; unreferenced NEW paths mean Added. GUI saved mappings apply even with Removed rows. Input changes invalidate saved maps. ECU mappings apply before evidence and property comparison while original routing values remain available for reports.

Names must be unique per DBC/message; frame keys `(can_id, is_extended_frame)` must be unique per DBC. Parsed lists are checked before conversion to dictionaries. API mappings are checked for duplicate values/names and inconsistent keys; entities lost before reaching the API cannot be reconstructed.

Direct-file parse failure aborts. Folder failures record side/path/reason and produce Incomplete. A valid peer of a failed fixed pair is Not compared. Automatic same-path candidates are not fixed: valid unmatched files stay in the inventory and can be paired elsewhere or reported Added/Removed. Every valid entity must appear exactly once in the pairing ledger as paired, unmatched or not compared; the invariant runs before filtering. Unknown unreadable inventory is never assumed zero. ECU node-existence checks are deferred only on unreadable sides; known-side mapping validation remains active.

## Recall-v1 matching

Eligibility is the OR of the following evidence, independent of ranking:

| Level | Minimum evidence |
|---|---|
| DBC | Equal relative path; meaningful shared path/filename keyword; or ≥0.50 overlap in frame keys, message names, signal names or message structures |
| Message | Equal frame key/name; ≥0.50 signal-name/layout overlap; or name similarity ≥0.45 with equal DLC or transmitter |
| Signal | Equal name/layout; equal properties except name/start; name similarity ≥0.45 with equal length/byte order; or position shift ≤8 with equal encoding, scaling/range and unit |

Names use casefolded `SequenceMatcher(autojunk=False)`. Overlap is intersection divided by the smaller inventory; empty collections supply no evidence. Layout/structure Counters preserve multiplicity and multiplex branches, resolving parent layouts recursively so renamed multiplexers retain their topology. Empty messages supply no structural evidence. Message structure ignores names, CAN ID and cycle time. Keyword version/date removal uses fixed path strengths, with no inventory-wide frequency weights.

Every eligible edge is retained: no confidence cutoff or top-K. Sort full identities, quantize similarity to 1e-6, split the bipartite graph into independent connected components, then use Hungarian assignment with integer pair bonuses. Each extra pair outweighs every possible similarity improvement; total similarity is the second objective and stable traversal breaks ties. Use the smaller component axis as rows and add dummy unmatched columns. Same path/frame/name and complete-property matches are never reserved in advance.

| Level | Similarity group weights |
|---|---|
| DBC | Path/keyword 20, frames 20, message names 20, signal names 20, structure 20 |
| Message | Frame 10, name 20, signal names 25, layout 30, DLC 5, transmitter 5, cycle 5 |
| Signal | Name 25, layout 25, encoding 15, scaling/range 15, unit 5, receivers 5, multiplexing 10 |

Unavailable scalar/collection metadata drops its weight; remaining groups renormalize. Scalars compare by value; groups average their available fields. Signal layout averages position/length/byte order; position uses `1 / (1 + distance / 16)` with continuous decay after 8 bits. Encoding averages length/order/type/sign. Profiles are built once per inventory and name similarity has a bounded cache. Candidate metadata is O(edges); rival references are retained on selected pairs to avoid cubic duplication. Dense components still require quadratic candidate storage and cubic Hungarian work; coverage is never reduced for speed.

Confidence is heuristic: High ≥0.90, Medium ≥0.70, otherwise Low. Start at `0.99 × similarity`; only a complete-property edge with no eligible rival gets 1.0. A rival within 0.05 or better applies a margin penalty and caps confidence at 0.89. A nonfixed parent's confidence caps children; its review requirement also caps them below High. Confidence is floored to two decimals before classification. Event-like signals use the same policy as other signals.

`PairingMetadata` retains identities, similarity, confidence, evidence, selected/fixed state, review requirement and competitors. `Change` and file summaries reference it directly; report reasons are never parsed from descriptions. Selected pairs include unchanged entities even when no change row is emitted.

Move suggestions evaluate all eligible unmatched message pairs across different DBC parents and signal pairs across different message parents. Corresponding paired parents are excluded, as are manual exclusions and not-compared inventories. Suggestions do not alter assignment, coverage, Added/Removed or totals. Split/merge is unsupported.

## Reports and entry points

The workbook keeps Summary, Message Details and Signal Details; folders add DBC Overview. Pairing Review appears for selected review pairs, every eligible competitor and move suggestions. It records full identities/paths/parents, scores, selected status and evidence. Excel row/text limits fail export explicitly. Export uses a sibling temporary file then replaces the target, preserving an existing workbook on failure. Cell text is written as literal strings.

`summary()` only counts detail changes and excludes Unchanged from Total Changes. Completeness, diagnostics, coverage, policy and review count are separate metadata. `filter_result()` changes only detail lists; Include Unchanged bypasses filtering. Suppressed unchanged review pairs still appear in Pairing Review. Incomplete and Unknown are prominent in Summary/DBC Overview.

GUI comparison/discovery/export run in workers and retain existing QSettings behavior. No review-confirmation step precedes export. The completion status includes completeness, file errors and review count.

| Entry point | Target |
|---|---|
| `dbc-compare-tool-gui`, `python -m dbc_compare_tool` | `ui.main_window:main` |
| `dbc-compare-tool`, `python -m dbc_compare_tool.cli` | `cli:main` |

CLI: 0 complete export; 1 direct-file parse/processing/export error; 2 invalid input/mapping; 3 exported Incomplete. Existing automation must handle 3 separately from success. Source GUI installations now require the `gui` extra.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui]" ruff pyinstaller
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts/evaluate_pairing.py --benchmark
.\.venv\Scripts\python.exe -m dbc_compare_tool.cli --old examples/old --new examples/new --out "$env:TEMP\dbc-smoke.xlsx"
```

Retained regressions cover duplicate inventories, missing cycle time, greedy message/exact signal traps, filename plus frame changes, DBC cardinality versus total score, standard/extended IDs, multiplexing, small deltas, ECU mapping, filtering and moves. Small graphs are exhaustively checked against brute-force cardinality/similarity optima. A shared generated fixture runs through API, CLI and GUI workers, then Excel contents are compared including coverage, confidence and diagnostics.

`tests/fixtures/pairing_corpus.json` labels supported rename scenarios; `scripts/evaluate_pairing.py` emits recall/precision/coverage per level and exits nonzero on a failed acceptance condition. Ambiguous cases label pair count/review rather than arbitrary identity truth. `--benchmark` measures a fixed 32-message × 12-signal fixture with perf_counter/tracemalloc. Performance is informational, not a timing gate. There is no labeled production corpus: these results do not demonstrate real-world accuracy.

CI retains Linux/Windows Python 3.9/3.10/3.12 engine jobs and Windows/Python 3.12 GUI verification. Core jobs omit Qt, GUI tests skip if unavailable, and packaged artifacts require startup/export smoke checks.

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

- Custom `BA_` attributes except `GenMsgCycleTime` are not compared.
- Minimum evidence may admit ambiguous pairs intentionally; review metadata is part of the result.
- Manual editing applies to DBC files and ECU nodes. Message/signal matching is automatic; possible moves remain separate suggestions.
- Large dense inventories can produce large review sheets; Excel limits cause an explicit export error.
