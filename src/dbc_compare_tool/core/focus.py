from __future__ import annotations

from collections.abc import Iterable
from itertools import chain
from dataclasses import replace

from dbc_compare_tool.core.models import Change, ComparisonResult, Message, Signal


def apply_ecu_focus(result: ComparisonResult, nodes: Iterable[str]) -> ComparisonResult:
    """Project a complete comparison onto the selected OLD/NEW routes."""
    selected = set(nodes)
    if not selected:
        raise ValueError("Select at least one ECU node for focus")
    missing = selected - (result.old_nodes | result.new_nodes)
    if missing:
        raise ValueError(f"Focus ECU nodes not found in readable inputs: {', '.join(sorted(missing))}")
    # Expand only the pairs touched by the original selection. In particular,
    # selecting A with A->B and B->C does not also select C.
    pairs = tuple(sorted(
        (old, new) for old, new in result.ecu_map.items()
        if old != new and (old in selected or new in selected)
    ))
    old_nodes = (selected | {old for old, _ in pairs}) & result.old_nodes
    new_nodes = (selected | {new for _, new in pairs}) & result.new_nodes

    def touches(change: Change, *, signal: bool) -> bool:
        return _matches_route(change.old_message, change.old_signal, old_nodes, signal) or (
            _matches_route(change.new_message, change.new_signal, new_nodes, signal)
        )

    return restrict_focus_overview(replace(
        result,
        message_changes=[change for change in result.message_changes if touches(change, signal=False)],
        signal_changes=[change for change in result.signal_changes if touches(change, signal=True)],
        focus_nodes=tuple(sorted(selected)),
        focus_pairs=pairs,
    ))


def _matches_route(
    message: Message | None, signal: Signal | None, nodes: set[str], signal_row: bool,
) -> bool:
    if not nodes or message is None or (signal_row and signal is None):
        return False
    if any(sender.strip() in nodes for sender in message.transmitter.split(",")):
        return True
    if signal is not None:
        return not nodes.isdisjoint(signal.receivers)
    return any(not nodes.isdisjoint(item.receivers) for item in message.signals.values())


def restrict_focus_overview(result: ComparisonResult) -> ComparisonResult:
    """Keep the DBC pairs represented by the final detail rows."""
    if not result.focus_nodes:
        return result
    paths = set()
    labels = set()
    for change in chain(result.message_changes, result.signal_changes):
        if change.file_pair_paths is None:
            labels.add(change.dbc_file)
        else:
            paths.add(change.file_pair_paths)
    return replace(result, file_pairs=[
        pair for pair in result.file_pairs
        if (pair.old_path, pair.new_path) in paths or pair.dbc_file in labels
    ])
