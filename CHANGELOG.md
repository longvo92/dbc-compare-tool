# Changelog

Everything worth knowing about a new version, written for the people who use the tool.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries land
under `## [Unreleased]` as they are merged; cutting a release moves them under a version
heading with its date.

## [1.0.0] - 2026-11-17

DBC Compare Tool is its own app again. Versions up to 0.8.0 shipped here, then the comparison
travelled inside CAN Toolbox for a while; this release brings it back as a single window that
does one job, with everything 2.0 added to it.

### Added

- **Compare two DBC files or two baseline folders** into an Excel report: added, removed, modified and renamed messages and signals, with OLD and NEW values for CAN ID, DLC, cycle time, signal layout, scaling, value tables and ECU Tx/Rx routing.
- **Pairing you can correct.** Files are paired by path and then by rename score; **Manual Pairing…** forces the pairs you want and marks OLD files as removed. **ECU Pairing…** pairs renamed nodes so a rename is not reported as a routing change.
- **ECU Focus** limits the report to the nodes you select, using routes from both baselines, so an ECU that gains or loses a Tx or Rx role still shows up.
- **A report in English or Vietnamese**, chosen independently of the interface language, and a **light or dark theme** that can follow Windows.
- Settings, including the two languages, the theme and the last baselines, are stored where DBC Compare Tool 0.8.0 kept them, so an older install carries over.

### Changed

- The report title is **DBC Comparison Report**.
- Settings moved into **Settings → Settings…**; the window itself only holds what a comparison needs.
