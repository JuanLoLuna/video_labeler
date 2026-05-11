from pathlib import Path

from src.label_import import (
    ImportedLabelEvent,
    ImportedLabelRange,
    load_metadata_events,
    pair_label_events,
    save_metadata_label_ranges,
)


def test_load_metadata_events_filters_non_label_rows(tmp_path: Path):
    csv_path = tmp_path / "metadata.csv"
    csv_path.write_text(
        "\n".join(
            [
                "record_frame_index,camera_frame_id,timestamp_us,system_time,sync_pulse,sync_label,adl_id,adl_label",
                "1,10,100,1.0,False,,,",
                "2,11,101,1.1,False,label_start,1,Pick up coins from purses",
                "3,12,102,1.2,False,label_end,1,Pick up coins from purses",
            ]
        )
        + "\n"
    )

    events = load_metadata_events(str(csv_path))

    assert [event.sync_label for event in events] == ["label_start", "label_end"]
    assert [event.csv_frame_index for event in events] == [2, 3]
    assert [event.frame_index for event in events] == [1, 2]


def test_pair_label_events_builds_ranges_from_matching_markers():
    events = [
        ImportedLabelEvent(10, 9, "label_start", "1", "Pick up coins from purses", 2),
        ImportedLabelEvent(20, 19, "label_end", "1", "Pick up coins from purses", 3),
    ]

    ranges, warnings = pair_label_events(events)

    assert warnings == []
    assert len(ranges) == 1
    assert ranges[0].start_frame == 9
    assert ranges[0].end_frame == 19
    assert ranges[0].start_csv_frame_index == 10
    assert ranges[0].end_csv_frame_index == 20


def test_pair_label_events_prefers_latest_unmatched_start_and_reports_leftovers():
    events = [
        ImportedLabelEvent(100, 99, "label_start", "13", "Typing on keyboard", 2),
        ImportedLabelEvent(110, 109, "label_start", "13", "Typing on keyboard", 3),
        ImportedLabelEvent(120, 119, "label_end", "13", "Typing on keyboard", 4),
    ]

    ranges, warnings = pair_label_events(events)

    assert len(ranges) == 2
    assert ranges[0].start_csv_frame_index == 100
    assert ranges[0].end_csv_frame_index is None
    assert not ranges[0].is_complete
    assert ranges[1].start_csv_frame_index == 110
    assert ranges[1].end_csv_frame_index == 120
    assert ranges[1].is_complete
    assert len(warnings) == 1
    assert "Imported incomplete range" in warnings[0]
    assert "no matching end marker" in warnings[0]


def test_pair_label_events_imports_unmatched_end_markers():
    events = [
        ImportedLabelEvent(200, 199, "label_end", "4", "Unscrew lid of jars", 2),
    ]

    ranges, warnings = pair_label_events(events)

    assert len(ranges) == 1
    assert ranges[0].start_csv_frame_index is None
    assert ranges[0].end_csv_frame_index == 200
    assert not ranges[0].is_complete
    assert len(warnings) == 1
    assert "Imported incomplete range" in warnings[0]
    assert "no matching start marker" in warnings[0]


def test_save_metadata_label_ranges_adds_staged_range_without_changing_source(tmp_path: Path):
    source_path = tmp_path / "metadata.csv"
    output_path = tmp_path / "metadata_edited.csv"
    source_text = (
        "\n".join(
            [
                "record_frame_index,camera_frame_id,sync_label,adl_id,adl_label",
                "1,10,,,",
                "2,11,,,",
                "3,12,,,",
            ]
        )
        + "\n"
    )
    source_path.write_text(source_text)

    written_path = save_metadata_label_ranges(
        str(source_path),
        output_csv_path=str(output_path),
        label_ranges=[
            ImportedLabelRange(
                label_id="13",
                label="Typing on keyboard",
                start_frame=0,
                end_frame=2,
                start_csv_frame_index=1,
                end_csv_frame_index=3,
                start_row_number=None,
                end_row_number=None,
            )
        ],
    )

    assert written_path == str(output_path)
    assert source_path.read_text() == source_text

    events = load_metadata_events(str(output_path))
    assert [event.sync_label for event in events] == ["label_start", "label_end"]
    assert [event.adl_id for event in events] == ["13", "13"]
    assert [event.adl_label for event in events] == [
        "Typing on keyboard",
        "Typing on keyboard",
    ]


def test_save_metadata_label_ranges_deletes_removed_range_without_changing_source(tmp_path: Path):
    source_path = tmp_path / "metadata.csv"
    output_path = tmp_path / "metadata_deleted.csv"
    source_text = (
        "\n".join(
            [
                "record_frame_index,camera_frame_id,sync_label,adl_id,adl_label",
                "1,10,label_start,13,Typing on keyboard",
                "2,11,,,",
                "3,12,label_end,13,Typing on keyboard",
            ]
        )
        + "\n"
    )
    source_path.write_text(source_text)
    written_path = save_metadata_label_ranges(
        str(source_path),
        output_csv_path=str(output_path),
        label_ranges=[],
    )

    assert written_path == str(output_path)
    assert source_path.read_text() == source_text
    assert load_metadata_events(str(output_path)) == []
