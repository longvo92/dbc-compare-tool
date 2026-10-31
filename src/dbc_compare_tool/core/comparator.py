from __future__ import annotations

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
from dbc_compare_tool.core.models import Change, ComparisonResult, DbcDatabase, Diagnostic, EntityIdentity, FilePairSummary, Message, Signal
from dbc_compare_tool.core.pairing import DatabaseCandidate, match_renamed_databases
from dbc_compare_tool.core.parser import DbcParseError, parse_dbc, validate_database
from dbc_compare_tool.core.rename import EventMessageDetector, MessageRenameDetector, SignalRenameDetector

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
    def __init__(self, include_unchanged: bool = False, ecu_map: dict[str, str] | None = None) -> None:
        self.include_unchanged = include_unchanged
        self.ecu_map = dict(ecu_map or {})
        validate_ecu_map(self.ecu_map)

    def compare_paths(
        self,
        old_path: Path,
        new_path: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        """Compare two folders or explicitly pair two selected DBC files."""
        old_path, new_path = Path(old_path), Path(new_path)
        validate_dbc_input(old_path)
        validate_dbc_input(new_path)
        if old_path.is_dir() != new_path.is_dir():
            raise ValueError("Select two folders or two .dbc files; file/folder inputs cannot be mixed")
        if old_path.is_dir():
            return self.compare_folders(old_path, new_path, progress_callback)
        return self.compare_files(old_path, new_path, progress_callback)

    def compare_files(
        self,
        old_path: Path,
        new_path: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        """Force the selected files into one pair regardless of their names/content."""
        old_path, new_path = Path(old_path), Path(new_path)
        for path in (old_path, new_path):
            validate_dbc_input(path)
            if not path.is_file():
                raise ValueError(f"Direct file comparison requires a .dbc file: {path}")
        old_db, new_db = parse_dbc(old_path), parse_dbc(new_path)
        label = _format_file_pair_label(old_path.name, new_path.name)
        if progress_callback:
            progress_callback(f"[1/1] Comparing selected files: {label}")
        result = self.compare_databases(label, old_db, new_db)
        result.is_file_comparison = True
        result.file_pairs.append(_file_pair_summary(
            label=label,
            status="Matched" if old_path.name == new_path.name else "Manually Paired",
            old_path=str(old_path.resolve()),
            new_path=str(new_path.resolve()),
            pairing_reasons=("Explicit file selection",),
            old_db=old_db,
            new_db=new_db,
        ))
        return result

    def _property_changes(
        self, old: Message | Signal, new: Message | Signal,
    ) -> tuple[str, tuple[tuple[str, str, str], ...]]:
        """Compare mapped identities, displaying the original values for actual deltas."""
        old_properties, new_properties = old.comparable_properties(), new.comparable_properties()
        changed_keys = {
            key for key in old_properties.keys() | new_properties.keys()
            if old_properties.get(key) != new_properties.get(key)
        }
        if self.ecu_map:
            if isinstance(old, Message) and isinstance(new, Message):
                key = "Transmitter"
                equivalent = transmitters_match(old.transmitter, new.transmitter, self.ecu_map)
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

    def _load_folders(self, old_folder, new_folder, progress):
        for folder in (old_folder, new_folder):
            validate_dbc_input(Path(folder))
            if not Path(folder).is_dir():
                raise ValueError(f"Folder comparison requires a directory: {folder}")
        files = {
            "OLD": collect_dbc_files(old_folder),
            "NEW": collect_dbc_files(new_folder),
        }
        result = ComparisonResult(include_unchanged=self.include_unchanged,
                                  ecu_map=dict(self.ecu_map), policy_version="classic-v067")
        loaded = {"OLD": {}, "NEW": {}}
        for side in ("OLD", "NEW"):
            for rel, path in sorted(files[side].items()):
                try:
                    loaded[side][rel] = parse_dbc(path)
                except DbcParseError as exc:
                    result.diagnostics.append(Diagnostic(side, rel, str(exc)))
                    if progress:
                        progress(f"Parse error: {side} {rel}: {exc}")
        failed = {d.side for d in result.diagnostics}
        validate_ecu_map(
            self.ecu_map,
            None if "OLD" in failed else set().union(*(database_ecu_nodes(db) for db in loaded["OLD"].values())),
            None if "NEW" in failed else set().union(*(database_ecu_nodes(db) for db in loaded["NEW"].values())),
        )
        return result, files, loaded

    def compare_folders(
        self,
        old_folder: Path,
        new_folder: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        result, files, loaded = self._load_folders(old_folder, new_folder, progress_callback)
        old_only: list[DatabaseCandidate] = []
        new_only: list[DatabaseCandidate] = []
        fixed_failed = set()
        for rel in sorted(files["OLD"].keys() & files["NEW"].keys()):
            old_db, new_db = loaded["OLD"].get(rel), loaded["NEW"].get(rel)
            label = _format_file_pair_label(rel, rel)
            if old_db is None or new_db is None:
                fixed_failed.add(rel)
                self._not_compared(result, "OLD", rel, old_db)
                self._not_compared(result, "NEW", rel, new_db)
                result.file_pairs.append(_file_pair_summary(
                    label=label, status="Parse Error", old_path=rel, new_path=rel,
                    old_db=old_db, new_db=new_db,
                ))
                continue
            if progress_callback:
                progress_callback(f"Comparing: {rel}")
            self.compare_databases(label, old_db, new_db, result)
            result.file_pairs.append(_file_pair_summary(
                label=label, status="Matched", old_path=rel, new_path=rel,
                old_db=old_db, new_db=new_db,
            ))
        for side, only in (("OLD", old_only), ("NEW", new_only)):
            for rel, db in sorted(loaded[side].items()):
                if rel not in files["OLD"].keys() & files["NEW"].keys():
                    only.append(DatabaseCandidate(rel, db))
        file_matches = match_renamed_databases(old_only, new_only, self.ecu_map)
        matched_old = {match.old.relative_path for match in file_matches}
        matched_new = {match.new.relative_path for match in file_matches}
        for match in file_matches:
            old_rel, new_rel = match.old.relative_path, match.new.relative_path
            label = _format_file_pair_label(old_rel, new_rel)
            if progress_callback:
                progress_callback(
                    f"Comparing renamed DBC: {label} "
                    f"({match.confidence:.2f}; {'; '.join(match.reasons)})"
                )
            self.compare_databases(label, match.old.database, match.new.database, result)
            result.file_pairs.append(_file_pair_summary(
                label=label, status="DBC Renamed", old_path=old_rel,
                new_path=new_rel, pairing_confidence=match.confidence,
                pairing_reasons=match.reasons, old_db=match.old.database,
                new_db=match.new.database,
            ))
        for side, candidates, matched in (("OLD", old_only, matched_old), ("NEW", new_only, matched_new)):
            for candidate in candidates:
                if candidate.relative_path in matched:
                    continue
                rel, db = candidate.relative_path, candidate.database
                empty = DbcDatabase(path=Path(rel))
                self.compare_databases(rel, db if side == "OLD" else empty,
                                       empty if side == "OLD" else db, result,
                                       present_old=side == "OLD", present_new=side == "NEW")
                result.file_pairs.append(_file_pair_summary(
                    label=rel, status="DBC Removed" if side == "OLD" else "DBC Added",
                    old_path=rel if side == "OLD" else "",
                    new_path=rel if side == "NEW" else "",
                    old_db=db if side == "OLD" else None,
                    new_db=db if side == "NEW" else None,
                ))
        for side in ("OLD", "NEW"):
            for rel in sorted(files[side].keys() - loaded[side].keys() - fixed_failed):
                result.file_pairs.append(_file_pair_summary(
                    label=rel, status="Parse Error",
                    old_path=rel if side == "OLD" else "",
                    new_path=rel if side == "NEW" else "",
                ))
        return result

    def compare_manual(
        self,
        old_folder: Path,
        new_folder: Path,
        pair_map: dict[str, str | None],
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        if not isinstance(pair_map, dict) or any(
            not isinstance(a, str) or not a or
            (b is not None and (not isinstance(b, str) or not b))
            for a, b in pair_map.items()
        ):
            raise ValueError("Manual DBC mapping requires nonempty OLD paths and NEW paths or None")
        old_files, new_files = collect_dbc_files(old_folder), collect_dbc_files(new_folder)
        missing = [p for p in pair_map if p not in old_files]
        missing += [p for p in pair_map.values() if p is not None and p not in new_files]
        if missing:
            raise FileNotFoundError(f"Paired DBC files not found on disk: {', '.join(missing)}")
        targets = [p for p in pair_map.values() if p is not None]
        if len(targets) != len(set(targets)):
            raise ValueError("New DBC files paired more than once")
        result, files, loaded = self._load_folders(old_folder, new_folder, progress_callback)
        for old_rel in sorted(files["OLD"]):
            new_rel = pair_map.get(old_rel)
            old_db = loaded["OLD"].get(old_rel)
            new_db = loaded["NEW"].get(new_rel) if new_rel is not None else None
            if new_rel is not None:
                label = _format_file_pair_label(old_rel, new_rel)
                if old_db is None or new_db is None:
                    self._not_compared(result, "OLD", old_rel, old_db)
                    self._not_compared(result, "NEW", new_rel, new_db)
                    result.file_pairs.append(_file_pair_summary(
                        label=label, status="Parse Error", old_path=old_rel,
                        new_path=new_rel, old_db=old_db, new_db=new_db,
                    ))
                else:
                    if progress_callback:
                        progress_callback(f"Comparing (manual pair): {label}")
                    self.compare_databases(label, old_db, new_db, result)
                    result.file_pairs.append(_file_pair_summary(
                        label=label, status="Matched" if old_rel == new_rel else "Manually Paired",
                        old_path=old_rel, new_path=new_rel, old_db=old_db, new_db=new_db,
                    ))
            elif old_db is None:
                result.file_pairs.append(_file_pair_summary(
                    label=old_rel, status="Parse Error", old_path=old_rel, new_path="",
                ))
            else:
                self.compare_databases(old_rel, old_db, DbcDatabase(path=Path(old_rel)),
                                       result, present_new=False)
                result.file_pairs.append(_file_pair_summary(
                    label=old_rel, status="DBC Removed", old_path=old_rel,
                    new_path="", old_db=old_db,
                ))
        for new_rel in sorted(files["NEW"].keys() - set(targets)):
            new_db = loaded["NEW"].get(new_rel)
            if new_db is None:
                result.file_pairs.append(_file_pair_summary(
                    label=new_rel, status="Parse Error", old_path="", new_path=new_rel,
                ))
            else:
                self.compare_databases(new_rel, DbcDatabase(path=Path(new_rel)),
                                       new_db, result, present_old=False)
                result.file_pairs.append(_file_pair_summary(
                    label=new_rel, status="DBC Added", old_path="",
                    new_path=new_rel, new_db=new_db,
                ))
        return result

    @staticmethod
    def _not_compared(result, side, rel, db):
        if db is None:
            return
        for entity in _entities(side, db):
            result.inventory[entity] = "not compared"

    def compare_databases(
        self,
        dbc_file: str,
        old_db: DbcDatabase,
        new_db: DbcDatabase,
        result: ComparisonResult | None = None,
        *,
        present_old: bool = True,
        present_new: bool = True,
    ) -> ComparisonResult:
        validate_database(old_db)
        validate_database(new_db)
        dbc_file = _format_file_pair_label(*dbc_file.split(" -> ", 1))
        if result is None:
            validate_ecu_map(self.ecu_map, database_ecu_nodes(old_db), database_ecu_nodes(new_db))
            result = ComparisonResult(policy_version="classic-v067")
        result.policy_version = "classic-v067"
        for side, db, present in (("OLD", old_db, present_old), ("NEW", new_db, present_new)):
            if present:
                for entity in _entities(side, db):
                    if entity in result.inventory:
                        raise AssertionError(f"Inventory registered twice: {entity}")
                    result.inventory[entity] = "unmatched"
        if present_old and present_new:
            result.inventory[EntityIdentity("OLD", str(old_db.path), "dbc")] = "paired"
            result.inventory[EntityIdentity("NEW", str(new_db.path), "dbc")] = "paired"
        result.ecu_map = dict(self.ecu_map)
        result.include_unchanged = result.include_unchanged or self.include_unchanged
        message_start = len(result.message_changes)
        signal_start = len(result.signal_changes)

        old_by_id = _messages_by_frame_id(old_db)
        new_by_id = _messages_by_frame_id(new_db)

        for frame_id in sorted(set(old_by_id) & set(new_by_id)):
            old_message = old_by_id[frame_id]
            new_message = new_by_id[frame_id]
            description, property_diffs = self._property_changes(old_message, new_message)
            if old_message.name != new_message.name:
                result.message_changes.append(
                    Change(
                        dbc_file=dbc_file,
                        change_type="Renamed",
                        old_name=old_message.name,
                        new_name=new_message.name,
                        confidence=1.0,
                        description=_with_match_reasons(
                            description,
                            ("Identical CAN ID",),
                        ),
                        can_id=new_message.can_id,
                        property_diffs=property_diffs,
                    )
                )
            else:
                if description or self.include_unchanged:
                    result.message_changes.append(
                        Change(
                            dbc_file=dbc_file,
                            change_type="Modified" if description else "Unchanged",
                            old_name=old_message.name,
                            new_name=new_message.name,
                            confidence=None,
                            description=description or "Message properties unchanged",
                            can_id=new_message.can_id,
                            property_diffs=property_diffs,
                        )
                    )
            self._compare_signals(dbc_file, old_message, new_message, result)

        old_only_ids = sorted(set(old_by_id) - set(new_by_id))
        new_only_ids = sorted(set(new_by_id) - set(old_by_id))
        unmatched_old_msgs = [old_by_id[fid] for fid in old_only_ids]
        unmatched_new_msgs = [new_by_id[fid] for fid in new_only_ids]

        # Preserve known names after frame-key matching, before heuristic renames.
        old_by_name = {message.name: message for message in unmatched_old_msgs}
        new_by_name = {message.name: message for message in unmatched_new_msgs}
        common_names = old_by_name.keys() & new_by_name.keys()
        for name in sorted(common_names):
            old_message, new_message = old_by_name[name], new_by_name[name]
            description, property_diffs = self._property_changes(old_message, new_message)
            result.message_changes.append(Change(
                dbc_file=dbc_file,
                change_type="Modified",
                old_name=name,
                new_name=name,
                confidence=None,
                description=description,
                can_id=new_message.can_id,
                property_diffs=property_diffs,
            ))
            self._compare_signals(dbc_file, old_message, new_message, result)

        detector = MessageRenameDetector(ecu_map=self.ecu_map)
        rename_matches = detector.match(
            [message for message in unmatched_old_msgs if message.name not in common_names],
            [message for message in unmatched_new_msgs if message.name not in common_names],
        )

        matched_old_ids = {_frame_key(old_by_name[name]) for name in common_names}
        matched_new_ids = {_frame_key(new_by_name[name]) for name in common_names}
        matched_old_ids.update(_frame_key(match.old) for match in rename_matches)
        matched_new_ids.update(_frame_key(match.new) for match in rename_matches)

        for match in rename_matches:
            old_message = match.old
            new_message = match.new
            description, property_diffs = self._property_changes(old_message, new_message)
            result.message_changes.append(
                Change(
                    dbc_file=dbc_file,
                    change_type="Renamed",
                    old_name=old_message.name,
                    new_name=new_message.name,
                    confidence=match.confidence,
                    confidence_level=match.confidence_level,
                    description=_with_match_reasons(
                        description,
                        match.reasons,
                    ),
                    can_id=new_message.can_id,
                    property_diffs=property_diffs,
                )
            )
            self._compare_signals(dbc_file, old_message, new_message, result)

        for frame_id in old_only_ids:
            if frame_id in matched_old_ids:
                continue
            message = old_by_id[frame_id]
            result.message_changes.append(
                Change(dbc_file, "Removed", message.name, "", None, "Message removed", message.can_id)
            )
            self._append_all_signals(dbc_file, message, "Removed", result)

        for frame_id in new_only_ids:
            if frame_id in matched_new_ids:
                continue
            message = new_by_id[frame_id]
            result.message_changes.append(
                Change(dbc_file, "Added", "", message.name, None, "Message added", message.can_id)
            )
            self._append_all_signals(dbc_file, message, "Added", result)

        for index in range(message_start, len(result.message_changes)):
            change = result.message_changes[index]
            result.message_changes[index] = replace(
                change,
                old_message=old_db.messages.get(change.old_name),
                new_message=new_db.messages.get(change.new_name),
            )
        paired_messages = [(old_by_id[key], new_by_id[key]) for key in old_by_id.keys() & new_by_id.keys()]
        paired_messages += [
            (change.old_message, change.new_message)
            for change in result.message_changes[message_start:]
            if change.old_message is not None and change.new_message is not None
        ]
        for old_message, new_message in paired_messages:
            for side, db, message in (("OLD", old_db, old_message), ("NEW", new_db, new_message)):
                result.inventory[_entity(side, db, message)] = "paired"
            for name in old_message.signals.keys() & new_message.signals.keys():
                result.inventory[_entity("OLD", old_db, old_message, old_message.signals[name])] = "paired"
                result.inventory[_entity("NEW", new_db, new_message, new_message.signals[name])] = "paired"
        for change in result.signal_changes[signal_start:]:
            if change.old_signal is not None and change.new_signal is not None:
                result.inventory[_entity("OLD", old_db, change.old_message, change.old_signal)] = "paired"
                result.inventory[_entity("NEW", new_db, change.new_message, change.new_signal)] = "paired"
        return result

    def _compare_signals(
        self,
        dbc_file: str,
        old_message: Message,
        new_message: Message,
        result: ComparisonResult,
    ) -> None:
        parent_name = new_message.name
        signal_start = len(result.signal_changes)
        common_names = sorted(set(old_message.signals) & set(new_message.signals))
        matched_old = set(common_names)
        matched_new = set(common_names)

        for name in common_names:
            old_signal = old_message.signals[name]
            new_signal = new_message.signals[name]
            description, property_diffs = self._property_changes(old_signal, new_signal)
            if description or self.include_unchanged:
                result.signal_changes.append(
                    Change(
                        dbc_file, "Modified" if description else "Unchanged", name, name,
                        None, description or "Signal properties unchanged",
                        parent_message=parent_name,
                        property_diffs=property_diffs,
                    )
                )

        unmatched_old = [signal for name, signal in old_message.signals.items() if name not in matched_old]
        unmatched_new = [signal for name, signal in new_message.signals.items() if name not in matched_new]

        # Detect if this is an event-like message and create appropriate detector
        is_event_like = EventMessageDetector.is_event_like(old_message) or EventMessageDetector.is_event_like(new_message)
        signal_detector = SignalRenameDetector(is_event_like=is_event_like, ecu_map=self.ecu_map)
        rename_matches = signal_detector.match(unmatched_old, unmatched_new)

        for match in rename_matches:
            old_signal = match.old
            new_signal = match.new
            description, property_diffs = self._property_changes(old_signal, new_signal)
            result.signal_changes.append(
                Change(
                    dbc_file=dbc_file,
                    parent_message=parent_name,
                    change_type="Renamed",
                    old_name=old_signal.name,
                    new_name=new_signal.name,
                    confidence=match.confidence,
                    confidence_level=match.confidence_level,
                    description=_with_match_reasons(
                        description,
                        match.reasons,
                    ),
                    property_diffs=property_diffs,
                )
            )
            matched_old.add(old_signal.name)
            matched_new.add(new_signal.name)

        new_signal_keys = {signal.signal_key() for signal in new_message.signals.values()}
        old_signal_keys = {signal.signal_key() for signal in old_message.signals.values()}

        for name, signal in old_message.signals.items():
            if name in matched_old:
                continue
            if signal.signal_key() not in new_signal_keys:
                description = "Signal removed"
            else:
                description = "Signal removed after layout/name change"
            result.signal_changes.append(
                Change(dbc_file, "Removed", signal.name, "", None, description, parent_message=parent_name)
            )

        for name, signal in new_message.signals.items():
            if name in matched_new:
                continue
            if signal.signal_key() not in old_signal_keys:
                description = "Signal added"
            else:
                description = "Signal added after layout/name change"
            result.signal_changes.append(
                Change(dbc_file, "Added", "", signal.name, None, description, parent_message=parent_name)
            )

        for index in range(signal_start, len(result.signal_changes)):
            change = result.signal_changes[index]
            result.signal_changes[index] = replace(
                change,
                can_id=new_message.can_id if change.new_name else old_message.can_id,
                old_message=old_message,
                new_message=new_message,
                old_signal=old_message.signals.get(change.old_name),
                new_signal=new_message.signals.get(change.new_name),
            )

    def _append_all_signals(self, dbc_file: str, message: Message, change_type: str, result: ComparisonResult) -> None:
        for signal in message.signals.values():
            result.signal_changes.append(
                Change(
                    dbc_file=dbc_file,
                    parent_message=message.name,
                    change_type=change_type,
                    old_name=signal.name if change_type == "Removed" else "",
                    new_name=signal.name if change_type == "Added" else "",
                    confidence=None,
                    description=f"Signal {change_type.lower()} with parent message",
                    can_id=message.can_id,
                    old_message=message if change_type == "Removed" else None,
                    new_message=message if change_type == "Added" else None,
                    old_signal=signal if change_type == "Removed" else None,
                    new_signal=signal if change_type == "Added" else None,
                )
            )


def filter_result(result: ComparisonResult, selected_types: set[str]) -> ComparisonResult:
    """Keep only the change types the user asked for.

    An empty selection means "no filter" and returns the result unchanged.
    Include Unchanged bypasses type filtering to preserve the complete inventory.
    File pairs are always preserved so the DBC Overview sheet still lists
    every compared file, including the ones whose changes were filtered out.
    """
    if not selected_types or result.include_unchanged:
        return result
    return replace(
        result,
        message_changes=[c for c in result.message_changes if c.change_type in selected_types],
        signal_changes=[c for c in result.signal_changes if c.change_type in selected_types],
        ecu_map=dict(result.ecu_map),
    )


def _get_property_diffs(
    old: dict[str, object], new: dict[str, object], changed_keys: set[str] | None = None,
) -> tuple[tuple[str, str, str], ...]:
    if changed_keys is None:
        changed_keys = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
    diffs: list[tuple[str, str, str]] = []
    for key in _ordered_changed_keys(changed_keys):
        label = PROPERTY_LABELS.get(key, key)
        diffs.append((label, _format_property_value(key, old.get(key)), _format_property_value(key, new.get(key))))
    return tuple(diffs)


def _changed_properties(
    old: dict[str, object], new: dict[str, object], changed_keys: set[str] | None = None,
) -> str:
    if changed_keys is None:
        changed_keys = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
    if not changed_keys:
        return ""

    changes: list[str] = []
    layout_keys = [key for key in LAYOUT_PROPERTIES if key in changed_keys]
    if layout_keys:
        changes.append(f"Layout changed: {_format_change_segments(layout_keys, old, new)}")

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


def _format_change_segments(keys: list[str], old: dict[str, object], new: dict[str, object]) -> str:
    return ", ".join(_format_change_segment(key, old.get(key), new.get(key)) for key in keys)


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


def _entity(side: str, db: DbcDatabase, message: Message | None = None,
            signal: Signal | None = None) -> EntityIdentity:
    if message is None:
        return EntityIdentity(side, str(db.path), "dbc")
    if signal is None:
        return EntityIdentity(side, str(db.path), "message", message.can_id,
                              message.is_extended_frame, message.name)
    return EntityIdentity(side, str(db.path), "signal", message.can_id,
                          message.is_extended_frame, message.name, signal.name)


def _entities(side: str, db: DbcDatabase):
    yield _entity(side, db)
    for message in db.messages.values():
        yield _entity(side, db, message)
        for signal in message.signals.values():
            yield _entity(side, db, message, signal)


def _messages_by_frame_id(database: DbcDatabase) -> dict[tuple[int, bool], Message]:
    # validate_database rejects duplicate keys before this index is built.
    return {_frame_key(message): message for message in database.messages.values()}


def _frame_key(message: Message) -> tuple[int, bool]:
    return (message.can_id, message.is_extended_frame)


def _format_file_pair_label(old_relative_path: str, new_relative_path: str = "") -> str:
    """Keep only filenames in display labels; paths live in DBC Overview."""
    return " -> ".join(
        PureWindowsPath(path).name for path in (old_relative_path, new_relative_path) if path
    )


def _count_signals(db: DbcDatabase) -> int:
    return sum(len(msg.signals) for msg in db.messages.values())


def _file_pair_summary(
    *,
    label: str,
    status: str,
    old_path: str,
    new_path: str,
    old_db: DbcDatabase | None = None,
    new_db: DbcDatabase | None = None,
    pairing_confidence: float | None = None,
    pairing_reasons: tuple[str, ...] = (),
) -> FilePairSummary:
    def counts(db: DbcDatabase | None, path: str) -> tuple[int | None, int | None]:
        if db is not None:
            return len(db.messages), _count_signals(db)
        if status == "Parse Error" and path:
            return None, None
        return 0, 0

    old_messages, old_signals = counts(old_db, old_path)
    new_messages, new_signals = counts(new_db, new_path)
    return FilePairSummary(
        dbc_file=_format_file_pair_label(*label.split(" -> ", 1)),
        status=status,
        old_path=old_path,
        new_path=new_path,
        pairing_confidence=pairing_confidence,
        pairing_reasons=pairing_reasons,
        message_count_old=old_messages,
        message_count_new=new_messages,
        signal_count_old=old_signals,
        signal_count_new=new_signals,
    )
