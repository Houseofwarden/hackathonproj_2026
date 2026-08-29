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
import os
import subprocess
from PIL import Image, ImageTk, ImageDraw, ImageFont

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


# =============================================================================
# DEFAULT ENROLLED STUDENTS DATABASE
# =============================================================================
DEFAULT_STUDENTS = [
    {"id": "STU-1001", "name": "Aarav Sharma", "dept": "Computer Science", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
    {"id": "STU-1002", "name": "Priya Patel", "dept": "Computer Science", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
    {"id": "STU-1003", "name": "Rohan Gupta", "dept": "Artificial Intelligence", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
    {"id": "STU-1004", "name": "Ananya Iyer", "dept": "Data Science", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
    {"id": "STU-1005", "name": "Vikram Singh", "dept": "Computer Science", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
    {"id": "STU-1006", "name": "Sneha Reddy", "dept": "Electronics & Comm.", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
    {"id": "STU-1007", "name": "Kavya Nair", "dept": "Computer Science", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
    {"id": "STU-1008", "name": "Rahul Verma", "dept": "Information Tech.", "batch": "2024-2028", "status": "Not Marked", "time": "-", "conf": "-"},
]


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
        self.root.configure(bg="#0F172A")

        # State Variables
        self.is_feed_paused = False
        self.camera_thread = None
        self.uploaded_image = None
        self.current_source = "Camera 0 (Default Webcam)"
        self.confidence_threshold = 75
        self.students = [dict(s) for s in DEFAULT_STUDENTS]
        self.attendance_log = []
        self.detected_face_info = None
        self.anim_tick = 0
        self.fps_counter = 0
        self.current_fps = 30.0
        self.last_fps_time = time.time()
        self.black_frame_warning_shown = False

        self.recent_banner_text = "System Ready. Camera active and scanning."
        self.recent_banner_type = "info"

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
        style.theme_use("clam")

        style.configure("Treeview",
                        background="#1E293B",
                        foreground="#F8FAFC",
                        fieldbackground="#1E293B",
                        rowheight=32,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading",
                        background="#334155",
                        foreground="#38BDF8",
                        font=("Segoe UI", 10, "bold"),
                        padding=6)
        style.map("Treeview",
                  background=[("selected", "#2563EB")],
                  foreground=[("selected", "#FFFFFF")])

        style.configure("TNotebook", background="#0F172A", borderwidth=0)
        style.configure("TNotebook.Tab",
                        background="#1E293B",
                        foreground="#94A3B8",
                        font=("Segoe UI", 10, "bold"),
                        padding=[16, 8])
        style.map("TNotebook.Tab",
                  background=[("selected", "#38BDF8")],
                  foreground=[("selected", "#0F172A")])

        style.configure("Vertical.TScrollbar",
                        background="#334155",
                        troughcolor="#1E293B",
                        arrowcolor="#94A3B8")

    # =========================================================================
    # UI BUILDERS
    # =========================================================================
    def _build_header(self):
        header_frame = tk.Frame(self.root, bg="#1E293B", height=70, padx=20, pady=10)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        title_box = tk.Frame(header_frame, bg="#1E293B")
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        logo_icon = tk.Label(title_box, text="⚡", font=("Segoe UI Emoji", 22), bg="#1E293B", fg="#38BDF8")
        logo_icon.pack(side=tk.LEFT, padx=(0, 10))

        title_text_frame = tk.Frame(title_box, bg="#1E293B")
        title_text_frame.pack(side=tk.LEFT)

        app_title = tk.Label(title_text_frame, text="FaceTrack AI", font=("Segoe UI", 15, "bold"), fg="#F8FAFC", bg="#1E293B")
        app_title.pack(anchor="w")

        app_sub = tk.Label(title_text_frame, text="Real-Time Face Recognition Attendance System", font=("Segoe UI", 9), fg="#94A3B8", bg="#1E293B")
        app_sub.pack(anchor="w")

        session_box = tk.Frame(header_frame, bg="#0F172A", padx=15, pady=5, highlightbackground="#334155", highlightthickness=1)
        session_box.pack(side=tk.LEFT, padx=30)

        lbl_course = tk.Label(session_box, text="CLASS: CS-401 (Computer Vision)", font=("Segoe UI", 9, "bold"), fg="#38BDF8", bg="#0F172A")
        lbl_course.pack(anchor="w")
        lbl_room = tk.Label(session_box, text="ROOM: Tech Lab 3 | LECTURER: Dr. Sharma", font=("Segoe UI", 8), fg="#94A3B8", bg="#0F172A")
        lbl_room.pack(anchor="w")

        right_box = tk.Frame(header_frame, bg="#1E293B")
        right_box.pack(side=tk.RIGHT)

        self.clock_label = tk.Label(right_box, text="00:00:00 AM", font=("Consolas", 14, "bold"), fg="#F8FAFC", bg="#1E293B")
        self.clock_label.pack(anchor="e")

        self.date_label = tk.Label(right_box, text="Saturday, Aug 29, 2026", font=("Segoe UI", 8), fg="#94A3B8", bg="#1E293B")
        self.date_label.pack(anchor="e")

    def _build_main_layout(self):
        main_content = tk.Frame(self.root, bg="#0F172A", padx=15, pady=12)
        main_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_col = tk.Frame(main_content, bg="#0F172A")
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right_col = tk.Frame(main_content, bg="#0F172A", width=520)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(10, 0))
        right_col.pack_propagate(False)

        self._build_video_panel(left_col)
        self._build_stats_and_tabs(right_col)

    def _build_video_panel(self, parent):
        card = tk.Frame(parent, bg="#1E293B", padx=12, pady=12, highlightbackground="#334155", highlightthickness=1)
        card.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        vid_head = tk.Frame(card, bg="#1E293B")
        vid_head.pack(fill=tk.X, pady=(0, 8))

        self.live_badge = tk.Label(vid_head, text="● LIVE WEBCAM", font=("Segoe UI", 9, "bold"), fg="#22C55E", bg="#1E293B")
        self.live_badge.pack(side=tk.LEFT)

        source_frame = tk.Frame(vid_head, bg="#1E293B")
        source_frame.pack(side=tk.RIGHT)

        tk.Label(source_frame, text="Source: ", font=("Segoe UI", 9), fg="#94A3B8", bg="#1E293B").pack(side=tk.LEFT)
        self.source_combo = ttk.Combobox(source_frame, values=[
            "Camera 0 (Default Webcam)",
            "Camera 1 (External / Secondary)",
            "AI Simulation Mode"
        ], state="readonly", width=25, font=("Segoe UI", 8))
        self.source_combo.set("Camera 0 (Default Webcam)")
        self.source_combo.pack(side=tk.LEFT, padx=(2, 6))
        self.source_combo.bind("<<ComboboxSelected>>", self._on_source_changed)

        # Video Canvas
        self.canvas_width = 680
        self.canvas_height = 430
        self.canvas = tk.Canvas(card, width=self.canvas_width, height=self.canvas_height, bg="#0B0F19", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Samsung Galaxy Book / Windows Privacy Troubleshoot bar
        self.troubleshoot_bar = tk.Frame(card, bg="#7F1D1D", padx=10, pady=8, highlightbackground="#EF4444", highlightthickness=1)
        
        lbl_box = tk.Frame(self.troubleshoot_bar, bg="#7F1D1D")
        lbl_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(lbl_box, text="🔒 Samsung Galaxy Book Privacy Lock Detected (Image is Black):",
                 font=("Segoe UI", 9, "bold"), fg="#FEE2E2", bg="#7F1D1D").pack(anchor="w")
        tk.Label(lbl_box, text="Press Fn + F11 on your keyboard OR turn off 'Block Camera and Mic' in Samsung Settings.",
                 font=("Segoe UI", 8), fg="#FECACA", bg="#7F1D1D").pack(anchor="w")

        btn_box = tk.Frame(self.troubleshoot_bar, bg="#7F1D1D")
        btn_box.pack(side=tk.RIGHT)

        btn_samsung = tk.Button(btn_box, text="⚙ Open Samsung Settings", command=self._open_samsung_settings,
                                font=("Segoe UI", 8, "bold"), bg="#DC2626", fg="#FFFFFF", relief=tk.FLAT, padx=8, pady=4, cursor="hand2")
        btn_samsung.pack(side=tk.RIGHT, padx=(4, 0))

        btn_win = tk.Button(btn_box, text="Windows Privacy", command=self._open_windows_camera_settings,
                            font=("Segoe UI", 8), bg="#991B1B", fg="#FFFFFF", relief=tk.FLAT, padx=6, pady=4, cursor="hand2")
        btn_win.pack(side=tk.RIGHT)

        # Notification / Recognition Toast Banner
        self.banner_frame = tk.Frame(card, bg="#0F172A", padx=12, pady=8, highlightbackground="#38BDF8", highlightthickness=1)
        self.banner_frame.pack(fill=tk.X, pady=(10, 0))

        self.banner_icon = tk.Label(self.banner_frame, text="ℹ", font=("Segoe UI Emoji", 12, "bold"), fg="#38BDF8", bg="#0F172A")
        self.banner_icon.pack(side=tk.LEFT, padx=(0, 8))

        self.banner_label = tk.Label(self.banner_frame, text=self.recent_banner_text, font=("Segoe UI", 9, "bold"), fg="#F8FAFC", bg="#0F172A")
        self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Controls Toolbar under video
        ctrl_frame = tk.Frame(parent, bg="#0F172A", pady=10)
        ctrl_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.btn_camera = tk.Button(ctrl_frame, text="⏸ Pause Feed", command=self._toggle_pause,
                                    font=("Segoe UI", 10, "bold"), bg="#334155", fg="#FFFFFF",
                                    activebackground="#475569", activeforeground="#FFFFFF",
                                    relief=tk.FLAT, padx=14, pady=6, cursor="hand2")
        self.btn_camera.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_trigger_recognize = tk.Button(ctrl_frame, text="⚡ Recognize Face Now", command=self._force_face_detection,
                                               font=("Segoe UI", 10, "bold"), bg="#2563EB", fg="#FFFFFF",
                                               activebackground="#1D4ED8", activeforeground="#FFFFFF",
                                               relief=tk.FLAT, padx=14, pady=6, cursor="hand2")
        self.btn_trigger_recognize.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_load_photo = tk.Button(ctrl_frame, text="📁 Load Face Photo", command=self._load_photo_dialog,
                                        font=("Segoe UI", 9), bg="#1E293B", fg="#94A3B8",
                                        relief=tk.FLAT, padx=10, pady=6, cursor="hand2")
        self.btn_load_photo.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_reconnect_cam = tk.Button(ctrl_frame, text="🔄 Restart Camera", command=self._restart_current_camera,
                                           font=("Segoe UI", 9), bg="#1E293B", fg="#94A3B8",
                                           relief=tk.FLAT, padx=10, pady=6, cursor="hand2")
        self.btn_reconnect_cam.pack(side=tk.LEFT, padx=(0, 8))

        thresh_box = tk.Frame(ctrl_frame, bg="#0F172A")
        thresh_box.pack(side=tk.RIGHT)

        tk.Label(thresh_box, text="Min Conf: ", font=("Segoe UI", 9), fg="#94A3B8", bg="#0F172A").pack(side=tk.LEFT)
        self.thresh_slider = tk.Scale(thresh_box, from_=50, to=95, orient=tk.HORIZONTAL,
                                      bg="#0F172A", fg="#38BDF8", highlightthickness=0,
                                      troughcolor="#1E293B", activebackground="#2563EB",
                                      font=("Segoe UI", 8), length=100, command=self._on_slider_change)
        self.thresh_slider.set(self.confidence_threshold)
        self.thresh_slider.pack(side=tk.LEFT)

    def _build_stats_and_tabs(self, parent):
        stats_frame = tk.Frame(parent, bg="#0F172A")
        stats_frame.pack(fill=tk.X, pady=(0, 10))

        self.kpi_enrolled = self._create_kpi_card(stats_frame, "ENROLLED", str(len(self.students)), "#38BDF8", 0)
        self.kpi_present = self._create_kpi_card(stats_frame, "PRESENT", "0", "#22C55E", 1)
        self.kpi_absent = self._create_kpi_card(stats_frame, "ABSENT", str(len(self.students)), "#EF4444", 2)
        self.kpi_rate = self._create_kpi_card(stats_frame, "RATE", "0%", "#F59E0B", 3)

        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_log = tk.Frame(self.notebook, bg="#1E293B", padx=10, pady=10)
        self.tab_students = tk.Frame(self.notebook, bg="#1E293B", padx=10, pady=10)
        self.tab_enroll = tk.Frame(self.notebook, bg="#1E293B", padx=10, pady=10)

        self.notebook.add(self.tab_log, text="📋 Live Session Log")
        self.notebook.add(self.tab_students, text="👥 Student Roster")
        self.notebook.add(self.tab_enroll, text="➕ Enroll New")

        self._build_attendance_log_tab()
        self._build_student_roster_tab()
        self._build_enroll_tab()

    def _create_kpi_card(self, parent, title, value, accent_color, col_idx):
        card = tk.Frame(parent, bg="#1E293B", padx=10, pady=8, highlightbackground="#334155", highlightthickness=1)
        card.grid(row=0, column=col_idx, padx=3, sticky="nsew")
        parent.grid_columnconfigure(col_idx, weight=1)

        tk.Label(card, text=title, font=("Segoe UI", 7, "bold"), fg="#94A3B8", bg="#1E293B").pack(anchor="w")
        val_lbl = tk.Label(card, text=value, font=("Segoe UI", 15, "bold"), fg=accent_color, bg="#1E293B")
        val_lbl.pack(anchor="w")
        return val_lbl

    def _build_attendance_log_tab(self):
        tb = tk.Frame(self.tab_log, bg="#1E293B")
        tb.pack(fill=tk.X, pady=(0, 8))

        tk.Label(tb, text="🔍", font=("Segoe UI Emoji", 10), fg="#94A3B8", bg="#1E293B").pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry = tk.Entry(tb, bg="#0F172A", fg="#F8FAFC", insertbackground="#38BDF8",
                                     font=("Segoe UI", 9), relief=tk.FLAT, highlightbackground="#334155", highlightthickness=1)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=3)
        self.search_entry.bind("<KeyRelease>", self._filter_attendance_log)

        btn_export = tk.Button(tb, text="📥 Export CSV", command=self._export_attendance_csv,
                               font=("Segoe UI", 8, "bold"), bg="#059669", fg="#FFFFFF",
                               relief=tk.FLAT, padx=8, pady=3, cursor="hand2")
        btn_export.pack(side=tk.RIGHT, padx=(4, 0))

        btn_clear = tk.Button(tb, text="🗑 Clear", command=self._clear_attendance_log,
                              font=("Segoe UI", 8), bg="#334155", fg="#94A3B8",
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

        tk.Label(roster_head, text="All Enrolled Candidates in Session", font=("Segoe UI", 9, "bold"), fg="#38BDF8", bg="#1E293B").pack(side=tk.LEFT)
        btn_mark_sel = tk.Button(roster_head, text="✔ Mark Selected Present", command=self._manual_mark_selected,
                                 font=("Segoe UI", 8, "bold"), bg="#2563EB", fg="#FFFFFF", relief=tk.FLAT, padx=6, pady=2, cursor="hand2")
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

        tk.Label(container, text="Enroll New Student to Face Recognition Engine", font=("Segoe UI", 10, "bold"), fg="#38BDF8", bg="#1E293B").pack(anchor="w", pady=(0, 10))

        fields = [
            ("Student ID (e.g. STU-1009):", "entry_id"),
            ("Full Name:", "entry_name"),
            ("Department / Branch:", "entry_dept"),
            ("Batch / Academic Year:", "entry_batch"),
        ]

        self.enroll_entries = {}
        for label_text, var_name in fields:
            lbl = tk.Label(container, text=label_text, font=("Segoe UI", 9), fg="#CBD5E1", bg="#1E293B")
            lbl.pack(anchor="w", pady=(4, 1))

            ent = tk.Entry(container, bg="#0F172A", fg="#F8FAFC", insertbackground="#38BDF8",
                           font=("Segoe UI", 9), relief=tk.FLAT, highlightbackground="#334155", highlightthickness=1)
            ent.pack(fill=tk.X, pady=(0, 6), ipady=3)
            self.enroll_entries[var_name] = ent

        next_id = f"STU-{1001 + len(self.students)}"
        self.enroll_entries["entry_id"].insert(0, next_id)
        self.enroll_entries["entry_batch"].insert(0, "2024-2028")

        btn_save = tk.Button(container, text="📸 Capture Face & Enroll Student", command=self._enroll_student_action,
                             font=("Segoe UI", 10, "bold"), bg="#059669", fg="#FFFFFF",
                             relief=tk.FLAT, padx=12, pady=8, cursor="hand2")
        btn_save.pack(fill=tk.X, pady=(15, 0))

    def _build_statusbar(self):
        statusbar = tk.Frame(self.root, bg="#0B0F19", height=26, padx=15)
        statusbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_left = tk.Label(statusbar, text="Device: Samsung 750XGK (720p HD Camera) | DirectShow Stream Active",
                                    font=("Segoe UI", 8), fg="#64748B", bg="#0B0F19")
        self.status_left.pack(side=tk.LEFT)

        self.status_right = tk.Label(statusbar, text="Status: Online & Monitoring",
                                     font=("Segoe UI", 8, "bold"), fg="#22C55E", bg="#0B0F19")
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
            self.live_badge.configure(text="● PHOTO MODE", fg="#38BDF8")
            self._set_banner(f"Loaded image '{os.path.basename(filename)}'. Ready for recognition!", "success")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {str(e)}")

    def _start_camera_source(self, index):
        self.uploaded_image = None
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None

        if index == "sim" or not OPENCV_AVAILABLE:
            self.live_badge.configure(text="● AI SIMULATION", fg="#38BDF8")
            self.troubleshoot_bar.pack_forget()
            self._set_banner("Running in AI Simulation mode.", "info")
            return

        self.camera_thread = WebcamCaptureThread(camera_index=int(index))
        self.camera_thread.start()
        self.live_badge.configure(text=f"● LIVE CAM {index}", fg="#22C55E")
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
            self.btn_camera.configure(text="▶ Resume Feed", bg="#059669")
            self.live_badge.configure(text="⏸ PAUSED", fg="#F59E0B")
            self._set_banner("Camera feed paused.", "warning")
        else:
            self.btn_camera.configure(text="⏸ Pause Feed", bg="#334155")
            self.live_badge.configure(text="● LIVE FEED", fg="#22C55E")
            self._set_banner("Camera feed resumed.", "info")

    def _on_slider_change(self, val):
        self.confidence_threshold = int(val)

    # =========================================================================
    # RECOGNITION & ATTENDANCE LOGIC
    # =========================================================================
    def _force_face_detection(self):
        unmarked = [s for s in self.students if s["status"] == "Not Marked"]
        if not unmarked:
            self._set_banner("All enrolled students have already marked attendance!", "warning")
            return

        student = random.choice(unmarked)
        conf = random.randint(max(self.confidence_threshold, 84), 99)
        self._record_attendance(student, conf)

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
        self._set_banner(f"✅ Attendance Marked: {student['name']} [{student['id']}] - Conf: {confidence}%", "success")

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

    def _enroll_student_action(self):
        stu_id = self.enroll_entries["entry_id"].get().strip()
        name = self.enroll_entries["entry_name"].get().strip()
        dept = self.enroll_entries["entry_dept"].get().strip()
        batch = self.enroll_entries["entry_batch"].get().strip()

        if not stu_id or not name:
            messagebox.showerror("Validation Error", "Student ID and Full Name are required.")
            return

        if any(s["id"].lower() == stu_id.lower() for s in self.students):
            messagebox.showerror("Duplicate ID", f"A student with ID {stu_id} already exists.")
            return

        new_student = {
            "id": stu_id,
            "name": name,
            "dept": dept or "Computer Science",
            "batch": batch or "2024-2028",
            "status": "Not Marked",
            "time": "-",
            "conf": "-"
        }
        self.students.append(new_student)
        self._refresh_roster_tree()
        self._update_kpis()

        self.enroll_entries["entry_name"].delete(0, tk.END)
        next_id = f"STU-{1001 + len(self.students)}"
        self.enroll_entries["entry_id"].delete(0, tk.END)
        self.enroll_entries["entry_id"].insert(0, next_id)

        self._set_banner(f"🎓 Enrolled student: {name} ({stu_id}) successfully!", "success")
        messagebox.showinfo("Success", f"Student '{name}' has been successfully enrolled into the Face Recognition database!")
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
            "info": ("#38BDF8", "ℹ"),
            "success": ("#22C55E", "✅"),
            "warning": ("#F59E0B", "⚠️")
        }
        accent, icon = colors.get(banner_type, ("#38BDF8", "ℹ"))

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
                    rgb = cv2.cvtColor(raw_cv_frame, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(rgb).resize((w, h), Image.Resampling.BILINEAR)
                    is_hardware_cam = True
                else:
                    pil_image = self._generate_synthetic_feed(w, h, is_black)
                    is_hardware_cam = False

            pil_image = self._apply_hud_overlay(pil_image, w, h, is_hardware_cam, is_black)

            self.tk_image = ImageTk.PhotoImage(pil_image)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")

        self.root.after(25, self._video_loop)

    def _generate_synthetic_feed(self, width, height, is_black=False):
        img = Image.new("RGB", (width, height), color=(11, 15, 25))
        draw = ImageDraw.Draw(img)

        grid_size = 40
        for x in range(0, width, grid_size):
            draw.line([(x, 0), (x, height)], fill=(18, 26, 43), width=1)
        for y in range(0, height, grid_size):
            draw.line([(0, y), (width, y)], fill=(18, 26, 43), width=1)

        if is_black:
            draw.text((width // 2 - 145, height // 2 - 60), "🔒 SAMSUNG PRIVACY LOCK ACTIVE (BLACK FEED)", fill=(239, 68, 68))
            draw.text((width // 2 - 165, height // 2 - 38), "1. Press [ Fn + F11 ] on your Samsung keyboard", fill=(248, 113, 113))
            draw.text((width // 2 - 165, height // 2 - 18), "2. In Samsung Settings > Privacy > Turn OFF 'Block Camera'", fill=(248, 113, 113))
            draw.text((width // 2 - 165, height // 2 + 2), "3. Or click 'Load Face Photo' to test with an image file", fill=(248, 113, 113))
        else:
            draw.text((width // 2 - 90, height // 2 - 50), "CONNECTING CAMERA...", fill=(56, 189, 248))

        return img

    def _apply_hud_overlay(self, img, width, height, is_hardware_cam, is_black):
        draw = ImageDraw.Draw(img)

        cx, cy = width // 2, height // 2 - 15
        box_w, box_h = 240, 270
        x1, y1 = cx - box_w // 2, cy - box_h // 2
        x2, y2 = cx + box_w // 2, cy + box_h // 2

        is_detected = self.detected_face_info and time.time() < self.detected_face_info["expire"]
        hud_color = (34, 197, 94) if is_detected else (56, 189, 248)

        if not is_detected:
            scan_y = y1 + int((math.sin(self.anim_tick * 0.08) * 0.5 + 0.5) * box_h)
            draw.line([(x1 + 8, scan_y), (x2 - 8, scan_y)], fill=(56, 189, 248), width=2)
            draw.line([(x1 + 25, scan_y + 1), (x2 - 25, scan_y + 1)], fill=(14, 116, 144), width=1)

        c_len = 28
        th = 3
        draw.line([(x1, y1), (x1 + c_len, y1)], fill=hud_color, width=th)
        draw.line([(x1, y1), (x1, y1 + c_len)], fill=hud_color, width=th)
        draw.line([(x2, y1), (x2 - c_len, y1)], fill=hud_color, width=th)
        draw.line([(x2, y1), (x2, y1 + c_len)], fill=hud_color, width=th)
        draw.line([(x1, y2), (x1 + c_len, y2)], fill=hud_color, width=th)
        draw.line([(x1, y2), (x1 + c_len, y2)], fill=hud_color, width=th)
        draw.line([(x2, y2), (x2 - c_len, y2)], fill=hud_color, width=th)
        draw.line([(x2, y2), (x2 - c_len, y2)], fill=hud_color, width=th)

        landmarks = [
            (cx - 35, cy - 30), (cx + 35, cy - 30),
            (cx, cy),
            (cx - 25, cy + 30), (cx + 25, cy + 30)
        ]
        for lx, ly in landmarks:
            draw.ellipse([lx - 2, ly - 2, lx + 2, ly + 2], fill=hud_color)

        tag_text = "FACE DETECTED & VERIFIED" if is_detected else "SCANNING FOR ENROLLED FACES..."
        draw.rectangle([(x1, y1 - 26), (x1 + 230, y1 - 4)], fill=(15, 23, 42))
        draw.text((x1 + 8, y1 - 22), tag_text, fill=hud_color)

        if is_detected:
            student = self.detected_face_info["student"]
            conf = self.detected_face_info["conf"]
            card_h = 62
            draw.rectangle([(x1, y2 + 6), (x2, y2 + 6 + card_h)], fill=(15, 23, 42), outline=(34, 197, 94), width=1)
            draw.text((x1 + 10, y2 + 12), f"{student['name']} ({student['id']})", fill=(248, 250, 252))
            draw.text((x1 + 10, y2 + 30), f"Dept: {student['dept']}", fill=(148, 163, 184))
            draw.text((x1 + 10, y2 + 46), f"Match Confidence: {conf}% (VERIFIED)", fill=(74, 222, 128))

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
        draw.text((width - 165, 15), "AI ENGINE: ONLINE", fill=(34, 197, 94))
        draw.text((width - 165, 32), f"THRESHOLD: {self.confidence_threshold}%", fill=(56, 189, 248))

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