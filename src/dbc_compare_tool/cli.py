from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.core.parser import DbcParseError
from dbc_compare_tool.report.excel import default_report_path, write_excel_report


def _path_from_parts(parts: list[str]) -> Path:
    return Path(" ".join(parts))


def main(argv: list[str] | None = None) -> int:
    # Windows consoles often use cp1252; replace unencodable characters
    # instead of crashing when file paths or DBC content contain them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Compare DBC baseline folders and generate an Excel report.")
    parser.add_argument("--old", required=True, nargs="+", metavar="PATH", help="Old baseline folder")
    parser.add_argument("--new", required=True, nargs="+", metavar="PATH", help="New baseline folder")
    parser.add_argument(
        "--out",
        nargs="+",
        metavar="PATH",
        help="Output .xlsx report path (default: beside NEW as compared_<folder>.xlsx)",
    )
    args = parser.parse_args(argv)

    old_folder = _path_from_parts(args.old)
    new_folder = _path_from_parts(args.new)
    output_path = _path_from_parts(args.out) if args.out else default_report_path(new_folder)

    if output_path.suffix.lower() != ".xlsx":
        print(f"Error: output path must end with .xlsx: {output_path}", file=sys.stderr)
        return 2

    try:
        result = DbcComparator().compare_folders(old_folder, new_folder, progress_callback=print)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except DbcParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

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
