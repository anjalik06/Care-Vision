import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

PATIENT_ID = os.getenv("PATIENT_ID", "patient_001")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000/api/emotions")
SEND_INTERVAL = int(os.getenv("SEND_INTERVAL", "5"))
LIVE_STREAM_PORT = int(os.getenv("LIVE_STREAM_PORT", "5001"))
PATIENT_PHOTO_DIR = os.getenv("PATIENT_PHOTO_DIR", os.path.join(BASE_DIR, "patient_photos"))

# Twilio WhatsApp Sandbox (custom-body alerts, no phone number purchase needed).
# The caretaker must first opt-in by sending the sandbox join code via WhatsApp.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
CARETAKER_PHONE = os.getenv("CARETAKER_PHONE", "")

# Demo distress detection: send an alert after 5 continuous seconds of
# uncomfortable emotion.
DISTRESS_THRESHOLD = float(os.getenv("DISTRESS_THRESHOLD", "45"))
DISTRESS_HOLD_SECONDS = float(os.getenv("DISTRESS_HOLD_SECONDS", "5"))
DISTRESS_COOLDOWN = int(os.getenv("DISTRESS_COOLDOWN", "60"))

# Only send alerts when the reference patient's face is detected.
# Keep False in production. Flip to True only for testing with a stand-in face.
BYPASS_IDENTITY_CHECK = False
