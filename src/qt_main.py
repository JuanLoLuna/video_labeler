import csv
import os
import sys

import cv2

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

try:
    from src.label_import import (
        ImportedLabelEvent,
        ImportedLabelRange,
        load_metadata_events,
        pair_label_events,
        save_metadata_label_ranges,
    )
except ImportError:
    from label_import import (
        ImportedLabelEvent,
        ImportedLabelRange,
        load_metadata_events,
        pair_label_events,
        save_metadata_label_ranges,
    )


DEFAULT_VIDEO_PATH = ""
ADL_STUDY = "ADL"
OCD_SLEEVE_STUDY = "OCD Sleeve"
ADL_LABELS = [
    ("1", "Pick up coins from purses"),
    ("2", "Pick up wooden blocks"),
    ("3", "Pick up nuts and put in bolts"),
    ("4", "Unscrew lid of jars"),
    ("5", "Cut play-doh"),
    ("6", "Writing"),
    ("7", "Pick up telephone and put in ear"),
    ("8", "Pour water from pure pack"),
    ("9", "Pour water from jug"),
    ("10", "Pour water from cup"),
    ("11", "Typing on smartphone"),
    ("12", "Scrolling on smartphone"),
    ("13", "Typing on keyboard"),
    ("14", "Start sensors recording"),
    ("15", "Dynamometer hand grip baseline"),
    ("16", "Dynamometer hand grip active"),
]
OCD_SLEEVE_LABELS = [
    ("symptom_provocation", "Symptom provocation"),
    ("relax", "Relax"),
    ("compulsion", "Compulsion"),
    ("control", "Control"),
]
STUDY_LABELS = {
    ADL_STUDY: ADL_LABELS,
    OCD_SLEEVE_STUDY: OCD_SLEEVE_LABELS,
}
LABEL_TO_STUDY = {
    label: study
    for study, labels in STUDY_LABELS.items()
    for _label_id, label in labels
}


class MainWindow(QMainWindow):
    """
    Video labeling tool with manual annotations plus imported marker playback.
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Qt Video Labeler")

        self.video_path: str | None = None
        self.cap = None
        self.total_frames = 0
        self.fps = 30.0
        self.current_frame_idx = 0
        self.audio_path: str | None = None
        self.audio_output = QAudioOutput(self)
        self.audio_player = QMediaPlayer(self)
        self.audio_player.setAudioOutput(self.audio_output)

        self.annotations: list[dict[str, int | str]] = []
        self.temp_start: int | None = None
        self.temp_end: int | None = None

        self.imported_csv_path: str | None = None
        self.imported_events: list[ImportedLabelEvent] = []
        self.imported_ranges: list[ImportedLabelRange] = []
        self.filtered_imported_ranges: list[ImportedLabelRange] = []

        self.playing = False
        self.playback_end_frame: int | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)

        self._build_ui()
        self._clear_imported_labels()

        if DEFAULT_VIDEO_PATH and os.path.exists(DEFAULT_VIDEO_PATH):
            self.load_video(DEFAULT_VIDEO_PATH)
        else:
            self.video_label.setText("No video loaded. Click 'Open Video' to begin.")

    def load_video(self, path: str):
        if self.cap is not None:
            self.cap.release()

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            QMessageBox.critical(self, "Error", f"Cannot open video:\n{path}")
            return

        self._stop_playback()
        self.cap = cap
        self.video_path = path
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.current_frame_idx = 0

        self.frame_slider.blockSignals(True)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(max(0, self.total_frames - 1))
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)

        self.annotations.clear()
        self.annotation_list.clear()
        self._clear_temp_marks()
        self._clear_imported_labels()

        base_name = os.path.basename(path)
        self.setWindowTitle(f"Qt Video Labeler - {base_name}")
        self._show_frame(0)
        self._update_frame_position_label()

    def _build_ui(self):
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCentralWidget(scroll_area)

        central = QWidget()
        scroll_area.setWidget(central)
        main_layout = QVBoxLayout(central)

        self.video_label = QLabel("No video loaded")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #222; color: #ddd;")
        self.video_label.setMinimumSize(480, 270)
        self.video_label.setScaledContents(True)
        main_layout.addWidget(self.video_label, stretch=4)

        controls_layout = QHBoxLayout()
        self.prev_button = QPushButton("Prev")
        self.back_second_button = QPushButton("-1s")
        self.play_button = QPushButton("Play")
        self.forward_second_button = QPushButton("+1s")
        self.next_button = QPushButton("Next")

        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(max(0, self.total_frames - 1))
        self.frame_slider.setValue(0)

        controls_layout.addWidget(self.prev_button)
        controls_layout.addWidget(self.back_second_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.forward_second_button)
        controls_layout.addWidget(self.next_button)
        controls_layout.addWidget(self.frame_slider)
        self.frame_position_label = QLabel("Frame: – / –")
        controls_layout.addWidget(self.frame_position_label)
        main_layout.addLayout(controls_layout, stretch=0)

        mark_layout = QHBoxLayout()
        self.start_button = QPushButton("Mark Start")
        self.end_button = QPushButton("Mark End")
        mark_layout.addWidget(self.start_button)
        mark_layout.addWidget(self.end_button)
        mark_layout.addStretch(1)
        main_layout.addLayout(mark_layout)

        label_layout = QHBoxLayout()
        self.add_label_button = QPushButton("Add Label")
        self.study_selector = QComboBox()
        self.study_selector.addItems(list(STUDY_LABELS))

        self.label_dropdown = QComboBox()
        self._populate_label_dropdown(ADL_STUDY)

        label_layout.addWidget(QLabel("Study"))
        label_layout.addWidget(self.study_selector)
        label_layout.addWidget(QLabel("Label"))
        label_layout.addWidget(self.label_dropdown, stretch=2)
        label_layout.addWidget(self.add_label_button)
        main_layout.addLayout(label_layout)

        self.mark_status_label = QLabel("Start: –   End: –")
        main_layout.addWidget(self.mark_status_label)

        import_button_layout = QHBoxLayout()
        self.import_labels_button = QPushButton("Import Labels CSV")
        self.load_selected_range_button = QPushButton("Load Selected Range")
        self.play_selected_range_button = QPushButton("Play Selected Range")
        self.delete_imported_range_button = QPushButton("Delete Selected Imported")
        self.save_imported_csv_button = QPushButton("Save Imported List as CSV")
        import_button_layout.addWidget(self.import_labels_button)
        import_button_layout.addWidget(self.load_selected_range_button)
        import_button_layout.addWidget(self.play_selected_range_button)
        import_button_layout.addWidget(self.delete_imported_range_button)
        import_button_layout.addWidget(self.save_imported_csv_button)
        main_layout.addLayout(import_button_layout)

        review_layout = QHBoxLayout()
        review_layout.addWidget(QLabel("Label"))
        self.adl_selector = QComboBox()
        review_layout.addWidget(self.adl_selector, stretch=2)
        review_layout.addWidget(QLabel("Start frame"))
        self.start_frame_input = QLineEdit()
        review_layout.addWidget(self.start_frame_input, stretch=1)
        review_layout.addWidget(QLabel("End frame"))
        self.end_frame_input = QLineEdit()
        review_layout.addWidget(self.end_frame_input, stretch=1)
        main_layout.addLayout(review_layout)

        self.import_status_label = QLabel("No labels imported.")
        main_layout.addWidget(self.import_status_label)

        main_layout.addWidget(QLabel("Imported Label Ranges"))
        self.imported_range_list = QListWidget()
        main_layout.addWidget(self.imported_range_list, stretch=1)

        main_layout.addWidget(QLabel("Manual Annotations"))
        self.annotation_list = QListWidget()
        main_layout.addWidget(self.annotation_list, stretch=1)

        export_layout = QHBoxLayout()
        self.delete_button = QPushButton("Delete Selected")
        self.export_button = QPushButton("Export CSV")
        export_layout.addWidget(self.delete_button)
        export_layout.addWidget(self.export_button)
        export_layout.addStretch(1)
        main_layout.addLayout(export_layout)

        file_layout = QHBoxLayout()
        self.open_button = QPushButton("Open Video")
        self.open_audio_button = QPushButton("Open Audio WAV")
        self.audio_status_label = QLabel("No audio loaded.")
        self.exit_button = QPushButton("Exit")

        file_layout.addWidget(self.open_button)
        file_layout.addWidget(self.open_audio_button)
        file_layout.addWidget(self.audio_status_label, stretch=1)
        file_layout.addWidget(self.exit_button)
        main_layout.addLayout(file_layout)

        self.prev_button.clicked.connect(self.on_prev)
        self.back_second_button.clicked.connect(self.on_back_second)
        self.next_button.clicked.connect(self.on_next)
        self.forward_second_button.clicked.connect(self.on_forward_second)
        self.play_button.clicked.connect(self.on_play_pause)
        self.frame_slider.valueChanged.connect(self.on_slider_changed)

        self.start_button.clicked.connect(self.on_mark_start)
        self.end_button.clicked.connect(self.on_mark_end)
        self.add_label_button.clicked.connect(self.on_add_label)
        self.study_selector.currentTextChanged.connect(self.on_study_changed)

        self.import_labels_button.clicked.connect(self.on_import_labels_csv)
        self.load_selected_range_button.clicked.connect(self.on_load_selected_range)
        self.play_selected_range_button.clicked.connect(self.on_play_selected_range)
        self.delete_imported_range_button.clicked.connect(self.on_delete_imported_csv_label)
        self.save_imported_csv_button.clicked.connect(self.on_save_imported_csv)
        self.imported_range_list.currentRowChanged.connect(self.on_imported_range_selected)
        self.adl_selector.currentIndexChanged.connect(self.on_selected_adl_changed)

        self.delete_button.clicked.connect(self.on_delete_label)
        self.export_button.clicked.connect(self.on_export_csv)
        self.exit_button.clicked.connect(self.close)
        self.open_button.clicked.connect(self.on_open_video)
        self.open_audio_button.clicked.connect(self.on_open_audio)

    def _show_frame(self, frame_idx: int):
        if self.cap is None:
            return

        if frame_idx < 0 or frame_idx >= self.total_frames:
            return

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if not ret:
            return

        self.current_frame_idx = frame_idx

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(q_img)
        self.video_label.setPixmap(pix)

        if self.frame_slider.value() != frame_idx:
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(frame_idx)
            self.frame_slider.blockSignals(False)

        self._update_frame_position_label()

    def _update_frame_position_label(self):
        if self.total_frames <= 0:
            self.frame_position_label.setText("Frame: – / –")
            return

        self.frame_position_label.setText(
            f"Frame: {self.current_frame_idx + 1} / {self.total_frames}"
        )

    def _audio_position_ms_for_frame(self, frame_idx: int) -> int:
        if self.fps <= 0:
            return 0
        return max(0, int(round((frame_idx / self.fps) * 1000)))

    def _sync_audio_to_frame(self, frame_idx: int):
        if self.audio_path is None:
            return
        self.audio_player.setPosition(self._audio_position_ms_for_frame(frame_idx))

    def _start_playback(self, end_frame: int | None = None):
        if self.cap is None:
            QMessageBox.information(self, "No video", "Open a video before starting playback.")
            return

        self.playback_end_frame = end_frame
        self.playing = True
        self.play_button.setText("Pause")
        self._sync_audio_to_frame(self.current_frame_idx)
        if self.audio_path is not None:
            self.audio_player.play()
        interval_ms = int(1000 / self.fps) if self.fps > 0 else 33
        self.timer.start(interval_ms)

    def _stop_playback(self):
        self.playing = False
        self.playback_end_frame = None
        self.play_button.setText("Play")
        self.timer.stop()
        self.audio_player.pause()

    def on_slider_changed(self, value: int):
        was_playing = self.playing
        playback_end_frame = self.playback_end_frame
        if was_playing:
            self._stop_playback()
        self._show_frame(value)
        self._sync_audio_to_frame(value)
        if was_playing:
            self._start_playback(end_frame=playback_end_frame)

    def on_prev(self):
        new_idx = max(0, self.current_frame_idx - 1)
        self._show_frame(new_idx)
        self._sync_audio_to_frame(new_idx)

    def on_back_second(self):
        step = self._one_second_step()
        new_idx = max(0, self.current_frame_idx - step)
        self._show_frame(new_idx)
        self._sync_audio_to_frame(new_idx)

    def on_next(self):
        new_idx = min(self.total_frames - 1, self.current_frame_idx + 1)
        self._show_frame(new_idx)
        self._sync_audio_to_frame(new_idx)

    def on_forward_second(self):
        step = self._one_second_step()
        new_idx = min(self.total_frames - 1, self.current_frame_idx + step)
        self._show_frame(new_idx)
        self._sync_audio_to_frame(new_idx)

    def _one_second_step(self) -> int:
        return max(1, int(round(self.fps)) if self.fps > 0 else 30)

    def on_play_pause(self):
        if self.playing:
            self._stop_playback()
        else:
            self._start_playback()

    def next_frame(self):
        max_frame = self.total_frames - 1
        if max_frame < 0:
            self._stop_playback()
            return

        if self.current_frame_idx >= max_frame:
            self._stop_playback()
            return

        next_idx = self.current_frame_idx + 1
        if self.playback_end_frame is not None:
            next_idx = min(next_idx, self.playback_end_frame)

        self._show_frame(next_idx)

        if self.playback_end_frame is not None and self.current_frame_idx >= self.playback_end_frame:
            self._stop_playback()

    def on_open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open video",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)",
        )
        if path:
            self.load_video(path)

    def on_open_audio(self):
        initial_dir = os.path.dirname(self.video_path) if self.video_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open audio WAV",
            initial_dir,
            "WAV Files (*.wav);;Audio Files (*.wav *.mp3 *.m4a *.aac *.flac);;All Files (*)",
        )
        if not path:
            return

        self.audio_path = path
        self.audio_player.setSource(QUrl.fromLocalFile(path))
        self._sync_audio_to_frame(self.current_frame_idx)
        self.audio_status_label.setText(f"Audio: {os.path.basename(path)}")

    def _clear_temp_marks(self):
        self.temp_start = None
        self.temp_end = None
        self._update_mark_status()

    def _update_mark_status(self):
        start_txt = str(self.temp_start) if self.temp_start is not None else "–"
        end_txt = str(self.temp_end) if self.temp_end is not None else "–"
        self.mark_status_label.setText(f"Start: {start_txt}   End: {end_txt}")

    def _populate_label_dropdown(self, study: str):
        current_label_key = self.label_dropdown.currentData()
        self.label_dropdown.blockSignals(True)
        self.label_dropdown.clear()
        for label_id, label in STUDY_LABELS.get(study, ADL_LABELS):
            self.label_dropdown.addItem(label, (label_id, label))
        self.label_dropdown.blockSignals(False)

        if isinstance(current_label_key, tuple):
            for index in range(self.label_dropdown.count()):
                if self.label_dropdown.itemData(index) == current_label_key:
                    self.label_dropdown.setCurrentIndex(index)
                    return

    def on_study_changed(self, study: str):
        self._populate_label_dropdown(study)

    def on_mark_start(self):
        self.temp_start = self.current_frame_idx
        self._update_mark_status()

    def on_mark_end(self):
        self.temp_end = self.current_frame_idx
        self._update_mark_status()

    def on_add_label(self):
        if self.temp_start is None or self.temp_end is None:
            QMessageBox.warning(self, "Missing Marks", "Please mark both start and end frames first.")
            return

        start = min(self.temp_start, self.temp_end)
        end = max(self.temp_start, self.temp_end)
        label = self.label_dropdown.currentText()

        if self.imported_csv_path is not None:
            if start == end:
                QMessageBox.warning(
                    self,
                    "Invalid range",
                    "Imported CSV labels need different start and end frames.",
                )
                return
            self._add_imported_range_from_marks(start, end)
            self._clear_temp_marks()
            return

        annotation = {"start": start, "end": end, "label": label}
        self.annotations.append(annotation)
        self.annotation_list.addItem(QListWidgetItem(f"{label}: {start}–{end}"))
        self._clear_temp_marks()

    def on_delete_label(self):
        row = self.annotation_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "No selection", "Please select an annotation to delete.")
            return

        self.annotation_list.takeItem(row)
        if 0 <= row < len(self.annotations):
            del self.annotations[row]

    def on_export_csv(self):
        if not self.annotations:
            QMessageBox.information(self, "No annotations", "There are no annotations to export.")
            return

        if self.video_path:
            video_dir = os.path.dirname(self.video_path)
            video_stem = os.path.splitext(os.path.basename(self.video_path))[0]
            default_name = os.path.join(video_dir, f"{video_stem}_labels.csv")
        else:
            default_name = "annotations.csv"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export annotations",
            default_name,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["start_frame", "end_frame", "label"])
            for ann in self.annotations:
                writer.writerow([ann["start"], ann["end"], ann["label"]])

        QMessageBox.information(self, "Export complete", f"Annotations exported to:\n{path}")

    def _clear_imported_labels(self):
        self.imported_csv_path = None
        self.imported_events.clear()
        self.imported_ranges.clear()
        self.filtered_imported_ranges.clear()
        self.imported_range_list.clear()
        self.adl_selector.clear()
        self.start_frame_input.clear()
        self.end_frame_input.clear()
        self.import_status_label.setText("No labels imported.")
        self._set_import_controls_enabled(False)

    def _set_import_controls_enabled(self, enabled: bool):
        self.adl_selector.setEnabled(enabled)
        self.start_frame_input.setEnabled(enabled)
        self.end_frame_input.setEnabled(enabled)
        self.load_selected_range_button.setEnabled(enabled)
        self.play_selected_range_button.setEnabled(enabled)
        self.delete_imported_range_button.setEnabled(enabled)
        self.save_imported_csv_button.setEnabled(enabled)
        self.imported_range_list.setEnabled(enabled)

    def on_import_labels_csv(self):
        initial_dir = os.path.dirname(self.video_path) if self.video_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import label metadata CSV",
            initial_dir,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            events = load_metadata_events(path)
            ranges, warnings = pair_label_events(events)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return

        self.imported_csv_path = path
        self.imported_events = events
        self.imported_ranges = ranges
        self._populate_import_controls()
        self._set_manual_study(self._infer_imported_study())

        summary = (
            f"Imported {len(events)} markers and {len(ranges)} ranges from "
            f"{os.path.basename(path)}."
        )
        if not events:
            summary = (
                f"Selected {os.path.basename(path)}. No label_start or label_end "
                "markers found yet."
            )
        self.import_status_label.setText(summary)

        if warnings:
            preview = "\n".join(warnings[:5])
            extra_count = len(warnings) - min(len(warnings), 5)
            if extra_count > 0:
                preview += f"\n... plus {extra_count} more."
            QMessageBox.information(
                self,
                "Imported with notes",
                f"{summary}\n\n{preview}",
            )

    def _populate_import_controls(self):
        self.adl_selector.blockSignals(True)
        self.adl_selector.clear()

        seen_adls: set[tuple[str, str]] = set()
        for adl_key in self._import_label_options():
            self.adl_selector.addItem(self._format_adl_text(*adl_key), adl_key)
            seen_adls.add(adl_key)

        for label_range in self.imported_ranges:
            adl_key = (label_range.label_id, label_range.label)
            if adl_key in seen_adls:
                continue
            seen_adls.add(adl_key)
            self.adl_selector.addItem(self._format_adl_text(*adl_key), adl_key)

        self.adl_selector.blockSignals(False)

        enabled = self.imported_csv_path is not None
        self._set_import_controls_enabled(enabled)

        if enabled:
            self.adl_selector.setCurrentIndex(0)
            self._refresh_imported_range_list()
        else:
            self.imported_range_list.clear()
            self.start_frame_input.clear()
            self.end_frame_input.clear()

    def _import_label_options(self) -> list[tuple[str, str]]:
        study = self._infer_imported_study()
        return list(STUDY_LABELS.get(study, ADL_LABELS))

    def _infer_imported_study(self) -> str:
        for label_range in self.imported_ranges:
            study = LABEL_TO_STUDY.get(label_range.label)
            if study:
                return study

        if self.imported_csv_path:
            csv_name = os.path.basename(self.imported_csv_path).lower()
            if "ocd" in csv_name or "sleeve" in csv_name:
                return OCD_SLEEVE_STUDY

        return ADL_STUDY

    def _set_manual_study(self, study: str):
        for index in range(self.study_selector.count()):
            if self.study_selector.itemText(index) == study:
                self.study_selector.setCurrentIndex(index)
                return
        self._populate_label_dropdown(study)

    def _format_adl_text(self, adl_id: str, label: str) -> str:
        if adl_id:
            return f"{adl_id} | {label}"
        return label

    def _format_range_text(self, index: int, label_range: ImportedLabelRange) -> str:
        start_text = (
            str(label_range.start_csv_frame_index)
            if label_range.start_csv_frame_index is not None
            else "NO START"
        )
        end_text = (
            str(label_range.end_csv_frame_index)
            if label_range.end_csv_frame_index is not None
            else "NO END"
        )
        return (
            f"{index:03d}: start {start_text}   "
            f"end {end_text}"
        )

    def on_selected_adl_changed(self, _index: int):
        self._refresh_imported_range_list()

    def _refresh_imported_range_list(self):
        adl_key = self.adl_selector.currentData()
        if not isinstance(adl_key, tuple):
            self.filtered_imported_ranges = []
        else:
            self.filtered_imported_ranges = [
                label_range
                for label_range in self.imported_ranges
                if (label_range.label_id, label_range.label) == adl_key
            ]

        self.imported_range_list.clear()
        for index, label_range in enumerate(self.filtered_imported_ranges, start=1):
            item = QListWidgetItem(self._format_range_text(index, label_range))
            item.setData(Qt.ItemDataRole.UserRole, label_range)
            if not label_range.is_complete:
                item.setForeground(QBrush(QColor("red")))
            self.imported_range_list.addItem(item)

        adl_text = self.adl_selector.currentText()
        if adl_text and self.filtered_imported_ranges:
            incomplete_count = sum(1 for item in self.filtered_imported_ranges if not item.is_complete)
            status = f"{adl_text}: {len(self.filtered_imported_ranges)} imported ranges"
            if incomplete_count:
                status += f" ({incomplete_count} incomplete)"
            self.import_status_label.setText(
                status
            )
            self.imported_range_list.setCurrentRow(0)
        elif adl_text:
            self.import_status_label.setText(f"{adl_text}: no complete start/end ranges")
            self.start_frame_input.clear()
            self.end_frame_input.clear()

    def on_imported_range_selected(self, row: int):
        if row < 0 or row >= self.imported_range_list.count():
            self.start_frame_input.clear()
            self.end_frame_input.clear()
            return

        item = self.imported_range_list.item(row)
        label_range = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(label_range, ImportedLabelRange):
            self.start_frame_input.clear()
            self.end_frame_input.clear()
            return

        if label_range.start_csv_frame_index is None:
            self.start_frame_input.clear()
        else:
            self.start_frame_input.setText(str(label_range.start_csv_frame_index))

        if label_range.end_csv_frame_index is None:
            self.end_frame_input.clear()
        else:
            self.end_frame_input.setText(str(label_range.end_csv_frame_index))

    def _selected_range_bounds(self) -> tuple[int, int] | None:
        if self.cap is None:
            QMessageBox.information(self, "No video", "Open a video before loading imported ranges.")
            return None
        if self.total_frames <= 0:
            QMessageBox.information(self, "No frames", "The loaded video does not contain any frames.")
            return None

        start_frame_text = self.start_frame_input.text().strip()
        end_frame_text = self.end_frame_input.text().strip()
        if not start_frame_text or not end_frame_text:
            QMessageBox.information(
                self,
                "No range",
                "Select an imported range or enter start and end frames.",
            )
            return None

        try:
            start_csv_frame = int(start_frame_text)
            end_csv_frame = int(end_frame_text)
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid frame",
                "Start frame and end frame must be integer frame numbers.",
            )
            return None

        if start_csv_frame <= 0 or end_csv_frame <= 0:
            QMessageBox.warning(
                self,
                "Invalid frame",
                "Start frame and end frame must be positive 1-based frame numbers.",
            )
            return None

        start_frame = max(0, min(self.total_frames - 1, start_csv_frame - 1))
        end_frame = max(0, min(self.total_frames - 1, end_csv_frame - 1))
        if start_frame > end_frame:
            QMessageBox.warning(
                self,
                "Invalid range",
                "The selected start marker comes after the selected end marker.",
            )
            return None

        return start_frame, end_frame

    def _selected_csv_frame_bounds(self) -> tuple[int, int] | None:
        start_frame_text = self.start_frame_input.text().strip()
        end_frame_text = self.end_frame_input.text().strip()
        if not start_frame_text or not end_frame_text:
            QMessageBox.information(
                self,
                "No range",
                "Enter both start and end CSV frame numbers.",
            )
            return None

        try:
            start_csv_frame = int(start_frame_text)
            end_csv_frame = int(end_frame_text)
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid frame",
                "Start frame and end frame must be integer frame numbers.",
            )
            return None

        if start_csv_frame <= 0 or end_csv_frame <= 0:
            QMessageBox.warning(
                self,
                "Invalid frame",
                "Start frame and end frame must be positive 1-based frame numbers.",
            )
            return None
        if start_csv_frame > end_csv_frame:
            QMessageBox.warning(
                self,
                "Invalid range",
                "The start frame cannot be after the end frame.",
            )
            return None

        return start_csv_frame, end_csv_frame

    def _default_edited_csv_path(self) -> str:
        if self.imported_csv_path is None:
            return "edited_labels.csv"

        directory = os.path.dirname(self.imported_csv_path)
        stem, ext = os.path.splitext(os.path.basename(self.imported_csv_path))
        ext = ext or ".csv"
        candidate = os.path.join(directory, f"{stem}_edited{ext}")
        suffix = 2
        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{stem}_edited_{suffix}{ext}")
            suffix += 1
        return candidate

    def _choose_edited_csv_path(self) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save edited label metadata CSV",
            self._default_edited_csv_path(),
            "CSV Files (*.csv);;All Files (*)",
        )
        return path or None

    def _current_label_key(self) -> tuple[str, str]:
        label_key = self.label_dropdown.currentData()
        if isinstance(label_key, tuple):
            return label_key
        return "", self.label_dropdown.currentText()

    def _set_adl_selector_to_key(self, label_key: tuple[str, str]):
        for index in range(self.adl_selector.count()):
            if self.adl_selector.itemData(index) == label_key:
                self.adl_selector.setCurrentIndex(index)
                return

    def _add_imported_range_from_marks(self, start_frame: int, end_frame: int):
        label_id, label = self._current_label_key()
        label_range = ImportedLabelRange(
            label_id=label_id,
            label=label,
            start_frame=start_frame,
            end_frame=end_frame,
            start_csv_frame_index=start_frame + 1,
            end_csv_frame_index=end_frame + 1,
            start_row_number=None,
            end_row_number=None,
        )
        self.imported_ranges.append(label_range)
        self.imported_ranges.sort(
            key=lambda item: (
                item.start_frame if item.start_frame is not None else item.end_frame or 0,
                item.end_frame
                if item.end_frame is not None
                else item.start_frame if item.start_frame is not None
                else 0,
                item.label,
            )
        )
        self._populate_import_controls()
        self._set_adl_selector_to_key((label_id, label))
        self._refresh_imported_range_list()
        self.import_status_label.setText(
            f"Staged new range for {label}: start {start_frame + 1}, end {end_frame + 1}."
        )

    def on_delete_imported_csv_label(self):
        if self.imported_csv_path is None:
            QMessageBox.information(self, "No CSV", "Import a label metadata CSV first.")
            return

        row = self.imported_range_list.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "No selection",
                "Select an imported label range to remove from the staged list.",
            )
            return

        item = self.imported_range_list.item(row)
        label_range = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(label_range, ImportedLabelRange):
            QMessageBox.information(
                self,
                "No selection",
                "Select an imported label range to remove from the staged list.",
            )
            return

        for index, item in enumerate(self.imported_ranges):
            if item == label_range:
                del self.imported_ranges[index]
                break
        self._refresh_imported_range_list()
        self.import_status_label.setText("Removed selected range from the staged list.")

    def on_save_imported_csv(self):
        if self.imported_csv_path is None:
            QMessageBox.information(self, "No CSV", "Import a label metadata CSV first.")
            return
        output_csv_path = self._choose_edited_csv_path()
        if output_csv_path is None:
            return

        try:
            written_path = save_metadata_label_ranges(
                self.imported_csv_path,
                output_csv_path=output_csv_path,
                label_ranges=self.imported_ranges,
            )
            QMessageBox.information(
                self,
                "CSV copy saved",
                f"Saved staged imported labels to:\n{written_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could not save CSV", str(exc))

    def on_load_selected_range(self):
        bounds = self._selected_range_bounds()
        if bounds is None:
            return

        start_frame, end_frame = bounds
        self._stop_playback()
        self.temp_start = start_frame
        self.temp_end = end_frame
        self._update_mark_status()
        self._show_frame(start_frame)
        self._sync_audio_to_frame(start_frame)

    def on_play_selected_range(self):
        bounds = self._selected_range_bounds()
        if bounds is None:
            return

        start_frame, end_frame = bounds
        self.temp_start = start_frame
        self.temp_end = end_frame
        self._update_mark_status()
        self._show_frame(start_frame)
        self._sync_audio_to_frame(start_frame)
        self._start_playback(end_frame=end_frame)

    def closeEvent(self, event):
        self._stop_playback()
        if self.cap is not None:
            self.cap.release()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
