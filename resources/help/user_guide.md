# User Guide

The tool reports every change between two DBC baselines.

## Getting Started

1. **Input Type** — choose **Folders** to compare two baselines recursively, or **Files** to compare two `.dbc` files directly.
2. **Old Baseline** and **New Baseline** — select (or drag & drop) the OLD and NEW folders or DBC files. Both inputs must match the selected type.
3. **Report Path** — choose where to save the Excel report (`.xlsx`), or leave it empty to save beside NEW as `compared_<folder-name>.xlsx` or `compared_<file-stem>.xlsx`.
4. **Include Change Types** — tick the change categories you want in the report (Added / Removed / Modified / Renamed). All are included by default.
   For a complete inventory, tick **Include Unchanged**. It includes every message and signal and disables the change-type filters.
5. If ECU nodes were renamed, select their OLD/NEW counterparts with **ECU Pairing…** before running.
6. Click **Run Compare**. In file mode, the selected files form one pair regardless of their names. In folder mode, it uses the file pairs you saved in **Manual Pairing…** when they cover every old file (see below); otherwise it matches files automatically. Progress appears in the Execution Log. When finished, click **Open Report** to view the result in Excel.

The tool remembers your input type, last-used input paths and report path, so the next session starts pre-filled. Saved file and ECU pairs are cleared when either input or input type changes.

Input selection, **Manual Pairing…** and **ECU Pairing…** are grouped under **Baselines**; output and export options are under **Report**. **Run Compare** and **Open Report** stay visible at the bottom when you scroll a small window. Inputs are locked while comparison/export runs, and the footer shows progress, completion or failure.

---

## Understanding the Report

The Excel report contains the following sheets:

* **Summary** — total change counts by category, with report title and generation time.
* **DBC Overview** — one row per DBC file pair: pairing status (`Matched` / `DBC Added` / `DBC Removed` / `DBC Renamed` / `Manually Paired` / `Parse Error`), pairing confidence/reasons, and message/signal counts for both baselines.
* **Message Details** — every added, removed, modified, or renamed message.
* **Signal Details** — every added, removed, modified, or renamed signal.
* **Changed Properties** — before/after table for every changed property, one row per property. Old values highlighted in salmon, new values in green. This replaces the former Property Diff sheet.

Rows are color-coded by change type: green = Added, salmon = Removed, yellow = Modified, blue = Renamed. CAN IDs are shown in hexadecimal (e.g. `0x1A3`).

The detail and Changed Properties sheets include **ECU Node Tx (Old/New)** and **ECU Node Rx (Old/New)** for filtering. Message Rx aggregates all signal receivers; signal Tx is its parent message's transmitter. For cells listing several ECUs, use Excel **Text Filters → Contains** to find one node.

Detail sheets retain names, parent message names, OLD/NEW CAN IDs, ECU context and rename evidence. They do not repeat technical property columns or before/after descriptions. Changes to DLC, cycle time, layout, signedness/value type, scaling, range, unit, multiplexing, value tables and comments appear only in **Changed Properties**.

### Include Unchanged

Enable **Include Unchanged** to export the complete compared message/signal inventory, with unchanged rows in gray. It works with direct files and automatic or manual folder pairing. **Summary** lists unchanged counts separately; **Total Changes** excludes them. **Changed Properties** still contains changed properties only.

`Unchanged` means the entity's own properties match after applying any selected ECU mappings. A message may still contain changed signals; an unchanged signal may still be affected by a change to its parent message (CAN ID, Tx, cycle time, etc.). Review both detail sheets and Changed Properties together. Check the Summary's skipped parse-error count and DBC Overview before treating the report as complete.

The default mode exports changes only. For CLI full mode:

```powershell
dbc-compare-tool --old "path\to\old baseline" --new "path\to\new baseline" --include-unchanged --out impact_review.xlsx
```

---

## Main Features

### Automatic DBC File Matching

Files with the same relative path are compared first. For the remaining files, the tool looks across both inventories and chooses the one-to-one assignment with the highest total score. It uses shared filename/folder keywords, CAN IDs, message names and layouts. Common release/version decorations are ignored; keywords that distinguish files within the inventory carry more weight.

Example: `OEM_Powertrain_2024.dbc` vs `Vehicle_Powertrain_2026.dbc` can pair through `Powertrain`, even with completely different messages and CAN IDs. This deliberately allows more matches and can pair unrelated content. Check **Pairing Reason**, paths and counts in **DBC Overview**, or override the DBC pairs manually. The confidence is a heuristic score, not a probability.

### Direct File Comparison

Select **Files** and choose one OLD and one NEW `.dbc` file. The selected files are compared directly, without automatic file discovery or DBC file rename scoring. Message and signal rename detection still runs. **Manual Pairing…** is disabled because the file pair is already explicit. Mixing one file and one folder is rejected.

```powershell
dbc-compare-tool --old old.dbc --new new.dbc --out file_changes.xlsx
```

### ECU Node Pairing

Click **ECU Pairing…** to load node names from the selected inputs. The footer shows **Loading ECU nodes…** only during discovery, then **Editing ECU pairing…** while the dialog is open. The progress bar appears only while loading, comparing or exporting. For each renamed OLD ECU, select its NEW counterpart and save. Leave other rows on **Keep original name**. This works for both file and folder inputs and applies across the whole comparison; it does not filter the comparison to selected ECUs.

Each NEW node can have only one OLD counterpart. A mapping may not collide with an unmapped OLD node that retains that name. Changing either input or input type clears the saved pairs.

Paired names are treated as the same node for message Tx, signal Rx and rename scoring. A selected node rename alone does not create a modified message or signal. Actual routing changes and other property changes still appear in **Changed Properties**, with original OLD/NEW values. Original node names also remain in the report's ECU context columns; **Summary** records selected mappings.

If node names are swapped or reused, the same literal OLD/NEW name can represent different ECU identities. Such routing changes are still reported; use the mappings in Summary to interpret them.

For the CLI, repeat `--ecu-pair` for multiple nodes:

```powershell
dbc-compare-tool --old old.dbc --new new.dbc --ecu-pair VCU=VCU_NEW --ecu-pair BMS=BMS_NEW
```

### Manual DBC Pairing

If automatic matching does not pair the files the way you want, choose the pairs yourself:

1. Select both baseline folders, then click **Manual Pairing…** to open the pairing dialog.
2. For each old-baseline file, pick its new-baseline counterpart from the drop-down. New-baseline files not selected in any pair are reported as added.
3. Click **Save**, then **Run Compare** to export directly. There is no message/signal pairing dialog; their rename detection runs automatically.

**Run Compare** uses the saved pairing only when every old file is paired; leave any old file on `— Removed (no pair) —` and it falls back to automatic matching for the whole run. Manually matched pairs with different file names appear as **Manually Paired** on the DBC Overview sheet. Each new file can only be used in one pair. Changing either baseline folder discards the saved pairing — open the dialog again.

### Message Rename Detection

Message renames are identified even when the message name changes, based on CAN ID, DLC, signal layout, signal composition, and message attributes.

Example: `VehicleStatus` renamed to `Vehicle_Status` — classified as **Renamed**, with matching evidence in the report.

### Signal Rename Detection

Signal renames are identified by comparing technical characteristics — start bit, length, byte order, signedness, scaling (factor/offset), unit, receivers, and layout within the message — rather than relying on names alone.

Example: `VehSpd` renamed to `VehicleSpeed` — classified as **Renamed**.

### Confidence Levels

Every detected rename carries a confidence score and a level — **High**, **Medium**, or **Low** — shown in the report. Use it to decide how much of the result needs a second look; anything below High is worth checking.

Two situations lower confidence on purpose:

* **Event Matrix messages** — messages containing many structurally similar signals. There, the technical properties carry almost no information (dozens of signals share them), so the signal name drives the match and confidence never reaches High. Review these rows.
* **Ambiguous matches** — when several signals on one side are equally plausible matches for a single signal on the other, they are downgraded and the report notes `Ambiguous: ...` in the match reasons.

### Robust File Handling

* In folder mode, a corrupt or unparsable DBC is marked **Parse Error** (highlighted red in DBC Overview) and the remaining files are still compared. ECU pairing discovers nodes from readable files. A direct file parse failure stops the run.
* Files with special characters or unusual encodings (UTF-8 with/without BOM, CANdb++ default encoding) open reliably.

---

## Tips

* Drag a folder or `.dbc` file from Windows Explorer onto the baseline fields, matching the selected input type.
* Untick change types you don't need before running to get a smaller, focused report.
* If the report fails to save, make sure the file is not currently open in Excel.
