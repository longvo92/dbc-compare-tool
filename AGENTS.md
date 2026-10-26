# DBC Compare Tool

## Project Context
- Python application for comparing DBC files and generating comparison reports through CLI and GUI.
- Source package: `src/dbc_compare_tool/`.
- Runtime, dependencies, and build configuration are defined in `pyproject.toml`.
- Existing technologies include cantools, openpyxl, and optional PySide6.
- Follow global working preferences unless overridden by project-specific requirements.

## Architecture and Engineering
- Prioritize correctness, maintainability, extensibility, performance, and a coherent architecture.
- Large refactors, multi-module changes, architectural redesigns, and repository restructuring are allowed when they meaningfully improve the project.
- Do not limit implementations to minimal patches or preserve legacy patterns solely for compatibility.
- Keep the comparison engine and report generation independent of GUI frameworks.
- Maintain clear boundaries between core logic, reporting, CLI, and GUI. Refactor these boundaries when beneficial.
- Centralize shared behavior so CLI and GUI produce consistent comparison results and reports.
- Introduce, replace, or remove dependencies, abstractions, and tools when justified by measurable benefits or simpler design.
- Existing public APIs, CLI options, report formats, and configuration contracts should remain compatible when practical. Breaking changes are allowed when justified and documented.
- Remove obsolete code and redundant implementations when their replacements are complete and verified.
- Address root causes and relevant architectural weaknesses rather than applying temporary workarounds.

## Runtime and Dependencies
- Support Python >=3.9 as declared in `pyproject.toml`.
- Use compatible syntax and standard library APIs; enable postponed annotations where appropriate.
- The minimum Python version may be raised when a substantial benefit justifies the migration. Update metadata, tests, CI, and documentation accordingly.
- Keep core engine and reporting usable without installing PySide6.
- GUI-specific dependencies must remain optional for headless CLI usage.
- Choose additional dependencies autonomously and explain significant additions or replacements.

## Documentation
- Keep documentation concise, practical, and consistent with actual behavior.
- User guides should explain supported workflows, options, limitations, and result interpretation.
- Maintainer documentation should describe architecture, important contracts, and development workflows.
- Update relevant documentation when behavior, interfaces, or architecture changes.
- Record meaningful user-visible changes in `CHANGELOG.md`.
- Avoid duplicating existing guidance, temporary implementation notes, historical status reports, and unnecessary documentation churn.
- Documentation structure may be reorganized or consolidated when it improves clarity and maintainability.

## Testing and Verification
- Own verification end-to-end using the project's existing tests, linting, smoke tests, and packaging workflows.
- Add, restructure, or replace tests and verification tools when this improves coverage, reliability, or execution speed.
- For code changes, start with relevant targeted tests and run broader checks before delivery when practical.
- Maintain regression coverage for comparison semantics, report consistency, CLI behavior, and affected GUI workflows.
- Verify headless operation independently of GUI dependencies.
- Use appropriate temporary directories for generated reports and test artifacts.
- Existing verification entry points:
  - Environment: `PYTHONPATH=src`
  - Tests: `python -m unittest discover -s tests -v`
  - Lint: `python -m ruff check .`
  - Engine smoke: `python -m dbc_compare_tool.cli --old examples/old --new examples/new --out <temporary-report.xlsx>`
  - Packaging: `python scripts/build.py`
  - Windows launchers: `run_gui.bat`, `run_cli.bat`
- These commands are reference entry points, not restrictions against improving the testing or build infrastructure.
- Run release preflight for authorized releases.
- Report skipped checks and unavailable environments without claiming unverified success.

## Delivery
- Follow global Git autonomy for branch creation, commits, push, and PR creation.
- Implement related changes across modules when necessary for a complete solution.
- Review changes and run relevant verification before committing.
- Create a draft PR when important verification remains incomplete.
- Merge, publish releases, or deploy only when explicitly requested.
- Preserve unrelated user work, local data, secrets, and generated artifacts.
- Summarize significant architectural decisions, breaking changes, dependencies, and verification limitations.