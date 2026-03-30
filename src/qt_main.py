import csv
import os
import sys
import cv2

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QMessageBox,
    QComboBox,
    QListWidget,
    QListWidgetItem, QFileDialog,
    QCheckBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QImage

# Path to the video being labeled
DEFAULT_VIDEO_PATH = ""

class MainWindow(QMainWindow):
    """
    Simple video labeling tool.

    Features:
      - Load and display a video.
      - Scrub through frames with a slider and Prev/Next buttons.
      - Play/pause playback.
      - Mark a start and end frame, assign a label, and store that annotation.
      - View annotations in a list.
      - Delete selected annotation.
      - Export all annotations to CSV.
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Qt Video Labeler")

        # Path of the currently loaded video (None until a video is loaded)
        self.video_path: str | None = None

        # --- Video state (initialized later in load_video) ---
        self.cap = None
        self.total_frames = 0
        self.fps = 30.0
        self.current_frame_idx = 0

        # --- Annotation state ---
        # Each element is a dict { "start": int, "end": int, "label": str }
        self.annotations = []

        # Temporary marks used before creating an annotation
        self.temp_start = None
        self.temp_end = None

        # --- Playback timer ---
        self.playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)  # called when playing

        # Build the UI and optionally load a default video
        self._build_ui()

        if DEFAULT_VIDEO_PATH and os.path.exists(DEFAULT_VIDEO_PATH):
            self.load_video(DEFAULT_VIDEO_PATH)
        else:
            # No default video: show a hint
            self.video_label.setText("No video loaded. Click 'Open Video' to begin.")

    def load_video(self, path: str):
        """
        Load a new video file and reset all video-related state.
        """
        # Release any existing capture
        if self.cap is not None:
            self.cap.release()

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            QMessageBox.critical(self, "Error", f"Cannot open video:\n{path}")
            return

        self.cap = cap
        self.video_path = path
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.current_frame_idx = 0

        # Reset slider range to match new video
        self.frame_slider.blockSignals(True)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(max(0, self.total_frames - 1))
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)

        # Clear annotations for the new video
        self.annotations.clear()
        self.annotation_list.clear()

        # Clear temp marks and update label
        self.temp_start = None
        self.temp_end = None
        self._update_mark_status()

        # Update window title to include filename
        base_name = os.path.basename(path)
        self.setWindowTitle(f"Qt Video Labeler - {base_name}")

        # Show first frame
        self._show_frame(0)

    def _build_ui(self):
        """
        Create all widgets, layouts, and wire up signals/slots.
        """
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # ===== Video display area =====
        self.video_label = QLabel("No video loaded")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #222; color: #ddd;")
        self.video_label.setMinimumSize(640, 360)
        self.video_label.setScaledContents(True)  # scale frame to fit widget
        main_layout.addWidget(self.video_label, stretch=4)

        # ===== Playback controls (prev / play / next + slider) =====
        controls_layout = QHBoxLayout()

        self.prev_button = QPushButton("Prev")
        self.play_button = QPushButton("Play")
        self.next_button = QPushButton("Next")

        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(max(0, self.total_frames - 1))
        self.frame_slider.setValue(0)

        controls_layout.addWidget(self.prev_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.next_button)
        controls_layout.addWidget(self.frame_slider)

        main_layout.addLayout(controls_layout, stretch=0)

        # ===== Annotation controls (start/end/label) =====
        anno_layout = QHBoxLayout()

        self.start_button = QPushButton("Mark Start")
        self.end_button = QPushButton("Mark End")
        self.add_label_button = QPushButton("Add Label")

        # Dropdown with some example labels; can be customized
        self.label_dropdown = QComboBox()
        self.label_dropdown.addItems([
            "Pick up coins from purses",
            "Pick up wooden blocks",
            "Pick up nuts and put in bolts",
            "Unscrew lid of jars",
            "Cut play-doh",
            "Writing",
            "Pick up telephone and put in ear",
            "Pour water from pure pack",
            "Pour water from jug",
            "Pour water from cup",
            "Typing on smartphone",
            "Scrolling on smartphone",
            "Typing on keyboard",
            "Start sensors recording",
            "Dynamometer hand grip baseline",
            "Dynamometer hand grip active"
        ])

        anno_layout.addWidget(self.start_button)
        anno_layout.addWidget(self.end_button)
        anno_layout.addWidget(self.label_dropdown)
        anno_layout.addWidget(self.add_label_button)
        main_layout.addLayout(anno_layout)

        # Text showing current temporary start/end frame marks
        self.mark_status_label = QLabel("Start: –   End: –")
        main_layout.addWidget(self.mark_status_label)

        # ===== Annotation list (for existing labels) =====
        self.annotation_list = QListWidget()
        main_layout.addWidget(self.annotation_list, stretch=1)

        # ===== Bottom action buttons (delete/export/exit) =====
        bottom_layout = QHBoxLayout()

        self.open_button = QPushButton("Open Video")
        self.delete_button = QPushButton("Delete Selected")
        self.export_button = QPushButton("Export CSV")
        self.exit_button = QPushButton("Exit")

        bottom_layout.addWidget(self.open_button)
        bottom_layout.addWidget(self.delete_button)
        bottom_layout.addWidget(self.export_button)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.exit_button)

        main_layout.addLayout(bottom_layout)

        # ===== Signal connections =====
        # Playback controls
        self.prev_button.clicked.connect(self.on_prev)
        self.next_button.clicked.connect(self.on_next)
        self.play_button.clicked.connect(self.on_play_pause)
        self.frame_slider.valueChanged.connect(self.on_slider_changed)

        # Annotation controls
        self.start_button.clicked.connect(self.on_mark_start)
        self.end_button.clicked.connect(self.on_mark_end)
        self.add_label_button.clicked.connect(self.on_add_label)

        # Annotation list actions
        self.delete_button.clicked.connect(self.on_delete_label)
        self.export_button.clicked.connect(self.on_export_csv)
        self.exit_button.clicked.connect(self.close)

        # Open video
        self.open_button.clicked.connect(self.on_open_video)

    # -------------------------------------------------------------------------
    # Video helpers
    # -------------------------------------------------------------------------
    def _show_frame(self, frame_idx: int):
        """
        Seek to the given frame index and display it in the video_label.
        """
        if self.cap is None:
            return

        if frame_idx < 0 or frame_idx >= self.total_frames:
            return

        # Position capture at the desired frame and grab it
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if not ret:
            return

        self.current_frame_idx = frame_idx

        # OpenCV gives BGR; Qt expects RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(q_img)

        self.video_label.setPixmap(pix)

        # Keep slider in sync with current frame without triggering slider handler
        if self.frame_slider.value() != frame_idx:
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(frame_idx)
            self.frame_slider.blockSignals(False)

    def on_slider_changed(self, value: int):
        """
        Called when the user drags the slider to a new position.
        """
        self._show_frame(value)

    def on_prev(self):
        """
        Go to previous frame (if possible).
        """
        new_idx = max(0, self.current_frame_idx - 1)
        self._show_frame(new_idx)

    def on_next(self):
        """
        Go to next frame (if possible).
        """
        new_idx = min(self.total_frames - 1, self.current_frame_idx + 1)
        self._show_frame(new_idx)

    def on_play_pause(self):
        """
        Toggle between playing and paused. Uses a QTimer to advance frames.
        """
        if not self.playing:
            # Start playback
            self.playing = True
            self.play_button.setText("Pause")
            interval_ms = int(1000 / self.fps) if self.fps > 0 else 33
            self.timer.start(interval_ms)
        else:
            # Pause playback
            self.playing = False
            self.play_button.setText("Play")
            self.timer.stop()

    def next_frame(self):
        """
        Advance one frame during playback. Stops at the end of the video.
        """
        if self.current_frame_idx >= self.total_frames - 1:
            # Reached the end: stop playback
            self.on_play_pause()
            return
        self._show_frame(self.current_frame_idx + 1)

    def on_open_video(self):
        """
        Show a file dialog to choose a video file and load it.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open video",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)"
        )
        if not path:
            return
        self.load_video(path)

    # -------------------------------------------------------------------------
    # Annotation helpers
    # -------------------------------------------------------------------------
    def _update_mark_status(self):
        """
        Update the text showing current temporary start/end frame indices.
        """
        start_txt = str(self.temp_start) if self.temp_start is not None else "–"
        end_txt = str(self.temp_end) if self.temp_end is not None else "–"
        self.mark_status_label.setText(f"Start: {start_txt}   End: {end_txt}")

    def on_mark_start(self):
        """
        Remember the current frame index as the start of an annotation.
        """
        self.temp_start = self.current_frame_idx
        self._update_mark_status()

    def on_mark_end(self):
        """
        Remember the current frame index as the end of an annotation.
        """
        self.temp_end = self.current_frame_idx
        self._update_mark_status()

    def on_add_label(self):
        """
        Create a new annotation from temp_start and temp_end with the
        currently selected label.
        """
        if self.temp_start is None or self.temp_end is None:
            QMessageBox.warning(self, "Missing Marks", "Please mark both start and end frames first.")
            return

        label = self.label_dropdown.currentText()
        start = min(self.temp_start, self.temp_end)
        end = max(self.temp_start, self.temp_end)

        annotation = {"start": start, "end": end, "label": label}
        self.annotations.append(annotation)

        # Also add a human-readable line to the list widget
        item_text = f"{label}: {start}–{end}"
        self.annotation_list.addItem(QListWidgetItem(item_text))

        # Clear temporary marks
        self.temp_start = None
        self.temp_end = None
        self._update_mark_status()

    def on_delete_label(self):
        """
        Remove the currently selected annotation from both the list
        widget and the backing annotations list.
        """
        row = self.annotation_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "No selection", "Please select an annotation to delete.")
            return

        # Remove item from the list widget
        self.annotation_list.takeItem(row)

        # Remove the matching entry from annotations, if available
        if 0 <= row < len(self.annotations):
            del self.annotations[row]

    def on_export_csv(self):
        """
        Save the current annotations to a CSV file with columns:
        start_frame, end_frame, label.

        Default filename is <video_stem>_labels.csv next to the video.
        """
        if not self.annotations:
            QMessageBox.information(self, "No annotations", "There are no annotations to export.")
            return

        # Build default filename based on the loaded video, if available
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
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["start_frame", "end_frame", "label"])
            for ann in self.annotations:
                writer.writerow([ann["start"], ann["end"], ann["label"]])

        QMessageBox.information(self, "Export complete", f"Annotations exported to:\n{path}")

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def closeEvent(self, event):
        """
        Called when the window is closing. Ensures video capture is released.
        """
        if self.cap is not None:
            self.cap.release()
        event.accept()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
