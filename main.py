"""
=============================================================================
FaceTrack AI - Real-Time Attendance System via Face Recognition
=============================================================================
A modern, high-performance desktop application built with Python & Tkinter.
Features:
- Multi-threaded hardware webcam capture (DirectShow & Media Foundation)
- Hardware Privacy Detection (Samsung Galaxy Book Fn+F11 / Windows Settings)
- Image / Photo Upload Face Recognition mode
- Real-time Augmented Reality Face Recognition HUD
- Live session logging, anti-duplicate scan guards, and KPI analytics
- Interactive student enrollment & CSV report export
=============================================================================
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import datetime
import math
import random
import csv
import json
import os
import subprocess
import re
from PIL import Image, ImageTk, ImageDraw, ImageFont

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

FaceEngine = None
if OPENCV_AVAILABLE:
    try:
        from face_engine import FaceEngine
    except ImportError:
        FaceEngine = None


# =============================================================================
# PERSISTENT STUDENT ROSTER (saved to disk, next to this script / the .exe)
# =============================================================================
STUDENTS_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "students_db.json")
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_settings.json")


def load_students_db():
    """Load the enrolled-student roster from disk. Only identity fields
    (id/name/dept/batch) are persisted -- attendance status always resets
    to 'Not Marked' at the start of a new session."""
    if not os.path.isfile(STUDENTS_DB_PATH):
        return []
    try:
        with open(STUDENTS_DB_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    students = []
    for s in raw:
        if not isinstance(s, dict) or "id" not in s or "name" not in s:
            continue
        students.append({
            "id": s["id"],
            "name": s["name"],
            "dept": s.get("dept", "Computer Science"),
            "batch": s.get("batch", "2026-2030"),
            "status": "Not Marked",
            "time": "-",
            "conf": "-",
        })
    return students


def save_students_db(students):
    """Persist only identity fields for each student -- never the
    per-session status/time/confidence, which are meant to reset."""
    try:
        payload = [
            {"id": s["id"], "name": s["name"], "dept": s["dept"], "batch": s["batch"]}
            for s in students
        ]
        with open(STUDENTS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return True
    except OSError:
        return False


def load_confidence_threshold():
    """Load the last recognition threshold, falling back to 60 percent."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
            # Accept the old key so existing installations keep their saved threshold.
            value = settings.get("match_score_threshold", settings.get("confidence_threshold", 60))
        value = int(value)
        return value if 50 <= value <= 95 else 60
    except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return 60


def save_confidence_threshold(value):
    """Persist the recognition threshold used by the slider."""
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"match_score_threshold": int(value)}, f, indent=2)
        return True
    except OSError:
        return False


# =============================================================================
# BACKGROUND THREADED CAMERA CAPTURE ENGINE
# =============================================================================
class WebcamCaptureThread:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.cap = None
        self.running = False
        self.latest_frame = None
        self.lock = threading.Lock()
        self.thread = None
        self.is_connected = False
        self.is_black_screen = False
        self.status_msg = "Initializing..."

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._capture_worker, daemon=True)
        self.thread.start()

    def _capture_worker(self):
        if not OPENCV_AVAILABLE:
            self.is_connected = False
            self.status_msg = "OpenCV not available"
            return

        try:
            self.status_msg = f"Connecting to Camera {self.camera_index} (DirectShow)..."
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(self.camera_index)

            if not self.cap.isOpened():
                self.is_connected = False
                self.status_msg = f"Camera {self.camera_index} could not be opened"
                return

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            # Warm-up loop
            consecutive_failures = 0
            for _ in range(15):
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    with self.lock:
                        self.latest_frame = frame
                        self.is_black_screen = bool(np.mean(frame) < 1.0)
                    self.is_connected = True
                    self.status_msg = f"Camera {self.camera_index} Connected (Live)"
                    break
                time.sleep(0.04)

            # Frame capture loop
            while self.running and self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    consecutive_failures = 0
                    with self.lock:
                        self.latest_frame = frame
                        self.is_black_screen = bool(np.mean(frame) < 1.0)
                    self.is_connected = True
                else:
                    consecutive_failures += 1
                    if consecutive_failures > 30:
                        self.is_connected = False
                        self.status_msg = "Camera feed lost. Retrying..."
                        time.sleep(0.5)
                time.sleep(0.015)
        except Exception as e:
            self.is_connected = False
            self.status_msg = f"Camera error: {str(e)}"
        finally:
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None

    def get_frame_and_status(self):
        with self.lock:
            frame_copy = self.latest_frame.copy() if self.latest_frame is not None else None
            return frame_copy, self.is_black_screen

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.8)


# =============================================================================
# MAIN ATTENDANCE APPLICATION
# =============================================================================
class AttendanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FaceTrack AI - Real-Time Smart Attendance System")
        self.root.geometry("1280x840")
        self.root.minsize(1100, 720)
        self.root.configure(bg="#07111d")
        self.root.option_add("*Font", "Arial 9")

        self.palette = {
            "bg": "#07111d",
            "bg_alt": "#0b1728",
            "panel": "#101d2d",
            "panel_2": "#14273c",
            "card": "#122235",
            "card_2": "#0d1b2d",
            "line": "#233548",
            "text": "#e5eefb",
            "muted": "#9bb0c9",
            "primary": "#4cc9f0",
            "primary_2": "#3b82f6",
            "success": "#34d399",
            "warning": "#fbbf24",
            "danger": "#f87171",
            "violet": "#8b5cf6",
        }

        # State Variables
        self.is_feed_paused = False
        self.camera_thread = None
        self.uploaded_image = None
        self.current_source = "Camera 0 (Default Webcam)"
        self.room_name = "Tech Lab 3"
        self.lecturer_name = "Dr. Sharma"
        self.confidence_threshold = load_confidence_threshold()
        self.students = load_students_db()
        self.attendance_log = []
        self.detected_face_info = None
        self.anim_tick = 0
        self.fps_counter = 0
        self.current_fps = 30.0
        self.last_fps_time = time.time()
        self.black_frame_warning_shown = False

        self.recent_banner_text = "System Ready. Enroll a student's face in 'Enroll New', then use 'Recognize Face Now' to test recognition."
        self.recent_banner_type = "info"

        # Face detection / recognition engine state (real, not simulated)
        self.face_engine = None
        self.recognition_enabled = False
        self.last_face_rect = None          # (x, y, w, h) in source-frame pixel coords
        self.last_face_gray = None          # cropped grayscale face, ready for recognizer.predict
        self.last_face_source_size = (0, 0)  # (w, h) of the frame the detection ran on
        self.last_face_seen_time = 0.0

        if OPENCV_AVAILABLE and FaceEngine is not None:
            try:
                self.face_engine = FaceEngine()
                self.recognition_enabled = self.face_engine.has_recognizer_backend
                self.face_engine.train()  # silently load any previously-enrolled faces from disk
            except Exception as e:
                self.face_engine = None
                self.recognition_enabled = False
                self.recent_banner_text = f"Face engine failed to load: {e}"
                self.recent_banner_type = "warning"

        # Theme & Styles
        self._setup_theme_and_styles()

        # Build UI layout
        self._build_header()
        self._build_main_layout()
        self._build_statusbar()

        # Window close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start Camera Thread
        self._start_camera_source(0)

        # Start Loops
        self._update_clock()
        self._video_loop()

    def _setup_theme_and_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Treeview",
                        background=self.palette["card"],
                        foreground=self.palette["text"],
                        fieldbackground=self.palette["card"],
                        rowheight=32,
                        font=("Arial", 10))
        style.configure("Treeview.Heading",
                        background="#1a2d43",
                        foreground=self.palette["primary"],
                        font=("Arial", 10, "bold"),
                        padding=8)
        style.map("Treeview",
                  background=[("selected", self.palette["primary_2"])],
                  foreground=[("selected", "#FFFFFF")])

        style.configure("TNotebook", background=self.palette["bg"], borderwidth=0)
        style.configure("TNotebook.Tab",
                        background="#13273d",
                        foreground="#b5c7db",
                        font=("Arial", 10, "bold"),
                        padding=[18, 10])
        style.map("TNotebook.Tab",
                  background=[("selected", self.palette["primary"]), ("active", "#1a3559")],
                  foreground=[("selected", "#03131d"), ("active", self.palette["text"])])

        style.configure("Vertical.TScrollbar",
                        background="#324968",
                        troughcolor="#0d1c2c",
                        arrowcolor="#cfe2ff")

        style.configure("Modern.TCombobox",
                        fieldbackground="#0d1f2f",
                        background="#162b3e",
                        foreground="#e5eefb",
                        arrowcolor="#8bd3ff",
                        selectbackground="#1a3559",
                        selectforeground="#ffffff",
                        padding=6)
        style.map("Modern.TCombobox",
                  fieldbackground=[("readonly", "#0d1f2f")],
                  background=[("readonly", "#162b3e")],
                  foreground=[("readonly", "#e5eefb")])

    def _build_action_button(self, parent, text, command=None, bg="#1b3050", fg="#e5eefb",
                            active_bg="#233f66", font=("Arial", 9, "bold"), padx=12, pady=6,
                            side=tk.LEFT, anchor=None, width=None):
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground="#ffffff",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=padx,
            pady=pady,
            font=font,
            cursor="hand2",
            width=width,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=active_bg))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        if side is not None:
            btn.pack(side=side, padx=(0, 8) if side == tk.LEFT else (0, 0))
        if anchor is not None:
            btn.pack(anchor=anchor)
        return btn

    # =========================================================================
    # UI BUILDERS
    # =========================================================================
    def _build_header(self):
        header_frame = tk.Frame(self.root, bg="#0b1728", height=96, padx=18, pady=14)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        title_box = tk.Frame(header_frame, bg="#0b1728")
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        logo_icon = tk.Label(title_box, text="AI", font=("Arial", 22, "bold"), bg="#0b1728", fg="#7dd3fc")
        logo_icon.pack(side=tk.LEFT, padx=(0, 10))

        title_text_frame = tk.Frame(title_box, bg="#0b1728")
        title_text_frame.pack(side=tk.LEFT)

        app_title = tk.Label(title_text_frame, text="FaceTrack AI", font=("Arial", 18, "bold"), fg="#f5f9ff", bg="#0b1728")
        app_title.pack(anchor="w")

        app_sub = tk.Label(title_text_frame, text="Real-Time Face Recognition Attendance System", font=("Arial", 9), fg="#9bb0c9", bg="#0b1728")
        app_sub.pack(anchor="w")

        session_box = tk.Frame(header_frame, bg="#122235", padx=16, pady=8, highlightbackground="#294868", highlightthickness=1)
        session_box.pack(side=tk.LEFT, padx=26)

        lbl_course = tk.Label(session_box, text="CLASS: CS-401 (Computer Vision)", font=("Arial", 9, "bold"), fg="#7dd3fc", bg="#122235")
        lbl_course.pack(anchor="w")
        self.lbl_room = tk.Label(session_box, text="", font=("Arial", 8), fg="#b5c7db", bg="#122235")
        self.lbl_room.pack(anchor="w")
        self._refresh_session_details()

        btn_edit_session = self._build_action_button(
            session_box,
            "Edit Session Details",
            command=self._edit_session_details,
            bg="#1b3050",
            fg="#e5eefb",
            active_bg="#233f66",
            font=("Arial", 8, "bold"),
            padx=8,
            pady=3,
            side=None,
        )
        btn_edit_session.pack(anchor="w", pady=(6, 0))

        right_box = tk.Frame(header_frame, bg="#0b1728")
        right_box.pack(side=tk.RIGHT)

        self.clock_label = tk.Label(right_box, text="00:00:00 AM", font=("Consolas", 15, "bold"), fg="#f5f9ff", bg="#0b1728")
        self.clock_label.pack(anchor="e")

        self.date_label = tk.Label(right_box, text="Saturday, Aug 29, 2026", font=("Arial", 8), fg="#9bb0c9", bg="#0b1728")
        self.date_label.pack(anchor="e")

    def _refresh_session_details(self):
        self.lbl_room.configure(text=f"ROOM: {self.room_name} | LECTURER: {self.lecturer_name}")

    def _edit_session_details(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Session Details")
        dialog.configure(bg="#1E293B")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        container = tk.Frame(dialog, bg="#1E293B", padx=18, pady=16)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(container, text="Room Name", font=("Arial", 9, "bold"),
                 fg="#CBD5E1", bg="#1E293B").pack(anchor="w")
        room_entry = tk.Entry(container, bg="#0F172A", fg="#F8FAFC", insertbackground="#38BDF8",
                              font=("Arial", 9), relief=tk.FLAT, highlightbackground="#334155", highlightthickness=1)
        room_entry.pack(fill=tk.X, pady=(3, 10), ipady=3)
        room_entry.insert(0, self.room_name)

        tk.Label(container, text="Lecturer Name", font=("Arial", 9, "bold"),
                 fg="#CBD5E1", bg="#1E293B").pack(anchor="w")
        lecturer_entry = tk.Entry(container, bg="#0F172A", fg="#F8FAFC", insertbackground="#38BDF8",
                                  font=("Arial", 9), relief=tk.FLAT, highlightbackground="#334155", highlightthickness=1)
        lecturer_entry.pack(fill=tk.X, pady=(3, 14), ipady=3)
        lecturer_entry.insert(0, self.lecturer_name)

        def save_details():
            room = room_entry.get().strip()
            lecturer = lecturer_entry.get().strip()
            if not room or not lecturer:
                messagebox.showerror("Validation Error", "Room and lecturer name are required.", parent=dialog)
                return
            self.room_name = room
            self.lecturer_name = lecturer
            self._refresh_session_details()
            dialog.destroy()

        tk.Button(container, text="Save Details", command=save_details,
                  font=("Arial", 9, "bold"), bg="#2563EB", fg="#FFFFFF",
                  relief=tk.FLAT, padx=10, pady=5, cursor="hand2").pack(fill=tk.X)

    def _build_main_layout(self):
        main_content = tk.Frame(self.root, bg="#07111d", padx=15, pady=12)
        main_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_col = tk.Frame(main_content, bg="#07111d")
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right_col = tk.Frame(main_content, bg="#07111d", width=520)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(10, 0))
        right_col.pack_propagate(False)

        self._build_video_panel(left_col)
        self._build_stats_and_tabs(right_col)

    def _build_video_panel(self, parent):
        shell = tk.Frame(parent, bg="#0b1623", padx=6, pady=6, highlightbackground="#17314f", highlightthickness=1)
        shell.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        card = tk.Frame(shell, bg="#122235", padx=12, pady=12, highlightbackground="#294868", highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True)

        vid_head = tk.Frame(card, bg="#122235")
        vid_head.pack(fill=tk.X, pady=(0, 8))

        self.live_badge = tk.Label(vid_head, text="LIVE WEBCAM", font=("Arial", 9, "bold"), fg="#34d399", bg="#122235")
        self.live_badge.pack(side=tk.LEFT)

        source_frame = tk.Frame(vid_head, bg="#122235")
        source_frame.pack(side=tk.RIGHT)

        tk.Label(source_frame, text="Source: ", font=("Arial", 9), fg="#9bb0c9", bg="#122235").pack(side=tk.LEFT)
        self.source_combo = ttk.Combobox(source_frame, values=[
            "Camera 0 (Default Webcam)",
            "Camera 1 (External / Secondary)",
            "AI Simulation Mode"
        ], state="readonly", width=25, font=("Arial", 8), style="Modern.TCombobox")
        self.source_combo.set("Camera 0 (Default Webcam)")
        self.source_combo.pack(side=tk.LEFT, padx=(2, 6))
        self.source_combo.bind("<<ComboboxSelected>>", self._on_source_changed)

        self.canvas_width = 680
        self.canvas_height = 430
        self.canvas = tk.Canvas(card, width=self.canvas_width, height=self.canvas_height, bg="#081521",
                               highlightthickness=1, highlightbackground="#18324c", bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.troubleshoot_bar = tk.Frame(card, bg="#4c1d1d", padx=10, pady=8, highlightbackground="#ef4444", highlightthickness=1)

        lbl_box = tk.Frame(self.troubleshoot_bar, bg="#4c1d1d")
        lbl_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(lbl_box, text="Samsung Galaxy Book Privacy Lock Detected (Image is Black):",
                 font=("Arial", 9, "bold"), fg="#fee2e2", bg="#4c1d1d").pack(anchor="w")
        tk.Label(lbl_box, text="Press Fn + F11 on your keyboard OR turn off 'Block Camera and Mic' in Samsung Settings.",
                 font=("Arial", 8), fg="#fecaca", bg="#4c1d1d").pack(anchor="w")

        btn_box = tk.Frame(self.troubleshoot_bar, bg="#4c1d1d")
        btn_box.pack(side=tk.RIGHT)

        btn_samsung = tk.Button(btn_box, text="Open Samsung Settings", command=self._open_samsung_settings,
                                font=("Arial", 8, "bold"), bg="#dc2626", fg="#FFFFFF", relief=tk.FLAT, padx=8, pady=4, cursor="hand2")
        btn_samsung.pack(side=tk.RIGHT, padx=(4, 0))

        btn_win = tk.Button(btn_box, text="Windows Privacy", command=self._open_windows_camera_settings,
                            font=("Arial", 8), bg="#991b1b", fg="#FFFFFF", relief=tk.FLAT, padx=6, pady=4, cursor="hand2")
        btn_win.pack(side=tk.RIGHT)

        self.banner_frame = tk.Frame(card, bg="#0d1e2d", padx=12, pady=8, highlightbackground="#4cc9f0", highlightthickness=1)
        self.banner_frame.pack(fill=tk.X, pady=(10, 0))

        self.banner_icon = tk.Label(self.banner_frame, text="i", font=("Arial", 12, "bold"), fg="#7dd3fc", bg="#0d1e2d")
        self.banner_icon.pack(side=tk.LEFT, padx=(0, 8))

        self.banner_label = tk.Label(self.banner_frame, text=self.recent_banner_text, font=("Arial", 9, "bold"), fg="#f5f9ff", bg="#0d1e2d")
        self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ctrl_frame = tk.Frame(parent, bg="#07111d", pady=10)
        ctrl_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.btn_camera = self._build_action_button(
            ctrl_frame,
            "Pause Feed",
            command=self._toggle_pause,
            bg="#213d5a",
            fg="#f5f9ff",
            active_bg="#2e4f74",
            font=("Arial", 10, "bold"),
            padx=14,
            pady=6,
            side=tk.LEFT,
        )

        self.btn_trigger_recognize = self._build_action_button(
            ctrl_frame,
            "Recognize Face Now",
            command=self._force_face_detection,
            bg="#3b82f6",
            fg="#FFFFFF",
            active_bg="#2563eb",
            font=("Arial", 10, "bold"),
            padx=14,
            pady=6,
            side=tk.LEFT,
        )

        self.btn_load_photo = self._build_action_button(
            ctrl_frame,
            "Load Face Photo",
            command=self._load_photo_dialog,
            bg="#122235",
            fg="#cfe2ff",
            active_bg="#1a3559",
            font=("Arial", 9),
            padx=10,
            pady=6,
            side=tk.LEFT,
        )

        self.btn_reconnect_cam = self._build_action_button(
            ctrl_frame,
            "Restart Camera",
            command=self._restart_current_camera,
            bg="#122235",
            fg="#cfe2ff",
            active_bg="#1a3559",
            font=("Arial", 9),
            padx=10,
            pady=6,
            side=tk.LEFT,
        )

        thresh_box = tk.Frame(ctrl_frame, bg="#07111d")
        thresh_box.pack(side=tk.RIGHT)

        tk.Label(thresh_box, text="Min Match: ", font=("Arial", 9), fg="#9bb0c9", bg="#07111d").pack(side=tk.LEFT)
        self.thresh_slider = tk.Scale(thresh_box, from_=50, to=95, orient=tk.HORIZONTAL,
                                      bg="#07111d", fg="#7dd3fc", highlightthickness=0,
                                      troughcolor="#122235", activebackground="#3b82f6",
                                      font=("Arial", 8), length=100, command=self._on_slider_change)
        self.thresh_slider.set(self.confidence_threshold)
        self.thresh_slider.pack(side=tk.LEFT)

    def _build_stats_and_tabs(self, parent):
        stats_frame = tk.Frame(parent, bg="#07111d")
        stats_frame.pack(fill=tk.X, pady=(0, 10))

        self.kpi_enrolled = self._create_kpi_card(stats_frame, "ENROLLED", str(len(self.students)), "#7dd3fc", 0)
        self.kpi_present = self._create_kpi_card(stats_frame, "PRESENT", "0", "#34d399", 1)
        self.kpi_absent = self._create_kpi_card(stats_frame, "ABSENT", str(len(self.students)), "#f87171", 2)
        self.kpi_rate = self._create_kpi_card(stats_frame, "RATE", "0%", "#fbbf24", 3)

        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_log = tk.Frame(self.notebook, bg="#122235", padx=10, pady=10, highlightbackground="#294868", highlightthickness=1)
        self.tab_students = tk.Frame(self.notebook, bg="#122235", padx=10, pady=10, highlightbackground="#294868", highlightthickness=1)
        self.tab_enroll = tk.Frame(self.notebook, bg="#122235", padx=10, pady=10, highlightbackground="#294868", highlightthickness=1)

        self.notebook.add(self.tab_log, text="Live Session Log")
        self.notebook.add(self.tab_students, text="Student Roster")
        self.notebook.add(self.tab_enroll, text="Enroll New")

        self._build_attendance_log_tab()
        self._build_student_roster_tab()
        self._build_enroll_tab()

    def _create_kpi_card(self, parent, title, value, accent_color, col_idx):
        card = tk.Frame(parent, bg="#122235", padx=10, pady=10, highlightbackground="#2d4d6d", highlightthickness=1)
        card.grid(row=0, column=col_idx, padx=4, pady=0, sticky="nsew")
        parent.grid_columnconfigure(col_idx, weight=1)

        tk.Label(card, text=title, font=("Arial", 7, "bold"), fg="#9bb0c9", bg="#122235").pack(anchor="w")
        val_lbl = tk.Label(card, text=value, font=("Arial", 16, "bold"), fg=accent_color, bg="#122235")
        val_lbl.pack(anchor="w")
        return val_lbl

    def _build_attendance_log_tab(self):
        tb = tk.Frame(self.tab_log, bg="#1E293B")
        tb.pack(fill=tk.X, pady=(0, 8))

        tk.Label(tb, text="Search", font=("Arial", 10), fg="#94A3B8", bg="#1E293B").pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry = tk.Entry(tb, bg="#0F172A", fg="#F8FAFC", insertbackground="#38BDF8",
                                     font=("Arial", 9), relief=tk.FLAT, highlightbackground="#334155", highlightthickness=1)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=3)
        self.search_entry.bind("<KeyRelease>", self._filter_attendance_log)

        btn_export = tk.Button(tb, text="Export CSV", command=self._export_attendance_csv,
                               font=("Arial", 8, "bold"), bg="#059669", fg="#FFFFFF",
                               relief=tk.FLAT, padx=8, pady=3, cursor="hand2")
        btn_export.pack(side=tk.RIGHT, padx=(4, 0))

        btn_clear = tk.Button(tb, text="Clear", command=self._clear_attendance_log,
                              font=("Arial", 8), bg="#334155", fg="#94A3B8",
                              relief=tk.FLAT, padx=6, pady=3, cursor="hand2")
        btn_clear.pack(side=tk.RIGHT)

        tree_frame = tk.Frame(self.tab_log, bg="#1E293B")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "name", "time", "conf", "status")
        self.log_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.log_tree.heading("id", text="Student ID")
        self.log_tree.heading("name", text="Full Name")
        self.log_tree.heading("time", text="Time Marked")
        self.log_tree.heading("conf", text="Confidence")
        self.log_tree.heading("status", text="Status")

        self.log_tree.column("id", width=85, anchor="center")
        self.log_tree.column("name", width=140, anchor="w")
        self.log_tree.column("time", width=90, anchor="center")
        self.log_tree.column("conf", width=80, anchor="center")
        self.log_tree.column("status", width=85, anchor="center")

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=scroll.set)

        self.log_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_tree.tag_configure("verified", foreground="#4ADE80")
        self.log_tree.tag_configure("manual", foreground="#38BDF8")
        self.log_tree.tag_configure("late", foreground="#FBBF24")

    def _build_student_roster_tab(self):
        roster_head = tk.Frame(self.tab_students, bg="#1E293B")
        roster_head.pack(fill=tk.X, pady=(0, 6))

        tk.Label(roster_head, text="All Enrolled Candidates in Session", font=("Arial", 9, "bold"), fg="#38BDF8", bg="#1E293B").pack(side=tk.LEFT)
        btn_delete_sel = tk.Button(roster_head, text="Delete Selected", command=self._delete_selected_student,
                       font=("Arial", 8, "bold"), bg="#991B1B", fg="#FFFFFF", relief=tk.FLAT, padx=6, pady=2, cursor="hand2")
        btn_delete_sel.pack(side=tk.RIGHT, padx=(6, 0))
        btn_mark_sel = tk.Button(roster_head, text="Mark Selected Present", command=self._manual_mark_selected,
                                 font=("Arial", 8, "bold"), bg="#2563EB", fg="#FFFFFF", relief=tk.FLAT, padx=6, pady=2, cursor="hand2")
        btn_mark_sel.pack(side=tk.RIGHT)

        tree_frame = tk.Frame(self.tab_students, bg="#1E293B")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "name", "dept", "status")
        self.roster_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.roster_tree.heading("id", text="Student ID")
        self.roster_tree.heading("name", text="Name")
        self.roster_tree.heading("dept", text="Department")
        self.roster_tree.heading("status", text="Attendance")

        self.roster_tree.column("id", width=85, anchor="center")
        self.roster_tree.column("name", width=140, anchor="w")
        self.roster_tree.column("dept", width=130, anchor="w")
        self.roster_tree.column("status", width=95, anchor="center")

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.roster_tree.yview)
        self.roster_tree.configure(yscrollcommand=scroll.set)

        self.roster_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.roster_tree.tag_configure("present", foreground="#4ADE80")
        self.roster_tree.tag_configure("absent", foreground="#94A3B8")

        self._refresh_roster_tree()

    def _build_enroll_tab(self):
        container = tk.Frame(self.tab_enroll, bg="#1E293B", padx=10, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(container, text="Enroll New Student to Face Recognition Engine", font=("Arial", 10, "bold"), fg="#38BDF8", bg="#1E293B").pack(anchor="w", pady=(0, 10))

        fields = [
            ("Student ID (e.g. STU-1009):", "entry_id"),
            ("Full Name:", "entry_name"),
            ("Department / Branch:", "entry_dept"),
            ("Batch / Academic Year:", "entry_batch"),
        ]

        self.enroll_entries = {}
        for label_text, var_name in fields:
            lbl = tk.Label(container, text=label_text, font=("Arial", 9), fg="#CBD5E1", bg="#1E293B")
            lbl.pack(anchor="w", pady=(4, 1))

            ent = tk.Entry(container, bg="#0F172A", fg="#F8FAFC", insertbackground="#38BDF8",
                           font=("Arial", 9), relief=tk.FLAT, highlightbackground="#334155", highlightthickness=1)
            ent.pack(fill=tk.X, pady=(0, 6), ipady=3)
            self.enroll_entries[var_name] = ent

        next_id = f"STU-{1001 + len(self.students)}"
        self.enroll_entries["entry_id"].insert(0, next_id)
        self.enroll_entries["entry_batch"].insert(0, "2026-2030")

        self.btn_enroll_save = tk.Button(container, text="Capture Face & Enroll Student", command=self._enroll_student_action,
                             font=("Arial", 10, "bold"), bg="#059669", fg="#FFFFFF",
                             relief=tk.FLAT, padx=12, pady=8, cursor="hand2")
        self.btn_enroll_save.pack(fill=tk.X, pady=(15, 0))

        self.enroll_hint_label = tk.Label(
            container,
            text="Tip: face the camera clearly before enrolling. 8 face samples are captured automatically over ~2.5s.",
            font=("Arial", 8), fg="#64748B", bg="#1E293B", wraplength=340, justify=tk.LEFT
        )
        self.enroll_hint_label.pack(anchor="w", pady=(8, 0))

    def _build_statusbar(self):
        statusbar = tk.Frame(self.root, bg="#081521", height=28, padx=15)
        statusbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_left = tk.Label(statusbar, text="Device: Samsung 750XGK (720p HD Camera) | DirectShow Stream Active",
                                    font=("Arial", 8), fg="#8aa4bb", bg="#081521")
        self.status_left.pack(side=tk.LEFT)

        self.status_right = tk.Label(statusbar, text="Status: Online & Monitoring",
                                     font=("Arial", 8, "bold"), fg="#34d399", bg="#081521")
        self.status_right.pack(side=tk.RIGHT)

    # =========================================================================
    # HARDWARE & PRIVACY INTEGRATION
    # =========================================================================
    def _open_samsung_settings(self):
        try:
            subprocess.Popen(["cmd", "/c", "start", "samsungsettings:"], shell=True)
            self._set_banner("Opened Samsung Settings! Look for 'Privacy' > 'Block Camera and Mic' and toggle OFF.", "info")
        except Exception:
            messagebox.showinfo("Samsung Settings", "Please open Samsung Settings from your Windows Start Menu, go to 'Privacy' and disable 'Block Camera and Mic'.")

    def _open_windows_camera_settings(self):
        try:
            os.system("start ms-settings:privacy-webcam")
            self._set_banner("Opened Windows Camera Privacy Settings.", "info")
        except Exception:
            pass

    def _load_photo_dialog(self):
        filename = filedialog.askopenfilename(
            title="Select Face Image to Recognize",
            filetypes=[("Image Files", "*.jpg;*.jpeg;*.png;*.bmp;*.webp"), ("All Files", "*.*")]
        )
        if not filename:
            return

        try:
            img = Image.open(filename).convert("RGB")
            self.uploaded_image = img
            self.source_combo.set("Custom Image / Photo")
            self.live_badge.configure(text="PHOTO MODE", fg="#38BDF8")

            self.last_face_rect = None
            self.last_face_gray = None

            if self.face_engine is not None:
                cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                rect, face_gray = self.face_engine.largest_face(cv_img)
                if rect is not None:
                    self.last_face_rect = rect
                    self.last_face_gray = face_gray
                    self.last_face_source_size = (cv_img.shape[1], cv_img.shape[0])
                    self.last_face_seen_time = time.time()
                    self._set_banner(f"Loaded '{os.path.basename(filename)}' - face detected, ready for recognition!", "success")
                else:
                    self._set_banner(f"Loaded '{os.path.basename(filename)}', but no face was detected in it.", "warning")
            else:
                self._set_banner(f"Loaded image '{os.path.basename(filename)}'. (Face engine unavailable.)", "warning")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {str(e)}")

    def _start_camera_source(self, index):
        self.uploaded_image = None
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None

        if index == "sim" or not OPENCV_AVAILABLE:
            self.live_badge.configure(text="AI SIMULATION", fg="#38BDF8")
            self.troubleshoot_bar.pack_forget()
            self._set_banner("Running in AI Simulation mode.", "info")
            return

        self.camera_thread = WebcamCaptureThread(camera_index=int(index))
        self.camera_thread.start()
        self.live_badge.configure(text=f"LIVE CAM {index}", fg="#22C55E")
        self._set_banner(f"Connecting to Camera {index}...", "info")

    def _on_source_changed(self, event=None):
        val = self.source_combo.get()
        if "Camera 0" in val:
            self._start_camera_source(0)
        elif "Camera 1" in val:
            self._start_camera_source(1)
        else:
            self._start_camera_source("sim")

    def _restart_current_camera(self):
        self._set_banner("Restarting camera stream...", "info")
        self._on_source_changed()

    def _toggle_pause(self):
        self.is_feed_paused = not self.is_feed_paused
        if self.is_feed_paused:
            self.btn_camera.configure(text="Resume Feed", bg="#059669")
            self.live_badge.configure(text="PAUSED", fg="#F59E0B")
            self._set_banner("Camera feed paused.", "warning")
        else:
            self.btn_camera.configure(text="Pause Feed", bg="#334155")
            self.live_badge.configure(text="LIVE FEED", fg="#22C55E")
            self._set_banner("Camera feed resumed.", "info")

    def _on_slider_change(self, val):
        self.confidence_threshold = int(val)
        save_confidence_threshold(self.confidence_threshold)

    # =========================================================================
    # RECOGNITION & ATTENDANCE LOGIC
    # =========================================================================
    def _force_face_detection(self):
        if self.face_engine is None:
            self._set_banner("Face engine unavailable - check the console for the load error.", "warning")
            return

        if not self.recognition_enabled:
            self._set_banner("Recognition disabled: install opencv-contrib-python (pip install opencv-contrib-python).", "warning")
            return

        if self.last_face_gray is None or (time.time() - self.last_face_seen_time) > 1.5:
            self._set_banner("No face currently detected in frame. Face the camera and try again.", "warning")
            return

        student_id, confidence = self.face_engine.predict(self.last_face_gray)

        if student_id is None:
            self._set_banner("No enrolled faces to match against yet. Enroll a student first.", "warning")
            return

        if confidence < self.confidence_threshold:
            self._set_banner(f"Face detected but not confidently recognized (best match: {confidence:.0f}%, threshold: {self.confidence_threshold}%).", "warning")
            return

        student = next((s for s in self.students if s["id"] == student_id), None)
        if not student:
            self._set_banner("Recognized a face but no matching roster entry was found.", "warning")
            return

        self._record_attendance(student, round(confidence))

    def _record_attendance(self, student, confidence):
        curr_time = datetime.datetime.now().strftime("%I:%M:%S %p")

        for item in self.attendance_log:
            if item["id"] == student["id"]:
                self._set_banner(f"Duplicate scan: {student['name']} ({student['id']}) already marked at {item['time']}", "warning")
                return

        record = {
            "id": student["id"],
            "name": student["name"],
            "time": curr_time,
            "conf": f"{confidence}%",
            "status": "Verified"
        }
        self.attendance_log.insert(0, record)

        student["status"] = "Present"
        student["time"] = curr_time
        student["conf"] = f"{confidence}%"

        self.detected_face_info = {
            "student": student,
            "conf": confidence,
            "expire": time.time() + 3.5
        }

        self._refresh_log_tree()
        self._refresh_roster_tree()
        self._update_kpis()
        self._set_banner(f"Attendance Marked: {student['name']} [{student['id']}] - Conf: {confidence}%", "success")

    def _manual_mark_selected(self):
        sel = self.roster_tree.selection()
        if not sel:
            messagebox.showwarning("Select Student", "Please select a student from the roster first.")
            return

        item = self.roster_tree.item(sel[0])
        stu_id = item["values"][0]

        student = next((s for s in self.students if s["id"] == stu_id), None)
        if student:
            if student["status"] == "Present":
                messagebox.showinfo("Already Marked", f"{student['name']} is already marked present.")
                return
            self._record_attendance(student, confidence=100)

    def _delete_selected_student(self):
        sel = self.roster_tree.selection()
        if not sel:
            messagebox.showwarning("Select Student", "Please select a student from the roster first.")
            return

        item = self.roster_tree.item(sel[0])
        stu_id = item["values"][0]
        student = next((s for s in self.students if s["id"] == stu_id), None)
        if student is None:
            return

        confirmed = messagebox.askyesno(
            "Delete Student",
            f"Delete {student['name']} ({student['id']}) and all saved face samples?"
        )
        if not confirmed:
            return

        if self.face_engine is not None and not self.face_engine.delete_student(stu_id):
            messagebox.showerror("Delete Failed", f"Could not delete saved face samples for {student['name']}.")
            return

        self.students.remove(student)
        self.attendance_log = [record for record in self.attendance_log if record["id"] != stu_id]
        if self.detected_face_info and self.detected_face_info["student"]["id"] == stu_id:
            self.detected_face_info = None

        if self.face_engine is not None:
            self.face_engine.train()
        save_students_db(self.students)
        self._refresh_log_tree()
        self._refresh_roster_tree()
        self._update_kpis()
        self._set_banner(f"Deleted student {student['name']} ({student['id']}).", "info")

    def _enroll_student_action(self):
        stu_id = self.enroll_entries["entry_id"].get().strip()
        name = self.enroll_entries["entry_name"].get().strip()
        dept = self.enroll_entries["entry_dept"].get().strip()
        batch = self.enroll_entries["entry_batch"].get().strip()

        if not stu_id or not name:
            messagebox.showerror("Validation Error", "Student ID and Full Name are required.")
            return

        if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", stu_id):
            messagebox.showerror(
                "Invalid Student ID",
                "Student ID must be 2-32 characters and contain only letters, numbers, '-' or '_'."
            )
            return

        if any(s["id"].lower() == stu_id.lower() for s in self.students):
            messagebox.showerror("Duplicate ID", f"A student with ID {stu_id} already exists.")
            return

        if self.face_engine is None:
            messagebox.showerror("Face Engine Unavailable", "The face engine failed to load, so students can't be enrolled with face data.")
            return

        if not self.recognition_enabled:
            messagebox.showerror(
                "Recognition Disabled",
                "Recognition requires opencv-contrib-python (pip install opencv-contrib-python).\n"
                "Detection works without it, but faces can't be enrolled/matched yet."
            )
            return

        if self.last_face_gray is None or (time.time() - self.last_face_seen_time) > 1.5:
            messagebox.showerror("No Face Detected", "Position the person's face clearly in the camera preview (or load a clear photo of them) before enrolling.")
            return

        new_student = {
            "id": stu_id,
            "name": name,
            "dept": dept or "Computer Science",
            "batch": batch or "2026-2030",
            "status": "Not Marked",
            "time": "-",
            "conf": "-"
        }
        self.students.append(new_student)
        self._refresh_roster_tree()
        self._update_kpis()

        self.btn_enroll_save.configure(state=tk.DISABLED)
        self._enroll_capture_step(stu_id, name, sample_index=0, total_samples=8)

    def _enroll_capture_step(self, stu_id, name, sample_index, total_samples):
        """Grabs a fresh face sample from the current live detection every ~300ms
        so consecutive samples capture slightly different angles/expressions."""
        if self.last_face_gray is not None and (time.time() - self.last_face_seen_time) < 1.5:
            self.face_engine.save_sample(stu_id, self.last_face_gray, sample_index)
            sample_index += 1
            self._set_banner(f"Capturing face samples for {name}... ({sample_index}/{total_samples})", "info")

        if sample_index < total_samples:
            self.root.after(300, lambda: self._enroll_capture_step(stu_id, name, sample_index, total_samples))
        else:
            ok, msg = self.face_engine.train()
            save_students_db(self.students)  # persist roster so a restart doesn't lose enrolled students
            if ok:
                self._set_banner(f"Enrolled {name} ({stu_id}) - {msg}", "success")
            else:
                self._set_banner(f"Enrolled {name} ({stu_id}), but training failed: {msg}", "warning")

            self.btn_enroll_save.configure(state=tk.NORMAL)
            self.enroll_entries["entry_name"].delete(0, tk.END)
            next_id = f"STU-{1001 + len(self.students)}"
            self.enroll_entries["entry_id"].delete(0, tk.END)
            self.enroll_entries["entry_id"].insert(0, next_id)
            self.notebook.select(self.tab_students)

    def _export_attendance_csv(self):
        if not self.attendance_log:
            messagebox.showwarning("Empty Log", "No attendance records to export yet.")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=f"Attendance_Log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not filename:
            return

        try:
            with open(filename, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Student ID", "Full Name", "Time Marked", "Confidence", "Status", "Date"])
                date_str = datetime.date.today().isoformat()
                for rec in self.attendance_log:
                    writer.writerow([rec["id"], rec["name"], rec["time"], rec["conf"], rec["status"], date_str])

            messagebox.showinfo("Export Successful", f"Attendance log exported successfully to:\n{filename}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"An error occurred while saving the file:\n{str(e)}")

    def _clear_attendance_log(self):
        if not self.attendance_log:
            return
        if messagebox.askyesno("Confirm Clear", "Are you sure you want to clear the session attendance log?"):
            self.attendance_log.clear()
            self.detected_face_info = None
            for s in self.students:
                s["status"] = "Not Marked"
                s["time"] = "-"
                s["conf"] = "-"
            self._refresh_log_tree()
            self._refresh_roster_tree()
            self._update_kpis()
            self._set_banner("Session attendance log reset.", "info")

    def _set_banner(self, text, banner_type="info"):
        self.recent_banner_text = text
        self.recent_banner_type = banner_type

        colors = {
            "info": ("#38BDF8", "i"),
            "success": ("#22C55E", "OK"),
            "warning": ("#F59E0B", "!")
        }
        accent, icon = colors.get(banner_type, ("#38BDF8", "i"))

        self.banner_frame.configure(highlightbackground=accent)
        self.banner_icon.configure(text=icon, fg=accent)
        self.banner_label.configure(text=text)

    # =========================================================================
    # REFRESH HELPERS
    # =========================================================================
    def _refresh_log_tree(self, filter_text=""):
        for item in self.log_tree.get_children():
            self.log_tree.delete(item)

        filter_text = filter_text.lower().strip()
        for rec in self.attendance_log:
            if filter_text and filter_text not in rec["name"].lower() and filter_text not in rec["id"].lower():
                continue
            tag = "verified" if rec["status"] == "Verified" else "manual"
            self.log_tree.insert("", tk.END, values=(rec["id"], rec["name"], rec["time"], rec["conf"], rec["status"]), tags=(tag,))

    def _filter_attendance_log(self, event=None):
        text = self.search_entry.get()
        self._refresh_log_tree(text)

    def _refresh_roster_tree(self):
        for item in self.roster_tree.get_children():
            self.roster_tree.delete(item)

        for s in self.students:
            tag = "present" if s["status"] == "Present" else "absent"
            self.roster_tree.insert("", tk.END, values=(s["id"], s["name"], s["dept"], s["status"]), tags=(tag,))

    def _update_kpis(self):
        total = len(self.students)
        present = sum(1 for s in self.students if s["status"] == "Present")
        absent = total - present
        rate = f"{(present / total * 100):.0f}%" if total > 0 else "0%"

        self.kpi_enrolled.configure(text=str(total))
        self.kpi_present.configure(text=str(present))
        self.kpi_absent.configure(text=str(absent))
        self.kpi_rate.configure(text=rate)

    def _update_clock(self):
        now = datetime.datetime.now()
        self.clock_label.configure(text=now.strftime("%I:%M:%S %p"))
        self.date_label.configure(text=now.strftime("%A, %b %d, %Y"))
        self.root.after(1000, self._update_clock)

    # =========================================================================
    # VIDEO RENDERING PIPELINE
    # =========================================================================
    def _video_loop(self):
        if not self.is_feed_paused:
            self.anim_tick += 1
            self.fps_counter += 1

            now = time.time()
            if now - self.last_fps_time >= 1.0:
                self.current_fps = self.fps_counter / (now - self.last_fps_time)
                self.fps_counter = 0
                self.last_fps_time = now

            w = max(self.canvas.winfo_width(), self.canvas_width)
            h = max(self.canvas.winfo_height(), self.canvas_height)

            if self.uploaded_image is not None:
                pil_image = self.uploaded_image.copy().resize((w, h), Image.Resampling.BILINEAR)
                is_hardware_cam = True
                is_black = False
                if self.last_face_rect is not None:
                    # Static photo: keep its one-time detection "fresh" so it doesn't
                    # expire from the HUD/recognition just because time passed.
                    self.last_face_seen_time = time.time()
                if self.black_frame_warning_shown:
                    self.troubleshoot_bar.pack_forget()
                    self.black_frame_warning_shown = False
            else:
                raw_cv_frame, is_black = self.camera_thread.get_frame_and_status() if self.camera_thread else (None, False)

                if is_black and self.camera_thread and self.camera_thread.is_connected:
                    if not self.black_frame_warning_shown:
                        self.troubleshoot_bar.pack(fill=tk.X, pady=(4, 0))
                        self.black_frame_warning_shown = True
                else:
                    if self.black_frame_warning_shown:
                        self.troubleshoot_bar.pack_forget()
                        self.black_frame_warning_shown = False

                if raw_cv_frame is not None and not is_black:
                    raw_cv_frame = cv2.flip(raw_cv_frame, 1)
                    if self.face_engine is not None and self.anim_tick % 2 == 0:
                        self._update_face_detection(raw_cv_frame)
                    rgb = cv2.cvtColor(raw_cv_frame, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(rgb).resize((w, h), Image.Resampling.BILINEAR)
                    is_hardware_cam = True
                else:
                    pil_image = self._generate_synthetic_feed(w, h, is_black)
                    is_hardware_cam = False
                    self.last_face_rect = None  # no real frame -> nothing real was detected

            pil_image = self._apply_hud_overlay(pil_image, w, h, is_hardware_cam, is_black)

            self.tk_image = ImageTk.PhotoImage(pil_image)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")

        self.root.after(25, self._video_loop)

    def _update_face_detection(self, bgr_frame):
        """Runs real Haar-cascade detection on the current camera frame and
        updates the last-known face box/crop used for the HUD and recognition."""
        try:
            rect, face_gray = self.face_engine.largest_face(bgr_frame, downscale=0.5)
        except Exception:
            rect, face_gray = None, None

        if rect is not None:
            self.last_face_rect = rect
            self.last_face_gray = face_gray
            self.last_face_source_size = (bgr_frame.shape[1], bgr_frame.shape[0])
            self.last_face_seen_time = time.time()
        # If no face this tick, we deliberately leave the old rect in place.
        # _apply_hud_overlay expires it based on last_face_seen_time, so a brief
        # miss doesn't cause flicker, but a real absence still expires within ~1.2s.

    def _generate_synthetic_feed(self, width, height, is_black=False):
        img = Image.new("RGB", (width, height), color=(11, 15, 25))
        draw = ImageDraw.Draw(img)

        grid_size = 40
        for x in range(0, width, grid_size):
            draw.line([(x, 0), (x, height)], fill=(18, 26, 43), width=1)
        for y in range(0, height, grid_size):
            draw.line([(0, y), (width, y)], fill=(18, 26, 43), width=1)

        if is_black:
            draw.text((width // 2 - 145, height // 2 - 60), "SAMSUNG PRIVACY LOCK ACTIVE (BLACK FEED)", fill=(239, 68, 68))
            draw.text((width // 2 - 165, height // 2 - 38), "1. Press [ Fn + F11 ] on your Samsung keyboard", fill=(248, 113, 113))
            draw.text((width // 2 - 165, height // 2 - 18), "2. In Samsung Settings > Privacy > Turn OFF 'Block Camera'", fill=(248, 113, 113))
            draw.text((width // 2 - 165, height // 2 + 2), "3. Or click 'Load Face Photo' to test with an image file", fill=(248, 113, 113))
        else:
            draw.text((width // 2 - 90, height // 2 - 50), "CONNECTING CAMERA...", fill=(56, 189, 248))

        return img

    def _apply_hud_overlay(self, img, width, height, is_hardware_cam, is_black):
        draw = ImageDraw.Draw(img)

        now = time.time()
        is_recognized = self.detected_face_info and now < self.detected_face_info["expire"]

        # Resolve the REAL detected face box (from Haar cascade), scaled from
        # the source frame's pixel space into this canvas's pixel space.
        face_box = None
        if self.last_face_rect is not None and (now - self.last_face_seen_time) < 1.2:
            src_w, src_h = self.last_face_source_size
            if src_w and src_h:
                sx, sy = width / src_w, height / src_h
                fx, fy, fw, fh = self.last_face_rect
                bx1, by1 = int(fx * sx), int(fy * sy)
                bx2, by2 = int((fx + fw) * sx), int((fy + fh) * sy)
                face_box = (bx1, by1, bx2, by2)

        if face_box:
            x1, y1, x2, y2 = face_box
            hud_color = (34, 197, 94) if is_recognized else (56, 189, 248)

            c_len = max(14, int(min(x2 - x1, y2 - y1) * 0.18))
            th = 3
            draw.line([(x1, y1), (x1 + c_len, y1)], fill=hud_color, width=th)
            draw.line([(x1, y1), (x1, y1 + c_len)], fill=hud_color, width=th)
            draw.line([(x2, y1), (x2 - c_len, y1)], fill=hud_color, width=th)
            draw.line([(x2, y1), (x2, y1 + c_len)], fill=hud_color, width=th)
            draw.line([(x1, y2), (x1 + c_len, y2)], fill=hud_color, width=th)
            draw.line([(x1, y2), (x1, y2 - c_len)], fill=hud_color, width=th)
            draw.line([(x2, y2), (x2 - c_len, y2)], fill=hud_color, width=th)
            draw.line([(x2, y2), (x2, y2 - c_len)], fill=hud_color, width=th)

            tag_text = "FACE RECOGNIZED & VERIFIED" if is_recognized else "FACE DETECTED"
            draw.rectangle([(x1, y1 - 22), (x1 + 200, y1 - 2)], fill=(15, 23, 42))
            draw.text((x1 + 6, y1 - 19), tag_text, fill=hud_color)

            if is_recognized:
                student = self.detected_face_info["student"]
                conf = self.detected_face_info["conf"]
                card_h = 62
                draw.rectangle([(x1, y2 + 6), (x1 + 230, y2 + 6 + card_h)], fill=(15, 23, 42), outline=(34, 197, 94), width=1)
                draw.text((x1 + 10, y2 + 12), f"{student['name']} ({student['id']})", fill=(248, 250, 252))
                draw.text((x1 + 10, y2 + 30), f"Dept: {student['dept']}", fill=(148, 163, 184))
                draw.text((x1 + 10, y2 + 46), f"Match Confidence: {conf}% (VERIFIED)", fill=(74, 222, 128))
        else:
            # No real face currently detected - an honest "searching" indicator,
            # not a fake bounding box sitting over nothing.
            scan_y = int(height * 0.5 + math.sin(self.anim_tick * 0.08) * height * 0.15)
            draw.line([(40, scan_y), (width - 40, scan_y)], fill=(56, 189, 248), width=1)
            draw.rectangle([(width // 2 - 95, height - 34), (width // 2 + 95, height - 12)], fill=(15, 23, 42))
            draw.text((width // 2 - 85, height - 30), "SEARCHING FOR FACE...", fill=(56, 189, 248))

        if is_black:
            cam_status_text = "SAMSUNG PRIVACY LOCK [BLACK]"
        elif self.uploaded_image is not None:
            cam_status_text = "PHOTO SOURCE [LOADED]"
        elif is_hardware_cam:
            cam_status_text = "HARDWARE WEBCAM [LIVE]"
        else:
            cam_status_text = "AI SIMULATION [ACTIVE]"

        draw.text((15, 15), f"STREAM: {cam_status_text}", fill=(148, 163, 184))
        draw.text((15, 32), f"FPS: {self.current_fps:.1f} | RES: {width}x{height}", fill=(100, 116, 139))

        if self.recognition_enabled:
            engine_text, engine_color = "AI ENGINE: ONLINE", (34, 197, 94)
        elif self.face_engine is not None:
            engine_text, engine_color = "AI ENGINE: DETECT-ONLY", (245, 158, 11)
        else:
            engine_text, engine_color = "AI ENGINE: OFFLINE", (239, 68, 68)
        draw.text((width - 190, 15), engine_text, fill=engine_color)
        draw.text((width - 190, 32), f"THRESHOLD: {self.confidence_threshold}%", fill=(56, 189, 248))

        return img

    def _on_close(self):
        if self.camera_thread:
            self.camera_thread.stop()
        self.root.destroy()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
def main():
    root = tk.Tk()
    app = AttendanceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
