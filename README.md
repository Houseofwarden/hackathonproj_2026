# FaceTrack AI - Real-Time Attendance System via Face Recognition

A modern, high-performance desktop application for automated student attendance tracking using face recognition.

---

## 🌟 Key Features

1. **Live Camera Feed & HUD Viewport**:
   - Real-time video frame rendering with dynamic bounding-box HUD overlay, corner bracket tracking, and facial landmark simulation.
   - Dual-mode support: Seamlessly works with hardware webcams via OpenCV or built-in AI simulation mode.
2. **Instant Attendance Recognition & Anti-Spoofing Duplicate Prevention**:
   - Automatically marks recognized students in the live session log with match confidence scores.
   - Alerts if a duplicate scan occurs within the same session.
3. **Real-Time Live KPI Metrics**:
   - Displays Total Enrolled, Present Count, Absent Count, and Attendance Rate (%) updated live.
4. **Live Session Log & Searchable Table**:
   - Filter records instantly by Student ID or Name.
   - Tagged records for Verified vs Manual overrides.
5. **Student Enrollment System**:
   - Register new students directly with ID, Name, Department, and Academic Batch.
6. **Data Exporting**:
   - One-click CSV export with complete session timestamp records.

---

## 🚀 Running the Desktop Application

### Prerequisites:
- Python 3.9+ installed (`py` or `python`)
- `Pillow` (installed by default)
- Optional (for live physical webcam):
  ```bash
  pip install opencv-python
  ```

### Start the App:
```bash
py main.py
```
*(or `python main.py`)*

---

## 📁 Project Structure

```
hello-world/
├── main.py       # Main GUI and face recognition application
└── README.md     # Documentation and usage guide
```
