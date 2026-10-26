# User Guide

## Tool (GUI)

1. Open the tool. Choose **Files** or **Folders** under **Input Type**.
2. Select **Old Baseline** and **New Baseline**; both must use the same input type.
3. Set an `.xlsx` **Report Path**, or leave it empty to save automatically beside NEW.
4. Optional: use **Manual Pairing…** for files (folders; pair every OLD file). In **ECU Pairing…**, select only nodes to rename, leave the rest at **Keep original name**, then **Save**.
5. Select change types. For all entries, enable **Include Unchanged**; change-type filters will be ignored.
6. Click **Run Compare**, then **Open Report** when finished.

## CLI

After source installation, run from the repository folder: `.\run_cli.bat --old "old.dbc" --new "new.dbc" --out "report.xlsx"`.
For folders, pass two folder paths. Add `--include-unchanged` for all entries. Repeat `--ecu-pair OLD=NEW` for renamed nodes; other nodes keep their names.

## Excel Basics

- Start with **Summary** for totals. Folder reports also include **DBC Overview** to check file pairs and parse errors; file reports omit this sheet.
- Filter **Message Details** and **Signal Details** by change type, CAN ID or ECU. Review **Medium/Low** confidence and **Match Reason**.
- Message and signal names, including parent message names, use separate OLD/NEW columns. Other fields show unchanged values once (`EVCC`) and changes as `EVCC->EVCC2`. Added/removed entries show only the existing value, without an arrow.
- Read the **Changed Properties** column in each detail sheet. Multiple changes share one cell, separated by `; `, for example `Start Bit: 56->57; Length: 8->16`. Entries without property changes leave this cell blank.
- For cells listing multiple ECUs, use **Text Filters → Contains**. Close the workbook before regenerating the same report.
