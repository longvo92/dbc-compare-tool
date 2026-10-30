from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Generic, Iterable, Protocol, TypeVar

from dbc_compare_tool.core.ecu import receivers_match, transmitters_match
from dbc_compare_tool.core.models import Message, Signal, jaccard
from dbc_compare_tool.core.pairing import _maximum_assignment


T = TypeVar("T")


@dataclass(frozen=True)
class RenameMatch(Generic[T]):
    old: T
    new: T
    confidence: float
    confidence_level: str  # "High", "Medium", or "Low"
    reasons: tuple[str, ...]


class RenameDetector(Protocol[T]):
    threshold: float

    def score(self, old: T, new: T) -> tuple[float, tuple[str, ...]]:
        ...

    def match(self, old_items: Iterable[T], new_items: Iterable[T]) -> list[RenameMatch[T]]:
        ...

    def get_confidence_level(self, confidence: float) -> str:
        ...


class GreedyRenameDetector(Generic[T]):
    threshold = 0.8
    high_confidence_threshold = 0.90
    medium_confidence_threshold = 0.70

    def score(self, old: T, new: T) -> tuple[float, tuple[str, ...]]:
        raise NotImplementedError

    def get_confidence_level(self, confidence: float) -> str:
        """Categorize confidence as High, Medium, or Low."""
        if confidence >= self.high_confidence_threshold:
            return "High"
        if confidence >= self.medium_confidence_threshold:
            return "Medium"
        return "Low"

    def match(self, old_items: Iterable[T], new_items: Iterable[T]) -> list[RenameMatch[T]]:
        candidates: list[RenameMatch[T]] = []
        old_list = list(old_items)
        new_list = list(new_items)

        for old in old_list:
            for new in new_list:
                confidence, reasons = self.score(old, new)
                if confidence >= self.threshold:
                    confidence_level = self.get_confidence_level(confidence)
                    candidates.append(RenameMatch(old=old, new=new, confidence=confidence, confidence_level=confidence_level, reasons=reasons))

        candidates = self._adjust_for_ambiguity(candidates)
        candidates = [candidate for candidate in candidates if candidate.confidence >= self.threshold]

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        matches: list[RenameMatch[T]] = []
        used_old: set[int] = set()
        used_new: set[int] = set()
        for candidate in candidates:
            old_id = id(candidate.old)
            new_id = id(candidate.new)
            if old_id in used_old or new_id in used_new:
                continue
            matches.append(candidate)
            used_old.add(old_id)
            used_new.add(new_id)
        return matches

    def _adjust_for_ambiguity(self, candidates: list[RenameMatch[T]]) -> list[RenameMatch[T]]:
        """Reduce confidence for ambiguous matches where one item has rival matches.

        Ambiguity is symmetric: several old items competing for one new item is
        just as uncertain as several new items competing for one old item, so
        both directions are counted.
        """
        new_match_counts: dict[int, int] = {}
        old_match_counts: dict[int, int] = {}
        for candidate in candidates:
            new_match_counts[id(candidate.new)] = new_match_counts.get(id(candidate.new), 0) + 1
            old_match_counts[id(candidate.old)] = old_match_counts.get(id(candidate.old), 0) + 1

        adjusted_candidates: list[RenameMatch[T]] = []
        for candidate in candidates:
            rivals = max(new_match_counts[id(candidate.new)], old_match_counts[id(candidate.old)])
            if rivals > 1:
                confidence_reduction = 0.15 * (rivals - 1)
                reduced_confidence = max(self.medium_confidence_threshold, candidate.confidence - confidence_reduction)
                # Never report a score above the unadjusted one: for detectors
                # whose threshold sits below the Medium floor (event-like
                # signals at 0.65), the floor alone could otherwise raise it.
                reduced_confidence = min(reduced_confidence, candidate.confidence)
                new_reasons = list(candidate.reasons) + [f"Ambiguous: {rivals} rival matches for this item"]
                adjusted_candidates.append(RenameMatch(
                    old=candidate.old,
                    new=candidate.new,
                    confidence=reduced_confidence,
                    confidence_level=self.get_confidence_level(reduced_confidence),
                    reasons=tuple(new_reasons),
                ))
            else:
                adjusted_candidates.append(candidate)

        return adjusted_candidates


class EventMessageDetector:
    """Detects if a message appears to be an Event Matrix message with many repetitive signals."""

    SHORT_SIGNAL_THRESHOLD = 4  # bits
    EVENT_SIGNAL_PERCENTAGE = 0.7  # 70% of signals must be short
    PROPERTY_REPETITION_THRESHOLD = 0.6  # 60% of signals must share properties

    @classmethod
    def is_event_like(cls, message: Message) -> bool:
        """Check if a message appears to be an Event Matrix message."""
        if len(message.signals) < 5:
            return False

        short_signal_count = sum(1 for signal in message.signals.values() if signal.length <= cls.SHORT_SIGNAL_THRESHOLD)
        if short_signal_count / len(message.signals) < cls.EVENT_SIGNAL_PERCENTAGE:
            return False

        return cls._has_highly_repetitive_properties(message)

    @classmethod
    def _has_highly_repetitive_properties(cls, message: Message) -> bool:
        """Check if many signals share the same technical properties."""
        if len(message.signals) < 3:
            return False

        signals = list(message.signals.values())

        # Create property signatures for each signal
        signatures: dict[tuple, int] = {}
        for signal in signals:
            sig = (signal.length, signal.byte_order, signal.factor, signal.offset, signal.unit)
            signatures[sig] = signatures.get(sig, 0) + 1

        # If one signature appears in 60%+ of signals, it's repetitive
        max_count = max(signatures.values())
        return max_count / len(signals) >= cls.PROPERTY_REPETITION_THRESHOLD

    @classmethod
    def get_warning(cls) -> str:
        """Return a warning message for Event Matrix messages."""
        return (
            "Rename detection confidence is reduced because this message appears to be "
            "an Event Matrix message with many structurally identical signals."
        )


class MessageRenameDetector(GreedyRenameDetector[Message]):
    threshold = 0.60

    def __init__(self, ecu_map: dict[str, str] | None = None) -> None:
        self.ecu_map = dict(ecu_map or {})

    def score(self, old: Message, new: Message) -> tuple[float, tuple[str, ...]]:
        score = 0.0
        reasons: list[str] = []
        if old.can_id == new.can_id:
            score += 0.35
            reasons.append("CAN ID matched")
        if old.dlc == new.dlc:
            score += 0.12
            reasons.append("DLC matched")
        if transmitters_match(old.transmitter, new.transmitter, self.ecu_map):
            score += 0.08
            reasons.append("Transmitter matched")
        if old.cycle_time_ms is not None and old.cycle_time_ms == new.cycle_time_ms:
            score += 0.08
            reasons.append("Cycle time matched")
        if len(old.signals) == len(new.signals):
            score += 0.10
            reasons.append("Signal count matched")

        layout_score = jaccard(old.signal_layout(), new.signal_layout())
        if layout_score:
            score += 0.22 * layout_score
            reasons.append(f"Signal layout {layout_score:.0%} matched")

        name_score = _name_similarity(old.name, new.name)
        score += 0.05 * name_score
        if name_score >= 0.5:
            reasons.append("Names are similar")

        return min(score, 1.0), tuple(reasons)


class SignalRenameDetector(GreedyRenameDetector[Signal]):
    threshold = 0.65
    event_threshold = 0.55
    heuristic_confidence_cap = 0.89

    def __init__(self, is_event_like: bool = False, ecu_map: dict[str, str] | None = None) -> None:
        """Initialize the detector for a normal or event-like message.

        Args:
            is_event_like: Whether the parent message is event-like, which changes scoring.
        """
        self.is_event_like = is_event_like
        self.ecu_map = dict(ecu_map or {})
        if is_event_like:
            self.threshold = self.event_threshold

    def _property_key(self, signal: Signal, *, old: bool) -> tuple:
        properties = signal.comparable_properties()
        if self.ecu_map:
            properties["Receivers"] = tuple(sorted(
                self.ecu_map.get(node, node) if old else node
                for node in signal.receivers
            ))
        return tuple(properties.items())

    def match(self, old_items: Iterable[Signal], new_items: Iterable[Signal]) -> list[RenameMatch[Signal]]:
        """Reserve unique pure renames before scoring the remaining candidates.

        Repeated scaling or overlapping multiplexed layouts must not penalize a
        pair whose complete properties identify it uniquely on both sides.
        Remaining signals favor pairing coverage; ambiguity lowers reported
        confidence without removing an otherwise eligible pair.
        """
        old_list, new_list = list(old_items), list(new_items)
        old_groups: dict[tuple, list[Signal]] = defaultdict(list)
        new_groups: dict[tuple, list[Signal]] = defaultdict(list)
        for signal in old_list:
            old_groups[self._property_key(signal, old=True)].append(signal)
        for signal in new_list:
            new_groups[self._property_key(signal, old=False)].append(signal)

        # Index nearby alternatives with equal non-position properties. A batch
        # shift can put a renamed signal exactly on its neighbor's old layout.
        old_positions: dict[tuple, list[Signal]] = defaultdict(list)
        new_positions: dict[tuple, list[Signal]] = defaultdict(list)
        for key, group in old_groups.items():
            properties = tuple(item for item in key if item[0] != "Start Bit")
            old_positions[properties, group[0].start_bit].extend(group)
        for key, group in new_groups.items():
            properties = tuple(item for item in key if item[0] != "Start Bit")
            new_positions[properties, group[0].start_bit].extend(group)

        def better_shifted_pair(old: Signal, new: Signal, key: tuple) -> bool:
            score, _ = self.score(old, new)
            properties = tuple(item for item in key if item[0] != "Start Bit")
            for shift in range(-8, 9):
                if not shift:
                    continue
                for other in new_positions.get((properties, old.start_bit + shift), ()):
                    other_score = self.score(old, other)[0]
                    if other_score >= self.threshold and other_score > score:
                        return True
                for other in old_positions.get((properties, new.start_bit + shift), ()):
                    other_score = self.score(other, new)[0]
                    if other_score >= self.threshold and other_score > score:
                        return True
            return False

        exact_matches = []
        for key, old_group in old_groups.items():
            new_group = new_groups.get(key, [])
            if len(old_group) == len(new_group) == 1 and not better_shifted_pair(old_group[0], new_group[0], key):
                exact_matches.append(RenameMatch(
                    old_group[0], new_group[0], 1.0, "High",
                    ("All signal properties matched uniquely (after ECU mapping)"
                     if self.ecu_map else "All signal properties matched uniquely",),
                ))
        used_old = {id(match.old) for match in exact_matches}
        used_new = {id(match.new) for match in exact_matches}
        return exact_matches + self._match_candidates(
            [signal for signal in old_list if id(signal) not in used_old],
            [signal for signal in new_list if id(signal) not in used_new],
        )

    def _match_candidates(self, old_list: list[Signal], new_list: list[Signal]) -> list[RenameMatch[Signal]]:
        if not old_list or not new_list:
            return []
        old_list = sorted(old_list, key=lambda signal: signal.name)
        new_list = sorted(new_list, key=lambda signal: signal.name)
        old_keys = [self._property_key(signal, old=True) for signal in old_list]
        new_keys = [self._property_key(signal, old=False) for signal in new_list]
        candidates: dict[tuple[int, int], tuple[float, tuple[str, ...]]] = {}
        old_scores: dict[int, list[tuple[int, float]]] = defaultdict(list)
        new_scores: dict[int, list[tuple[int, float]]] = defaultdict(list)
        for old_index, old in enumerate(old_list):
            for new_index, new in enumerate(new_list):
                score, reasons = self.score(old, new)
                same_properties = old_keys[old_index] == new_keys[new_index]
                if score >= self.threshold or same_properties:
                    if same_properties:
                        reasons += ("All signal properties matched; identity requires review",)
                    candidates[old_index, new_index] = score, reasons
                    old_scores[old_index].append((new_index, score))
                    new_scores[new_index].append((old_index, score))

        # A whole extra pair outweighs every possible similarity improvement.
        # Transpose to keep the smaller inventory on the Hungarian row axis.
        transpose = len(old_list) > len(new_list)
        rows, columns = (len(new_list), len(old_list)) if transpose else (len(old_list), len(new_list))
        pair_bonus = rows + 1.0
        weights = [[0.0] * (columns + rows) for _ in range(rows)]
        for (old_index, new_index), (score, _) in candidates.items():
            row, column = (new_index, old_index) if transpose else (old_index, new_index)
            weights[row][column] = pair_bonus + score

        matches = []
        for row, column in enumerate(_maximum_assignment(weights)):
            if column >= columns:
                continue
            key = (column, row) if transpose else (row, column)
            if key not in candidates:
                continue
            old_index, new_index = key
            score, reasons = candidates[key]
            confidence = score * self.heuristic_confidence_cap
            rivals = [value for index, value in old_scores[old_index] if index != new_index]
            rivals.extend(value for index, value in new_scores[new_index] if index != old_index)
            if rivals:
                margin = score - max(rivals)
                penalty = min(0.35, max(0.0, 0.20 - margin))
                confidence = max(0.0, confidence - penalty)
                reasons += (f"Ambiguous: {len(rivals)} competing pair(s), score margin {margin:.2f}",)
            reasons += ("Heuristic signal pairing; review recommended",)
            # Match the level to the score users see in the Excel report.
            confidence = round(confidence, 2)
            matches.append(RenameMatch(
                old_list[old_index], new_list[new_index], confidence,
                self.get_confidence_level(confidence), reasons,
            ))
        return matches

    @staticmethod
    def _start_bit_similarity(old: Signal, new: Signal) -> float:
        distance = abs(old.start_bit - new.start_bit)
        return 1.0 - distance / 16.0 if distance <= 8 else 0.0

    def score(self, old: Signal, new: Signal) -> tuple[float, tuple[str, ...]]:
        if self.is_event_like:
            return self._score_for_event_message(old, new)
        return self._score_for_normal_message(old, new)

    def _score_for_normal_message(self, old: Signal, new: Signal) -> tuple[float, tuple[str, ...]]:
        """Standard scoring for signals in non-event messages."""
        score = 0.0
        reasons: list[str] = []
        weighted_checks = [
            (old.start_bit == new.start_bit, 0.15, "Start bit matched"),
            (old.length == new.length, 0.15, "Length matched"),
            (old.byte_order == new.byte_order, 0.08, "Byte order matched"),
            (old.is_signed == new.is_signed, 0.04, "Signedness matched"),
            (old.factor == new.factor, 0.09, "Factor matched"),
            (old.offset == new.offset, 0.09, "Offset matched"),
            (old.unit == new.unit, 0.07, "Unit matched"),
            (receivers_match(old.receivers, new.receivers, self.ecu_map), 0.08, "Receivers matched"),
        ]
        for matched, weight, reason in weighted_checks:
            if matched:
                score += weight
                reasons.append(reason)

        name_score = _name_similarity(old.name, new.name)
        score += 0.25 * name_score
        if name_score >= 0.5:
            reasons.append("Names are similar")
        if old.start_bit != new.start_bit:
            score += 0.15 * self._start_bit_similarity(old, new)
            reasons.append(f"Start bit shifted by {abs(old.start_bit - new.start_bit)} bit(s)")
        return min(score, 1.0), tuple(reasons)

    def _score_for_event_message(self, old: Signal, new: Signal) -> tuple[float, tuple[str, ...]]:
        """
        Name-led scoring for signals in Event Matrix messages.
        De-emphasizes common technical properties, emphasizes name similarity.
        """
        score = 0.0
        reasons: list[str] = []

        # Technical properties are weighted much less for event messages
        # since many event signals share identical properties
        weighted_checks = [
            (old.start_bit == new.start_bit, 0.06, "Start bit matched"),
            (old.length == new.length, 0.06, "Length matched"),
            (old.byte_order == new.byte_order, 0.05, "Byte order matched"),
            (old.is_signed == new.is_signed, 0.03, "Signedness matched"),
            (old.factor == new.factor, 0.04, "Factor matched"),
            (old.offset == new.offset, 0.04, "Offset matched"),
            (old.unit == new.unit, 0.04, "Unit matched"),
            (receivers_match(old.receivers, new.receivers, self.ecu_map), 0.06, "Receivers matched"),
        ]
        for matched, weight, reason in weighted_checks:
            if matched:
                score += weight
                reasons.append(reason)

        # Name similarity is much more important for event messages
        name_score = _name_similarity(old.name, new.name)
        score += 0.50 * name_score
        if name_score >= 0.6:
            reasons.append("Names are similar")
        elif name_score >= 0.3:
            reasons.append("Names have some similarity")
        if old.start_bit != new.start_bit:
            score += 0.06 * self._start_bit_similarity(old, new)
            reasons.append(f"Start bit shifted by {abs(old.start_bit - new.start_bit)} bit(s)")

        # Event message warning
        reasons_list = list(reasons)
        reasons_list.append("Event Matrix message: name similarity is primary criterion")

        return min(score, 1.0), tuple(reasons_list)
def _name_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()
