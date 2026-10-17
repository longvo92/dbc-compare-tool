# User Guide

## Tool (GUI)

1. Open the tool and choose **Files** or **Folders** under **Input Type**.
2. Select **Old Baseline** and **New Baseline**; both must use the same input type.
3. Set an `.xlsx` **Report Path**, or leave it empty to save automatically beside NEW.
4. Optional: use **Manual Pairing…** for folders (pair every OLD file) or **ECU Pairing…** for renamed nodes, then **Save**.
5. Select change types, or enable **Include Unchanged** for the full inventory; this ignores change-type filters.
6. Click **Run Compare**, then **Open Report** when finished.

## CLI

After installing the Python package, run: `dbc-compare-tool --old "old.dbc" --new "new.dbc" --out "report.xlsx"`.
Use two folder paths for folder comparisons. Add `--include-unchanged` for all entries or `--ecu-pair OLD=NEW` for renamed nodes.

## Excel Basics

- Start with **Summary** for totals and **DBC Overview** to check file pairs and parse errors.
- Use column filters in **Message Details** and **Signal Details** to find a change type, CAN ID or ECU.
- Open **Changed Properties** to review each changed property's OLD and NEW values.
- For cells listing multiple ECUs, use **Text Filters → Contains**. Close the workbook before regenerating the same report.
