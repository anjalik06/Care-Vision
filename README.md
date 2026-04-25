# Care Vision

Care Vision is a real-time patient emotion monitoring system with three coordinated services:

- `frontend/`: React + Vite dashboard for monitoring, patient management, history, and medication reminders.
- `backend/`: Flask API with SQLite persistence, patient/photo management, medication reminder workflows, and video-feed proxy.
- `fer_service/`: OpenCV + DeepFace service that reads a camera stream, identifies the selected patient, analyzes emotions, and sends alerts.

## Features

- Real-time emotion tracking with live video feed.
- Patient registration with photo-based identity matching.
- Emotion timeline and latest state per patient.
- Medication reminders with scheduled and manual WhatsApp notifications.
- Distress detection with configurable threshold, hold time, and cooldown.
- Dashboard alerting for patients needing attention.

## Architecture

1. `fer_service` captures webcam frames and detects emotions.
2. `fer_service` posts emotion records to `backend` (`/api/emotions`).
3. `backend` stores data in SQLite and exposes APIs consumed by `frontend`.
4. `frontend` polls APIs for live status, history, reminders, and monitor control.
5. `backend` proxies the FER video stream via `/api/video_feed/<patient_id>`.

## Project Structure

```text
fer_new/
	backend/
		app.py
		requirements.txt
		instance/                 # SQLite DB directory (patients.db)
	fer_service/
		main.py
		config.py
		utils.py
		requirements.txt
	frontend/
		src/
		package.json
	patient_photos/             # Shared reference photos by patient_id
	scripts/
		test_whatsapp_alert.py
	.env.example
	README.md
```

## Prerequisites

- Python 3.10+ (recommended)
- Node.js 18+ and npm
- Webcam connected to the machine running `fer_service`
- (Optional) Twilio account for WhatsApp alerts

## Environment Setup

Create `.env` from the template:

```powershell
copy .env.example .env
```

Important `.env` variables:

- `PATIENT_ID`: fallback patient id used by FER service.
- `BACKEND_URL`: emotion ingest endpoint, default `http://localhost:5000/api/emotions`.
- `SEND_INTERVAL`: seconds between emotion sends.
- `LIVE_STREAM_PORT`: FER video stream port (default `5001`).
- `PATIENT_PHOTO_DIR`: folder containing patient reference photos.
- `DISTRESS_THRESHOLD`, `DISTRESS_HOLD_SECONDS`, `DISTRESS_COOLDOWN`: distress alert tuning.
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `CARETAKER_PHONE`: WhatsApp alert configuration.

Frontend environment override (optional):

- `VITE_API_URL` (default: `http://localhost:5000/api`)

## Installation

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
pip install -r fer_service/requirements.txt

cd frontend
npm install
cd ..
```

## Running the System

Start each service in a separate terminal (from project root).

1. Backend API

```powershell
python backend/app.py
```

2. FER service

```powershell
python fer_service/main.py
```

3. Frontend

```powershell
cd frontend
npm run dev
```

Default local URLs:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:5000`
- FER direct stream: `http://localhost:5001/video_feed`

## Typical Usage Flow

1. Open the frontend and create a patient with:
	 - unique `patient_id`
	 - patient details
	 - caretaker phone number
	 - optional photo upload
2. Ensure a reference photo exists in `patient_photos/` as `<patient_id>.jpg|png|jpeg|webp|avif`.
3. Set the active monitor patient in the monitor view.
4. Keep FER service running to continuously stream and post emotions.

## API Overview

Core endpoints exposed by `backend/app.py`:

- Health
	- `GET /`
- Monitor
	- `GET /api/monitor/active-patient`
	- `PUT /api/monitor/active-patient`
- Patients
	- `POST /api/patients`
	- `GET /api/patients`
	- `GET /api/patients/<patient_id>`
	- `DELETE /api/patients/<patient_id>`
	- `POST /api/patients/<patient_id>/photo`
	- `GET /api/patients/<patient_id>/photo`
- Emotions
	- `POST /api/emotions`
	- `GET /api/emotions/<patient_id>?minutes=1`
	- `GET /api/emotions/<patient_id>/latest`
- Medication reminders
	- `GET /api/medications/<patient_id>`
	- `POST /api/medications`
	- `PUT /api/medications/<id>`
	- `DELETE /api/medications/<id>`
	- `POST /api/medications/<id>/send-now`
	- `GET /api/medications/due?time=HH:MM&date=YYYY-MM-DD`
- Dashboard
	- `GET /api/dashboard/stats`

## WhatsApp Alert Testing

Use the helper script to validate Twilio WhatsApp configuration:

```powershell
python scripts/test_whatsapp_alert.py
```

If using Twilio Sandbox, the caretaker number must first opt in by sending the sandbox join code shown in the Twilio console.

## Troubleshooting

- `ModuleNotFoundError`:
	- activate your virtual environment and reinstall requirements.
- No video feed in frontend:
	- verify `fer_service` is running and `LIVE_STREAM_PORT` is free.
	- confirm selected patient's `feed_port` matches FER stream port.
- Patient emotions not updating:
	- check backend is reachable at `BACKEND_URL`.
	- verify active monitor patient has a valid reference photo.
- WhatsApp messages not sent:
	- confirm Twilio credentials and sender number.
	- verify `CARETAKER_PHONE` format (`+<country><number>`).
	- ensure sandbox opt-in is completed.

## Data and Persistence

- SQLite DB: `backend/instance/patients.db`
- Patient photos: `patient_photos/`

These files are local runtime data and should be backed up if needed.
