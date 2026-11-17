"""Qt-free comparison pipeline shared by the GUI, tests and the smoke script."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from .core.comparator import DbcComparator
from .core.focus import apply_ecu_focus
from .core.models import ComparisonResult
from .report.excel import default_report_path, write_excel_report


def compare_inputs(
    old_path: Path,
    new_path: Path,
    *,
    include_unchanged: bool = False,
    ecu_map: dict[str, str] | None = None,
    focus_nodes: Iterable[str] = (),
    pair_map: dict[str, str | None] | None = None,
    progress: Callable[[str], None] | None = None,
) -> ComparisonResult:
    """Compare two folders or two DBC files, then apply the optional ECU focus.

    ``pair_map`` fixes OLD to NEW file pairs for a folder comparison; without it
    pairing is automatic. Input, parse and ECU mapping errors propagate.
    """
    comparator = DbcComparator(include_unchanged=include_unchanged, ecu_map=ecu_map)
    old_path, new_path = Path(old_path), Path(new_path)
    if pair_map is None:
        result = comparator.compare_paths(old_path, new_path, progress_callback=progress)
    else:
        result = comparator.compare_manual(old_path, new_path, pair_map, progress_callback=progress)
    nodes = set(focus_nodes)
    return apply_ecu_focus(result, nodes) if nodes else result


def resolve_report_path(old_path: Path, new_path: Path, output_path: Path | None = None) -> Path:
    """Return the explicit ``.xlsx`` path or the automatic one beside NEW."""
    path = Path(output_path) if output_path else default_report_path(old_path, new_path)
    if path.suffix.lower() != ".xlsx":
        raise ValueError(f"Report path must end with .xlsx: {path}")
    return path


def run_comparison(
    old_path: Path,
    new_path: Path,
    output_path: Path | None = None,
    *,
    language: str = "en",
    progress: Callable[[str], None] | None = None,
    **options,
) -> tuple[ComparisonResult, Path]:
    """Compare and export one Excel report; ``options`` go to :func:`compare_inputs`."""
    report = resolve_report_path(old_path, new_path, output_path)
    result = compare_inputs(old_path, new_path, progress=progress, **options)
    write_excel_report(result, report, language=language)
    return result, report
