from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Generic, Iterable, Protocol, TypeVar

from dbc_compare_tool.core.models import Message, Signal, jaccard


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

    def score(self, old: Message, new: Message) -> tuple[float, tuple[str, ...]]:
        score = 0.0
        reasons: list[str] = []
        if old.can_id == new.can_id:
            score += 0.35
            reasons.append("CAN ID matched")
        if old.dlc == new.dlc:
            score += 0.12
            reasons.append("DLC matched")
        if old.transmitter == new.transmitter:
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
    threshold = 0.82
    event_threshold = 0.65  # Lower threshold for event-like messages

    def __init__(self, is_event_like: bool = False) -> None:
        """Initialize the detector for a normal or event-like message.

        Args:
            is_event_like: Whether the parent message is event-like, which changes scoring.
        """
        self.is_event_like = is_event_like
        if is_event_like:
            self.threshold = self.event_threshold

    def score(self, old: Signal, new: Signal) -> tuple[float, tuple[str, ...]]:
        if self.is_event_like:
            return self._score_for_event_message(old, new)
        return self._score_for_normal_message(old, new)

    def _score_for_normal_message(self, old: Signal, new: Signal) -> tuple[float, tuple[str, ...]]:
        """Standard scoring for signals in non-event messages."""
        score = 0.0
        reasons: list[str] = []
        weighted_checks = [
            (old.start_bit == new.start_bit, 0.18, "Start bit matched"),
            (old.length == new.length, 0.18, "Length matched"),
            (old.byte_order == new.byte_order, 0.10, "Byte order matched"),
            (old.is_signed == new.is_signed, 0.06, "Signedness matched"),
            (old.factor == new.factor, 0.12, "Factor matched"),
            (old.offset == new.offset, 0.12, "Offset matched"),
            (old.unit == new.unit, 0.08, "Unit matched"),
            (old.receivers == new.receivers, 0.11, "Receivers matched"),
        ]
        for matched, weight, reason in weighted_checks:
            if matched:
                score += weight
                reasons.append(reason)

        name_score = _name_similarity(old.name, new.name)
        score += 0.05 * name_score
        if name_score >= 0.5:
            reasons.append("Names are similar")
        return min(score, 1.0), tuple(reasons)

    def _score_for_event_message(self, old: Signal, new: Signal) -> tuple[float, tuple[str, ...]]:
        """
        Conservative scoring for signals in Event Matrix messages.
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
            (old.receivers == new.receivers, 0.06, "Receivers matched"),
        ]
        for matched, weight, reason in weighted_checks:
            if matched:
                score += weight
                reasons.append(reason)

        # Name similarity is much more important for event messages
        name_score = _name_similarity(old.name, new.name)
        score += 0.50 * name_score  # Increased from 0.05 to 0.50
        if name_score >= 0.6:
            reasons.append("Names are similar")
        elif name_score >= 0.3:
            reasons.append("Names have some similarity")

        # Event message warning
        reasons_list = list(reasons)
        reasons_list.append("Event Matrix message: name similarity is primary criterion")

        return min(score, 1.0), tuple(reasons_list)
def _name_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()

