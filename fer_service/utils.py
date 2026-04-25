import requests
from datetime import datetime


def get_api_base(backend_url):
    return backend_url.split("/api/", 1)[0] + "/api"


def get_active_monitor_patient_id(backend_url, fallback_patient_id=""):
    api_base = get_api_base(backend_url)
    try:
        response = requests.get(f"{api_base}/monitor/active-patient", timeout=2)
        if response.status_code == 200:
            data = response.json() or {}
            return data.get("patient_id") or fallback_patient_id
        print("Warning: Failed to fetch active monitor patient", response.status_code)
    except Exception as e:
        print("Warning: Error fetching active monitor patient:", e)
    return fallback_patient_id

def send_emotion_data(patient_id, emotions, dominant_emotion, backend_url):
    emotions_serializable = {k: float(v) for k, v in emotions.items()}

    payload = {
        "patient_id": patient_id,
        "timestamp": datetime.utcnow().isoformat(),
        "emotions": emotions_serializable,
        "dominant_emotion": dominant_emotion
    }

    try:
        response = requests.post(backend_url, json=payload, timeout=2)
        if response.status_code != 200:
            print("Warning: Failed to send data", response.status_code)
    except Exception as e:
        print("Warning: Error sending data:", e)


def get_caretaker_phone(patient_id, backend_url, fallback_phone=""):
    api_base = get_api_base(backend_url)
    try:
        response = requests.get(f"{api_base}/patients/{patient_id}", timeout=2)
        if response.status_code == 200:
            return normalize_phone(response.json().get("caretaker_phone") or fallback_phone)
        print("Warning: Failed to fetch caretaker phone", response.status_code)
    except Exception as e:
        print("Warning: Error fetching caretaker phone:", e)
    return normalize_phone(fallback_phone)


def normalize_phone(phone):
    phone = (phone or "").strip()
    if not phone:
        return ""
    if phone.startswith("whatsapp:"):
        return phone
    if phone.startswith("+"):
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    return phone


def send_sms_alert(patient_id, emotions, window_samples,
                   account_sid, auth_token, whatsapp_from, caretaker_phone):
    """
    Send a distress alert via Twilio WhatsApp (Sandbox). Supports a fully custom
    message body. The caretaker must have joined the sandbox by messaging the
    Twilio sandbox number with the 'join <code>' pair from the Twilio console.
    """
    if not all([account_sid, auth_token, whatsapp_from, caretaker_phone]):
        print("Warning: WhatsApp not configured - skipping alert. "
              "Need Twilio settings and a caretaker phone number for this patient.")
        return

    from twilio.rest import Client

    top = sorted(emotions.items(), key=lambda kv: -kv[1])[:3]
    emotion_lines = "\n".join(f"  - {k}: {v:.0f}%" for k, v in top)

    body = (
        f"*CARE VISION ALERT*\n"
        f"*URGENT - IMMEDIATE ACTION REQUIRED*\n"
        f"\n"
        f"Patient distress or discomfort has been detected continuously for "
        f"{int(window_samples)} seconds.\n"
        f"\n"
        f"*Patient ID:* {patient_id}\n"
        f"*Alert Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"*Status:* Needs immediate attention\n"
        f"\n"
        f"*Detected emotion signals:*\n"
        f"{emotion_lines}\n"
        f"\n"
        f"Please check the patient immediately and provide assistance.\n"
        f"\n"
        f"- Care Vision Patient Monitoring"
    )

    wa_from = whatsapp_from if whatsapp_from.startswith("whatsapp:") else f"whatsapp:{whatsapp_from}"
    caretaker_phone = normalize_phone(caretaker_phone)
    wa_to = caretaker_phone if caretaker_phone.startswith("whatsapp:") else f"whatsapp:{caretaker_phone}"

    print(f"Sending WhatsApp alert from {wa_from} to {wa_to}")

    try:
        client = Client(account_sid, auth_token)
        msg = client.messages.create(from_=wa_from, to=wa_to, body=body)
        print(f"WhatsApp sent - sid={msg.sid}, status={msg.status}")
    except Exception as e:
        print(f"Warning: WhatsApp error: {e}")
