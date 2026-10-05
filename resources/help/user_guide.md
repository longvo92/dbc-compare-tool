# User Guide

The tool reports every change between two DBC baselines.

## Getting Started

1. **Old Baseline Folder** — select (or drag & drop) the folder containing the previous DBC baseline.
2. **New Baseline Folder** — select (or drag & drop) the folder containing the new DBC baseline.
3. **Report Path** — choose where to save the Excel report (`.xlsx`).
4. **Include Change Types** — tick the change categories you want in the report (Added / Removed / Modified / Renamed). All are included by default.
   For a complete inventory, tick **Include Unchanged**. It includes every message and signal and disables the change-type filters.
5. Click **Run Compare**. It uses the file pairs you saved in the **Manual Pairing** dialog when they cover every old file (see below); otherwise it matches files automatically. Progress appears in the Execution Log. When finished, click **Open Report** to view the result in Excel.

The tool remembers your last-used folders and report path, so the next session starts pre-filled.

Folder selection and **Manual Pairing** are grouped under **Baselines**; output and export options are under **Report**. **Run Compare** and **Open Report** stay visible at the bottom when you scroll a small window. Inputs are locked while comparison/export runs, and the footer shows progress, completion or failure.

---

## Understanding the Report

The Excel report contains the following sheets:

* **Summary** — total change counts by category, with report title and generation time.
* **DBC Overview** — one row per DBC file pair: pairing status (`Matched` / `DBC Added` / `DBC Removed` / `DBC Renamed` / `Manually Paired` / `Parse Error`), pairing confidence/reasons, and message/signal counts for both baselines.
* **Message Details** — every added, removed, modified, or renamed message.
* **Signal Details** — every added, removed, modified, or renamed signal.
* **Property Diff** — before/after table for every changed property, one row per property. Old values highlighted in salmon, new values in green.

Rows are color-coded by change type: green = Added, salmon = Removed, yellow = Modified, blue = Renamed. CAN IDs are shown in hexadecimal (e.g. `0x1A3`).

The detail and Property Diff sheets include **ECU Node Tx (Old/New)** and **ECU Node Rx (Old/New)** for filtering. Message Rx aggregates all signal receivers; signal Tx is its parent message's transmitter. For cells listing several ECUs, use Excel **Text Filters → Contains** to find one node.

Detail sheets include OLD/NEW CAN IDs, frame type, DLC, cycle time, signal counts and descriptions. Signal Details also includes both parent message names, layout, signedness/value type, scaling, range, unit, multiplexing, value tables and comments.

### Include Unchanged

Enable **Include Unchanged** to export the complete compared message/signal inventory, with unchanged rows in gray. It works with automatic and manual DBC pairing. **Summary** lists unchanged counts separately; **Total Changes** excludes them. **Property Diff** still contains changed properties only.

`Unchanged` means the entity's own properties match. A message may still contain changed signals; an unchanged signal may still be affected by a change to its parent message (CAN ID, Tx, cycle time, etc.). Review the OLD/NEW context and both detail sheets together. Check the Summary's skipped parse-error count and DBC Overview before treating the report as complete.

The default mode exports changes only. For CLI full mode:

```powershell
dbc-compare-tool --old "path\to\old baseline" --new "path\to\new baseline" --include-unchanged --out impact_review.xlsx
```

---

## Main Features

### Automatic DBC File Matching

Files with the same relative path are compared first. For the remaining files, the tool looks across both inventories and chooses the one-to-one assignment with the highest total score. It uses shared filename/folder keywords, CAN IDs, message names and layouts. Common release/version decorations are ignored; keywords that distinguish files within the inventory carry more weight.

Example: `OEM_Powertrain_2024.dbc` vs `Vehicle_Powertrain_2026.dbc` can pair through `Powertrain`, even with completely different messages and CAN IDs. This deliberately allows more matches and can pair unrelated content. Check **Pairing Reason**, paths and counts in **DBC Overview**, or override the DBC pairs manually. The confidence is a heuristic score, not a probability.

### Manual DBC Pairing

If automatic matching does not pair the files the way you want, choose the pairs yourself:

1. Select both baseline folders, then click **Manual Pairing…** to open the pairing dialog.
2. For each old-baseline file, pick its new-baseline counterpart from the drop-down. New-baseline files not selected in any pair are reported as added.
3. Click **Save**, then **Run Compare** to export directly. There is no message/signal pairing dialog; their rename detection runs automatically.

**Run Compare** uses the saved pairing only when every old file is paired; leave any old file on `— Removed (no pair) —` and it falls back to automatic matching for the whole run. Manually matched pairs with different file names appear as **Manually Paired** on the DBC Overview sheet. Each new file can only be used in one pair. Changing either baseline folder discards the saved pairing — open the dialog again.

### Message Rename Detection

Message renames are identified even when the message name changes, based on CAN ID, DLC, signal layout, signal composition, and message attributes.

Example: `VehicleStatus` renamed to `Vehicle_Status` — classified as **Renamed**, with a `Matched by: ...` explanation in the report.

### Signal Rename Detection

Signal renames are identified by comparing technical characteristics — start bit, length, byte order, signedness, scaling (factor/offset), unit, receivers, and layout within the message — rather than relying on names alone.

Example: `VehSpd` renamed to `VehicleSpeed` — classified as **Renamed**.

### Confidence Levels

Every detected rename carries a confidence score and a level — **High**, **Medium**, or **Low** — shown in the report. Use it to decide how much of the result needs a second look; anything below High is worth checking.

Two situations lower confidence on purpose:

* **Event Matrix messages** — messages containing many structurally similar signals. There, the technical properties carry almost no information (dozens of signals share them), so the signal name drives the match and confidence never reaches High. Review these rows.
* **Ambiguous matches** — when several signals on one side are equally plausible matches for a single signal on the other, they are downgraded and the report notes `Ambiguous: ...` in the match reasons.

### Robust File Handling

* A corrupt or unparsable DBC file does not stop the comparison: it is marked **Parse Error** (highlighted red in DBC Overview) and the remaining files are still compared.
* Files with special characters or unusual encodings (UTF-8 with/without BOM, CANdb++ default encoding) open reliably.

---

## Tips

* Drag a folder from Windows Explorer directly onto the baseline fields — no need to click Browse.
* Untick change types you don't need before running to get a smaller, focused report.
* If the report fails to save, make sure the file is not currently open in Excel.
