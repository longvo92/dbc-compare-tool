"""Versioned evidence policy. Eligibility and ranking are deliberately separate."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbc_compare_tool.core.models import DbcDatabase, Message, Signal


@dataclass(frozen=True)
class MatchingPolicy:
    version: str = "recall-v1"
    overlap_minimum: float = 0.50
    name_minimum: float = 0.45
    shift_limit: int = 8
    position_decay: int = 16
    score_scale: int = 1_000_000
    close_margin: float = 0.05
    ambiguous_cap: float = 0.89
    heuristic_cap: float = 0.99
    ambiguity_penalty: float = 0.20
    high_confidence: float = 0.90
    medium_confidence: float = 0.70
    confidence_decimals: int = 2
    dbc_weights: tuple[float, ...] = (20, 20, 20, 20, 20)
    message_weights: tuple[float, ...] = (10, 20, 25, 30, 5, 5, 5)
    signal_weights: tuple[float, ...] = (25, 25, 15, 15, 5, 5, 10)

    def confidence_level(self, confidence: float | None) -> str:
        if confidence is None:
            return ""
        if confidence >= self.high_confidence:
            return "High"
        return "Medium" if confidence >= self.medium_confidence else "Low"


RECALL_V1 = MatchingPolicy()


@dataclass(frozen=True)
class Evidence:
    similarity: float
    reasons: tuple[str, ...]
    complete: bool = False


@lru_cache(maxsize=65_536)
def name_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None, left.casefold(), right.casefold(), autojunk=False
    ).ratio()


def overlap(left, right) -> float | None:
    """Containment overlap, preserving multiplicity for Counter inputs."""
    if not left or not right:
        return None
    if isinstance(left, Counter):
        return sum((left & right).values()) / min(
            sum(left.values()), sum(right.values())
        )
    return len(set(left) & set(right)) / min(len(set(left)), len(set(right)))


def scalar(left, right) -> float | None:
    if left is None or right is None or left == "" or right == "":
        return None
    return float(left == right)


def average(values) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None


def weighted(values, weights) -> float:
    available = [(v, w) for v, w in zip(values, weights) if v is not None]
    return (
        sum(v * w for v, w in available) / sum(w for _, w in available)
        if available
        else 0.0
    )


def nodes(values, ecu_map=None) -> set[str]:
    if isinstance(values, str):
        values = (node.strip() for node in values.split(","))
    return {
        (ecu_map or {}).get(node, node)
        for node in values
        if node and node != "Vector__XXX"
    }


def layout(signal: Signal) -> tuple:
    return (
        *signal.layout_key(),
        signal.is_multiplexer,
        signal.multiplexer_ids,
        bool(signal.multiplexer_signal),
    )


def properties(signal: Signal, ecu_map=None, *, position: bool = True) -> tuple:
    props = signal.comparable_properties()
    props["Receivers"] = tuple(sorted(nodes(signal.receivers, ecu_map)))
    if not position:
        props.pop("Start Bit")
    return tuple(props.items())


@dataclass(frozen=True)
class SignalProfile:
    layout: tuple
    encoding: tuple
    scaling: tuple
    receivers: frozenset
    properties: tuple
    nonposition: tuple


def signal_profile(signal: Signal, ecu_map=None) -> SignalProfile:
    props = properties(signal, ecu_map)
    return SignalProfile(
        layout(signal),
        (signal.length, signal.byte_order, signal.value_type, signal.is_signed),
        (signal.factor, signal.offset, signal.minimum, signal.maximum),
        frozenset(nodes(signal.receivers, ecu_map)),
        props,
        tuple(p for p in props if p[0] != "Start Bit"),
    )


def signal_evidence(
    old: Signal,
    new: Signal,
    ecu_map,
    policy: MatchingPolicy,
    old_profile=None,
    new_profile=None,
) -> Evidence | None:
    a, b = (
        old_profile or signal_profile(old, ecu_map),
        new_profile or signal_profile(new),
    )
    name = name_similarity(old.name, new.name)
    reasons = []
    if old.name == new.name:
        reasons.append("Signal name matched")
    if a.layout == b.layout:
        reasons.append("Signal layout matched")
    if a.nonposition == b.nonposition:
        reasons.append("All non-name/non-position properties matched")
    if name >= policy.name_minimum and (old.length, old.byte_order) == (
        new.length,
        new.byte_order,
    ):
        reasons.append("Similar name with equal length and byte order")
    if (
        abs(old.start_bit - new.start_bit) <= policy.shift_limit
        and a.encoding == b.encoding
        and a.scaling == b.scaling
        and old.unit == new.unit
    ):
        reasons.append("Nearby position with unchanged encoding, scaling and unit")
    if not reasons:
        return None
    position = 1 / (1 + abs(old.start_bit - new.start_bit) / policy.position_decay)
    score = weighted(
        (
            name,
            average(
                (
                    position,
                    scalar(old.length, new.length),
                    scalar(old.byte_order, new.byte_order),
                )
            ),
            average(scalar(x, y) for x, y in zip(a.encoding, b.encoding)),
            average(scalar(x, y) for x, y in zip(a.scaling, b.scaling)),
            scalar(old.unit, new.unit),
            overlap(a.receivers, b.receivers),
            average(
                (
                    scalar(old.is_multiplexer, new.is_multiplexer),
                    scalar(bool(old.multiplexer_signal), bool(new.multiplexer_signal)),
                    overlap(set(old.multiplexer_ids), set(new.multiplexer_ids)),
                    scalar(old.multiplexer_signal, new.multiplexer_signal),
                )
            ),
        ),
        policy.signal_weights,
    )
    return Evidence(score, tuple(reasons), a.properties == b.properties)


@dataclass(frozen=True)
class MessageProfile:
    names: frozenset
    layouts: Counter
    structure: tuple


def message_profile(message: Message, ecu_map=None) -> MessageProfile:
    signals = list(message.signals.values())
    # Names, CAN ID and cycle time are excluded; multiplex multiplicity survives.
    structure = (
        message.dlc,
        tuple(
            sorted(
                Counter(
                    (
                        layout(s),
                        s.value_type,
                        s.is_signed,
                        s.factor,
                        s.offset,
                        s.unit,
                        tuple(sorted(nodes(s.receivers, ecu_map))),
                    )
                    for s in signals
                ).items()
            )
        ),
    )
    return MessageProfile(
        frozenset(message.signals), Counter(layout(s) for s in signals), structure
    )


def message_evidence(
    old: Message,
    new: Message,
    ecu_map,
    policy: MatchingPolicy,
    old_profile=None,
    new_profile=None,
) -> Evidence | None:
    a, b = (
        old_profile or message_profile(old, ecu_map),
        new_profile or message_profile(new),
    )
    frame = (old.can_id, old.is_extended_frame) == (new.can_id, new.is_extended_frame)
    name = name_similarity(old.name, new.name)
    names, layouts = overlap(a.names, b.names), overlap(a.layouts, b.layouts)
    tx = overlap(nodes(old.transmitter, ecu_map), nodes(new.transmitter))
    reasons = []
    if frame:
        reasons.append("Frame key matched")
    if old.name == new.name:
        reasons.append("Message name matched")
    if names is not None and names >= policy.overlap_minimum:
        reasons.append(f"Signal name overlap {names:.0%}")
    if layouts is not None and layouts >= policy.overlap_minimum:
        reasons.append(f"Signal layout overlap {layouts:.0%}")
    if name >= policy.name_minimum and (old.dlc == new.dlc or tx == 1):
        reasons.append("Similar name with equal DLC or transmitter")
    if not reasons:
        return None
    values = (
        float(frame),
        name,
        names,
        layouts,
        scalar(old.dlc, new.dlc),
        tx,
        scalar(old.cycle_time_ms, new.cycle_time_ms),
    )
    old_props, new_props = old.comparable_properties(), new.comparable_properties()
    old_props["Transmitter"] = tuple(sorted(nodes(old.transmitter, ecu_map)))
    new_props["Transmitter"] = tuple(sorted(nodes(new.transmitter)))
    complete = (
        old_props == new_props
        and a == b
        and all(
            properties(old.signals[n], ecu_map) == properties(new.signals[n])
            for n in a.names & b.names
        )
    )
    return Evidence(weighted(values, policy.message_weights), tuple(reasons), complete)


_GENERIC_WORDS = frozenset(
    {
        "dbc",
        "old",
        "new",
        "baseline",
        "release",
        "version",
        "rev",
        "revision",
        "final",
        "draft",
        "copy",
        "database",
        "db",
        "network",
        "can",
        "bus",
        "v",
        "ver",
        "r",
    }
)


def keywords(path: str) -> dict[str, float]:
    """Fixed path weights: adding unrelated files cannot change an old score."""
    result: dict[str, float] = {}
    parts = PurePosixPath(path.replace("\\", "/")).with_suffix("").parts
    for index, part in enumerate(parts):
        part = re.sub(
            r"(?:[_\s-]+|(?<=[a-zA-Z]))(?:v|ver|rev)\d+(?:[._]\d+)*$",
            "",
            part,
            flags=re.I,
        )
        part = re.sub(r"([a-z])([A-Z])", r"\1_\2", part)
        part = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", part).lower()
        part = re.sub(r"(?<![a-z0-9])(can|bus)[_\s-]+(\d+)(?![a-z0-9])", r"\1\2", part)
        for token in re.findall(r"[a-z]+\d*", part):
            if not token.startswith(("can", "bus")):
                token = re.sub(r"(?:19|20)\d{2}(?:\d{4})?$", "", token)
            if (
                not token
                or token in _GENERIC_WORDS
                or re.fullmatch(r"(?:v|ver|rev|r)\d+", token)
            ):
                continue
            result[token] = max(
                result.get(token, 0), 1.0 if index == len(parts) - 1 else 0.35
            )
    return result


@dataclass(frozen=True)
class DatabaseProfile:
    path: str
    keywords: dict
    frames: frozenset
    names: frozenset
    signals: frozenset
    structures: Counter


def database_profile(path: str, db: DbcDatabase, ecu_map=None) -> DatabaseProfile:
    return DatabaseProfile(
        path,
        keywords(path),
        frozenset((m.can_id, m.is_extended_frame) for m in db.messages.values()),
        frozenset(db.messages),
        frozenset(s for m in db.messages.values() for s in m.signals),
        Counter(
            message_profile(m, ecu_map).structure
            for m in db.messages.values()
            if m.signals
        ),
    )


def database_evidence(
    a: DatabaseProfile, b: DatabaseProfile, policy: MatchingPolicy
) -> Evidence | None:
    shared = a.keywords.keys() & b.keywords.keys()
    word_score = None
    if a.keywords and b.keywords:
        word_score = sum(
            min(a.keywords[w], b.keywords[w]) for w in sorted(shared)
        ) / min(sum(a.keywords.values()), sum(b.keywords.values()))
    values = [
        overlap(x, y)
        for x, y in (
            (a.frames, b.frames),
            (a.names, b.names),
            (a.signals, b.signals),
            (a.structures, b.structures),
        )
    ]
    reasons = []
    if a.path == b.path:
        reasons.append("Relative path matched")
    if shared:
        reasons.append("Shared DBC keywords: " + ", ".join(sorted(shared)))
    for label, value in zip(
        ("Frame key", "Message name", "Signal name", "Message structure"), values
    ):
        if value is not None and value >= policy.overlap_minimum:
            reasons.append(f"{label} overlap {value:.0%}")
    if not reasons:
        return None
    path = 1.0 if a.path == b.path else word_score
    return Evidence(weighted((path, *values), policy.dbc_weights), tuple(reasons))
