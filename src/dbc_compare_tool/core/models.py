from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def jaccard(left: set[tuple[Any, ...]], right: set[tuple[Any, ...]]) -> float:
    """Jaccard similarity of two sets. Two empty sets count as identical."""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True)
class Signal:
    name: str
    start_bit: int
    length: int
    byte_order: int
    value_type: str
    is_signed: bool
    factor: float
    offset: float
    minimum: float | None
    maximum: float | None
    unit: str
    receivers: tuple[str, ...]
    is_multiplexer: bool = False
    multiplexer_ids: tuple[int, ...] = ()
    multiplexer_signal: str | None = None
    value_descriptions: tuple[tuple[int, str], ...] = ()
    comment: str = ""

    def comparable_properties(self) -> dict[str, Any]:
        return {
            "Start Bit": self.start_bit,
            "Length": self.length,
            "Byte Order": self.byte_order,
            "Value Type": self.value_type,
            "Signed": self.is_signed,
            "Factor": self.factor,
            "Offset": self.offset,
            "Minimum": self.minimum,
            "Maximum": self.maximum,
            "Unit": self.unit,
            "Receivers": self.receivers,
            "Multiplexer": self.is_multiplexer,
            "Multiplexer IDs": self.multiplexer_ids,
            "Multiplexer Signal": self.multiplexer_signal,
            "Value Descriptions": self.value_descriptions,
            "Description": self.comment,
        }

    def layout_key(self) -> tuple[Any, ...]:
        return (self.start_bit, self.length, self.byte_order)

    def signal_key(self) -> tuple[Any, ...]:
        return (self.start_bit, self.length)


@dataclass
class Message:
    name: str
    can_id: int
    dlc: int
    transmitter: str
    is_extended_frame: bool = False
    signals: dict[str, Signal] = field(default_factory=dict)
    cycle_time_ms: int | None = None
    comment: str = ""

    def comparable_properties(self) -> dict[str, Any]:
        return {
            "CAN ID": self.can_id,
            "DLC": self.dlc,
            "Transmitter": self.transmitter,
            "Extended Frame": self.is_extended_frame,
            "Cycle Time": self.cycle_time_ms,
            "Signal Count": len(self.signals),
            "Description": self.comment,
        }

    def signal_layout(self) -> set[tuple[Any, ...]]:
        return {signal.layout_key() for signal in self.signals.values()}


@dataclass
class DbcDatabase:
    path: Path
    messages: dict[str, Message] = field(default_factory=dict)


@dataclass(frozen=True)
class FilePair:
    relative_path: str
    old_path: Path | None
    new_path: Path | None


@dataclass(frozen=True)
class FilePairSummary:
    dbc_file: str
    status: str  # "Matched" | "DBC Added" | "DBC Removed" | "DBC Renamed"
    old_path: str
    new_path: str
    pairing_confidence: float | None
    message_count_old: int
    message_count_new: int
    signal_count_old: int
    signal_count_new: int
    pairing_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Change:
    dbc_file: str
    change_type: str
    old_name: str
    new_name: str
    confidence: float | None
    description: str
    can_id: int | None = None
    parent_message: str = ""
    confidence_level: str = ""  # "High", "Medium", "Low", or ""
    property_diffs: tuple[tuple[str, str, str], ...] = ()  # (property_name, old_value, new_value)
    # Matched parent context can exist on both sides even for an added/removed signal.
    old_message: Message | None = None
    new_message: Message | None = None
    old_signal: Signal | None = None
    new_signal: Signal | None = None


@dataclass
class ComparisonResult:
    message_changes: list[Change] = field(default_factory=list)
    signal_changes: list[Change] = field(default_factory=list)
    file_pairs: list[FilePairSummary] = field(default_factory=list)
    include_unchanged: bool = False

    def summary(self) -> dict[str, int]:
        metrics = {
            "Messages Added": 0,
            "Messages Removed": 0,
            "Messages Modified": 0,
            "Messages Renamed": 0,
            "Signals Added": 0,
            "Signals Removed": 0,
            "Signals Modified": 0,
            "Signals Renamed": 0,
        }
        for change in self.message_changes:
            key = f"Messages {change.change_type}"
            metrics[key] = metrics.get(key, 0) + 1
        for change in self.signal_changes:
            key = f"Signals {change.change_type}"
            metrics[key] = metrics.get(key, 0) + 1
        metrics["Total Changes"] = sum(
            count for key, count in metrics.items() if not key.endswith(" Unchanged")
        )
        if self.include_unchanged:
            metrics.setdefault("Messages Unchanged", 0)
            metrics.setdefault("Signals Unchanged", 0)
        return metrics
