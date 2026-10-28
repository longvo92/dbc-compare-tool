<div align="center">

# DBC Compare Tool

**Compare CAN DBC baselines and review changes in Excel.**

[![CI](https://github.com/longvo92/dbc-compare-tool/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/longvo92/dbc-compare-tool/actions/workflows/test.yml)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-22A699.svg)](LICENSE)

[Download](https://github.com/longvo92/dbc-compare-tool/releases/latest) · [Quick start](#quick-start) · [Usage](#usage) · [User Guide](resources/help/user_guide.md) · [Changelog](CHANGELOG.md)

</div>

Compare two CAN DBC files or baseline folders and export changes to Excel. Detect added, removed, modified and renamed messages and signals, including value tables and comments.

## Features

| Feature | Use it to |
|---|---|
| File or folder comparison | Compare individual DBCs or complete baselines |
| Recall-first pairing | Match DBCs, messages and signals; flag weak or competing pairs for review |
| ECU pairing | Map renamed nodes and review routing changes |
| Excel reports | Filter changes and inspect OLD/NEW property values |

![DBC Compare Tool](docs/screenshot_main.png)

## Quick start

1. Download the Windows `.exe` from [Releases](https://github.com/longvo92/dbc-compare-tool/releases/latest) and open it. No Python installation is needed.
2. Choose **Files** or **Folders**, then select the OLD and NEW inputs.
3. Click **Run Compare**, then **Open Report**.

See the [User Guide](resources/help/user_guide.md) for pairing, CLI and Excel basics. Sample inputs are in [examples/old](examples/old) and [examples/new](examples/new).

## The report

| Sheet | Use it to |
|---|---|
| Summary | Check Complete/Incomplete status, policy, inventory coverage and review counts |
| DBC Overview (folder mode only) | Review file pairs, paths and parse errors |
| Message Details | Review message changes and ECU routing |
| Signal Details | Review signal changes and heuristic confidence |
| Pairing Review (when needed) | Inspect weak pairs, all competing candidates and possible parent moves |

Use Excel column filters to find a change type, CAN ID or ECU.
Use **Pair ID** to trace a pair into **Pairing Review**, and filter **Review Required** for uncertain results.
Read **Changed Properties** in each detail sheet for compact deltas, such as `Start Bit: 56->57; Length: 8->16`.
Message and signal names, including parent message names, use separate OLD/NEW columns. Other fields show unchanged values once (`EVCC`) and changes as `EVCC->EVCC2`. Added/removed entries show only the existing value, without an arrow.

## Requirements

- Windows for the packaged desktop app.
- Python 3.9+ for source use; core installation includes `cantools` and `openpyxl`. The GUI requires the `gui` extra (`PySide6`).

## Install from source

```powershell
git clone https://github.com/longvo92/dbc-compare-tool.git
cd dbc-compare-tool
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
```

## Usage

From the repository folder, start the GUI with `.\run_gui.bat`, or run the CLI:

```powershell
.\run_cli.bat --old "examples\old" --new "examples\new" --out "report.xlsx"
```

- Pass two folders or two `.dbc` files. Quote paths containing spaces.
- Omit `--out` to save beside NEW as `compared_<name>.xlsx`.
- Add `--include-unchanged` to include the full inventory.
- Add `--ecu-pair OLD=NEW` for renamed ECU nodes; repeat for multiple pairs.

## Review the results

- The shared `recall-v1` policy maximizes eligible pair count, then similarity. Same path, CAN ID and name are evidence rather than fixed matches; only direct-file selection and manual DBC mapping force a pair.
- Weak pairs remain visible. Review **Review Required**, confidence and **Pairing Review**; confidence is a heuristic, not a probability. Parent uncertainty limits child confidence.
- Folder parse errors produce an **Incomplete** report with OLD/NEW paths and causes. Unreadable counts are **Unknown**; a valid file whose fixed manual counterpart failed is **Not compared**. Direct-file parse errors stop export.
- Message names and frame keys must be unique per DBC; signal names must be unique per message. Duplicate entities are rejected, including in the database API.
- Saved manual mappings are respected, including **Removed** rows. Possible message/signal moves appear only as suggestions and leave the main Added/Removed results unchanged.
- CLI exit codes: `0` complete, `1` parse/processing/export failure, `2` invalid input/mapping, **`3` report exported but incomplete**. Update scripts that previously treated partial reports as success.
- **Unchanged** describes an item's own properties. Its parent or children may still change. Synthetic regression results do not establish production matching accuracy.

## Documentation

- [User Guide](resources/help/user_guide.md) — basic GUI, CLI and Excel usage
- [Architecture](docs/architecture.md) — components, matching rules, testing and builds
- [Changelog](CHANGELOG.md) — release notes

## License

[MIT](LICENSE) · Long Vo Thien
