# DBC Compare Tool

Compare two CAN DBC files or baseline folders and export changes to Excel. Detect added, removed, modified and renamed messages and signals, including value tables and comments.

![DBC Compare Tool](docs/screenshot_main.png)

## Quick start

1. Download the Windows `.exe` from [Releases](https://github.com/longvo92/dbc-compare-tool/releases/latest) and open it. No Python installation is needed.
2. Choose **Files** or **Folders**, then select the OLD and NEW inputs.
3. Click **Run Compare**, then **Open Report**.

See the [User Guide](resources/help/user_guide.md) for pairing, CLI and Excel basics. Sample inputs are in [examples/old](examples/old) and [examples/new](examples/new).

## The report

| Sheet | Use it to |
|---|---|
| Summary | Check change counts and selected ECU mappings |
| DBC Overview | Review file pairs, paths and parse errors |
| Message Details | Review message changes and ECU routing |
| Signal Details | Review signal changes and rename confidence |
| Changed Properties | Compare OLD and NEW property values |

Use Excel column filters to find a change type, CAN ID or ECU.

## Requirements

- Windows for the packaged desktop app.
- Python 3.9+ for source use; installation includes `cantools`, `openpyxl` and `PySide6`.

## Install from source

```powershell
git clone https://github.com/longvo92/dbc-compare-tool.git
cd dbc-compare-tool
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
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

- Rename confidence is a heuristic. Review matches that affect your analysis.
- In folder mode, unreadable files are skipped and marked **Parse Error**. Check **DBC Overview** for missing inputs. A direct file parse error stops the run.
- **Unchanged** describes an item's own properties. Its parent message or contained signals may still have changes.

## Documentation

- [User Guide](resources/help/user_guide.md) — basic GUI, CLI and Excel usage
- [Architecture](docs/architecture.md) — components, matching rules, testing and builds
- [Changelog](CHANGELOG.md) — release notes

## License

[MIT](LICENSE) · Long Vo Thien
