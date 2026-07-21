import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "gps-tracker-super-secret-key-2024")
    
    # Database
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    db_url = os.environ.get("DATABASE_URL")
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = db_url or f"sqlite:///{os.path.join(BASE_DIR, 'gps_tracker.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Email (SMTP) — fill in your Gmail credentials or leave blank for demo mode
    MAIL_SERVER   = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
    MAIL_PORT     = int(os.environ.get("MAIL_PORT",  587))
    MAIL_USE_TLS  = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME",  "")   # your Gmail address
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD",  "")   # Gmail app password

    # Twilio Voice Calls — free trial at https://www.twilio.com
    TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID",  "")  # ACxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN",   "")  # from console
    TWILIO_FROM_NUMBER  = os.environ.get("TWILIO_FROM_NUMBER",  "")  # +1XXXXXXXXXX

    # Emergency detection thresholds
    NO_MOVEMENT_THRESHOLD_SECONDS = 120   # 2 minutes
    LOW_SPEED_THRESHOLD_KMH       = 1.0

    # Safe-zone geofence defaults (metres)
    DEFAULT_SAFE_RADIUS_M = 500

    # Socket.IO
    SOCKETIO_ASYNC_MODE = "eventlet"

    # Admin credentials (used for first-time setup)
    ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL",    "admin@gpstracker.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
