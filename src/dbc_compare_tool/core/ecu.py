from __future__ import annotations

from collections import Counter
from pathlib import Path

from dbc_compare_tool.core.discovery import collect_dbc_files
from dbc_compare_tool.core.models import DbcDatabase
from dbc_compare_tool.core.parser import UNDEFINED_NODE, DbcParseError, parse_dbc


def database_ecu_nodes(database: DbcDatabase) -> set[str]:
    """Include declared nodes and nodes referenced only by message/signal routing."""
    nodes = set(database.nodes)
    for message in database.messages.values():
        nodes.update(node.strip() for node in message.transmitter.split(","))
        for signal in message.signals.values():
            nodes.update(signal.receivers)
    return nodes - {"", UNDEFINED_NODE}


def validate_dbc_input(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")
    if not path.is_dir() and not (path.is_file() and path.suffix.lower() == ".dbc"):
        raise ValueError(f"Input must be a folder or a .dbc file: {path}")


def collect_ecu_nodes(path: Path) -> list[str]:
    """Discover selectable ECU nodes; skip invalid files in folder mode like comparison."""
    path = Path(path)
    validate_dbc_input(path)
    if path.is_file():
        return sorted(database_ecu_nodes(parse_dbc(path)))
    nodes: set[str] = set()
    for file_path in collect_dbc_files(path).values():
        try:
            nodes.update(database_ecu_nodes(parse_dbc(file_path)))
        except DbcParseError:
            continue
    return sorted(nodes)


def validate_ecu_map(
    ecu_map: dict[str, str], old_nodes: set[str] | None = None, new_nodes: set[str] | None = None,
) -> None:
    if any(not isinstance(node, str) or not node.strip() for pair in ecu_map.items() for node in pair):
        raise ValueError("ECU pairs must contain non-empty OLD and NEW node names")
    duplicates = sorted(node for node, count in Counter(ecu_map.values()).items() if count > 1)
    if duplicates:
        raise ValueError(f"NEW ECU nodes paired more than once: {', '.join(duplicates)}")
    if old_nodes is None or new_nodes is None:
        return
    missing_old = sorted(set(ecu_map) - old_nodes)
    missing_new = sorted(set(ecu_map.values()) - new_nodes)
    if missing_old or missing_new:
        details = []
        if missing_old:
            details.append(f"OLD: {', '.join(missing_old)}")
        if missing_new:
            details.append(f"NEW: {', '.join(missing_new)}")
        raise ValueError(f"Paired ECU nodes not found in selected inputs ({'; '.join(details)})")
    unchanged_old = old_nodes - set(ecu_map)
    collisions = sorted(set(ecu_map.values()) & unchanged_old)
    if collisions:
        raise ValueError(
            f"ECU pairs collide with unmapped OLD nodes: {', '.join(collisions)}. "
            "Pair those nodes to different NEW nodes as well."
        )


def transmitters_match(old: str, new: str, ecu_map: dict[str, str]) -> bool:
    if not ecu_map:
        return old == new
    old_nodes = tuple(sorted(ecu_map.get(node.strip(), node.strip()) for node in old.split(",")))
    new_nodes = tuple(sorted(node.strip() for node in new.split(",")))
    return old_nodes == new_nodes


def receivers_match(old: tuple[str, ...], new: tuple[str, ...], ecu_map: dict[str, str]) -> bool:
    if not ecu_map:
        return old == new
    return tuple(sorted(ecu_map.get(node, node) for node in old)) == tuple(sorted(new))
