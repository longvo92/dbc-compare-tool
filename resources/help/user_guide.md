# User Guide

## Tool (GUI)

1. Open the tool. Choose **Files** or **Folders** under **Input Type**.
2. Select **Old Baseline** and **New Baseline**; both must use the same input type.
3. Set an `.xlsx` **Report Path**, or leave it empty to save automatically beside NEW.
4. Optional: set file pairs with **Manual Pairing…** (folders; pair every OLD file) or renamed nodes with **ECU Pairing…**. Click **Save**.
5. Select change types. For all entries, enable **Include Unchanged**; change-type filters will be ignored.
6. Click **Run Compare**, then **Open Report** when finished.

## CLI

After source installation, run from the repository folder: `.\run_cli.bat --old "old.dbc" --new "new.dbc" --out "report.xlsx"`.
For folders, pass two folder paths. Add `--include-unchanged` for all entries or repeat `--ecu-pair OLD=NEW` for renamed nodes.

## Excel Basics

- Start with **Summary** for totals and **DBC Overview** to check file pairs and parse errors.
- Use column filters in **Message Details** and **Signal Details** to find a change type, CAN ID or ECU.
- Open **Changed Properties** to review each changed property's OLD and NEW values.
- For cells listing multiple ECUs, use **Text Filters → Contains**. Close the workbook before regenerating the same report.
