from __future__ import annotations

import warnings
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from dbc_compare_tool.core.discovery import collect_dbc_files, discover_dbc_pairs
from dbc_compare_tool.core.models import Change, ComparisonResult, DbcDatabase, FilePairSummary, Message, jaccard
from dbc_compare_tool.core.parser import DbcParseError, parse_dbc
from dbc_compare_tool.core.rename import EventMessageDetector, MessageRenameDetector, SignalRenameDetector

FILE_RENAME_THRESHOLD = 0.55
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


class DbcComparator:
    def compare_folders(
        self,
        old_folder: Path,
        new_folder: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ComparisonResult:
        result = ComparisonResult()
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
                    self.compare_databases(pair.relative_path, old_db, new_db, result)
                    result.file_pairs.append(_file_pair_summary(
                        label=pair.relative_path,
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

        file_matches = match_renamed_databases(old_only, new_only)
        matched_old = {match.old.relative_path for match in file_matches}
        matched_new = {match.new.relative_path for match in file_matches}

        for match in file_matches:
            label = _format_file_pair_label(match.old.relative_path, match.new.relative_path)
            if progress_callback:
                progress_callback(f"Comparing renamed DBC: {label}")
            self.compare_databases(label, match.old.database, match.new.database, result)
            result.file_pairs.append(_file_pair_summary(
                label=label,
                status="DBC Renamed",
                old_path=match.old.relative_path,
                new_path=match.new.relative_path,
                pairing_confidence=match.confidence,
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
        result = ComparisonResult()
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
        result = result or ComparisonResult()

        old_by_id = _messages_by_frame_id(old_db)
        new_by_id = _messages_by_frame_id(new_db)

        for frame_id in sorted(set(old_by_id) & set(new_by_id)):
            old_message = old_by_id[frame_id]
            new_message = new_by_id[frame_id]
            old_properties = old_message.comparable_properties()
            new_properties = new_message.comparable_properties()
            if old_message.name != new_message.name:
                result.message_changes.append(
                    Change(
                        dbc_file=dbc_file,
                        change_type="Renamed",
                        old_name=old_message.name,
                        new_name=new_message.name,
                        confidence=1.0,
                        description=_with_match_reasons(
                            _changed_properties(old_properties, new_properties),
                            ("Identical CAN ID",),
                        ),
                        can_id=new_message.can_id,
                        property_diffs=_get_property_diffs(old_properties, new_properties),
                    )
                )
            else:
                description = _changed_properties(old_properties, new_properties)
                if description:
                    result.message_changes.append(
                        Change(
                            dbc_file=dbc_file,
                            change_type="Modified",
                            old_name=old_message.name,
                            new_name=new_message.name,
                            confidence=None,
                            description=description,
                            can_id=new_message.can_id,
                            property_diffs=_get_property_diffs(old_properties, new_properties),
                        )
                    )
            self._compare_signals(dbc_file, old_message, new_message, result)

        old_only_ids = sorted(set(old_by_id) - set(new_by_id))
        new_only_ids = sorted(set(new_by_id) - set(old_by_id))
        unmatched_old_msgs = [old_by_id[fid] for fid in old_only_ids]
        unmatched_new_msgs = [new_by_id[fid] for fid in new_only_ids]

        detector = MessageRenameDetector()
        rename_matches = detector.match(unmatched_old_msgs, unmatched_new_msgs)

        matched_old_ids = {_frame_key(match.old) for match in rename_matches}
        matched_new_ids = {_frame_key(match.new) for match in rename_matches}

        for match in rename_matches:
            old_message = match.old
            new_message = match.new
            old_properties = old_message.comparable_properties()
            new_properties = new_message.comparable_properties()
            result.message_changes.append(
                Change(
                    dbc_file=dbc_file,
                    change_type="Renamed",
                    old_name=old_message.name,
                    new_name=new_message.name,
                    confidence=match.confidence,
                    confidence_level=match.confidence_level,
                    description=_with_match_reasons(
                        _changed_properties(old_properties, new_properties),
                        match.reasons,
                    ),
                    can_id=new_message.can_id,
                    property_diffs=_get_property_diffs(old_properties, new_properties),
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

        return result

    def _compare_signals(
        self,
        dbc_file: str,
        old_message: Message,
        new_message: Message,
        result: ComparisonResult,
    ) -> None:
        parent_name = new_message.name
        common_names = sorted(set(old_message.signals) & set(new_message.signals))
        matched_old = set(common_names)
        matched_new = set(common_names)

        for name in common_names:
            old_signal = old_message.signals[name]
            new_signal = new_message.signals[name]
            old_properties = old_signal.comparable_properties()
            new_properties = new_signal.comparable_properties()
            description = _changed_properties(old_properties, new_properties)
            if description:
                result.signal_changes.append(
                    Change(
                        dbc_file, "Modified", name, name, None, description,
                        parent_message=parent_name,
                        property_diffs=_get_property_diffs(old_properties, new_properties),
                    )
                )

        unmatched_old = [signal for name, signal in old_message.signals.items() if name not in matched_old]
        unmatched_new = [signal for name, signal in new_message.signals.items() if name not in matched_new]

        # Detect if this is an event-like message and create appropriate detector
        is_event_like = EventMessageDetector.is_event_like(old_message) or EventMessageDetector.is_event_like(new_message)
        signal_detector = SignalRenameDetector(is_event_like=is_event_like)
        rename_matches = signal_detector.match(unmatched_old, unmatched_new)

        for match in rename_matches:
            old_signal = match.old
            new_signal = match.new
            old_properties = old_signal.comparable_properties()
            new_properties = new_signal.comparable_properties()
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
                        _changed_properties(old_properties, new_properties),
                        match.reasons,
                    ),
                    property_diffs=_get_property_diffs(old_properties, new_properties),
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
                )
            )


def reject_signal_renames(result: ComparisonResult, rejected_indices: set[int]) -> ComparisonResult:
    """Convert user-rejected signal renames into Removed + Added changes.

    rejected_indices refer to the order of appearance of "Renamed" entries in
    result.signal_changes (0-based).
    """
    if not rejected_indices:
        return result

    signal_changes: list[Change] = []
    rename_index = 0
    for change in result.signal_changes:
        if change.change_type != "Renamed":
            signal_changes.append(change)
            continue
        if rename_index in rejected_indices:
            signal_changes.append(Change(
                dbc_file=change.dbc_file,
                change_type="Removed",
                old_name=change.old_name,
                new_name="",
                confidence=None,
                description="Signal removed (rename rejected by user)",
                parent_message=change.parent_message,
            ))
            signal_changes.append(Change(
                dbc_file=change.dbc_file,
                change_type="Added",
                old_name="",
                new_name=change.new_name,
                confidence=None,
                description="Signal added (rename rejected by user)",
                parent_message=change.parent_message,
            ))
        else:
            signal_changes.append(change)
        rename_index += 1

    return ComparisonResult(
        message_changes=result.message_changes,
        signal_changes=signal_changes,
        file_pairs=result.file_pairs,
    )


def filter_result(result: ComparisonResult, selected_types: set[str]) -> ComparisonResult:
    """Keep only the change types the user asked for.

    An empty selection means "no filter" and returns the result unchanged.
    File pairs are always preserved so the DBC Overview sheet still lists
    every compared file, including the ones whose changes were filtered out.
    """
    if not selected_types:
        return result
    return ComparisonResult(
        message_changes=[c for c in result.message_changes if c.change_type in selected_types],
        signal_changes=[c for c in result.signal_changes if c.change_type in selected_types],
        file_pairs=result.file_pairs,
    )


def _get_property_diffs(
    old: dict[str, object], new: dict[str, object]
) -> tuple[tuple[str, str, str], ...]:
    changed_keys = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
    diffs: list[tuple[str, str, str]] = []
    for key in _ordered_changed_keys(changed_keys):
        label = PROPERTY_LABELS.get(key, key)
        diffs.append((label, _format_property_value(key, old.get(key)), _format_property_value(key, new.get(key))))
    return tuple(diffs)


def _changed_properties(old: dict[str, object], new: dict[str, object]) -> str:
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
        return f"{value:g}"
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


def match_renamed_databases(
    old_candidates: list[DatabaseCandidate],
    new_candidates: list[DatabaseCandidate],
) -> list[DatabaseMatch]:
    """Pair DBC files whose relative paths differ, by CAN ID and structure overlap."""
    candidates: list[DatabaseMatch] = []
    for old in old_candidates:
        for new in new_candidates:
            confidence, reasons = _score_database_pair(old, new)
            if confidence >= FILE_RENAME_THRESHOLD:
                candidates.append(DatabaseMatch(old, new, confidence, reasons))

    candidates.sort(key=lambda item: item.confidence, reverse=True)
    matches: list[DatabaseMatch] = []
    used_old: set[str] = set()
    used_new: set[str] = set()
    for candidate in candidates:
        old_path = candidate.old.relative_path
        new_path = candidate.new.relative_path
        if old_path in used_old or new_path in used_new:
            continue
        matches.append(candidate)
        used_old.add(old_path)
        used_new.add(new_path)
    return matches


def _score_database_pair(old: DatabaseCandidate, new: DatabaseCandidate) -> tuple[float, tuple[str, ...]]:
    old_messages = old.database.messages
    new_messages = new.database.messages
    if not old_messages or not new_messages:
        return 0.0, ()

    old_by_id = {_frame_key(message): message for message in old_messages.values()}
    new_by_id = {_frame_key(message): message for message in new_messages.values()}
    common_ids = set(old_by_id) & set(new_by_id)
    if not common_ids:
        return 0.0, ()

    reasons: list[str] = []
    score = 0.0

    id_overlap = len(common_ids) / max(len(old_by_id), len(new_by_id))
    score += 0.55 * id_overlap
    reasons.append(f"DBC CAN ID overlap {id_overlap:.0%}")

    name_overlap = len(set(old_messages) & set(new_messages)) / max(len(old_messages), len(new_messages))
    if name_overlap:
        score += 0.15 * name_overlap
        reasons.append(f"Message names overlap {name_overlap:.0%}")

    structure_score = _common_message_structure_score(old_by_id, new_by_id, common_ids)
    if structure_score:
        score += 0.25 * structure_score
        reasons.append(f"Common CAN ID structures {structure_score:.0%} matched")

    file_name_score = SequenceMatcher(None, old.relative_path.lower(), new.relative_path.lower()).ratio()
    score += 0.05 * file_name_score
    if file_name_score >= 0.5:
        reasons.append("DBC file names are similar")

    return min(score, 1.0), tuple(reasons)


def _common_message_structure_score(
    old_by_id: dict[tuple[int, bool], Message],
    new_by_id: dict[tuple[int, bool], Message],
    common_ids: set[tuple[int, bool]],
) -> float:
    message_scores: list[float] = []
    for frame_key in common_ids:
        old = old_by_id[frame_key]
        new = new_by_id[frame_key]
        score = 0.0
        if old.dlc == new.dlc:
            score += 0.20
        if old.transmitter == new.transmitter:
            score += 0.15
        if old.cycle_time_ms == new.cycle_time_ms:
            score += 0.10
        if len(old.signals) == len(new.signals):
            score += 0.15
        score += 0.40 * jaccard(old.signal_layout(), new.signal_layout())
        message_scores.append(score)
    return sum(message_scores) / len(message_scores)


def _format_file_pair_label(old_relative_path: str, new_relative_path: str) -> str:
    if old_relative_path == new_relative_path:
        return old_relative_path
    return f"{old_relative_path} -> {new_relative_path}"


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
) -> FilePairSummary:
    return FilePairSummary(
        dbc_file=label,
        status=status,
        old_path=old_path,
        new_path=new_path,
        pairing_confidence=pairing_confidence,
        message_count_old=len(old_db.messages) if old_db is not None else 0,
        message_count_new=len(new_db.messages) if new_db is not None else 0,
        signal_count_old=_count_signals(old_db) if old_db is not None else 0,
        signal_count_new=_count_signals(new_db) if new_db is not None else 0,
    )
