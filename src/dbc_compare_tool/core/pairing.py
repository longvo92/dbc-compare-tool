"""DBC candidate convenience API using the shared recall-v1 engine."""

from __future__ import annotations
from dataclasses import dataclass

from dbc_compare_tool.core.assignment import _maximum_assignment  # noqa: F401
from dbc_compare_tool.core.matching import identity, match_entities
from dbc_compare_tool.core.models import DbcDatabase, PairingMetadata
from dbc_compare_tool.core.policy import RECALL_V1, database_profile, database_evidence


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
    pairing: PairingMetadata


def match_renamed_databases(old_candidates, new_candidates, ecu_map=None):
    old = {identity("OLD", c.relative_path): c for c in old_candidates}
    new = {identity("NEW", c.relative_path): c for c in new_candidates}
    a = {
        key: database_profile(c.relative_path, c.database, ecu_map)
        for key, c in old.items()
    }
    b = {key: database_profile(c.relative_path, c.database) for key, c in new.items()}
    pairs, _ = match_entities(
        old, new, lambda x, y: database_evidence(a[x], b[y], RECALL_V1), RECALL_V1
    )
    return [
        DatabaseMatch(old[p.old], new[p.new], p.confidence, p.evidence, p)
        for p in pairs
    ]
