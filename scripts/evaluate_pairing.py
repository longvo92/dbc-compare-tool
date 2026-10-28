"""Deterministic labeled synthetic corpus and fixed performance fixture.

Run with PYTHONPATH=src: python scripts/evaluate_pairing.py [--benchmark].
JSON goes to stdout; nonzero exit means a corpus acceptance condition failed.
No production accuracy claim follows from these generated fixtures.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from dbc_compare_tool.core.comparator import DbcComparator
from dbc_compare_tool.core.policy import name_similarity

CORPUS = Path(__file__).resolve().parents[1] / "tests/fixtures/pairing_corpus.json"


def create_case(root: Path, spec: dict):
    """Materialize DBCs and independent expected identities from a case schema."""
    expected = {"dbc": set(), "message": set(), "signal": set()}
    paths = (
        spec.get("old_path", "Powertrain_v1.dbc"),
        spec.get("new_path", "Powertrain_v2.dbc"),
    )
    names = {}
    for side in ("old", "new"):
        is_new = side == "new"
        prefix = spec.get(f"prefix_{side}", "Original")
        ecu = spec.get(f"ecu_{side}", "ECU")
        unrelated = is_new and spec.get("unrelated", False)
        if unrelated:
            ecu = "OTHER"
        text = f'VERSION ""\nBU_: {ecu}\n'
        records = []
        for m in range(spec["messages"]):
            frame = 100 + m + (spec.get("frame_shift", 0) if is_new else 0)
            name = f"{prefix}_Message_{m}"
            dlc = 4 if unrelated else 64
            text += f"BO_ {frame} {name}: {dlc} {ecu}\n"
            signals = []
            if spec.get("multiplexed"):
                mux_name = f"{prefix}_Mux" if spec.get("rename_mux") else "Mux"
                text += f' SG_ {mux_name} M : 0|8@1+ (1,0) [0|255] "" {ecu}\n'
                signals.append(mux_name)
            for s in range(spec["signals"]):
                sig = f"{prefix}_Signal_{s}"
                if spec.get("ambiguous"):
                    # Equal names' suffix similarity and identical properties create
                    # several equally plausible identities; only count is labeled.
                    sig = chr((65 if not is_new else 75) + s) * 4
                mux = f" m{s + 1}" if spec.get("multiplexed") else ""
                start = 8 if mux else 0 if spec.get("ambiguous") else 16 * s
                start += spec.get("shift", 0) if is_new else 0
                unit = "unit" if spec.get("ambiguous") else f"Unit{s}"
                if unrelated:
                    text += (
                        f' SG_ {sig} : {8 * s + 7}|3@0- (7,9) [9|30] "other" {ecu}\n'
                    )
                else:
                    text += (
                        f' SG_ {sig}{mux} : {start}|8@1+ (1,0) [0|255] "{unit}" {ecu}\n'
                    )
                signals.append(sig)
            records.append((frame, name, signals))
        target = root / side / paths[is_new]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        names[side] = records
    if spec.get("unrelated"):
        return expected
    expected["dbc"].add((paths[0], paths[1]))
    for old, new in zip(names["old"], names["new"]):
        expected["message"].add((paths[0], old[0], old[1], paths[1], new[0], new[1]))
        for a, b in zip(old[2], new[2]):
            expected["signal"].add(
                (paths[0], old[0], old[1], a, paths[1], new[0], new[1], b)
            )
    return expected


def pair_key(pair):
    a, b = pair.old, pair.new
    if a.kind == "dbc":
        return a.dbc_path, b.dbc_path
    if a.kind == "message":
        return (
            a.dbc_path,
            a.frame_id,
            a.message_name,
            b.dbc_path,
            b.frame_id,
            b.message_name,
        )
    return (
        a.dbc_path,
        a.frame_id,
        a.message_name,
        a.signal_name,
        b.dbc_path,
        b.frame_id,
        b.message_name,
        b.signal_name,
    )


def evaluate_case(root, spec):
    expected = create_case(root, spec)
    result = DbcComparator(ecu_map=spec.get("ecu_map")).compare_folders(
        root / "old", root / "new"
    )
    metrics = {}
    passed = result.completeness == "Complete"
    for kind, gold in expected.items():
        selected = {
            pair_key(p)
            for p in result.pairings
            if p.old and p.new and p.old.kind == kind
        }
        correct = len(selected & gold)
        ambiguous = spec.get("ambiguous") and kind == "signal"
        metrics[kind] = {
            "expected": len(gold),
            "selected": len(selected),
            "recall": None if ambiguous else correct / len(gold) if gold else 1.0,
            "precision": None
            if ambiguous
            else correct / len(selected)
            if selected
            else (1.0 if not gold else 0.0),
            "coverage": sum(
                n
                for group, values in result.coverage.items()
                if group.endswith(f" {kind}")
                for status, n in values.items()
                if status == "paired"
            )
            / sum(
                n
                for group, values in result.coverage.items()
                if group.endswith(f" {kind}")
                for n in values.values()
            ),
        }
        if ambiguous:
            passed = (
                passed
                and len(selected) == len(gold)
                and all(
                    p.requires_review
                    for p in result.pairings
                    if p.old and p.old.kind == kind
                )
            )
        else:
            passed = passed and selected == gold
    return {
        "name": spec["name"],
        "passed": passed,
        "metrics": metrics,
        "review_count": result.review_count,
        "diagnostics": len(result.diagnostics),
    }


def benchmark():
    """Measure the fixed fixture with a cold name-similarity cache."""
    spec = {
        "name": "fixed-32x12",
        "messages": 32,
        "signals": 12,
        "prefix_old": "VCU",
        "prefix_new": "IVC",
        "shift": 1,
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_case(root, spec)
        name_similarity.cache_clear()
        tracemalloc.start()
        start = time.perf_counter()
        result = DbcComparator().compare_folders(root / "old", root / "new")
        elapsed = time.perf_counter() - start
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        return {
            "fixture": spec["name"],
            "seconds": elapsed,
            "peak_bytes": peak,
            "message_changes": len(result.message_changes),
            "signal_changes": len(result.signal_changes),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        cases = [
            evaluate_case(Path(tmp) / spec["name"], spec)
            for spec in json.loads(CORPUS.read_text(encoding="utf-8"))
        ]
    output = {"policy": "recall-v1", "synthetic_only": True, "cases": cases}
    if args.benchmark:
        output["benchmark"] = benchmark()
    print(json.dumps(output, indent=2))
    return 0 if all(case["passed"] for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
