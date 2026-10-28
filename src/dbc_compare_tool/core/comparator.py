from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PureWindowsPath

from dbc_compare_tool.core.discovery import collect_dbc_files
from dbc_compare_tool.core.ecu import (
    database_ecu_nodes,
    receivers_match,
    transmitters_match,
    validate_dbc_input,
    validate_ecu_map,
)
from dbc_compare_tool.core.models import (
    Change,
    ComparisonResult,
    DbcDatabase,
    Diagnostic,
    FilePairSummary,
    Message,
    PairingMetadata,
    Signal,
)
from dbc_compare_tool.core.matching import identity, match_entities
from dbc_compare_tool.core.parser import DbcParseError, parse_dbc, validate_database
from dbc_compare_tool.core.policy import (
    RECALL_V1,
    MatchingPolicy,
    database_evidence,
    database_profile,
    message_evidence,
    message_profile,
    signal_evidence,
    signal_profile,
)

LAYOUT_PROPERTIES = ("Start Bit", "Length", "Byte Order")
PROPERTY_ORDER = (
    "Start Bit",
    "Length",
    "Byte Order",
    "Minimum",
    "Maximum",
    "Factor",
    "Offset",
    "Unit",
    "Value Type",
    "Signed",
    "Receivers",
    "Multiplexer",
    "Multiplexer IDs",
    "Multiplexer Signal",
    "Value Descriptions",
    "CAN ID",
    "DLC",
    "Transmitter",
    "Extended Frame",
    "Cycle Time",
    "Signal Count",
    "Description",
)
PROPERTY_LABELS = {
    "Minimum": "Min",
    "Maximum": "Max",
}


class DbcComparator:
    def __init__(
        self,
        include_unchanged: bool = False,
        ecu_map: dict[str, str] | None = None,
        *,
        policy: MatchingPolicy | str = "recall-v1",
    ) -> None:
        if isinstance(policy, str):
            if policy != RECALL_V1.version:
                raise ValueError(f"Unknown matching policy: {policy}")
            policy = RECALL_V1
        self.policy = policy
        self.include_unchanged = include_unchanged
        self.ecu_map = dict(ecu_map or {})
        validate_ecu_map(self.ecu_map)

    def _result(self):
        return ComparisonResult(
            include_unchanged=self.include_unchanged,
            ecu_map=dict(self.ecu_map),
            policy_version=self.policy.version,
        )

    def compare_paths(
        self,
        old_path: Path,
        new_path: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        old_path, new_path = Path(old_path), Path(new_path)
        validate_dbc_input(old_path)
        validate_dbc_input(new_path)
        if old_path.is_dir() != new_path.is_dir():
            raise ValueError(
                "Select two folders or two .dbc files; file/folder inputs cannot be mixed"
            )
        return (self.compare_folders if old_path.is_dir() else self.compare_files)(
            old_path, new_path, progress_callback
        )

    def compare_files(
        self,
        old_path: Path,
        new_path: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        old_path, new_path = Path(old_path), Path(new_path)
        for path in (old_path, new_path):
            validate_dbc_input(path)
            if not path.is_file():
                raise ValueError(f"Direct file comparison requires a .dbc file: {path}")
        old, new = parse_dbc(old_path), parse_dbc(new_path)
        result = self._result()
        result.is_file_comparison = True
        self._validate_mapping([old], [new])
        paths = str(old_path.resolve()), str(new_path.resolve())
        self._register(result, "OLD", paths[0], old)
        self._register(result, "NEW", paths[1], new)
        pair = self._fixed_pair(*paths, reason="Explicit file selection")
        self._process_file(result, pair, old, new, progress_callback)
        return self._finish(result)

    def _validate_mapping(self, old, new, diagnostics=()):
        # Missing nodes on an unreadable side are unknown, not invalid mappings.
        failed_sides = {diagnostic.side for diagnostic in diagnostics}
        validate_ecu_map(
            self.ecu_map,
            None
            if "OLD" in failed_sides
            else set().union(*(database_ecu_nodes(db) for db in old)),
            None
            if "NEW" in failed_sides
            else set().union(*(database_ecu_nodes(db) for db in new)),
        )

    def _load_folders(self, old_folder, new_folder, progress):
        result = self._result()
        loaded = {}
        files = {}
        for side, folder in (("OLD", old_folder), ("NEW", new_folder)):
            folder = Path(folder)
            validate_dbc_input(folder)
            if not folder.is_dir():
                raise ValueError(f"Folder comparison requires a directory: {folder}")
            files[side] = collect_dbc_files(folder)
            loaded[side] = {}
            for path, disk in sorted(files[side].items()):
                try:
                    db = parse_dbc(disk)
                except DbcParseError as exc:
                    result.diagnostics.append(Diagnostic(side, path, str(exc)))
                    if progress:
                        progress(f"Parse error: {side} {path}: {exc}")
                else:
                    loaded[side][path] = db
                    self._register(result, side, path, db)
        self._validate_mapping(
            loaded["OLD"].values(), loaded["NEW"].values(), result.diagnostics
        )
        return result, files, loaded

    def compare_folders(
        self,
        old_folder: Path,
        new_folder: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        result, files, loaded = self._load_folders(
            old_folder, new_folder, progress_callback
        )
        old, new = loaded["OLD"], loaded["NEW"]
        old_profiles = {
            identity("OLD", p): database_profile(p, db, self.ecu_map)
            for p, db in old.items()
        }
        new_profiles = {
            identity("NEW", p): database_profile(p, db) for p, db in new.items()
        }
        pairs, candidates = match_entities(
            old_profiles,
            new_profiles,
            lambda a, b: database_evidence(
                old_profiles[a], new_profiles[b], self.policy
            ),
            self.policy,
        )
        result.pairing_candidates.extend(candidates)
        used_old, used_new = set(), set()
        for pair in pairs:
            a, b = pair.old.dbc_path, pair.new.dbc_path
            used_old.add(a)
            used_new.add(b)
            self._process_file(result, pair, old[a], new[b], progress_callback)
        for side, dbs, used in (("OLD", old, used_old), ("NEW", new, used_new)):
            for path, db in sorted(dbs.items()):
                if path not in used:
                    self._unmatched_file(result, side, path, db)
        for side in ("OLD", "NEW"):
            for path in sorted(files[side].keys() - loaded[side].keys()):
                result.file_pairs.append(
                    _file_pair_summary(
                        label=path,
                        status="Parse Error",
                        old_path=path if side == "OLD" else "",
                        new_path=path if side == "NEW" else "",
                    )
                )
        return self._finish(result)

    def compare_manual(
        self,
        old_folder: Path,
        new_folder: Path,
        pair_map: dict[str, str | None],
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        # Validate the map before parsing; a malformed map is an input error.
        if not isinstance(pair_map, dict) or any(
            not isinstance(a, str)
            or not a
            or (b is not None and (not isinstance(b, str) or not b))
            for a, b in pair_map.items()
        ):
            raise ValueError(
                "Manual DBC mapping requires nonempty OLD paths and NEW paths or None"
            )
        old_files, new_files = (
            collect_dbc_files(Path(old_folder)),
            collect_dbc_files(Path(new_folder)),
        )
        missing = [p for p in pair_map if p not in old_files]
        missing += [
            p for p in pair_map.values() if p is not None and p not in new_files
        ]
        if missing:
            raise FileNotFoundError(
                f"Paired DBC files not found on disk: {', '.join(missing)}"
            )
        targets = [p for p in pair_map.values() if p is not None]
        if len(targets) != len(set(targets)):
            raise ValueError("New DBC files paired more than once")
        result, files, loaded = self._load_folders(
            old_folder, new_folder, progress_callback
        )
        for old_path in sorted(files["OLD"]):
            new_path = pair_map.get(old_path)
            old = loaded["OLD"].get(old_path)
            new = loaded["NEW"].get(new_path) if new_path is not None else None
            if new_path is not None:
                pair = self._fixed_pair(old_path, new_path, reason="Manual DBC mapping")
                if old is None or new is None:
                    pair.selected = False
                    pair.category = "Not compared"
                    pair.evidence += (
                        "OLD Parse Error; NEW Not compared"
                        if old is None and new is not None
                        else "NEW Parse Error; OLD Not compared"
                        if new is None and old is not None
                        else "Both fixed files failed parsing",
                    )
                    for side, path, db in (
                        ("OLD", old_path, old),
                        ("NEW", new_path, new),
                    ):
                        if db is not None:
                            self._not_compared(result, side, path, db)
                    result.file_pairs.append(
                        _file_pair_summary(
                            label=_format_file_pair_label(old_path, new_path),
                            status="Parse Error",
                            old_path=old_path,
                            new_path=new_path,
                            old_db=old,
                            new_db=new,
                            pairing=pair,
                        )
                    )
                else:
                    self._process_file(result, pair, old, new, progress_callback)
            elif old is not None:
                self._unmatched_file(result, "OLD", old_path, old, excluded=True)
            else:
                result.file_pairs.append(
                    _file_pair_summary(
                        label=old_path,
                        status="Parse Error",
                        old_path=old_path,
                        new_path="",
                    )
                )
        for new_path in sorted(files["NEW"].keys() - set(targets)):
            new = loaded["NEW"].get(new_path)
            if new is not None:
                self._unmatched_file(result, "NEW", new_path, new)
            else:
                result.file_pairs.append(
                    _file_pair_summary(
                        label=new_path,
                        status="Parse Error",
                        old_path="",
                        new_path=new_path,
                    )
                )
        return self._finish(result)

    @staticmethod
    def _fixed_pair(old_path, new_path, *, reason):
        return PairingMetadata(
            identity("OLD", old_path),
            identity("NEW", new_path),
            confidence=1.0,
            evidence=(reason,),
            fixed=True,
        )

    @staticmethod
    def _register(result, side, path, db):
        validate_database(db)
        entities = [identity(side, path)]
        for message in db.messages.values():
            entities.append(identity(side, path, message))
            entities.extend(
                identity(side, path, signal, message)
                for signal in message.signals.values()
            )
        for entity in entities:
            if entity in result.inventory:
                raise AssertionError(f"Inventory registered twice: {entity}")
            result.inventory[entity] = "pending"

    @staticmethod
    def _account(result, pair, status="paired"):
        for entity in (pair.old, pair.new):
            if entity is not None:
                if result.inventory.get(entity) != "pending":
                    raise AssertionError(
                        f"Entity accounted more than once or absent: {entity}"
                    )
                result.inventory[entity] = status
        result.pairings.append(pair)

    def _not_compared(self, result, side, path, db):
        for entity in sorted(result.inventory):
            if entity.side == side and entity.dbc_path == path:
                pair = PairingMetadata(
                    entity if side == "OLD" else None,
                    entity if side == "NEW" else None,
                    evidence=("Fixed counterpart failed parsing",),
                    category="Not compared",
                )
                self._account(result, pair, "not compared")

    def _process_file(self, result, pair, old, new, progress=None):
        a, b = pair.old.dbc_path, pair.new.dbc_path
        label = _format_file_pair_label(a, b)
        if progress:
            progress(f"Comparing: {a} -> {b}; {'; '.join(pair.evidence)}")
        self._account(result, pair)
        self._compare_messages(result, label, a, b, old, new, pair)
        status = (
            "Matched" if a == b else "Manually Paired" if pair.fixed else "DBC Renamed"
        )
        result.file_pairs.append(
            _file_pair_summary(
                label=label,
                status=status,
                old_path=a,
                new_path=b,
                old_db=old,
                new_db=new,
                pairing=pair,
            )
        )

    def _unmatched_file(self, result, side, path, db, excluded=False):
        entity = identity(side, path)
        pair = PairingMetadata(
            entity if side == "OLD" else None,
            entity if side == "NEW" else None,
            evidence=(
                "Excluded by manual mapping" if excluded else "No eligible assignment",
            ),
            category="Unmatched",
            fixed=excluded,
        )
        self._account(result, pair, "unmatched")
        for message in sorted(
            db.messages.values(), key=lambda m: (m.can_id, m.is_extended_frame, m.name)
        ):
            self._unmatched_message(
                result, _format_file_pair_label(path), side, path, message, excluded
            )
        result.file_pairs.append(
            _file_pair_summary(
                label=path,
                status="DBC Removed" if side == "OLD" else "DBC Added",
                old_path=path if side == "OLD" else "",
                new_path=path if side == "NEW" else "",
                old_db=db if side == "OLD" else None,
                new_db=db if side == "NEW" else None,
                pairing=pair,
            )
        )

    def compare_databases(
        self,
        dbc_file: str,
        old_db: DbcDatabase,
        new_db: DbcDatabase,
        result: ComparisonResult | None = None,
    ) -> ComparisonResult:
        own_result = result is None
        if own_result:
            result = self._result()
            self._validate_mapping([old_db], [new_db])
        result.include_unchanged = result.include_unchanged or self.include_unchanged
        result.ecu_map = dict(self.ecu_map)
        result.policy_version = self.policy.version
        a, b = str(old_db.path), str(new_db.path)
        self._register(result, "OLD", a, old_db)
        self._register(result, "NEW", b, new_db)
        pair = self._fixed_pair(a, b, reason="Explicit database comparison")
        self._account(result, pair)
        self._compare_messages(result, dbc_file, a, b, old_db, new_db, pair)
        return self._finish(result)

    def _compare_messages(
        self, result, label, old_path, new_path, old_db, new_db, parent
    ):
        old = {identity("OLD", old_path, m): m for m in old_db.messages.values()}
        new = {identity("NEW", new_path, m): m for m in new_db.messages.values()}
        profiles_old = {k: message_profile(m, self.ecu_map) for k, m in old.items()}
        profiles_new = {k: message_profile(m) for k, m in new.items()}
        pairs, candidates = match_entities(
            old,
            new,
            lambda a, b: message_evidence(
                old[a],
                new[b],
                self.ecu_map,
                self.policy,
                profiles_old[a],
                profiles_new[b],
            ),
            self.policy,
            parent,
        )
        result.pairing_candidates.extend(candidates)
        used = set()
        for pair in pairs:
            self._account(result, pair)
            used.update((pair.old, pair.new))
            a, b = old[pair.old], new[pair.new]
            self._change(result.message_changes, label, a, b, pair)
            self._compare_signals(result, label, old_path, new_path, a, b, pair)
        for side, items in (("OLD", old), ("NEW", new)):
            for entity, message in sorted(items.items()):
                if entity not in used:
                    self._unmatched_message(
                        result, label, side, entity.dbc_path, message
                    )

    def _unmatched_message(self, result, label, side, path, message, excluded=False):
        entity = identity(side, path, message)
        pair = PairingMetadata(
            entity if side == "OLD" else None,
            entity if side == "NEW" else None,
            fixed=excluded,
            category="Unmatched",
        )
        self._account(result, pair, "unmatched")
        self._change(
            result.message_changes,
            label,
            message if side == "OLD" else None,
            message if side == "NEW" else None,
            pair,
        )
        for signal in sorted(message.signals.values(), key=lambda s: s.name):
            self._unmatched_signal(
                result,
                label,
                side,
                path,
                signal,
                message if side == "OLD" else None,
                message if side == "NEW" else None,
                excluded,
            )

    def _compare_signals(
        self, result, label, old_path, new_path, old_message, new_message, parent
    ):
        old = {
            identity("OLD", old_path, s, old_message): s
            for s in old_message.signals.values()
        }
        new = {
            identity("NEW", new_path, s, new_message): s
            for s in new_message.signals.values()
        }
        profiles_old = {k: signal_profile(s, self.ecu_map) for k, s in old.items()}
        profiles_new = {k: signal_profile(s) for k, s in new.items()}
        pairs, candidates = match_entities(
            old,
            new,
            lambda a, b: signal_evidence(
                old[a],
                new[b],
                self.ecu_map,
                self.policy,
                profiles_old[a],
                profiles_new[b],
            ),
            self.policy,
            parent,
        )
        result.pairing_candidates.extend(candidates)
        used = set()
        for pair in pairs:
            self._account(result, pair)
            used.update((pair.old, pair.new))
            self._change(
                result.signal_changes,
                label,
                old[pair.old],
                new[pair.new],
                pair,
                old_message,
                new_message,
            )
        for side, items in (("OLD", old), ("NEW", new)):
            for entity, signal in sorted(items.items()):
                if entity not in used:
                    self._unmatched_signal(
                        result,
                        label,
                        side,
                        entity.dbc_path,
                        signal,
                        old_message,
                        new_message,
                    )

    def _unmatched_signal(
        self,
        result,
        label,
        side,
        path,
        signal,
        old_message,
        new_message,
        excluded=False,
    ):
        entity = identity(
            side, path, signal, old_message if side == "OLD" else new_message
        )
        pair = PairingMetadata(
            entity if side == "OLD" else None,
            entity if side == "NEW" else None,
            fixed=excluded,
            category="Unmatched",
        )
        self._account(result, pair, "unmatched")
        self._change(
            result.signal_changes,
            label,
            signal if side == "OLD" else None,
            signal if side == "NEW" else None,
            pair,
            old_message,
            new_message,
        )

    def _change(
        self, target, label, old, new, pair, old_message=None, new_message=None
    ):
        signal = isinstance(old or new, Signal)
        if not signal:
            old_message, new_message = old, new
        description, diffs = (
            self._property_changes(old, new)
            if old is not None and new is not None
            else ("", ())
        )
        if old is None:
            kind = "Added"
        elif new is None:
            kind = "Removed"
        elif old.name != new.name:
            kind = "Renamed"
        else:
            kind = "Modified" if diffs else "Unchanged"
        if kind == "Unchanged" and not self.include_unchanged:
            return
        target.append(
            Change(
                dbc_file=label,
                change_type=kind,
                old_name=old.name if old is not None else "",
                new_name=new.name if new is not None else "",
                confidence=pair.confidence,
                confidence_level=pair.confidence_level,
                description=_with_match_reasons(description, pair.evidence)
                if old is not None and new is not None
                else f"Entity {kind.lower()}",
                can_id=(new_message or old_message).can_id
                if (new_message or old_message)
                else None,
                parent_message=(new_message or old_message).name if signal else "",
                property_diffs=diffs,
                old_message=old_message,
                new_message=new_message,
                old_signal=old if signal else None,
                new_signal=new if signal else None,
                pairing=pair,
            )
        )

    def _finish(self, result):
        if any(status == "pending" for status in result.inventory.values()):
            raise AssertionError("Inventory coverage is incomplete")
        accounted = Counter(
            e for p in result.pairings for e in (p.old, p.new) if e is not None
        )
        if set(accounted) != set(result.inventory) or any(
            n != 1 for n in accounted.values()
        ):
            raise AssertionError("Every valid entity must be accounted exactly once")
        self._suggest_moves(result)

        def key(pair):
            return (
                pair.old is None,
                pair.old,
                pair.new is None,
                pair.new,
                pair.category,
            )

        # The same selected metadata object is referenced by changes, summaries and candidates.
        unique = {
            id(p): p
            for p in result.pairings
            + result.pairing_candidates
            + result.move_suggestions
            + [fp.pairing for fp in result.file_pairs if fp.pairing is not None]
        }
        for index, pair in enumerate(sorted(unique.values(), key=key), 1):
            pair.pair_id = f"P{index:07d}"
        result.pairings.sort(key=key)
        result.pairing_candidates.sort(key=key)
        result.file_pairs.sort(key=lambda p: (p.old_path, p.new_path))
        result.diagnostics.sort(key=lambda d: (d.side, d.path, d.reason))
        return result

    def _suggest_moves(self, result):
        result.move_suggestions.clear()
        # Context comes from unfiltered changes; unmatched rows always exist.
        objects = {}
        for change in result.message_changes + result.signal_changes:
            pair = change.pairing
            if pair is None or pair.category != "Unmatched" or pair.fixed:
                continue
            entity = pair.old or pair.new
            objects[entity] = (
                (change.old_signal or change.new_signal)
                if entity.kind == "signal"
                else (change.old_message or change.new_message)
            )
        paired_parents = {}
        parent_confidence = {}
        for pair in result.pairings:
            if pair.old and pair.new and pair.old.kind in {"dbc", "message"}:
                parent_old = (
                    (pair.old.dbc_path,)
                    if pair.old.kind == "dbc"
                    else (
                        pair.old.dbc_path,
                        pair.old.frame_id,
                        pair.old.extended,
                        pair.old.message_name,
                    )
                )
                parent_new = (
                    (pair.new.dbc_path,)
                    if pair.new.kind == "dbc"
                    else (
                        pair.new.dbc_path,
                        pair.new.frame_id,
                        pair.new.extended,
                        pair.new.message_name,
                    )
                )
                paired_parents[pair.old.kind, parent_old] = parent_new
                if not pair.fixed and pair.confidence is not None:
                    parent_confidence["OLD", pair.old.kind, parent_old] = (
                        pair.confidence
                    )
                    parent_confidence["NEW", pair.new.kind, parent_new] = (
                        pair.confidence
                    )
        for kind in ("message", "signal"):
            old = sorted(e for e in objects if e.side == "OLD" and e.kind == kind)
            new = sorted(e for e in objects if e.side == "NEW" and e.kind == kind)
            parent_kind = "dbc" if kind == "message" else "message"
            for a in old:
                for b in new:
                    if (
                        paired_parents.get((parent_kind, a.parent), a.parent)
                        == b.parent
                    ):
                        continue
                    evidence = (
                        message_evidence if kind == "message" else signal_evidence
                    )(objects[a], objects[b], self.ecu_map, self.policy)
                    if evidence is not None:
                        confidence = min(
                            self.policy.ambiguous_cap,
                            evidence.similarity * self.policy.heuristic_cap,
                        )
                        for entity in (a, b):
                            confidence = min(
                                confidence,
                                parent_confidence.get(
                                    (entity.side, "dbc", (entity.dbc_path,)), confidence
                                ),
                            )
                            if kind == "signal":
                                confidence = min(
                                    confidence,
                                    parent_confidence.get(
                                        (entity.side, "message", entity.parent),
                                        confidence,
                                    ),
                                )
                        result.move_suggestions.append(
                            PairingMetadata(
                                a,
                                b,
                                evidence.similarity,
                                confidence,
                                evidence.reasons
                                + ("Possible parent move; main comparison unchanged",),
                                requires_review=True,
                                selected=False,
                                category="Move suggestion",
                                policy=self.policy,
                            )
                        )

    def _property_changes(
        self,
        old: Message | Signal,
        new: Message | Signal,
    ) -> tuple[str, tuple[tuple[str, str, str], ...]]:
        """Compare mapped identities, displaying the original values for actual deltas."""
        old_properties, new_properties = (
            old.comparable_properties(),
            new.comparable_properties(),
        )
        changed_keys = {
            key
            for key in old_properties.keys() | new_properties.keys()
            if old_properties.get(key) != new_properties.get(key)
        }
        if self.ecu_map:
            if isinstance(old, Message) and isinstance(new, Message):
                key = "Transmitter"
                equivalent = transmitters_match(
                    old.transmitter, new.transmitter, self.ecu_map
                )
            else:
                key = "Receivers"
                equivalent = receivers_match(old.receivers, new.receivers, self.ecu_map)
            if equivalent:
                changed_keys.discard(key)
            else:
                changed_keys.add(key)
        return (
            _changed_properties(old_properties, new_properties, changed_keys),
            _get_property_diffs(old_properties, new_properties, changed_keys),
        )


def filter_result(
    result: ComparisonResult, selected_types: set[str]
) -> ComparisonResult:
    """Filter detail changes only; preserve inventory, completeness and review evidence."""
    if not selected_types or result.include_unchanged:
        return result
    return replace(
        result,
        ecu_map=dict(result.ecu_map),
        message_changes=[
            c for c in result.message_changes if c.change_type in selected_types
        ],
        signal_changes=[
            c for c in result.signal_changes if c.change_type in selected_types
        ],
    )


def _format_file_pair_label(old_relative_path: str, new_relative_path: str = "") -> str:
    return " -> ".join(
        PureWindowsPath(path).name
        for path in (old_relative_path, new_relative_path)
        if path
    )


def _count_signals(db):
    return sum(len(message.signals) for message in db.messages.values())


def _file_pair_summary(
    *, label, status, old_path, new_path, old_db=None, new_db=None, pairing=None
):
    return FilePairSummary(
        _format_file_pair_label(*label.split(" -> ", 1)),
        status,
        old_path,
        new_path,
        pairing.confidence if pairing else None,
        len(old_db.messages) if old_db is not None else None if old_path else 0,
        len(new_db.messages) if new_db is not None else None if new_path else 0,
        _count_signals(old_db) if old_db is not None else None if old_path else 0,
        _count_signals(new_db) if new_db is not None else None if new_path else 0,
        pairing.evidence if pairing else (),
        pairing,
    )


def _get_property_diffs(
    old: dict[str, object],
    new: dict[str, object],
    changed_keys: set[str] | None = None,
) -> tuple[tuple[str, str, str], ...]:
    if changed_keys is None:
        changed_keys = {
            key for key in set(old) | set(new) if old.get(key) != new.get(key)
        }
    diffs: list[tuple[str, str, str]] = []
    for key in _ordered_changed_keys(changed_keys):
        label = PROPERTY_LABELS.get(key, key)
        diffs.append(
            (
                label,
                _format_property_value(key, old.get(key)),
                _format_property_value(key, new.get(key)),
            )
        )
    return tuple(diffs)


def _changed_properties(
    old: dict[str, object],
    new: dict[str, object],
    changed_keys: set[str] | None = None,
) -> str:
    if changed_keys is None:
        changed_keys = {
            key for key in set(old) | set(new) if old.get(key) != new.get(key)
        }
    if not changed_keys:
        return ""

    changes: list[str] = []
    layout_keys = [key for key in LAYOUT_PROPERTIES if key in changed_keys]
    if layout_keys:
        changes.append(
            f"Layout changed: {_format_change_segments(layout_keys, old, new)}"
        )

    for key in _ordered_changed_keys(changed_keys - set(LAYOUT_PROPERTIES)):
        changes.append(_format_change_segment(key, old.get(key), new.get(key)))
    return "\n".join(changes)


def _with_match_reasons(description: str, reasons: tuple[str, ...]) -> str:
    if not reasons:
        return description
    reasons_line = f"Matched by: {', '.join(reasons)}"
    return f"{description}\n{reasons_line}" if description else reasons_line


def _ordered_changed_keys(keys: set[str]) -> list[str]:
    ordered = [key for key in PROPERTY_ORDER if key in keys]
    ordered.extend(sorted(keys - set(PROPERTY_ORDER)))
    return ordered


def _format_change_segments(
    keys: list[str], old: dict[str, object], new: dict[str, object]
) -> str:
    return ", ".join(
        _format_change_segment(key, old.get(key), new.get(key)) for key in keys
    )


def _format_change_segment(key: str, old_value: object, new_value: object) -> str:
    label = PROPERTY_LABELS.get(key, key)
    return f"{label}: {_format_property_value(key, old_value)} -> {_format_property_value(key, new_value)}"


def _format_property_value(key: str, value: object) -> str:
    if value is None:
        return "blank"
    if key == "Byte Order":
        if value == 1:
            return "Intel/little-endian (1)"
        if value == 0:
            return "Motorola/big-endian (0)"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        # Preserve distinct floating-point values, keeping integral values compact.
        text = repr(value)
        return text[:-2] if text.endswith(".0") else text
    if key == "Value Descriptions" and isinstance(value, tuple):
        return ", ".join(f"{raw}={label}" for raw, label in value) if value else "blank"
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value) if value else "blank"
    return str(value)
