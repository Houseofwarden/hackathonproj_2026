# FaceTrack AI - Real-Time Attendance System via Face Recognition

A desktop application for automated student attendance tracking using **real**
face detection and recognition, built with Python, Tkinter and OpenCV.

---

## 🌟 Key Features

1. **Live Camera Feed & HUD Viewport**
   - Real-time video via OpenCV (DirectShow on Windows, with a fallback).
   - The green/blue bounding box you see is drawn at the **actual detected
     face location** (Haar cascade), not a fixed placeholder — it only
     appears when a face is genuinely found in the frame.
2. **Real Face Detection & Recognition**
   - Detection: OpenCV Haar cascade (`haarcascade_frontalface_default.xml`).
   - Recognition: OpenCV's LBPH (Local Binary Patterns Histograms) face
     recognizer, trained from face samples captured during enrollment.
   - "Recognize Face Now" runs actual inference against enrolled students —
     it does not pick a random name from the roster.
3. **Student Enrollment with Real Face Capture, Persisted Across Sessions**
   - Enrolling a student captures 8 real face samples from the live camera
     (or a loaded photo) over ~2.5 seconds and trains the recognizer on them.
   - The roster (`students_db.json`) and face samples (`enrolled_faces/`)
     are both saved to disk, so enrolled students and their trained faces
     persist across restarts — no demo/placeholder students are pre-loaded.
   - A student can only be matched by "Recognize Face Now" **after** they've
     been enrolled this way.
4. **Real-Time KPIs, Session Log, Duplicate-Scan Guard, CSV Export**
   - Unchanged from before — these were already real.

---

## ⚠️ Known limitations (be upfront about these in a demo)

- LBPH is a lightweight, classic recognizer — good enough for a hackathon
  demo in controlled lighting with a handful of people, but noticeably less
  accurate than a modern deep-learning face embedding model (e.g.
  `face_recognition`/dlib, or a FaceNet/ArcFace model) once you have many
  enrolled people or varied lighting/angles.
- The confidence percentage shown is a rough conversion from LBPH's distance
  metric (`100 - distance`), not a calibrated probability.
- Detection re-runs every other frame (not every frame) to keep the UI
  responsive; recognition only runs when you click "Recognize Face Now".

---

## 🚀 Running the Desktop Application

### Prerequisites
- Python 3.9+
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
  This installs `Pillow` and `opencv-contrib-python` (the `-contrib` build is
  required — it includes `cv2.face`, which plain `opencv-python` does not).
  If you previously had `opencv-python` installed, uninstall it first to
  avoid a DLL conflict:
  ```bash
  pip uninstall opencv-python
  pip install opencv-contrib-python
  ```

### Start the App
```bash
python main.py
```
or on Windows, just run `run.bat`, which installs dependencies and launches it.

### Using real recognition in a demo
1. Go to the **"➕ Enroll New"** tab.
2. Fill in a Student ID / Name / Dept / Batch.
3. Make sure your face is clearly visible in the live camera preview.
4. Click **"📸 Capture Face & Enroll Student"** — hold still (or move your
   head slightly between samples) while it captures 8 samples and trains.
5. Go back to the main video panel and click **"⚡ Recognize Face Now"** —
   it should recognize you and mark you present with a real confidence score.
6. Have someone else's face in frame (or none at all) to show it correctly
   *doesn't* mark attendance for an unrecognized/absent face.

---

## 📁 Project Structure

```
hackathonproj_2026-main/
├── main.py                              # GUI application
├── face_engine.py                       # Haar cascade detection + LBPH recognition
├── haarcascade_frontalface_default.xml  # Bundled OpenCV detector model
├── students_db.json                     # Created at runtime: persisted roster (id/name/dept/batch)
├── enrolled_faces/                      # Created at runtime: saved face samples per student
├── requirements.txt
├── run.bat
└── README.md
```
