import os
from datetime import datetime

from dotenv import load_dotenv
from twilio.rest import Client


def with_whatsapp_prefix(number):
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
whatsapp_from = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886").strip()
caretaker_phone = os.getenv("CARETAKER_PHONE", "").strip()

missing = [
    name
    for name, value in {
        "TWILIO_ACCOUNT_SID": account_sid,
        "TWILIO_AUTH_TOKEN": auth_token,
        "TWILIO_WHATSAPP_FROM": whatsapp_from,
        "CARETAKER_PHONE": caretaker_phone,
    }.items()
    if not value
]

if missing:
    raise SystemExit(f"Missing .env values: {', '.join(missing)}")

client = Client(account_sid, auth_token)
message = client.messages.create(
    from_=with_whatsapp_prefix(whatsapp_from),
    to=with_whatsapp_prefix(caretaker_phone),
    body=f"Care Vision test alert sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
)

print(f"Sent WhatsApp test message: sid={message.sid}, status={message.status}")
