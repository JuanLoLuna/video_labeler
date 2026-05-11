import csv
from dataclasses import dataclass


START_MARKER = "label_start"
END_MARKER = "label_end"
SUPPORTED_MARKERS = {START_MARKER, END_MARKER}
REQUIRED_COLUMNS = {"record_frame_index", "sync_label", "adl_id", "adl_label"}


@dataclass(frozen=True)
class ImportedLabelEvent:
    csv_frame_index: int
    frame_index: int
    sync_label: str
    adl_id: str
    adl_label: str
    row_number: int

    @property
    def display_label(self) -> str:
        return self.adl_label or self.adl_id or "Unlabeled"

    @property
    def is_start(self) -> bool:
        return self.sync_label == START_MARKER

    @property
    def is_end(self) -> bool:
        return self.sync_label == END_MARKER


@dataclass(frozen=True)
class ImportedLabelRange:
    label_id: str
    label: str
    start_frame: int | None
    end_frame: int | None
    start_csv_frame_index: int | None
    end_csv_frame_index: int | None
    start_row_number: int | None
    end_row_number: int | None

    @property
    def is_complete(self) -> bool:
        return (
            self.start_frame is not None
            and self.end_frame is not None
            and self.start_csv_frame_index is not None
            and self.end_csv_frame_index is not None
        )


def load_metadata_events(csv_path: str) -> list[ImportedLabelEvent]:
    fieldnames, rows = _read_metadata_rows(csv_path)

    events: list[ImportedLabelEvent] = []
    for row_number, row in enumerate(rows, start=2):
        sync_label = (row.get("sync_label") or "").strip()
        if sync_label not in SUPPORTED_MARKERS:
            continue

        csv_frame_index = _parse_frame_index(row.get("record_frame_index"), row_number)
        events.append(
            ImportedLabelEvent(
                csv_frame_index=csv_frame_index,
                frame_index=max(0, csv_frame_index - 1),
                sync_label=sync_label,
                adl_id=(row.get("adl_id") or "").strip(),
                adl_label=(row.get("adl_label") or "").strip(),
                row_number=row_number,
            )
        )

    return events


def pair_label_events(
    events: list[ImportedLabelEvent],
) -> tuple[list[ImportedLabelRange], list[str]]:
    pending_by_label: dict[tuple[str, str], list[ImportedLabelEvent]] = {}
    ranges: list[ImportedLabelRange] = []
    warnings: list[str] = []

    for event in sorted(events, key=lambda item: (item.frame_index, item.row_number)):
        label_key = ((event.adl_id or "").strip(), event.display_label)

        if event.is_start:
            pending_by_label.setdefault(label_key, []).append(event)
            continue

        pending = pending_by_label.get(label_key)
        if not pending:
            ranges.append(
                ImportedLabelRange(
                    label_id=event.adl_id,
                    label=event.display_label,
                    start_frame=None,
                    end_frame=event.frame_index,
                    start_csv_frame_index=None,
                    end_csv_frame_index=event.csv_frame_index,
                    start_row_number=None,
                    end_row_number=event.row_number,
                )
            )
            warnings.append(
                f"Imported incomplete range for '{event.display_label}' at CSV frame "
                f"{event.csv_frame_index}: no matching start marker."
            )
            continue

        start_event = pending.pop()
        if event.frame_index < start_event.frame_index:
            warnings.append(
                f"Skipped range for '{event.display_label}' because end marker "
                f"{event.csv_frame_index} comes before start marker "
                f"{start_event.csv_frame_index}."
            )
            continue

        ranges.append(
            ImportedLabelRange(
                label_id=event.adl_id or start_event.adl_id,
                label=event.display_label,
                start_frame=start_event.frame_index,
                end_frame=event.frame_index,
                start_csv_frame_index=start_event.csv_frame_index,
                end_csv_frame_index=event.csv_frame_index,
                start_row_number=start_event.row_number,
                end_row_number=event.row_number,
            )
        )

    for pending_events in pending_by_label.values():
        for event in pending_events:
            ranges.append(
                ImportedLabelRange(
                    label_id=event.adl_id,
                    label=event.display_label,
                    start_frame=event.frame_index,
                    end_frame=None,
                    start_csv_frame_index=event.csv_frame_index,
                    end_csv_frame_index=None,
                    start_row_number=event.row_number,
                    end_row_number=None,
                )
            )
            warnings.append(
                f"Imported incomplete range for '{event.display_label}' at CSV frame "
                f"{event.csv_frame_index}: no matching end marker."
            )

    ranges.sort(
        key=lambda item: (
            item.start_frame if item.start_frame is not None else item.end_frame or 0,
            item.end_frame
            if item.end_frame is not None
            else item.start_frame if item.start_frame is not None
            else 0,
            item.label,
        )
    )
    return ranges, warnings


def save_metadata_label_ranges(
    csv_path: str,
    *,
    output_csv_path: str,
    label_ranges: list[ImportedLabelRange],
) -> str:
    fieldnames, rows = _read_metadata_rows(csv_path)
    rows_by_frame = _rows_by_csv_frame_index(rows)

    for row in rows:
        if (row.get("sync_label") or "").strip() in SUPPORTED_MARKERS:
            _clear_marker(row)

    staged_markers: dict[int, tuple[str, str, str]] = {}
    for label_range in label_ranges:
        for csv_frame_index, marker in (
            (label_range.start_csv_frame_index, START_MARKER),
            (label_range.end_csv_frame_index, END_MARKER),
        ):
            if csv_frame_index is None:
                continue
            if csv_frame_index <= 0:
                raise ValueError(
                    f"Frame {csv_frame_index} is not a positive 1-based frame number."
                )
            if csv_frame_index in staged_markers:
                raise ValueError(
                    f"Frame {csv_frame_index} has more than one staged label marker."
                )

            staged_markers[csv_frame_index] = (
                marker,
                label_range.label_id,
                label_range.label,
            )

    for csv_frame_index, (marker, label_id, label) in staged_markers.items():
        row = rows_by_frame.get(csv_frame_index)
        if row is None:
            raise ValueError(f"No CSV row found for frame {csv_frame_index}.")

        existing_marker = (row.get("sync_label") or "").strip()
        if existing_marker and existing_marker not in SUPPORTED_MARKERS:
            raise ValueError(
                f"Frame {csv_frame_index} contains non-label sync marker "
                f"{existing_marker!r}; choose another frame."
            )

        _set_marker(row, marker, label_id, label)

    _write_metadata_rows(output_csv_path, fieldnames, rows)
    return output_csv_path


def _read_metadata_rows(csv_path: str) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Metadata CSV is missing required columns: {missing}")
        return list(reader.fieldnames or []), list(reader)


def _write_metadata_rows(
    csv_path: str,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rows_by_csv_frame_index(rows: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    rows_by_frame: dict[int, dict[str, str]] = {}
    for row_number, row in enumerate(rows, start=2):
        frame_index = _parse_frame_index(row.get("record_frame_index"), row_number)
        rows_by_frame[frame_index] = row
    return rows_by_frame


def _set_marker(row: dict[str, str], marker: str, label_id: str, label: str) -> None:
    row["sync_label"] = marker
    row["adl_id"] = label_id
    row["adl_label"] = label


def _clear_marker(row: dict[str, str]) -> None:
    row["sync_label"] = ""
    row["adl_id"] = ""
    row["adl_label"] = ""


def _parse_frame_index(value: str | None, row_number: int) -> int:
    if value is None or not str(value).strip():
        raise ValueError(f"Row {row_number} is missing record_frame_index.")

    try:
        return int(float(value))
    except ValueError as exc:
        raise ValueError(
            f"Row {row_number} has an invalid record_frame_index: {value!r}"
        ) from exc
