import cv2
import numpy as np
from deepface import DeepFace
import time
import warnings
import os
import glob
import tensorflow as tf
from flask import Flask, Response
from flask_cors import CORS
from threading import Thread

try:
    import winsound  # Windows-only; gives us an audible beep on alert
    HAVE_BEEP = True
except ImportError:
    HAVE_BEEP = False
from config import (PATIENT_ID, BACKEND_URL, SEND_INTERVAL, LIVE_STREAM_PORT,
                    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, CARETAKER_PHONE,
                    DISTRESS_THRESHOLD, DISTRESS_HOLD_SECONDS, DISTRESS_COOLDOWN,
                    BYPASS_IDENTITY_CHECK, PATIENT_PHOTO_DIR)
from utils import get_active_monitor_patient_id, get_caretaker_phone, send_emotion_data, send_sms_alert

warnings.filterwarnings("ignore")
tf.get_logger().setLevel('ERROR')

# ---------- Load patient reference photo & embedding ----------
PHOTO_DIR = PATIENT_PHOTO_DIR
reference_photo_path = None
reference_embedding = None
active_patient_id = PATIENT_ID
last_active_sync_time = 0.0
ACTIVE_SYNC_INTERVAL = 2.0

def load_reference(patient_id):
    """Load reference photo and pre-compute face embedding once at startup."""
    global reference_photo_path, reference_embedding
    reference_photo_path = None
    reference_embedding = None

    pattern = os.path.join(PHOTO_DIR, f"{patient_id}.*")
    matches = glob.glob(pattern)
    for m in matches:
        if m.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif')):
            reference_photo_path = m
            break

    if reference_photo_path is None:
        print(f"Warning: No reference photo for {patient_id}. Patient-only matching is disabled until a valid photo is added.")
        return

    try:
        embeddings = DeepFace.represent(
            img_path=reference_photo_path,
            model_name="VGG-Face",
            enforce_detection=False
        )
        if embeddings:
            reference_embedding = np.array(embeddings[0]["embedding"])
            print(f"Reference embedding loaded for {patient_id}")
        else:
            print("Warning: Could not extract embedding from reference photo.")
    except Exception as e:
            print(f"Warning: Error loading reference embedding: {e}")


def set_active_patient(patient_id):
    """Switch FER tracking target to another patient and reload identity embedding."""
    global active_patient_id, cached_patient_idx, last_verify_time
    if not patient_id or patient_id == active_patient_id:
        return
    active_patient_id = patient_id
    cached_patient_idx = -1
    last_verify_time = 0
    distress_detector.started_at = None
    distress_detector.cooldown_until = 0.0
    load_reference(active_patient_id)
    print(f"Switched active monitor patient to {active_patient_id}")


active_patient_id = get_active_monitor_patient_id(BACKEND_URL, PATIENT_ID)
load_reference(active_patient_id)

# ---------- Face matching with caching ----------
cached_patient_idx = 0
last_verify_time = 0
VERIFY_INTERVAL = 3  # Re-verify identity every 3 seconds (not every frame)

MATCH_THRESHOLD = 0.4  # cosine distance; lower = stricter match


def find_patient_face(frame, all_faces):
    """
    Match detected faces against pre-computed reference embedding.
    Returns the index of the matching face, or -1 if no face matches.
    Uses cached result between verification intervals for performance.
    """
    global cached_patient_idx, last_verify_time

    if not all_faces:
        return -1

    # Testing mode: skip identity check, treat first detected face as the patient
    if BYPASS_IDENTITY_CHECK:
        return 0

    # No reference embedding available -> do not classify any face as patient.
    # This prevents accidentally tracking emotions for bystanders.
    if reference_embedding is None:
        return -1

    now = time.time()
    # Use cached result if recently verified
    if now - last_verify_time < VERIFY_INTERVAL and 0 <= cached_patient_idx < len(all_faces):
        return cached_patient_idx

    best_idx = -1
    best_score = float('inf')

    for i, face in enumerate(all_faces):
        try:
            region = face.get('region', {})
            x, y, w, h = region.get('x', 0), region.get('y', 0), region.get('w', 0), region.get('h', 0)
            if w < 30 or h < 30:
                continue

            # Add padding around face crop for better recognition
            pad = int(max(w, h) * 0.25)
            fx1 = max(0, x - pad)
            fy1 = max(0, y - pad)
            fx2 = min(frame.shape[1], x + w + pad)
            fy2 = min(frame.shape[0], y + h + pad)
            face_crop = frame[fy1:fy2, fx1:fx2]

            if face_crop.size == 0:
                continue

            # Get embedding for this face
            emb_result = DeepFace.represent(
                img_path=face_crop,
                model_name="VGG-Face",
                enforce_detection=False
            )
            if not emb_result:
                continue

            face_embedding = np.array(emb_result[0]["embedding"])

            # Cosine distance (lower = more similar)
            cos_sim = np.dot(reference_embedding, face_embedding) / (
                np.linalg.norm(reference_embedding) * np.linalg.norm(face_embedding) + 1e-8
            )
            distance = 1 - cos_sim

            if distance < best_score:
                best_score = distance
                best_idx = i

        except Exception:
            continue

    # Only accept a match if distance is below the threshold
    if best_score < MATCH_THRESHOLD:
        cached_patient_idx = best_idx
    else:
        cached_patient_idx = -1  # No face matches the reference patient

    last_verify_time = now
    return cached_patient_idx


# ---------- Distress detection ----------
class DistressHoldDetector:
    """
    Demo-friendly detector: starts a timer when the patient looks distressed and
    sends one alert after the score stays above threshold for hold_seconds.
    """
    def __init__(self, threshold, hold_seconds, cooldown):
        self.threshold = threshold
        self.hold_seconds = hold_seconds
        self.cooldown = cooldown
        self.started_at = None
        self.cooldown_until = 0.0

    @staticmethod
    def score(emotions):
        return (emotions.get('fear', 0)
                + emotions.get('sad', 0)
                + 0.5 * emotions.get('angry', 0)
                + 0.3 * emotions.get('disgust', 0))

    def update(self, emotions, dominant_emotion):
        """
        Returns (should_alert, current_score, held_seconds, is_distressed, in_cooldown).
        """
        now = time.time()
        score = self.score(emotions)
        is_distressed = (
            score >= self.threshold
            or dominant_emotion in ('sad', 'angry', 'fear', 'disgust')
        )

        if is_distressed:
            if self.started_at is None:
                self.started_at = now
            held_seconds = now - self.started_at
        else:
            self.started_at = None
            held_seconds = 0.0

        in_cooldown = now < self.cooldown_until
        should_alert = is_distressed and held_seconds >= self.hold_seconds and not in_cooldown

        if should_alert:
            self.cooldown_until = now + self.cooldown
            self.started_at = None

        return should_alert, score, held_seconds, is_distressed, in_cooldown


distress_detector = DistressHoldDetector(
    threshold=DISTRESS_THRESHOLD,
    hold_seconds=DISTRESS_HOLD_SECONDS,
    cooldown=DISTRESS_COOLDOWN,
)


# ---------- Initialize Flask app for live streaming ----------
app = Flask(__name__)
CORS(app)
cap = cv2.VideoCapture(0)
last_send_time = 0
last_sent_emotion = None
frame_to_stream = None
last_debug_log = 0.0

def generate_frames():
    global frame_to_stream
    while True:
        if frame_to_stream is None:
            continue
        _, buffer = cv2.imencode('.jpg', frame_to_stream)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

def run_flask():
    app.run(host='0.0.0.0', port=LIVE_STREAM_PORT, debug=False, threaded=True, use_reloader=False)

# Start Flask in a separate thread
flask_thread = Thread(target=run_flask)
flask_thread.start()

print(f"FER service started for {active_patient_id}. Live feed available on port {LIVE_STREAM_PORT}.")

window_name = "FER Service"
chart_height = 150
bar_color = (255, 140, 0)
bg_color = (30, 30, 30)
patient_color = (0, 255, 0)   # Green box for matched patient
other_color = (128, 128, 128) # Gray box for others

# Banner state: overlays "ALERT SENT" on the video for a few seconds after firing
alert_banner_until = 0.0
ALERT_BANNER_DURATION = 6  # seconds

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    if time.time() - last_active_sync_time >= ACTIVE_SYNC_INTERVAL:
        backend_selected_patient = get_active_monitor_patient_id(BACKEND_URL, active_patient_id)
        if backend_selected_patient and backend_selected_patient != active_patient_id:
            set_active_patient(backend_selected_patient)
        last_active_sync_time = time.time()

    frame = cv2.flip(frame, 1)
    display_frame = frame.copy()

    try:
        results = DeepFace.analyze(frame, actions=['emotion'], enforce_detection=False, silent=True)

        # Find the patient's face among all detected faces
        patient_idx = find_patient_face(frame, results)

        # Draw boxes on all faces, highlight the patient
        unknown_color = (0, 0, 255)  # Red box for faces that don't match the reference
        for i, face in enumerate(results):
            region = face.get('region', {})
            x, y, w, h = region.get('x', 0), region.get('y', 0), region.get('w', 0), region.get('h', 0)
            if w > 0 and h > 0:
                is_patient = (i == patient_idx)
                if is_patient:
                    color, thickness, label = patient_color, 2, active_patient_id
                elif patient_idx == -1:
                    color, thickness, label = unknown_color, 2, "UNKNOWN"
                else:
                    color, thickness, label = other_color, 1, "other"
                cv2.rectangle(display_frame, (x, y), (x + w, y + h), color, thickness)
                cv2.putText(display_frame, label, (x, y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        if patient_idx == -1:
            # Face in frame is not the registered patient -> no emotion tracking / alerts
            cv2.putText(display_frame, "NOT THE PATIENT - alerts disabled", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, unknown_color, 2)
            cv2.putText(display_frame, f"Target: {active_patient_id}", (30, 85),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            frame_to_stream = display_frame
            cv2.imshow(window_name, display_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
            continue

        # Use only the patient's emotions
        patient_result = results[patient_idx]
        emotions = patient_result['emotion']
        dominant_emotion = patient_result['dominant_emotion']

        # Overlay dominant emotion
        cv2.putText(display_frame, f"Emotion: {dominant_emotion.upper()}", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
        cv2.putText(display_frame, f"Target: {active_patient_id}", (30, 85),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Emotion bar chart
        chart = np.zeros((chart_height, display_frame.shape[1], 3), dtype=np.uint8)
        chart[:] = bg_color
        n = len(emotions)
        bar_width = display_frame.shape[1] // n
        for i, (emo, val) in enumerate(emotions.items()):
            h = int((val / 100) * chart_height)
            x1 = i * bar_width + 10
            y1 = chart_height - h
            x2 = (i + 1) * bar_width - 10
            y2 = chart_height
            cv2.rectangle(chart, (x1, y1), (x2, y2), bar_color, -1)
            cv2.putText(chart, emo[:3], (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        combined = np.vstack((display_frame, chart))
        frame_to_stream = combined

        # Send emotion data to backend every SEND_INTERVAL seconds (builds history,
        # not only on dominant-emotion change, so the DB has a full timeline).
        now = time.time()
        if now - last_send_time > SEND_INTERVAL:
            send_emotion_data(active_patient_id, emotions, dominant_emotion, BACKEND_URL)
            last_send_time = now
            last_sent_emotion = dominant_emotion

        # Demo distress detection -> alert after 5 continuous seconds.
        should_alert, d_score, held_seconds, is_distressed, in_cooldown = distress_detector.update(
            emotions, dominant_emotion
        )

        if in_cooldown:
            hud_color = (0, 200, 255)
            hud_status = "cooldown"
        elif is_distressed:
            hud_color = (0, 0, 255)
            hud_status = "distress"
        else:
            hud_color = (0, 255, 0)
            hud_status = "calm"
        hud_text = (f"{hud_status}   score {d_score:.0f}/{DISTRESS_THRESHOLD:.0f}"
                    f"   held {held_seconds:.1f}/{DISTRESS_HOLD_SECONDS:.0f}s")
        cv2.putText(combined, hud_text, (20, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, hud_color, 2)

        # Identity indicator (top right)
        if BYPASS_IDENTITY_CHECK:
            cv2.putText(combined, "ID CHECK: BYPASSED",
                        (combined.shape[1] - 340, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

        # Per-second debug log so we can watch the rolling stats
        if time.time() - last_debug_log > 1.0:
            top = sorted(emotions.items(), key=lambda kv: -kv[1])[:3]
            top_str = " ".join(f"{k}={v:.0f}" for k, v in top)
            print(f"[detect] {dominant_emotion:>9}  score={d_score:5.1f}/{DISTRESS_THRESHOLD:.0f}  "
                  f"held={held_seconds:3.1f}/{DISTRESS_HOLD_SECONDS:.0f}s  status={hud_status:>8}  "
                  f"top3=[{top_str}]")
            last_debug_log = time.time()

        if should_alert:
            print("=" * 60)
            print("DISTRESS DETECTED - triggering alert")
            print(f"   patient:   {active_patient_id}")
            print(f"   score:     {d_score:.1f}  (threshold {DISTRESS_THRESHOLD:.0f})")
            print(f"   held:      {DISTRESS_HOLD_SECONDS:.0f} continuous seconds")
            print(f"   top 3:     " + ", ".join(f"{k} {v:.0f}%"
                                                for k, v in sorted(emotions.items(),
                                                                   key=lambda kv: -kv[1])[:3]))
            caretaker_phone = get_caretaker_phone(active_patient_id, BACKEND_URL, CARETAKER_PHONE)
            print(f"   sending via Twilio Verify -> {caretaker_phone or 'no caretaker phone configured'} ...")
            print("=" * 60)
            alert_banner_until = time.time() + ALERT_BANNER_DURATION
            if HAVE_BEEP:
                # Short non-blocking beep: 1000 Hz for 400 ms
                Thread(target=lambda: winsound.Beep(1000, 400), daemon=True).start()
            Thread(
                target=send_sms_alert,
                    args=(active_patient_id, emotions, DISTRESS_HOLD_SECONDS,
                      TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
                      TWILIO_WHATSAPP_FROM, caretaker_phone),
                daemon=True,
            ).start()

        # Persistent "ALERT SENT" banner for a few seconds after firing
        if time.time() < alert_banner_until:
            h, w = combined.shape[:2]
            overlay = combined.copy()
            cv2.rectangle(overlay, (0, 0), (w, 70), (0, 0, 255), -1)
            cv2.addWeighted(overlay, 0.55, combined, 0.45, 0, combined)
            cv2.putText(combined, "ALERT SENT - CARETAKER NOTIFIED", (20, 47),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
            frame_to_stream = combined

    except Exception:
        cv2.putText(display_frame, "No face detected", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        combined = display_frame
        frame_to_stream = combined

    cv2.imshow(window_name, combined)

    # Proper exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break
    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
        break

cap.release()
cv2.destroyAllWindows()
print("FER service stopped.")
