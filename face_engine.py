"""
=============================================================================
face_engine.py - Real face detection & recognition backend for FaceTrack AI
=============================================================================
Detection : OpenCV Haar cascade (bundled haarcascade_frontalface_default.xml)
Recognition: OpenCV LBPH (Local Binary Patterns Histograms) face recognizer,
             trained on-the-fly from face samples captured during enrollment.

LBPH needs the `opencv-contrib-python` package (cv2.face.*). Detection alone
works with plain `opencv-python`. If cv2.face isn't available, recognition
is disabled but detection (a real bounding box) still works.
=============================================================================
"""

import os
import shutil
import re
import cv2
import numpy as np

FACE_SIZE = (200, 200)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CASCADE_PATH = os.path.join(_BASE_DIR, "haarcascade_frontalface_default.xml")
FACES_DIR = os.path.join(_BASE_DIR, "enrolled_faces")


class FaceEngine:
    def __init__(self):
        self.cascade = cv2.CascadeClassifier(CASCADE_PATH)
        if self.cascade.empty():
            raise RuntimeError(f"Failed to load Haar cascade at {CASCADE_PATH}")

        self.has_recognizer_backend = hasattr(cv2, "face")
        self.recognizer = None
        self.label_to_id = {}   # int label -> student_id
        self.id_to_label = {}   # student_id -> int label

        os.makedirs(FACES_DIR, exist_ok=True)

    # -------------------------------------------------------------------
    # Detection
    # -------------------------------------------------------------------
    def detect_faces(self, bgr_frame):
        """Return (faces, gray) where faces is a list of (x, y, w, h),
        largest first, and gray is the equalized grayscale frame used."""
        gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self.cascade.detectMultiScale(
            gray, scaleFactor=1.15, minNeighbors=6, minSize=(70, 70)
        )
        faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        return faces, gray

    def largest_face(self, bgr_frame, downscale=1.0):
        """Detect the largest face in bgr_frame. Returns ((x,y,w,h), face_gray)
        in ORIGINAL frame coordinates, or (None, None) if no face found.
        downscale < 1.0 runs detection on a smaller frame for speed, then
        rescales the box back up (cheaper for live video)."""
        if downscale != 1.0:
            small = cv2.resize(bgr_frame, None, fx=downscale, fy=downscale)
        else:
            small = bgr_frame

        faces, _ = self.detect_faces(small)
        if len(faces) == 0:
            return None, None

        x, y, w, h = faces[0]
        if downscale != 1.0:
            inv = 1.0 / downscale
            x, y, w, h = int(x * inv), int(y * inv), int(w * inv), int(h * inv)

        gray_full = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
        gray_full = cv2.equalizeHist(gray_full)
        face_gray = gray_full[max(0, y):y + h, max(0, x):x + w]
        if face_gray.size == 0:
            return None, None
        face_gray = cv2.resize(face_gray, FACE_SIZE)
        return (x, y, w, h), face_gray

    # -------------------------------------------------------------------
    # Enrollment sample storage
    # -------------------------------------------------------------------
    @staticmethod
    def _validate_student_id(student_id):
        if not isinstance(student_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", student_id):
            raise ValueError(
                "Invalid student ID. Use 2-32 characters: letters, numbers, '-' or '_'."
            )

    def student_dir(self, student_id):
        self._validate_student_id(student_id)
        d = os.path.join(FACES_DIR, student_id)
        os.makedirs(d, exist_ok=True)
        return d

    def save_sample(self, student_id, face_gray, index):
        path = os.path.join(self.student_dir(student_id), f"{index}.png")
        cv2.imwrite(path, face_gray)
        return path

    def has_samples(self, student_id):
        self._validate_student_id(student_id)
        d = os.path.join(FACES_DIR, student_id)
        return os.path.isdir(d) and any(f.lower().endswith(".png") for f in os.listdir(d))

    def delete_student(self, student_id):
        """Delete all saved face samples for a student."""
        self._validate_student_id(student_id)
        student_path = os.path.join(FACES_DIR, student_id)
        if not os.path.isdir(student_path):
            return True
        try:
            shutil.rmtree(student_path)
            return True
        except OSError:
            return False

    # -------------------------------------------------------------------
    # Training / recognition
    # -------------------------------------------------------------------
    def train(self):
        """(Re)train the recognizer from every saved sample on disk.
        Returns (ok: bool, message: str)."""
        if not self.has_recognizer_backend:
            return False, "opencv-contrib-python is not installed, so recognition is disabled (detection still works)."

        if not os.path.isdir(FACES_DIR):
            self.recognizer = None
            return False, "No enrolled faces yet."

        images, labels = [], []
        self.label_to_id = {}
        self.id_to_label = {}
        next_label = 0

        for student_id in sorted(os.listdir(FACES_DIR)):
            student_path = os.path.join(FACES_DIR, student_id)
            if not os.path.isdir(student_path):
                continue
            files = [f for f in os.listdir(student_path) if f.lower().endswith(".png")]
            if not files:
                continue
            label = next_label
            next_label += 1
            self.label_to_id[label] = student_id
            self.id_to_label[student_id] = label
            for f in files:
                img = cv2.imread(os.path.join(student_path, f), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                img = cv2.resize(img, FACE_SIZE)
                images.append(img)
                labels.append(label)

        if not images:
            self.recognizer = None
            return False, "No enrolled faces yet."

        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        self.recognizer.train(images, np.array(labels))
        return True, f"Trained on {len(images)} samples across {len(self.label_to_id)} enrolled student(s)."

    def predict(self, face_gray):
        """Return (student_id, match_score 0-100) for the best match,
        or (None, 0.0) if untrained / no match structure is available.

        LBPH's native output is a DISTANCE (lower = more similar), not a
        probability. The returned score is therefore only a UI-friendly
        heuristic, not a statistically calibrated confidence percentage."""
        if self.recognizer is None:
            return None, 0.0
        face_gray = cv2.resize(face_gray, FACE_SIZE)
        label, distance = self.recognizer.predict(face_gray)
        match_score = max(0.0, 100.0 - float(distance))
        student_id = self.label_to_id.get(label)
        return student_id, match_score
