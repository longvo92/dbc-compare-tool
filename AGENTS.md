# DBC Compare Tool

GUI-only Windows desktop app shipped as one PyInstaller exe. One window compares two DBC files
or two baseline folders and writes an Excel change report; pairing, ECU pairing and ECU focus are
dialogs on that window.

## Layout
- `src/dbc_compare_tool/`: `dbc_compare/` (`core/` engine, `report/` Excel, `i18n.py` translations, `pipeline.py`), `ui/` (`main_window.py` shell, `compare_tab.py` workspace, `ecu_focus.py`, `settings_dialog.py`, `widgets.py`, `theme.py`, `app.py`), `app_paths.py`, `i18n.py`, `release_notes.py`.
- `scripts/` (`build.py`, `release_check.py`, `smoke.py`), `examples/old|new/Bus_A.dbc`, `resources/` (`app.ico`, tinted SVGs, `help/`), `tests/`.

## Runtime
- Python >=3.11; PySide6, cantools, openpyxl as declared in `pyproject.toml`. No other runtime dependency.
- Distributed only as the exe.

## Commands
- Environment: `PYTHONPATH=src` and `QT_QPA_PLATFORM=offscreen` (tests must import the working tree, not an installed copy).
- Test: `python -m pytest -q` (`-m gui` / `-m "not gui"` split the Qt tests). Lint: `python -m ruff check .`
- Smoke: `python scripts/smoke.py` (headless comparison; `--gui` also opens the window offscreen).
- Build: `python scripts/build.py` (exe only). Release gate: `python scripts/release_check.py <X.Y.Z> --notes <file>`.

## Invariants
- The app is GUI-only: no CLI entry point. `dbc_compare/` imports no GUI framework.
- `dbc_compare/**`, `ui/compare_tab.py` and `ui/ecu_focus.py` are vendored verbatim into [can-toolbox](https://github.com/longvo92/can-toolbox); this repository is their source of truth. They use relative imports only and never name a package (`tests/test_shell.py`). Changing them means copying the files into can-toolbox and running its compare tests.
- The window drives the engine through `dbc_compare/pipeline.py`; no comparison logic lives in `ui/`.
- Colours live only in `ui/theme.py`; `tests/test_theme.py` fails on a hex colour elsewhere under `ui/` and on contrast below WCAG AA.
- Report formats and GUI options stay compatible; 0.8.0 preferences are migrated, not broken (`QSettings("DbcCompareTool", "DBCCompareTool")`).
- Engine log text stays English; GUI chrome and the Excel report are localized (EN/VI).
- Matching follows the `classic-v067` contract: same-path DBCs first, then renames; messages by frame key, name, rename; signals by name and rename. Only explicit file selection and manual mappings are fixed.

Working rules live in the owner's global instructions.
