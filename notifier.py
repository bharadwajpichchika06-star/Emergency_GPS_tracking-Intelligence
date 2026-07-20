"""
notifier.py — Email + Twilio Voice Call + SMS notification system.
Email: SMTP (Gmail, free).
Calls/SMS: Twilio API (free trial at twilio.com, ~$15 credit included).
"""
import sys, os

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Twilio Voice Calls
# ---------------------------------------------------------------------------
def _get_twilio_client(cfg):
    """Return a Twilio REST client or None if not configured."""
    try:
        from twilio.rest import Client
        sid   = cfg.get("TWILIO_ACCOUNT_SID", "")
        token = cfg.get("TWILIO_AUTH_TOKEN",  "")
        if not sid or not token:
            return None
        return Client(sid, token)
    except ImportError:
        logger.error("twilio package not installed — run: pip install twilio")
        return None
    except Exception as e:
        logger.error(f"Twilio client init failed: {e}")
        return None


def _normalize_phone(phone: str) -> str:
    """
    Ensure phone numbers have a proper E.164 country code prefix.
    - Already starts with '+' → leave as-is
    - 10-digit number (Indian mobile) → prepend +91
    - 12-digit starting with 91 (missing +) → prepend +
    - Anything else → leave as-is
    """
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return phone
    if len(phone) == 10 and phone.isdigit():
        return "+91" + phone          # bare Indian mobile, e.g. 9346699302
    if len(phone) == 12 and phone.startswith("91") and phone.isdigit():
        return "+" + phone            # has country code but missing +
    return phone


def _build_twiml(user_name, reason, address, maps_url):
    """Build TwiML XML that Twilio reads aloud when the contact picks up."""
    safe_name    = user_name.replace("&", "and").replace("<", "").replace(">", "")
    safe_reason  = reason.replace("&", "and").replace("<", "").replace(">", "")
    safe_address = (address or "unknown location").replace("&", "and").replace("<", "").replace(">", "")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" language="en-IN">
    Emergency Alert! Emergency Alert!
    {safe_name} needs immediate help.
    Reason: {safe_reason}.
    Last known location: {safe_address}.
    Please call {safe_name} immediately or go to their location.
    This is an automated call from the G P S Emergency Tracker system.
  </Say>
  <Pause length="1"/>
  <Say voice="alice" language="en-IN">
    Repeating the alert.
    {safe_name} needs immediate help.
    Reason: {safe_reason}.
    Location: {safe_address}.
    Please respond immediately.
  </Say>
</Response>"""


def make_emergency_calls(cfg, contacts, user_name, alert):
    """
    Dial every emergency contact that has a phone number using Twilio.
    Returns (success: bool, message: str, call_sids: list)
    """
    client = _get_twilio_client(cfg)
    if not client:
        return False, "Twilio not configured", []

    from_number = cfg.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        return False, "TWILIO_FROM_NUMBER not set", []

    reason  = alert.get("reason", "Emergency detected")
    address = alert.get("address", "")
    lat     = alert.get("latitude",  0)
    lon     = alert.get("longitude", 0)
    maps_url = f"https://maps.google.com/?q={lat},{lon}"

    twiml = _build_twiml(user_name, reason, address, maps_url)

    call_sids = []
    errors    = []

    for contact in contacts:
        phone = _normalize_phone((contact.phone or "").strip())
        if not phone:
            logger.info(f"Skipping {contact.name} — no phone number")
            continue
        try:
            call = client.calls.create(
                twiml    = twiml,
                to       = phone,
                from_    = from_number,
            )
            call_sids.append(call.sid)
            logger.info(f"Voice call initiated to {contact.name} ({phone}) — SID: {call.sid}")
        except Exception as e:
            errors.append(f"{contact.name}: {e}")
            logger.error(f"Twilio call to {phone} failed: {e}")

    if call_sids:
        return True, f"Called {len(call_sids)} contact(s)", call_sids
    elif errors:
        return False, f"All calls failed: {errors}", []
    else:
        return False, "No contacts with phone numbers", []


def make_test_call(cfg, to_number, user_name):
    """Make a single test call to verify Twilio is working."""
    client = _get_twilio_client(cfg)
    if not client:
        return False, "Twilio not configured — check Account SID and Auth Token"

    from_number = cfg.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        return False, "TWILIO_FROM_NUMBER not set in settings"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" language="en-IN">
    Hello! This is a test call from your G P S Emergency Tracker system.
    Voice call alerts are working correctly for {user_name}.
    You will receive calls like this during a real emergency.
    Thank you.
  </Say>
</Response>"""

    to_number = _normalize_phone(to_number)
    try:
        call = client.calls.create(
            twiml    = twiml,
            to       = to_number,
            from_    = from_number,
        )
        return True, f"Test call placed — SID: {call.sid}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Twilio SMS
# ---------------------------------------------------------------------------
def send_emergency_sms(cfg, contacts, user_name, alert):
    """
    Send an SMS to every emergency contact that has a phone number.
    Returns (success: bool, message: str, sms_sids: list)
    """
    client = _get_twilio_client(cfg)
    if not client:
        return False, "Twilio not configured", []

    from_number = cfg.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        return False, "TWILIO_FROM_NUMBER not set", []

    reason   = alert.get("reason",    "Emergency detected")
    address  = alert.get("address",   "")
    lat      = alert.get("latitude",  0)
    lon      = alert.get("longitude", 0)
    maps_url = f"https://maps.google.com/?q={lat},{lon}"

    body = (
        f"🚨 EMERGENCY ALERT\n"
        f"{user_name} needs immediate help!\n"
        f"Reason: {reason}\n"
        f"Location: {address or 'Unknown'}\n"
        f"Map: {maps_url}\n"
        f"-- GPS Emergency Tracker"
    )

    sms_sids = []
    errors   = []

    for contact in contacts:
        phone = _normalize_phone((contact.phone or "").strip())
        if not phone:
            logger.info(f"Skipping SMS to {contact.name} — no phone number")
            continue
        try:
            msg = client.messages.create(
                body  = body,
                to    = phone,
                from_ = from_number,
            )
            sms_sids.append(msg.sid)
            logger.info(f"SMS sent to {contact.name} ({phone}) — SID: {msg.sid}")
        except Exception as e:
            errors.append(f"{contact.name}: {e}")
            logger.error(f"Twilio SMS to {phone} failed: {e}")

    if sms_sids:
        return True, f"SMS sent to {len(sms_sids)} contact(s)", sms_sids
    elif errors:
        return False, f"All SMS failed: {errors}", []
    else:
        return False, "No contacts with phone numbers", []


def send_test_sms(cfg, to_number, user_name):
    """Send a single test SMS to verify Twilio is working."""
    client = _get_twilio_client(cfg)
    if not client:
        return False, "Twilio not configured — check Account SID and Auth Token"

    from_number = cfg.get("TWILIO_FROM_NUMBER", "")
    if not from_number:
        return False, "TWILIO_FROM_NUMBER not set in settings"

    body = (
        f"✅ Test SMS from GPS Emergency Tracker.\n"
        f"SMS alerts are working correctly for {user_name}.\n"
        f"You will receive messages like this during a real emergency."
    )

    to_number = _normalize_phone(to_number)
    try:
        msg = client.messages.create(
            body  = body,
            to    = to_number,
            from_ = from_number,
        )
        return True, f"Test SMS sent — SID: {msg.sid}"
    except Exception as e:
        return False, str(e)


def _build_emergency_html(user_name, alert_type, reason, confidence,
                           latitude, longitude, address, timestamp):
    maps_url = f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=16/{latitude}/{longitude}"
    gmaps_url = f"https://maps.google.com/?q={latitude},{longitude}"
    severity_color = {
        "CRITICAL": "#ff2d55",
        "HIGH":     "#ff6b35",
        "MEDIUM":   "#ffd60a",
        "LOW":      "#30d158",
    }.get(alert_type, "#ff2d55")

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #0a0a0f; color: #e0e0e0; margin: 0; padding: 0; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #12121a; border-radius: 16px; overflow: hidden; }}
    .header {{ background: {severity_color}; padding: 32px; text-align: center; }}
    .header h1 {{ color: #fff; margin: 0; font-size: 28px; }}
    .header p {{ color: rgba(255,255,255,0.85); margin: 8px 0 0; }}
    .body {{ padding: 32px; }}
    .card {{ background: #1c1c2e; border-radius: 12px; padding: 20px; margin-bottom: 16px; border-left: 4px solid {severity_color}; }}
    .card h3 {{ margin: 0 0 8px; color: #a0a0c0; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
    .card p {{ margin: 0; font-size: 16px; color: #fff; font-weight: 600; }}
    .btn {{ display: inline-block; padding: 14px 28px; background: {severity_color}; color: #fff; text-decoration: none; border-radius: 10px; font-weight: 700; margin: 8px 8px 8px 0; }}
    .footer {{ text-align: center; padding: 20px; color: #555; font-size: 12px; }}
  </style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🚨 Emergency Alert</h1>
    <p>{alert_type} — Confidence: {confidence}%</p>
  </div>
  <div class="body">
    <div class="card">
      <h3>Person in distress</h3>
      <p>{user_name}</p>
    </div>
    <div class="card">
      <h3>Reason detected</h3>
      <p>{reason}</p>
    </div>
    <div class="card">
      <h3>Last known address</h3>
      <p>{address or "Resolving address…"}</p>
    </div>
    <div class="card">
      <h3>GPS Coordinates</h3>
      <p>Lat: {latitude:.6f}, Lon: {longitude:.6f}</p>
    </div>
    <div class="card">
      <h3>Alert time</h3>
      <p>{timestamp}</p>
    </div>
    <p style="margin-top:24px;">
      <a href="{gmaps_url}" class="btn">📍 Open in Google Maps</a>
      <a href="{maps_url}" class="btn" style="background:#1c1c2e;border:2px solid {severity_color};">🗺 OpenStreetMap</a>
    </p>
  </div>
  <div class="footer">GPS Emergency Tracker — Automated Alert System</div>
</div>
</body>
</html>
"""


def send_emergency_email(app_config, contacts, user_name, alert):
    """
    Send emergency email to all emergency contacts.
    Returns (success: bool, message: str)
    """
    username = app_config.get("MAIL_USERNAME", "")
    password = app_config.get("MAIL_PASSWORD", "")

    if not username or not password:
        logger.warning("SMTP credentials not configured — skipping email notification")
        return False, "SMTP not configured (demo mode)"

    subject = f"🚨 EMERGENCY ALERT — {user_name} needs help!"
    html_body = _build_emergency_html(
        user_name    = user_name,
        alert_type   = alert.get("severity", "CRITICAL"),
        reason       = alert.get("reason", "Emergency detected"),
        confidence   = alert.get("confidence", 100),
        latitude     = alert.get("latitude", 0),
        longitude    = alert.get("longitude", 0),
        address      = alert.get("address", ""),
        timestamp    = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    sent_count = 0
    errors = []

    try:
        server = smtplib.SMTP(app_config["MAIL_SERVER"], app_config["MAIL_PORT"])
        server.starttls()
        server.login(username, password)

        for contact in contacts:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = f"GPS Tracker <{username}>"
                msg["To"]      = contact.email

                msg.attach(MIMEText(
                    f"EMERGENCY: {user_name} needs help!\n"
                    f"Reason: {alert.get('reason')}\n"
                    f"Location: https://maps.google.com/?q={alert.get('latitude')},{alert.get('longitude')}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "plain"
                ))
                msg.attach(MIMEText(html_body, "html"))

                server.sendmail(username, contact.email, msg.as_string())
                sent_count += 1
                logger.info(f"Emergency email sent to {contact.email}")
            except Exception as e:
                errors.append(str(e))
                logger.error(f"Failed to send to {contact.email}: {e}")

        server.quit()
    except Exception as e:
        logger.error(f"SMTP connection failed: {e}")
        return False, str(e)

    if sent_count:
        return True, f"Notified {sent_count} contact(s)"
    return False, f"No emails sent. Errors: {errors}"


def send_test_email(app_config, to_email, user_name):
    """Send a test email to verify SMTP is working."""
    username = app_config.get("MAIL_USERNAME", "")
    password = app_config.get("MAIL_PASSWORD", "")

    if not username or not password:
        return False, "SMTP not configured"

    try:
        msg = MIMEMultipart()
        msg["Subject"] = "✅ GPS Tracker — Test Email"
        msg["From"]    = f"GPS Tracker <{username}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(
            f"Hello {user_name},\n\nYour GPS Emergency Tracker email notifications are working correctly!\n\n— GPS Tracker System",
            "plain"
        ))

        server = smtplib.SMTP(app_config["MAIL_SERVER"], app_config["MAIL_PORT"])
        server.starttls()
        server.login(username, password)
        server.sendmail(username, to_email, msg.as_string())
        server.quit()
        return True, "Test email sent"
    except Exception as e:
        return False, str(e)
