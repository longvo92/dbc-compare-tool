from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePosixPath

from dbc_compare_tool.core.models import DbcDatabase, Message, jaccard

FILE_RENAME_THRESHOLD = 0.55
_GENERIC_WORDS = frozenset({
    "dbc", "old", "new", "baseline", "release", "version", "rev", "revision",
    "final", "draft", "copy", "database", "db", "network", "can", "bus", "v", "ver", "r",
})


@dataclass(frozen=True)
class DatabaseCandidate:
    relative_path: str
    database: DbcDatabase


@dataclass(frozen=True)
class DatabaseMatch:
    old: DatabaseCandidate
    new: DatabaseCandidate
    confidence: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _Profile:
    candidate: DatabaseCandidate
    keywords: dict[str, float]
    frames: dict[tuple[int, bool], Message]
    names: frozenset[str]


def _keywords(path: str) -> dict[str, float]:
    """Ignore release decorations, retaining channel numbers such as CAN1."""
    result: dict[str, float] = {}
    parts = PurePosixPath(path.replace("\\", "/")).with_suffix("").parts
    for index, part in enumerate(parts):
        part = re.sub(r"(?:[_\s-]+|(?<=[a-zA-Z]))(?:v|ver|rev)\d+(?:[._]\d+)*$", "", part, flags=re.I)
        part = re.sub(r"([a-z])([A-Z])", r"\1_\2", part)
        part = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", part).lower()
        part = re.sub(r"(?<![a-z0-9])(can|bus)[_\s-]+(\d+)(?![a-z0-9])", r"\1\2", part)
        for token in re.findall(r"[a-z]+\d*", part):
            if not token.startswith(("can", "bus")):
                token = re.sub(r"(?:19|20)\d{2}(?:\d{4})?$", "", token)
            if token in _GENERIC_WORDS or re.fullmatch(r"(?:v|ver|rev|r)\d+", token):
                continue
            result[token] = max(result.get(token, 0), 1.0 if index == len(parts) - 1 else 0.35)
    return result


def _profile(candidate: DatabaseCandidate) -> _Profile:
    return _Profile(
        candidate, _keywords(candidate.relative_path),
        {(msg.can_id, msg.is_extended_frame): msg for msg in candidate.database.messages.values()},
        frozenset(candidate.database.messages),
    )


def match_renamed_databases(
    old_candidates: list[DatabaseCandidate], new_candidates: list[DatabaseCandidate],
) -> list[DatabaseMatch]:
    """Choose a maximum-score one-to-one assignment over the unmatched inventory."""
    if not old_candidates or not new_candidates:
        return []
    old_profiles = [_profile(item) for item in sorted(old_candidates, key=lambda item: item.relative_path)]
    new_profiles = [_profile(item) for item in sorted(new_candidates, key=lambda item: item.relative_path)]
    profiles = old_profiles + new_profiles
    frequency = Counter(word for profile in profiles for word in profile.keywords)
    weights = {word: 1 + math.log((len(profiles) + 1) / (count + 1)) for word, count in frequency.items()}

    # Build profiles once and score only pairs with shared evidence.
    index: dict[tuple[str, object], set[int]] = defaultdict(set)
    for column, profile in enumerate(new_profiles):
        for kind, values in (("word", profile.keywords), ("frame", profile.frames), ("name", profile.names)):
            for value in values:
                index[kind, value].add(column)
    scores = [[0.0] * len(new_profiles) for _ in old_profiles]
    candidates: dict[tuple[int, int], DatabaseMatch] = {}
    for row, old in enumerate(old_profiles):
        possible: set[int] = set()
        for kind, values in (("word", old.keywords), ("frame", old.frames), ("name", old.names)):
            for value in values:
                possible.update(index.get((kind, value), ()))
        for column in sorted(possible):
            new = new_profiles[column]
            score, reasons = _score_database_pair(old, new, weights)
            if score >= FILE_RENAME_THRESHOLD:
                scores[row][column] = score
                candidates[row, column] = DatabaseMatch(old.candidate, new.candidate, score, reasons)
    if not candidates:
        return []
    # Use the smaller inventory as rows; zero-score dummy slots allow unpaired files.
    if len(old_profiles) <= len(new_profiles):
        assignment = _maximum_assignment([row + [0.0] * len(old_profiles) for row in scores])
        selected = [(row, column) for row, column in enumerate(assignment)]
    else:
        transposed = [list(column) + [0.0] * len(new_profiles) for column in zip(*scores)]
        assignment = _maximum_assignment(transposed)
        selected = [(row, column) for column, row in enumerate(assignment)]
    return [candidates[key] for key in sorted(selected) if key in candidates]


def _score_database_pair(old: _Profile, new: _Profile, weights: dict[str, float]) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []
    shared_words = old.keywords.keys() & new.keywords.keys()
    name_score = 0.0
    if shared_words:
        old_weight = sum(weights[word] * strength for word, strength in old.keywords.items())
        new_weight = sum(weights[word] * strength for word, strength in new.keywords.items())
        shared = sum(weights[word] * min(old.keywords[word], new.keywords[word]) for word in sorted(shared_words))
        containment = shared / min(old_weight, new_weight)
        overlap = shared / (old_weight + new_weight - shared)
        name_score = 0.65 + 0.20 * containment + 0.15 * overlap
        reasons.append("Shared DBC keywords: " + ", ".join(sorted(shared_words, key=lambda word: (-weights[word], word))))

    common_ids = old.frames.keys() & new.frames.keys()
    id_overlap = len(common_ids) / max(len(old.frames), len(new.frames), 1)
    name_overlap = len(old.names & new.names) / max(len(old.names), len(new.names), 1)
    structure = _common_message_structure_score(old.frames, new.frames, common_ids) if common_ids else 0.0
    similarity = SequenceMatcher(None, old.candidate.relative_path.lower(), new.candidate.relative_path.lower()).ratio()
    content_score = 0.55 * id_overlap + 0.15 * name_overlap + 0.25 * structure * id_overlap + 0.05 * similarity
    if id_overlap:
        reasons.append(f"DBC CAN ID overlap {id_overlap:.0%}")
    if name_overlap:
        reasons.append(f"Message names overlap {name_overlap:.0%}")
    if structure:
        reasons.append(f"Common CAN ID structures {structure:.0%} matched")
    score = max(content_score, 0.85 * name_score) + 0.10 * min(content_score, name_score)
    return min(score, 1.0), tuple(reasons)


def _common_message_structure_score(
    old_by_id: dict[tuple[int, bool], Message], new_by_id: dict[tuple[int, bool], Message],
    common_ids: set[tuple[int, bool]],
) -> float:
    scores: list[float] = []
    for frame_key in sorted(common_ids):
        old, new = old_by_id[frame_key], new_by_id[frame_key]
        score = 0.20 * (old.dlc == new.dlc) + 0.15 * (old.transmitter == new.transmitter)
        score += 0.10 * (old.cycle_time_ms == new.cycle_time_ms) + 0.15 * (len(old.signals) == len(new.signals))
        score += 0.40 * jaccard(old.signal_layout(), new.signal_layout())
        scores.append(score)
    return sum(scores) / len(scores)


def _maximum_assignment(scores: list[list[float]]) -> list[int]:
    """Rectangular Hungarian assignment; rows <= columns, O(rows² * columns)."""
    if not scores:
        return []
    rows, columns = len(scores), len(scores[0])
    u, v = [0.0] * (rows + 1), [0.0] * (columns + 1)
    owner, previous = [0] * (columns + 1), [0] * (columns + 1)
    for row in range(1, rows + 1):
        owner[0] = row
        column = 0
        distance = [float("inf")] * (columns + 1)
        visited = [False] * (columns + 1)
        while True:
            visited[column] = True
            current = owner[column]
            delta, next_column = float("inf"), 0
            for other in range(1, columns + 1):
                if visited[other]:
                    continue
                cost = -scores[current - 1][other - 1] - u[current] - v[other]
                if cost < distance[other]:
                    distance[other], previous[other] = cost, column
                if distance[other] < delta:
                    delta, next_column = distance[other], other
            for other in range(columns + 1):
                if visited[other]:
                    u[owner[other]] += delta
                    v[other] -= delta
                else:
                    distance[other] -= delta
            column = next_column
            if owner[column] == 0:
                break
        while column:
            owner[column] = owner[previous[column]]
            column = previous[column]
    assignment = [-1] * rows
    for column in range(1, columns + 1):
        if owner[column]:
            assignment[owner[column] - 1] = column - 1
    return assignment
