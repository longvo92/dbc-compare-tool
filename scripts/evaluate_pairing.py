"""End-to-end DBC comparison benchmark for the classic matching engine."""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.report.excel import write_excel_report


def _dbc(messages: int, changed: bool) -> str:
    lines = ['VERSION ""', 'BU_: ECU']
    for index in range(messages):
        lines.append(f'BO_ {100 + index} VehicleStatus_{index:04d}: 8 ECU')
        for signal in range(8):
            factor = 2 if changed and index == messages - 1 and signal == 7 else 1
            lines.append(
                f' SG_ Value_{index:04d}_{signal} : {signal * 8}|8@1+ '
                f'({factor},0) [0|255] "" ECU'
            )
    return "\n".join(lines) + "\n"


def benchmark(sizes=(32, 128, 256, 1024), repeats=3):
    measured = []
    with tempfile.TemporaryDirectory(prefix="dbc-benchmark-") as temporary:
        root = Path(temporary)
        for size in sizes:
            old, new = root / "old.dbc", root / "new.dbc"
            old.write_text(_dbc(size, False), encoding="utf-8")
            for changed in (False, True):
                new.write_text(_dbc(size, changed), encoding="utf-8")
                for include_unchanged in (False, True):
                    runs = []
                    for _ in range(repeats):
                        start = time.perf_counter()
                        result = DbcComparator(include_unchanged=include_unchanged).compare_files(old, new)
                        compared = time.perf_counter()
                        write_excel_report(result, root / "report.xlsx")
                        exported = time.perf_counter()
                        runs.append((compared - start, exported - compared))
                    measured.append({
                        "messages_per_file": size,
                        "signals_per_message": 8,
                        "changed": changed,
                        "include_unchanged": include_unchanged,
                        "compare_seconds_median": round(statistics.median(run[0] for run in runs), 3),
                        "export_seconds_median": round(statistics.median(run[1] for run in runs), 3),
                        "total_seconds_median": round(statistics.median(sum(run) for run in runs), 3),
                    })
    return measured


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true", help="Run the synthetic benchmark")
    parser.add_argument("--sizes", type=int, nargs="+", default=[32, 128, 256, 1024])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not args.benchmark or args.repeats < 1 or any(size < 1 for size in args.sizes):
        parser.error("Use --benchmark with positive sizes and repeats")
    print(json.dumps({"engine": "classic-v067", "results": benchmark(args.sizes, args.repeats)}, indent=2))


if __name__ == "__main__":
    main()
