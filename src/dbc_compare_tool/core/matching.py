"""Shared assignment and confidence for every hierarchy level."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable

from dbc_compare_tool.core.assignment import solve_assignment
from dbc_compare_tool.core.models import (
    EntityIdentity,
    Message,
    PairingMetadata,
    Signal,
)
from dbc_compare_tool.core.policy import Evidence, MatchingPolicy


def match_entities(
    old: Iterable[EntityIdentity],
    new: Iterable[EntityIdentity],
    evidence: Callable[[EntityIdentity, EntityIdentity], Evidence | None],
    policy: MatchingPolicy,
    parent: PairingMetadata | None = None,
) -> tuple[list[PairingMetadata], list[PairingMetadata]]:
    """Return selected pairs and every eligible edge, ordered by full identity."""
    old, new = sorted(old), sorted(new)
    edges = {}
    by_old, by_new = defaultdict(list), defaultdict(list)
    for i, a in enumerate(old):
        for j, b in enumerate(new):
            item = evidence(a, b)
            if item is not None:
                edges[i, j] = item
                by_old[i].append((i, j))
                by_new[j].append((i, j))
    selected = set(
        solve_assignment(
            {k: v.similarity for k, v in edges.items()}, scale=policy.score_scale
        )
    )
    best_old = {
        i: sorted((edges[k].similarity for k in keys), reverse=True)[:2]
        for i, keys in by_old.items()
    }
    best_new = {
        j: sorted((edges[k].similarity for k in keys), reverse=True)[:2]
        for j, keys in by_new.items()
    }
    candidates = []
    for (i, j), item in sorted(edges.items()):
        rival_count = len(by_old[i]) + len(by_new[j]) - 2
        # Only selected pairs need rival references; every edge is already retained
        # in the candidate list. Avoid cubic storage for dense ambiguous graphs.
        competitors = ()
        if (i, j) in selected:
            rivals = sorted(set(by_old[i] + by_new[j]) - {(i, j)})
            competitors = tuple(
                (old[a], new[b], edges[a, b].similarity) for a, b in rivals
            )
        confidence = item.similarity * policy.heuristic_cap
        reasons = item.reasons + ("Heuristic confidence",)
        if item.complete and not rival_count:
            confidence = 1.0
            reasons += ("Unique complete-property match without competing candidates",)
        if rival_count:

            def rival_best(scores):
                return (
                    scores[1]
                    if scores[0] == item.similarity and len(scores) > 1
                    else (-1.0 if scores[0] == item.similarity else scores[0])
                )

            margin = item.similarity - max(
                rival_best(best_old[i]), rival_best(best_new[j])
            )
            if margin <= policy.close_margin:
                confidence = min(
                    policy.ambiguous_cap,
                    max(0.0, confidence - max(0, policy.ambiguity_penalty - margin)),
                )
                reasons += (f"Competing candidates; score margin {margin:.6f}",)
        if parent is not None and not parent.fixed:
            confidence = min(
                confidence,
                parent.confidence
                if parent.confidence is not None
                else policy.ambiguous_cap,
            )
            if parent.requires_review:
                confidence = min(confidence, policy.ambiguous_cap)
                reasons += ("Parent pairing requires review",)
        # Round down so the displayed value never crosses a confidence boundary.
        precision = 10**policy.confidence_decimals
        confidence = int(confidence * precision) / precision
        candidates.append(
            PairingMetadata(
                old[i],
                new[j],
                item.similarity,
                confidence,
                reasons,
                competitors,
                confidence < policy.high_confidence,
                (i, j) in selected,
                policy=policy,
            )
        )
    return [p for p in candidates if p.selected], candidates


def identity(
    side: str,
    path: str,
    entity: Message | Signal | None = None,
    parent: Message | None = None,
) -> EntityIdentity:
    if entity is None:
        return EntityIdentity(side, path, "dbc")
    if parent is None:
        return EntityIdentity(
            side, path, "message", entity.can_id, entity.is_extended_frame, entity.name
        )
    return EntityIdentity(
        side,
        path,
        "signal",
        parent.can_id,
        parent.is_extended_frame,
        parent.name,
        entity.name,
    )
