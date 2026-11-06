# User Guide

## GUI

1. Choose **Files** or **Folders**; select the OLD and NEW inputs of the same type.
2. Open **Settings → Language…** to choose the **GUI Language** and **Report Language**. The report follows the GUI by default. Leave **Report Path** empty to save `compared_<old>_vs_<new>.xlsx` beside NEW, or choose an explicit `.xlsx` path.
3. Optional: in folder mode, use **Manual Pairing…** to force DBC pairs or mark OLD files **Removed**. Saved mappings override automatic matching, including Removed rows. Unlisted OLD files are removed; unreferenced NEW files are added.
4. In **ECU Pairing…**, select nodes to rename; leave other nodes at **Keep original name**. Original names remain in the report.
5. Enable **ECU Focus** to scan both inputs, then check the nodes to include. Use **Select ECUs…** to edit the selection. Changing the inputs or the ECU mapping clears the selected nodes.
6. The report includes all change types within the current ECU scope. Enable **Include Unchanged** to also list unchanged messages and signals.
7. Click **Run Compare**. Export is automatic; then click **Open Report**.

The finished status shows file errors and pairs requiring review. **Report incomplete** means some inputs could not be compared; zero changes in that report does not establish equality.

## CLI

Install the core with `pip install -e .`, or the GUI with `pip install -e ".[gui]"`. From the repository:

```powershell
.\run_cli.bat --old "old.dbc" --new "new.dbc" --out "report.xlsx"
.\run_cli.bat --old "old folder" --new "new folder" --include-unchanged --ecu-pair OLD_ECU=NEW_ECU
```

| Option | Behavior |
|---|---|
| `--old PATH`, `--new PATH` | Required; two folders or two `.dbc` files. Quote spaces. Mixed file/folder inputs are rejected. |
| `--out PATH` | Optional `.xlsx`. Defaults beside NEW to `compared_<old>_vs_<new>.xlsx` using folder names or file stems. |
| `--include-unchanged` | Include unchanged messages and signals; default is changes only. |
| `--ecu-pair OLD=NEW` | Repeat for multiple node renames. Other nodes keep their names; selected rename targets must be distinct and nodes must exist. |
| `--list-ecus` | Scan OLD and NEW and print their ECU nodes. Use with the two input paths. No report is written. |
| `--ecu-focus NODE` | Limit detail rows to Tx/Rx changes for this node. Repeat for multiple nodes. |
| `--report-language {en,vi}` | Choose the Excel report language. Default: English. |
| `-h`, `--help` | Show command help. |

Exit codes: **0** complete export; **1** direct-file parse, processing or export failure; **2** invalid input/mapping; **3** export or ECU scan completed with skipped DBCs. Automation should inspect code 3 and the report's diagnostics.

## Pairing

`classic-v067` pairs same-path DBCs first and then searches for renamed files. Within paired files it matches messages by frame key, then name, then rename score. Within paired messages it matches signals by name and then rename score. Selecting two files directly or saving a manual DBC map forces those file pairs.

Rename scores must reach 0.55 for DBCs, 0.60 for messages, 0.65 for signals or 0.55 for event-like signals. Unmatched entities become Added/Removed. **High/Medium/Low** confidence for selected renames is heuristic; ambiguity can lower it.

Message moves across DBCs and signal moves across messages appear as Added/Removed. Split/merge matching and message/signal mapping editors are not supported.

## ECU focus

Focus uses routes from both inputs, so the report includes changes that add or remove an ECU's Tx or Rx role. A selected transmitter includes all its changed signals. A selected receiver includes only its own signals and any message-level changes for the messages carrying them. Selecting an endpoint of a saved ECU pair also includes its counterpart on the other baseline. The same node name applies across all selected DBCs.

Summary lists the selected nodes, applicable mappings and change counts. DBC Overview shows only file pairs represented in the detail sheets, with counts for the whole DBC. Coverage and parse diagnostics still describe the full inputs.

## Excel

- Begin with **Summary**: Complete/Incomplete, matching policy, change totals, coverage, file diagnostics and ECU mappings. Coverage accounts for known entities as paired, unmatched or not compared; unreadable inventory is **Unknown**.
- Folder reports include **DBC Overview**. Direct-file reports omit it. If a forced counterpart cannot be parsed, its valid peer is **Not compared**, not Added/Removed.
- Filter **Message Details** and **Signal Details** by type, CAN ID or ECU. Rename confidence and match reasons appear on selected rename rows. Unchanged rows appear only with Include Unchanged.
- Names and parent names have separate OLD/NEW columns. Other fields show equal values once or changes as `old->new`. Added/removed entries show only the existing side.
- **Changed Properties** combines deltas, e.g. `Start Bit: 56->57; Length: 8->16`. No property delta means a blank cell. Use **Text Filters → Contains** for cells listing several ECUs.
- Close the workbook before regenerating it. Duplicate message names/frame keys or signal names are parse errors. Direct-file errors stop export; folder errors allow a partial report.

Matching has synthetic regression coverage; no production corpus with labeled mappings is available.
