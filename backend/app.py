from flask import Flask, request, jsonify, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
import os
import requests as http_requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTO_DIR = os.path.join(BASE_DIR, 'patient_photos')
os.makedirs(PHOTO_DIR, exist_ok=True)
load_dotenv(os.path.join(BASE_DIR, '.env'))

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '').strip()
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
TWILIO_WHATSAPP_FROM = os.getenv('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886').strip()
DEFAULT_CARETAKER_PHONE = os.getenv('CARETAKER_PHONE', '').strip()

app = Flask(__name__, instance_path=os.path.join(BACKEND_DIR, 'instance'))
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///patients.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
ACTIVE_MONITOR_PATIENT_ID = None


class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    room = db.Column(db.String(50), default='')
    condition = db.Column(db.String(100), default='')
    caretaker_phone = db.Column(db.String(30), default='')
    feed_port = db.Column(db.Integer, default=5001)
    has_photo = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EmotionRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(50), db.ForeignKey('patient.patient_id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    dominant_emotion = db.Column(db.String(50))
    emotions = db.Column(db.JSON)


class MedicationReminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(50), db.ForeignKey('patient.patient_id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    reminder_time = db.Column(db.String(5), nullable=False)  # HH:MM
    enabled = db.Column(db.Boolean, default=True)
    last_notified_date = db.Column(db.String(10), default='')  # YYYY-MM-DD
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def normalize_time(value):
    value = (value or '').strip()
    try:
        parsed = datetime.strptime(value, "%H:%M")
        return parsed.strftime("%H:%M")
    except ValueError:
        return None


def normalize_phone(phone):
    phone = (phone or '').strip()
    if not phone:
        return ''
    if phone.startswith('whatsapp:'):
        return phone
    if phone.startswith('+'):
        return phone
    digits = ''.join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        return f'+91{digits}'
    return phone


def send_whatsapp_medication_alert(patient, reminder_message, reminder_time, trigger):
    """Send medication reminder via Twilio WhatsApp and return (ok, details)."""
    caretaker_phone = normalize_phone(patient.caretaker_phone or DEFAULT_CARETAKER_PHONE)

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, caretaker_phone]):
        return False, 'WhatsApp config or caretaker phone missing'

    wa_from = (TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_FROM.startswith('whatsapp:')
               else f'whatsapp:{TWILIO_WHATSAPP_FROM}')
    wa_to = caretaker_phone if caretaker_phone.startswith('whatsapp:') else f'whatsapp:{caretaker_phone}'

    body = (
        f"*CARE VISION - MEDICATION REMINDER*\n"
        f"Patient: {patient.name} ({patient.patient_id})\n"
        f"Time: {reminder_time}\n"
        f"Message: {reminder_message}\n"
        f"Trigger: {trigger}\n"
        f"Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    try:
        from twilio.rest import Client
    except Exception:
        return False, 'Twilio SDK not installed. Run: pip install twilio'

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(from_=wa_from, to=wa_to, body=body)
        return True, f'sid={msg.sid}'
    except Exception as e:
        return False, str(e)


def ensure_schema():
    db.create_all()
    columns = db.session.execute(text("PRAGMA table_info(patient)")).fetchall()
    column_names = {column[1] for column in columns}
    if 'caretaker_phone' not in column_names:
        db.session.execute(text("ALTER TABLE patient ADD COLUMN caretaker_phone VARCHAR(30) DEFAULT ''"))
        db.session.commit()


def get_active_monitor_patient_id():
    global ACTIVE_MONITOR_PATIENT_ID
    if ACTIVE_MONITOR_PATIENT_ID:
        return ACTIVE_MONITOR_PATIENT_ID
    first_patient = Patient.query.order_by(Patient.created_at.asc()).first()
    if first_patient:
        ACTIVE_MONITOR_PATIENT_ID = first_patient.patient_id
        return ACTIVE_MONITOR_PATIENT_ID
    return None


# ---------- Health ----------

@app.route('/')
def health_check():
    return jsonify({"service": "backend", "status": "ok"})


# ---------- Video Feed Proxy ----------

@app.route('/api/video_feed/<patient_id>')
def proxy_video_feed(patient_id):
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    feed_url = f'http://localhost:{patient.feed_port}/video_feed'

    def generate():
        try:
            with http_requests.get(feed_url, stream=True, timeout=10) as r:
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        except Exception:
            pass

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


# ---------- Monitor Selection APIs ----------

@app.route('/api/monitor/active-patient', methods=['GET'])
def get_active_patient():
    patient_id = get_active_monitor_patient_id()
    if not patient_id:
        return jsonify({"patient_id": None})
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        return jsonify({"patient_id": None})
    return jsonify({
        "patient_id": patient.patient_id,
        "name": patient.name,
        "feed_port": patient.feed_port,
        "has_photo": patient.has_photo,
    })


@app.route('/api/monitor/active-patient', methods=['PUT'])
def set_active_patient():
    global ACTIVE_MONITOR_PATIENT_ID
    data = request.get_json(silent=True) or {}
    patient_id = data.get('patient_id')
    if not patient_id:
        return jsonify({"error": "Missing patient_id"}), 400
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    ACTIVE_MONITOR_PATIENT_ID = patient.patient_id
    return jsonify({"message": "Active monitor patient updated", "patient_id": ACTIVE_MONITOR_PATIENT_ID}), 200


# ---------- Patient APIs ----------

@app.route('/api/patients', methods=['POST'])
def add_patient():
    json_data = request.get_json(silent=True) or {}
    patient_id = request.form.get('patient_id') or json_data.get('patient_id')
    name = request.form.get('name') or json_data.get('name')
    room = request.form.get('room', '') or json_data.get('room', '')
    condition = request.form.get('condition', '') or json_data.get('condition', '')
    caretaker_phone = request.form.get('caretaker_phone', '') or json_data.get('caretaker_phone', '')
    feed_port = request.form.get('feed_port', 5001) or json_data.get('feed_port', 5001)

    if not name or not patient_id or not caretaker_phone:
        return jsonify({"error": "Missing patient_id, name, or caretaker_phone"}), 400

    if Patient.query.filter_by(patient_id=patient_id).first():
        return jsonify({"message": "Patient already exists"}), 200

    has_photo = False
    if 'photo' in request.files:
        photo = request.files['photo']
        if photo.filename:
            ext = photo.filename.rsplit('.', 1)[-1].lower() if '.' in photo.filename else 'jpg'
            photo_path = os.path.join(PHOTO_DIR, f"{patient_id}.{ext}")
            photo.save(photo_path)
            has_photo = True

    new_patient = Patient(
        name=name, patient_id=patient_id,
        room=room, condition=condition,
        caretaker_phone=caretaker_phone,
        feed_port=int(feed_port), has_photo=has_photo
    )
    db.session.add(new_patient)
    db.session.commit()
    global ACTIVE_MONITOR_PATIENT_ID
    if not ACTIVE_MONITOR_PATIENT_ID:
        ACTIVE_MONITOR_PATIENT_ID = patient_id
    return jsonify({"message": f"Patient {name} added successfully!"}), 201


@app.route('/api/patients/<patient_id>/photo', methods=['POST'])
def upload_photo(patient_id):
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    if 'photo' not in request.files:
        return jsonify({"error": "No photo uploaded"}), 400

    photo = request.files['photo']
    ext = photo.filename.rsplit('.', 1)[-1].lower() if '.' in photo.filename else 'jpg'
    photo_path = os.path.join(PHOTO_DIR, f"{patient_id}.{ext}")
    photo.save(photo_path)

    patient.has_photo = True
    db.session.commit()
    return jsonify({"message": "Photo uploaded successfully"}), 200


@app.route('/api/patients/<patient_id>/photo', methods=['GET'])
def get_photo(patient_id):
    for ext in ['jpg', 'jpeg', 'png', 'webp', 'avif']:
        photo_path = os.path.join(PHOTO_DIR, f"{patient_id}.{ext}")
        if os.path.exists(photo_path):
            return send_from_directory(PHOTO_DIR, f"{patient_id}.{ext}")
    return jsonify({"error": "No photo found"}), 404


@app.route('/api/patients', methods=['GET'])
def list_patients():
    patients = Patient.query.all()
    result = []
    for p in patients:
        latest = EmotionRecord.query.filter_by(patient_id=p.patient_id)\
            .order_by(EmotionRecord.timestamp.desc()).first()
        result.append({
            "name": p.name,
            "patient_id": p.patient_id,
            "room": p.room,
            "condition": p.condition,
            "caretaker_phone": p.caretaker_phone,
            "feed_port": p.feed_port,
            "has_photo": p.has_photo,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "latest_emotion": latest.dominant_emotion if latest else None,
            "latest_timestamp": latest.timestamp.isoformat() if latest else None,
        })
    return jsonify(result)


@app.route('/api/patients/<patient_id>', methods=['GET'])
def get_patient(patient_id):
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    latest = EmotionRecord.query.filter_by(patient_id=patient.patient_id)\
        .order_by(EmotionRecord.timestamp.desc()).first()
    return jsonify({
        "name": patient.name,
        "patient_id": patient.patient_id,
        "room": patient.room,
        "condition": patient.condition,
        "caretaker_phone": patient.caretaker_phone,
        "feed_port": patient.feed_port,
        "has_photo": patient.has_photo,
        "created_at": patient.created_at.isoformat() if patient.created_at else None,
        "latest_emotion": latest.dominant_emotion if latest else None,
        "latest_timestamp": latest.timestamp.isoformat() if latest else None,
    })


@app.route('/api/patients/<patient_id>', methods=['DELETE'])
def delete_patient(patient_id):
    global ACTIVE_MONITOR_PATIENT_ID
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    EmotionRecord.query.filter_by(patient_id=patient_id).delete()
    MedicationReminder.query.filter_by(patient_id=patient_id).delete()
    # Remove photo
    for ext in ['jpg', 'jpeg', 'png', 'webp', 'avif']:
        photo_path = os.path.join(PHOTO_DIR, f"{patient_id}.{ext}")
        if os.path.exists(photo_path):
            os.remove(photo_path)
    db.session.delete(patient)
    db.session.commit()
    if ACTIVE_MONITOR_PATIENT_ID == patient_id:
        ACTIVE_MONITOR_PATIENT_ID = None
        get_active_monitor_patient_id()
    return jsonify({"message": f"Patient {patient_id} deleted"}), 200


# ---------- Medication Reminder APIs ----------

@app.route('/api/medications/<patient_id>', methods=['GET'])
def list_medication_reminders(patient_id):
    if not Patient.query.filter_by(patient_id=patient_id).first():
        return jsonify({"error": "Patient not found"}), 404
    reminders = MedicationReminder.query.filter_by(patient_id=patient_id)\
        .order_by(MedicationReminder.reminder_time.asc(), MedicationReminder.created_at.asc()).all()
    return jsonify([
        {
            "id": r.id,
            "patient_id": r.patient_id,
            "message": r.message,
            "reminder_time": r.reminder_time,
            "enabled": bool(r.enabled),
            "last_notified_date": r.last_notified_date,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in reminders
    ])


@app.route('/api/medications', methods=['POST'])
def create_medication_reminder():
    data = request.get_json(silent=True) or {}
    patient_id = (data.get('patient_id') or '').strip()
    message = (data.get('message') or '').strip()
    reminder_time = normalize_time(data.get('reminder_time'))
    enabled = bool(data.get('enabled', True))

    if not patient_id or not message or not reminder_time:
        return jsonify({"error": "Missing patient_id, message, or valid reminder_time (HH:MM)"}), 400
    if not Patient.query.filter_by(patient_id=patient_id).first():
        return jsonify({"error": "Patient not found"}), 404

    reminder = MedicationReminder(
        patient_id=patient_id,
        message=message,
        reminder_time=reminder_time,
        enabled=enabled,
    )
    db.session.add(reminder)
    db.session.commit()
    return jsonify({
        "id": reminder.id,
        "patient_id": reminder.patient_id,
        "message": reminder.message,
        "reminder_time": reminder.reminder_time,
        "enabled": bool(reminder.enabled),
        "last_notified_date": reminder.last_notified_date,
    }), 201


@app.route('/api/medications/<int:reminder_id>', methods=['PUT'])
def update_medication_reminder(reminder_id):
    data = request.get_json(silent=True) or {}
    reminder = MedicationReminder.query.get(reminder_id)
    if not reminder:
        return jsonify({"error": "Reminder not found"}), 404

    if 'message' in data:
        new_message = (data.get('message') or '').strip()
        if not new_message:
            return jsonify({"error": "Message cannot be empty"}), 400
        reminder.message = new_message

    if 'reminder_time' in data:
        new_time = normalize_time(data.get('reminder_time'))
        if not new_time:
            return jsonify({"error": "Invalid reminder_time, expected HH:MM"}), 400
        reminder.reminder_time = new_time

    if 'enabled' in data:
        reminder.enabled = bool(data.get('enabled'))

    db.session.commit()
    return jsonify({
        "id": reminder.id,
        "patient_id": reminder.patient_id,
        "message": reminder.message,
        "reminder_time": reminder.reminder_time,
        "enabled": bool(reminder.enabled),
        "last_notified_date": reminder.last_notified_date,
    })


@app.route('/api/medications/<int:reminder_id>', methods=['DELETE'])
def delete_medication_reminder(reminder_id):
    reminder = MedicationReminder.query.get(reminder_id)
    if not reminder:
        return jsonify({"error": "Reminder not found"}), 404
    db.session.delete(reminder)
    db.session.commit()
    return jsonify({"message": "Reminder deleted"}), 200


@app.route('/api/medications/<int:reminder_id>/send-now', methods=['POST'])
def send_medication_reminder_now(reminder_id):
    reminder = MedicationReminder.query.get(reminder_id)
    if not reminder:
        return jsonify({"error": "Reminder not found"}), 404
    patient = Patient.query.filter_by(patient_id=reminder.patient_id).first()
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    wa_ok, wa_details = send_whatsapp_medication_alert(
        patient,
        reminder.message,
        reminder.reminder_time,
        trigger='manual',
    )
    return jsonify({
        "id": reminder.id,
        "patient_id": reminder.patient_id,
        "patient_name": patient.name,
        "message": reminder.message,
        "reminder_time": reminder.reminder_time,
        "trigger": "manual",
        "whatsapp_sent": wa_ok,
        "whatsapp_details": wa_details,
        "triggered_at": datetime.now().isoformat(),
    }), 200


@app.route('/api/medications/due', methods=['GET'])
def get_due_medication_reminders():
    now_time = normalize_time(request.args.get('time')) or datetime.now().strftime('%H:%M')
    today = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')

    due_items = MedicationReminder.query.filter_by(enabled=True, reminder_time=now_time).all()
    payload = []
    for reminder in due_items:
        if reminder.last_notified_date == today:
            continue
        patient = Patient.query.filter_by(patient_id=reminder.patient_id).first()
        if not patient:
            continue
        wa_ok, wa_details = send_whatsapp_medication_alert(
            patient,
            reminder.message,
            reminder.reminder_time,
            trigger='scheduled',
        )
        reminder.last_notified_date = today
        payload.append({
            "id": reminder.id,
            "patient_id": reminder.patient_id,
            "patient_name": patient.name,
            "message": reminder.message,
            "reminder_time": reminder.reminder_time,
            "trigger": "scheduled",
            "whatsapp_sent": wa_ok,
            "whatsapp_details": wa_details,
            "triggered_at": datetime.now().isoformat(),
        })

    if payload:
        db.session.commit()
    return jsonify(payload)


# ---------- Emotion APIs ----------

@app.route('/api/emotions', methods=['POST'])
def receive_emotion_data():
    data = request.get_json()
    patient_id = data.get('patient_id')
    dominant_emotion = data.get('dominant_emotion')
    emotions = data.get('emotions')

    if not Patient.query.filter_by(patient_id=patient_id).first():
        return jsonify({"error": "Unknown patient_id"}), 404

    record = EmotionRecord(
        patient_id=patient_id,
        dominant_emotion=dominant_emotion,
        emotions=emotions
    )
    db.session.add(record)
    db.session.commit()

    return jsonify({"message": "Emotion data stored successfully"}), 200


@app.route('/api/emotions/<patient_id>', methods=['GET'])
def get_patient_emotions(patient_id):
    minutes = request.args.get('minutes', 1, type=int)
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    records = EmotionRecord.query.filter_by(patient_id=patient_id)\
        .filter(EmotionRecord.timestamp >= since)\
        .order_by(EmotionRecord.timestamp.asc()).all()
    return jsonify([
        {
            "timestamp": r.timestamp.isoformat(),
            "dominant_emotion": r.dominant_emotion,
            "emotions": r.emotions
        } for r in records
    ])


@app.route('/api/emotions/<patient_id>/latest', methods=['GET'])
def get_latest_emotion(patient_id):
    record = EmotionRecord.query.filter_by(patient_id=patient_id)\
        .order_by(EmotionRecord.timestamp.desc()).first()
    if not record:
        return jsonify({
            "timestamp": None,
            "dominant_emotion": None,
            "emotions": None
        })
    return jsonify({
        "timestamp": record.timestamp.isoformat(),
        "dominant_emotion": record.dominant_emotion,
        "emotions": record.emotions
    })


# ---------- Dashboard Stats ----------

@app.route('/api/dashboard/stats', methods=['GET'])
def dashboard_stats():
    total_patients = Patient.query.count()
    total_records = EmotionRecord.query.count()

    # Emotion distribution from last 1 minute
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    recent_records = EmotionRecord.query.filter(EmotionRecord.timestamp >= since).all()

    emotion_counts = {}
    for r in recent_records:
        emo = r.dominant_emotion
        emotion_counts[emo] = emotion_counts.get(emo, 0) + 1

    # Patients needing attention (high sadness, anger, or fear)
    alerts = []
    patients = Patient.query.all()
    for p in patients:
        latest = EmotionRecord.query.filter_by(patient_id=p.patient_id)\
            .order_by(EmotionRecord.timestamp.desc()).first()
        if latest and latest.dominant_emotion in ('sad', 'angry', 'fear', 'disgust'):
            alerts.append({
                "patient_id": p.patient_id,
                "name": p.name,
                "room": p.room,
                "emotion": latest.dominant_emotion,
                "timestamp": latest.timestamp.isoformat()
            })

    return jsonify({
        "total_patients": total_patients,
        "total_records": total_records,
        "emotion_distribution": emotion_counts,
        "alerts": alerts,
        "recent_count": len(recent_records)
    })


if __name__ == '__main__':
    with app.app_context():
        ensure_schema()
    print("Backend server running on http://localhost:5000")
    app.run(debug=False, use_reloader=False)
