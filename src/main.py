import os
import csv
import cv2
import PySimpleGUI as sg

# ============================================================
# CONFIGURATION
# ============================================================

VIDEO_PATH = (
    "/Users/jl4459/Library/CloudStorage/Box-Box/SmartSleeve/"
    "RawData/11072025-ADL_pilot/Videos/temp-11072025164134-0000.avi"
)

# Label set: (label_id, label_description)
LABELS = [
    ("reach", "Reach to object"),
    ("grasp", "Grasp object"),
    ("release", "Release object"),
    ("other", "Other / misc"),
]
LABEL_ID_TO_DESC = {lid: desc for lid, desc in LABELS}
LABEL_IDS = [lid for lid, _ in LABELS]

# ============================================================
# OPEN VIDEO
# ============================================================

cap = cv2.VideoCapture(VIDEO_PATH)
if not cap.isOpened():
    raise RuntimeError(f"❌ Cannot open video: {VIDEO_PATH}")

total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps = cap.get(cv2.CAP_PROP_FPS) or 30
frame_delay_ms = int(1000 / fps)  # update interval during playback

# ============================================================
# GUI LAYOUT
# ============================================================

layout = [
    # Where frames will be displayed
    [sg.Image(filename="", key="-IMAGE-")],

    # Playback controls
    [
        sg.Button("⏮ Prev", key="-PREV-"),
        sg.Button("▶ Play", key="-PLAYPAUSE-"),  # TOGGLE button
        sg.Button("Next ⏭", key="-NEXT-"),
    ],

    # Labeling controls
    [
        sg.Text("Label:"),
        sg.Combo(
            LABEL_IDS,
            default_value=LABEL_IDS[0],
            key="-LABEL-",
            readonly=True,
            size=(15, 1),
        ),
        sg.Button("Mark Start", key="-MARK_START-"),
        sg.Button("Mark End", key="-MARK_END-"),
        sg.Button("Add Label", key="-ADD_LABEL-", button_color=("white", "green")),
    ],

    # Current start/end info
    [
        sg.Text("Start frame:", size=(12, 1)),
        sg.Text("-", key="-START_TXT-", size=(8, 1)),
        sg.Text("End frame:", size=(10, 1)),
        sg.Text("-", key="-END_TXT-", size=(8, 1)),
    ],

    # Frame position slider
    [
        sg.Slider(
            range=(0, total_frames - 1),
            orientation="h",
            size=(60, 15),
            default_value=0,
            key="-SLIDER-",
            enable_events=True,
        )
    ],

    # Annotation list + delete button
    [sg.Text("Annotations:")],
    [
        sg.Listbox(
            values=[],
            key="-ANNOTS_LIST-",
            size=(80, 8),
            enable_events=True,
            select_mode=sg.LISTBOX_SELECT_MODE_SINGLE,
            font=("Courier New", 9),
        )
    ],
    [
        sg.Button("Delete Selected", key="-DEL_ANN-", button_color=("white", "firebrick3")),
    ],

    # Export + Exit
    [
        sg.Button("Export CSV", key="-EXPORT-", button_color=("black", "lightblue")),
        sg.Button("Exit"),
    ],
]

window = sg.Window("🎞 Video Labeler", layout, resizable=True, finalize=True)

# ============================================================
# STATE VARIABLES
# ============================================================

current_frame = 0
playing = False

current_start = None  # type: int | None
current_end = None    # type: int | None

annotations = []      # list of dicts: {start, end, label_id, label_desc}


# ============================================================
# HELPERS
# ============================================================

def show_frame(frame_idx: int):
    """Seek to a frame index and show it in the GUI."""
    global current_frame
    frame_idx = max(0, min(total_frames - 1, frame_idx))

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if not ret:
        return

    # Resize for display (optional, keeps window compact)
    frame = cv2.resize(frame, (640, 360))

    # Convert BGR → RGB → PNG bytes
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    success, encoded = cv2.imencode(".png", frame_rgb)
    if not success:
        return
    imgbytes = encoded.tobytes()

    # Update PySimpleGUI Image element
    window["-IMAGE-"].update(data=imgbytes)
    window["-SLIDER-"].update(value=frame_idx)

    current_frame = frame_idx


def refresh_annotation_view():
    """Render the annotations list into the Listbox widget."""
    lines = []
    for i, ann in enumerate(annotations):
        lines.append(
            f"{i:03d}: frames {ann['start']:6d}–{ann['end']:6d}  "
            f"label={ann['label_id']:10s}  ({ann['label_desc']})"
        )
    window["-ANNOTS_LIST-"].update(values=lines)


def update_start_end_text():
    """Update the little status text showing current start/end."""
    window["-START_TXT-"].update("-" if current_start is None else str(current_start))
    window["-END_TXT-"].update("-" if current_end is None else str(current_end))


def toggle_play_pause():
    """Flip play state and update button text."""
    global playing
    playing = not playing
    window["-PLAYPAUSE-"].update("⏸ Pause" if playing else "▶ Play")


def export_annotations_to_csv():
    """Export current annotations to a CSV file chosen by the user."""
    if not annotations:
        sg.popup("No annotations to export.", title="Export CSV")
        return

    # Suggest a default filename based on the video path
    base, _ = os.path.splitext(VIDEO_PATH)
    default_csv = base + "_labels.csv"

    save_path = sg.popup_get_file(
        "Save annotations as...",
        save_as=True,
        default_path=default_csv,
        file_types=(("CSV Files", "*.csv"),),
        no_window=True,
    )

    if not save_path:
        return  # user cancelled

    # Write CSV
    fieldnames = [
        "video_path",
        "fps",
        "start_frame",
        "end_frame",
        "start_time_s",
        "end_time_s",
        "label_id",
        "label_desc",
    ]
    try:
        with open(save_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for ann in annotations:
                start_frame = ann["start"]
                end_frame = ann["end"]
                start_t = start_frame / fps
                end_t = end_frame / fps
                writer.writerow(
                    {
                        "video_path": VIDEO_PATH,
                        "fps": fps,
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "start_time_s": start_t,
                        "end_time_s": end_t,
                        "label_id": ann["label_id"],
                        "label_desc": ann["label_desc"],
                    }
                )
        sg.popup(f"Exported {len(annotations)} annotations to:\n{save_path}", title="Export CSV")
    except Exception as e:
        sg.popup(f"Error writing CSV:\n{e}", title="Export CSV Error")


# ============================================================
# INITIAL DISPLAY
# ============================================================

show_frame(current_frame)
update_start_end_text()
refresh_annotation_view()

# ============================================================
# MAIN EVENT LOOP
# ============================================================

while True:
    # timeout = frame delay, so play mode advances naturally
    event, values = window.read(timeout=frame_delay_ms)

    if event in (sg.WIN_CLOSED, "Exit"):
        break

    # --- Manual slider movement ---
    if event == "-SLIDER-":
        new_idx = int(values["-SLIDER-"])
        show_frame(new_idx)

    # --- Step one frame forward/back ---
    elif event == "-NEXT-":
        show_frame(current_frame + 1)
    elif event == "-PREV-":
        show_frame(current_frame - 1)

    # --- Playback toggle ---
    elif event == "-PLAYPAUSE-":
        toggle_play_pause()

    # --- Labeling: mark start/end on current frame ---
    elif event == "-MARK_START-":
        current_start = current_frame
        update_start_end_text()

    elif event == "-MARK_END-":
        current_end = current_frame
        update_start_end_text()

    # --- Labeling: finalize and add annotation ---
    elif event == "-ADD_LABEL-":
        label_id = values["-LABEL-"]
        label_desc = LABEL_ID_TO_DESC.get(label_id, "")

        # Basic validation: need both start & end
        if current_start is None or current_end is None:
            sg.popup(
                "Please mark both Start and End before adding a label.",
                title="Missing bounds",
            )
        else:
            start = min(current_start, current_end)
            end = max(current_start, current_end)

            ann = {
                "start": start,
                "end": end,
                "label_id": label_id,
                "label_desc": label_desc,
            }
            annotations.append(ann)

            print("Added annotation:", ann)  # Debug/console log
            refresh_annotation_view()

            # Optionally reset start/end so you must mark again
            current_start = None
            current_end = None
            update_start_end_text()

    # --- Delete selected annotation ---
    elif event == "-DEL_ANN-":
        selected = values["-ANNOTS_LIST-"]
        if not selected:
            sg.popup("No annotation selected to delete.", title="Delete annotation")
        else:
            line = selected[0]
            try:
                idx_str = line.split(":", 1)[0]
                idx = int(idx_str)
            except Exception:
                sg.popup("Could not parse selected annotation index.", title="Error")
                idx = None

            if idx is not None and 0 <= idx < len(annotations):
                removed = annotations.pop(idx)
                print("Deleted annotation:", removed)
                refresh_annotation_view()

    # --- Export annotations ---
    elif event == "-EXPORT-":
        export_annotations_to_csv()

    # --- Auto-playback mode ---
    if playing:
        show_frame(current_frame + 1)

# ============================================================
# CLEANUP
# ============================================================

cap.release()
window.close()
