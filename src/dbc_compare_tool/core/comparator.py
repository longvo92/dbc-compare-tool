from __future__ import annotations

import warnings
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PureWindowsPath

from dbc_compare_tool.core.discovery import collect_dbc_files, discover_dbc_pairs
from dbc_compare_tool.core.ecu import (
    collect_ecu_nodes,
    database_ecu_nodes,
    receivers_match,
    transmitters_match,
    validate_dbc_input,
    validate_ecu_map,
)
from dbc_compare_tool.core.models import Change, ComparisonResult, DbcDatabase, FilePairSummary, Message, Signal
from dbc_compare_tool.core.pairing import DatabaseCandidate, match_renamed_databases
from dbc_compare_tool.core.parser import DbcParseError, parse_dbc
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

    def _validate_folder_ecu_map(self, old_folder: Path, new_folder: Path) -> None:
        if self.ecu_map:
            validate_ecu_map(
                self.ecu_map, set(collect_ecu_nodes(old_folder)), set(collect_ecu_nodes(new_folder)),
            )

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

    def compare_folders(
        self,
        old_folder: Path,
        new_folder: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        self._validate_folder_ecu_map(old_folder, new_folder)
        result = ComparisonResult(include_unchanged=self.include_unchanged, ecu_map=dict(self.ecu_map))
        old_only: list[DatabaseCandidate] = []
        new_only: list[DatabaseCandidate] = []

        pairs = list(discover_dbc_pairs(old_folder, new_folder))
        total = len(pairs)

        for i, pair in enumerate(pairs, 1):
            try:
                if pair.old_path and pair.new_path:
                    old_db = parse_dbc(pair.old_path)
                    new_db = parse_dbc(pair.new_path)
                    if progress_callback:
                        progress_callback(f"[{i}/{total}] Comparing: {pair.relative_path}")
                    label = _format_file_pair_label(pair.relative_path, pair.relative_path)
                    self.compare_databases(label, old_db, new_db, result)
                    result.file_pairs.append(_file_pair_summary(
                        label=label,
                        status="Matched",
                        old_path=pair.relative_path,
                        new_path=pair.relative_path,
                        old_db=old_db,
                        new_db=new_db,
                    ))
                elif pair.old_path:
                    old_only.append(DatabaseCandidate(pair.relative_path, parse_dbc(pair.old_path)))
                elif pair.new_path:
                    new_only.append(DatabaseCandidate(pair.relative_path, parse_dbc(pair.new_path)))
            except DbcParseError as exc:
                if progress_callback:
                    progress_callback(f"[{i}/{total}] Parse error, skipped: {pair.relative_path} ({exc})")
                result.file_pairs.append(_file_pair_summary(
                    label=pair.relative_path,
                    status="Parse Error",
                    old_path=pair.relative_path if pair.old_path else "",
                    new_path=pair.relative_path if pair.new_path else "",
                ))

        file_matches = match_renamed_databases(old_only, new_only, self.ecu_map)
        matched_old = {match.old.relative_path for match in file_matches}
        matched_new = {match.new.relative_path for match in file_matches}

        for match in file_matches:
            label = _format_file_pair_label(match.old.relative_path, match.new.relative_path)
            if progress_callback:
                progress_callback(f"Comparing renamed DBC: {label} ({match.confidence:.2f}; {'; '.join(match.reasons)})")
            self.compare_databases(label, match.old.database, match.new.database, result)
            result.file_pairs.append(_file_pair_summary(
                label=label,
                status="DBC Renamed",
                old_path=match.old.relative_path,
                new_path=match.new.relative_path,
                pairing_confidence=match.confidence,
                pairing_reasons=match.reasons,
                old_db=match.old.database,
                new_db=match.new.database,
            ))

        for candidate in old_only:
            if candidate.relative_path not in matched_old:
                if progress_callback:
                    progress_callback(f"DBC removed: {candidate.relative_path}")
                self.compare_databases(
                    candidate.relative_path,
                    candidate.database,
                    DbcDatabase(path=Path(candidate.relative_path)),
                    result,
                )
                result.file_pairs.append(_file_pair_summary(
                    label=candidate.relative_path,
                    status="DBC Removed",
                    old_path=candidate.relative_path,
                    new_path="",
                    old_db=candidate.database,
                ))

        for candidate in new_only:
            if candidate.relative_path not in matched_new:
                if progress_callback:
                    progress_callback(f"DBC added: {candidate.relative_path}")
                self.compare_databases(
                    candidate.relative_path,
                    DbcDatabase(path=Path(candidate.relative_path)),
                    candidate.database,
                    result,
                )
                result.file_pairs.append(_file_pair_summary(
                    label=candidate.relative_path,
                    status="DBC Added",
                    old_path="",
                    new_path=candidate.relative_path,
                    new_db=candidate.database,
                ))

        return result

    def compare_manual(
        self,
        old_folder: Path,
        new_folder: Path,
        pair_map: dict[str, str | None],
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        """Compare using user-defined file pairs.

        pair_map maps an old-file relative path to a new-file relative path,
        or None to force the old file to be reported as removed. New files not
        referenced by any pair are reported as added. Each new file may be
        paired with at most one old file.
        """
        self._validate_folder_ecu_map(old_folder, new_folder)
        result = ComparisonResult(include_unchanged=self.include_unchanged, ecu_map=dict(self.ecu_map))
        old_files = collect_dbc_files(old_folder)
        new_files = collect_dbc_files(new_folder)

        missing = [rel for rel in pair_map if rel not in old_files]
        missing += [rel for rel in pair_map.values() if rel and rel not in new_files]
        if missing:
            raise FileNotFoundError(f"Paired DBC files not found on disk: {', '.join(missing)}")

        paired_new_list = [rel for rel in pair_map.values() if rel]
        duplicate_new = sorted(rel for rel, count in Counter(paired_new_list).items() if count > 1)
        if duplicate_new:
            raise ValueError(f"New DBC files paired more than once: {', '.join(duplicate_new)}")

        paired_new = set(paired_new_list)
        unpaired_new = [rel for rel in sorted(new_files) if rel not in paired_new]
        total = len(old_files) + len(unpaired_new)
        step = 0

        for old_rel in sorted(old_files):
            step += 1
            new_rel = pair_map.get(old_rel)
            if new_rel:
                label = _format_file_pair_label(old_rel, new_rel)
                try:
                    old_db = parse_dbc(old_files[old_rel])
                    new_db = parse_dbc(new_files[new_rel])
                except DbcParseError as exc:
                    if progress_callback:
                        progress_callback(f"[{step}/{total}] Parse error, skipped: {label} ({exc})")
                    result.file_pairs.append(_file_pair_summary(
                        label=label,
                        status="Parse Error",
                        old_path=old_rel,
                        new_path=new_rel,
                    ))
                    continue
                if progress_callback:
                    progress_callback(f"[{step}/{total}] Comparing (manual pair): {label}")
                self.compare_databases(label, old_db, new_db, result)
                result.file_pairs.append(_file_pair_summary(
                    label=label,
                    status="Matched" if old_rel == new_rel else "Manually Paired",
                    old_path=old_rel,
                    new_path=new_rel,
                    old_db=old_db,
                    new_db=new_db,
                ))
            else:
                try:
                    old_db = parse_dbc(old_files[old_rel])
                except DbcParseError as exc:
                    if progress_callback:
                        progress_callback(f"[{step}/{total}] Parse error, skipped: {old_rel} ({exc})")
                    result.file_pairs.append(_file_pair_summary(
                        label=old_rel,
                        status="Parse Error",
                        old_path=old_rel,
                        new_path="",
                    ))
                    continue
                if progress_callback:
                    progress_callback(f"[{step}/{total}] DBC removed: {old_rel}")
                self.compare_databases(old_rel, old_db, DbcDatabase(path=Path(old_rel)), result)
                result.file_pairs.append(_file_pair_summary(
                    label=old_rel,
                    status="DBC Removed",
                    old_path=old_rel,
                    new_path="",
                    old_db=old_db,
                ))

        for new_rel in unpaired_new:
            step += 1
            try:
                new_db = parse_dbc(new_files[new_rel])
            except DbcParseError as exc:
                if progress_callback:
                    progress_callback(f"[{step}/{total}] Parse error, skipped: {new_rel} ({exc})")
                result.file_pairs.append(_file_pair_summary(
                    label=new_rel,
                    status="Parse Error",
                    old_path="",
                    new_path=new_rel,
                ))
                continue
            if progress_callback:
                progress_callback(f"[{step}/{total}] DBC added: {new_rel}")
            self.compare_databases(new_rel, DbcDatabase(path=Path(new_rel)), new_db, result)
            result.file_pairs.append(_file_pair_summary(
                label=new_rel,
                status="DBC Added",
                old_path="",
                new_path=new_rel,
                new_db=new_db,
            ))

        return result

    def compare_databases(
        self,
        dbc_file: str,
        old_db: DbcDatabase,
        new_db: DbcDatabase,
        result: ComparisonResult | None = None,
    ) -> ComparisonResult:
        dbc_file = _format_file_pair_label(*dbc_file.split(" -> ", 1))
        if result is None:
            validate_ecu_map(self.ecu_map, database_ecu_nodes(old_db), database_ecu_nodes(new_db))
            result = ComparisonResult()
        result.ecu_map = dict(self.ecu_map)
        result.include_unchanged = result.include_unchanged or self.include_unchanged
        message_start = len(result.message_changes)

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
    return ComparisonResult(
        message_changes=[c for c in result.message_changes if c.change_type in selected_types],
        signal_changes=[c for c in result.signal_changes if c.change_type in selected_types],
        file_pairs=result.file_pairs,
        include_unchanged=result.include_unchanged,
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


def _messages_by_frame_id(database: DbcDatabase) -> dict[tuple[int, bool], Message]:
    # Standard and extended frames share the numeric ID space after masking,
    # so the extended flag must be part of the key to keep them distinct.
    by_id: dict[tuple[int, bool], Message] = {}
    for message in database.messages.values():
        key = _frame_key(message)
        existing = by_id.get(key)
        if existing is not None:
            # Two differently-named messages share one frame ID; the comparison
            # keys everything by frame ID, so one of them would silently drop
            # out of the diff. Keep the last (matching prior behaviour) but warn.
            warnings.warn(
                f"Duplicate frame ID 0x{message.can_id:X} "
                f"(extended={message.is_extended_frame}) in {database.path}: "
                f"'{existing.name}' and '{message.name}'; only '{message.name}' is compared.",
                stacklevel=2,
            )
        by_id[key] = message
    return by_id


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
    return FilePairSummary(
        dbc_file=_format_file_pair_label(*label.split(" -> ", 1)),
        status=status,
        old_path=old_path,
        new_path=new_path,
        pairing_confidence=pairing_confidence,
        pairing_reasons=pairing_reasons,
        message_count_old=len(old_db.messages) if old_db is not None else 0,
        message_count_new=len(new_db.messages) if new_db is not None else 0,
        signal_count_old=_count_signals(old_db) if old_db is not None else 0,
        signal_count_new=_count_signals(new_db) if new_db is not None else 0,
    )
