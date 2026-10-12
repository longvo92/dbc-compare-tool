from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.core.parser import DbcParseError
from dbc_compare_tool.report.excel import default_report_path, write_excel_report


def _path_from_parts(parts: list[str]) -> Path:
    return Path(" ".join(parts))


def _parse_ecu_pairs(pairs: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for pair in pairs:
        if pair.count("=") != 1:
            raise ValueError(f"Invalid ECU pair {pair!r}; use OLD_NODE=NEW_NODE")
        old, new = (node.strip() for node in pair.split("=", 1))
        if not old or not new:
            raise ValueError(f"Invalid ECU pair {pair!r}; use OLD_NODE=NEW_NODE")
        if old in mapping:
            raise ValueError(f"OLD ECU node paired more than once: {old}")
        mapping[old] = new
    return mapping


def main(argv: list[str] | None = None) -> int:
    # Windows consoles often use cp1252; replace unencodable characters
    # instead of crashing when file paths or DBC content contain them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Compare two DBC folders or two DBC files and generate an Excel report.")
    parser.add_argument("--old", required=True, nargs="+", metavar="PATH", help="Old baseline folder or .dbc file")
    parser.add_argument("--new", required=True, nargs="+", metavar="PATH", help="New baseline folder or .dbc file")
    parser.add_argument(
        "--ecu-pair", action="append", default=[], metavar="OLD=NEW",
        help="Treat an OLD ECU node as the paired NEW node (repeat for multiple pairs)",
    )
    parser.add_argument(
        "--include-unchanged",
        action="store_true",
        help="Include unchanged messages and signals in the report",
    )
    parser.add_argument(
        "--out",
        nargs="+",
        metavar="PATH",
        help="Output .xlsx report path (default: beside NEW as compared_<name>.xlsx)",
    )
    args = parser.parse_args(argv)

    old_path = _path_from_parts(args.old)
    new_path = _path_from_parts(args.new)
    output_path = _path_from_parts(args.out) if args.out else default_report_path(new_path)

    if output_path.suffix.lower() != ".xlsx":
        print(f"Error: output path must end with .xlsx: {output_path}", file=sys.stderr)
        return 2

    try:
        ecu_map = _parse_ecu_pairs(args.ecu_pair)
        result = DbcComparator(include_unchanged=args.include_unchanged, ecu_map=ecu_map).compare_paths(
            old_path, new_path, progress_callback=print
        )
    except DbcParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        write_excel_report(result, output_path)
    except OSError as exc:
        print(f"Error: unable to write report {output_path}: {exc}", file=sys.stderr)
        return 1

    parse_errors = [fp for fp in result.file_pairs if fp.status == "Parse Error"]
    for fp in parse_errors:
        print(f"Warning: skipped unparsable DBC: {fp.dbc_file}", file=sys.stderr)

    print(f"Report written: {output_path}")
    print(f"Total changes: {result.summary()['Total Changes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
