"""
app.py — Main Flask application for GPS Emergency Tracker
"""
import logging
import os
import requests
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, flash, session)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from flask_socketio import SocketIO, emit, join_room, leave_room

from config import Config
from models import db, User, Location, EmergencyContact, Alert, SafeZone
from emergency import analyze, check_geofence
from notifier import (send_emergency_email, send_test_email,
                      make_emergency_calls, make_test_call,
                      send_emergency_sms, send_test_sms)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Login manager
# ---------------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# Admin decorator
# ---------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Reverse geocoding (Nominatim — free, no key)
# ---------------------------------------------------------------------------
def reverse_geocode(lat, lon) -> str:
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "GPSEmergencyTracker/1.0"},
            timeout=5,
        )
        if resp.ok:
            data = resp.json()
            return data.get("display_name", f"{lat:.4f}, {lon:.4f}")
    except Exception as e:
        logger.warning(f"Geocoding failed: {e}")
    return f"{lat:.4f}, {lon:.4f}"


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("tracker"))
    return render_template("index.html")



@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("tracker"))

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        phone    = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Please fill in all required fields.", "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "danger")
            return render_template("register.html")

        user = User(name=name, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash(f"Welcome, {name}! Your account has been created.", "success")
        return redirect(url_for("tracker"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("tracker"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            flash(f"Welcome back, {user.name}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("tracker"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    current_user.is_active_tracking = False
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Routes — Tracker
# ---------------------------------------------------------------------------
@app.route("/tracker")
@login_required
def tracker():
    contacts   = EmergencyContact.query.filter_by(user_id=current_user.id).all()
    safe_zones = SafeZone.query.filter_by(user_id=current_user.id, active=True).all()
    return render_template("tracker.html", contacts=contacts, safe_zones=safe_zones)


@app.route("/history")
@login_required
def history():
    page      = request.args.get("page", 1, type=int)
    locations = (Location.query
                 .filter_by(user_id=current_user.id)
                 .order_by(Location.timestamp.desc())
                 .paginate(page=page, per_page=50, error_out=False))
    alerts = (Alert.query
              .filter_by(user_id=current_user.id)
              .order_by(Alert.timestamp.desc())
              .limit(20).all())
    return render_template("history.html", locations=locations, alerts=alerts)


@app.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name     = request.form.get("name", "").strip()
            email    = request.form.get("email", "").strip()
            phone    = request.form.get("phone", "").strip()
            relation = request.form.get("relation", "Contact").strip()

            if name and email:
                c = EmergencyContact(
                    user_id=current_user.id,
                    name=name, email=email,
                    phone=phone, relation=relation
                )
                db.session.add(c)
                db.session.commit()
                flash(f"Contact '{name}' added.", "success")
            else:
                flash("Name and email are required.", "danger")

        elif action == "delete":
            cid = request.form.get("contact_id", type=int)
            c   = EmergencyContact.query.filter_by(id=cid, user_id=current_user.id).first()
            if c:
                db.session.delete(c)
                db.session.commit()
                flash("Contact removed.", "info")

        return redirect(url_for("contacts"))

    all_contacts = EmergencyContact.query.filter_by(user_id=current_user.id).all()
    return render_template("contacts.html", contacts=all_contacts)


@app.route("/my-devices")
@login_required
def my_devices():
    """Show all devices logged into this account on one map."""
    device_locs = current_user.device_latest_locations
    return render_template("my_devices.html", device_locs=device_locs)


@app.route("/api/my-devices")
@login_required
def api_my_devices():
    """Return latest location per device for current user."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=24)
    device_locs = current_user.device_latest_locations
    result = []
    for loc in device_locs:
        if not loc.device_id:
            continue
        result.append({
            "device_id":   loc.device_id,
            "device_name": loc.device_name or "Unknown Device",
            "latitude":    loc.latitude,
            "longitude":   loc.longitude,
            "accuracy":    loc.accuracy,
            "address":     loc.address,
            "speed_kmh":   loc.speed_kmh,
            "timestamp":   loc.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "is_recent":   loc.timestamp >= cutoff,
        })
    return jsonify(result)


@app.route("/dashboard")
@login_required
@admin_required
def dashboard():
    users  = User.query.order_by(User.created_at.desc()).all()
    alerts = Alert.query.order_by(Alert.timestamp.desc()).limit(50).all()
    total_alerts    = Alert.query.count()
    active_users    = User.query.filter_by(is_active_tracking=True).count()
    unresolved      = Alert.query.filter_by(resolved=False).count()
    return render_template(
        "dashboard.html",
        users=users, alerts=alerts,
        total_alerts=total_alerts,
        active_users=active_users,
        unresolved=unresolved,
    )


# ---------------------------------------------------------------------------
# API — Location
# ---------------------------------------------------------------------------
@app.route("/api/location", methods=["POST"])
@login_required
def api_location():
    data = request.get_json(force=True)
    lat      = data.get("latitude")
    lon      = data.get("longitude")
    accuracy = data.get("accuracy", 0)
    speed    = data.get("speed_kmh", 0)

    if lat is None or lon is None:
        return jsonify({"error": "Missing coordinates"}), 400

    address     = reverse_geocode(lat, lon)
    device_id   = data.get("device_id",   "").strip()
    device_name = data.get("device_name", "").strip()

    loc = Location(
        user_id     = current_user.id,
        latitude    = lat,
        longitude   = lon,
        accuracy    = accuracy,
        speed_kmh   = speed,
        address     = address,
        device_id   = device_id,
        device_name = device_name,
    )
    db.session.add(loc)
    current_user.is_active_tracking = True
    db.session.commit()

    # Broadcast to all admin rooms (include device info)
    socketio.emit("location_update", {
        "user_id":     current_user.id,
        "user_name":   current_user.name,
        "latitude":    lat,
        "longitude":   lon,
        "address":     address,
        "speed_kmh":   speed,
        "device_id":   device_id,
        "device_name": device_name,
        "timestamp":   datetime.utcnow().strftime("%H:%M:%S"),
    }, room="admins")

    # Geofence check
    safe_zones = SafeZone.query.filter_by(user_id=current_user.id, active=True).all()
    fence_result = check_geofence(lat, lon, safe_zones)
    if fence_result["breach"]:
        return jsonify({
            "status": "ok",
            "address": address,
            "geofence_breach": True,
            "zone": fence_result["zone"],
            "distance_m": fence_result["distance_m"],
        })

    return jsonify({"status": "ok", "address": address, "geofence_breach": False})


@app.route("/api/emergency", methods=["POST"])
@login_required
def api_emergency():
    data = request.get_json(force=True)

    lat                  = data.get("latitude", 0)
    lon                  = data.get("longitude", 0)
    speed_kmh            = data.get("speed_kmh", 0)
    no_movement_seconds  = data.get("no_movement_seconds", 0)
    sos_triggered        = data.get("sos_triggered", False)
    fall_detected        = data.get("fall_detected", False)

    result = analyze(
        speed_kmh           = speed_kmh,
        no_movement_seconds = no_movement_seconds,
        sos_triggered       = sos_triggered,
        fall_detected       = fall_detected,
    )

    if result["emergency"]:
        address = reverse_geocode(lat, lon) if lat and lon else ""

        alert = Alert(
            user_id    = current_user.id,
            alert_type = "SOS" if sos_triggered else "EMERGENCY",
            latitude   = lat,
            longitude  = lon,
            address    = address,
            message    = result["reason"],
            confidence = result["confidence"],
        )
        db.session.add(alert)
        db.session.commit()

        # Notify emergency contacts via email
        contacts_list = EmergencyContact.query.filter_by(user_id=current_user.id).all()
        if contacts_list:
            mail_cfg = {
                "MAIL_SERVER":   app.config["MAIL_SERVER"],
                "MAIL_PORT":     app.config["MAIL_PORT"],
                "MAIL_USERNAME": app.config["MAIL_USERNAME"],
                "MAIL_PASSWORD": app.config["MAIL_PASSWORD"],
            }
            alert_dict = {
                "severity":   result["severity"],
                "reason":     result["reason"],
                "confidence": result["confidence"],
                "latitude":   lat,
                "longitude":  lon,
                "address":    address,
            }
            notified, msg = send_emergency_email(mail_cfg, contacts_list, current_user.name, alert_dict)
            alert.notified = notified
            db.session.commit()

        # Trigger Twilio voice calls
        twilio_cfg = {
            "TWILIO_ACCOUNT_SID": app.config.get("TWILIO_ACCOUNT_SID", ""),
            "TWILIO_AUTH_TOKEN":  app.config.get("TWILIO_AUTH_TOKEN",  ""),
            "TWILIO_FROM_NUMBER": app.config.get("TWILIO_FROM_NUMBER", ""),
        }
        alert_dict_for_call = {
            "reason":    result["reason"],
            "address":   address,
            "latitude":  lat,
            "longitude": lon,
        }
        call_ok, call_msg, call_sids = make_emergency_calls(
            twilio_cfg, contacts_list, current_user.name, alert_dict_for_call
        )
        if call_ok:
            logger.info(f"Voice calls placed: {call_sids}")
            result["calls_placed"] = len(call_sids)
        else:
            logger.warning(f"Voice calls skipped: {call_msg}")
            result["calls_placed"] = 0

        # Send SMS to emergency contacts
        sms_ok, sms_msg, sms_sids = send_emergency_sms(
            twilio_cfg, contacts_list, current_user.name, alert_dict_for_call
        )
        if sms_ok:
            logger.info(f"SMS sent: {sms_sids}")
            result["sms_sent"] = len(sms_sids)
        else:
            logger.warning(f"SMS skipped: {sms_msg}")
            result["sms_sent"] = 0

        # Broadcast to admins
        socketio.emit("emergency_alert", {
            "user_id":    current_user.id,
            "user_name":  current_user.name,
            "severity":   result["severity"],
            "reason":     result["reason"],
            "confidence": result["confidence"],
            "latitude":   lat,
            "longitude":  lon,
            "address":    address,
            "timestamp":  datetime.utcnow().strftime("%H:%M:%S"),
        }, room="admins")

    return jsonify(result)


@app.route("/api/alert/<int:alert_id>/resolve", methods=["POST"])
@login_required
def resolve_alert(alert_id):
    alert = Alert.query.filter_by(id=alert_id, user_id=current_user.id).first_or_404()
    alert.resolved = True
    db.session.commit()
    return jsonify({"status": "resolved"})


@app.route("/api/history")
@login_required
def api_history():
    hours = request.args.get("hours", 24, type=int)
    since = datetime.utcnow() - timedelta(hours=hours)
    locs  = (Location.query
             .filter(Location.user_id == current_user.id,
                     Location.timestamp >= since)
             .order_by(Location.timestamp.asc())
             .all())
    return jsonify([l.to_dict() for l in locs])


@app.route("/api/alerts")
@login_required
def api_alerts():
    alerts = (Alert.query
              .filter_by(user_id=current_user.id, resolved=False)
              .order_by(Alert.timestamp.desc())
              .limit(10).all())
    return jsonify([a.to_dict() for a in alerts])


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """User settings page — configure email, Twilio etc."""
    email_configured   = bool(app.config.get("MAIL_USERNAME") and app.config.get("MAIL_PASSWORD"))
    twilio_configured  = bool(app.config.get("TWILIO_ACCOUNT_SID") and app.config.get("TWILIO_AUTH_TOKEN") and app.config.get("TWILIO_FROM_NUMBER"))
    return render_template(
        "settings.html",
        email_configured   = email_configured,
        twilio_configured  = twilio_configured,
        mail_username      = app.config.get("MAIL_USERNAME",     ""),
        mail_server        = app.config.get("MAIL_SERVER",       "smtp.gmail.com"),
        mail_port          = app.config.get("MAIL_PORT",         587),
        twilio_sid         = app.config.get("TWILIO_ACCOUNT_SID",""),
        twilio_from        = app.config.get("TWILIO_FROM_NUMBER",""),
    )


@app.route("/api/save-email-config", methods=["POST"])
@login_required
def api_save_email_config():
    """Save Gmail SMTP credentials to .env and hot-reload into running app."""
    data     = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    server   = data.get("server", "smtp.gmail.com").strip()
    port     = int(data.get("port", 587))

    if not username or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    # ── Write / update .env file ────────────────────────────────────────────
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    env_lines = []
    keys_written = set()
    new_values = {
        "MAIL_USERNAME": username,
        "MAIL_PASSWORD": password,
        "MAIL_SERVER":   server,
        "MAIL_PORT":     str(port),
    }

    # Preserve existing lines for other keys
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                key = line.split("=")[0].strip()
                if key in new_values:
                    env_lines.append(f"{key}={new_values[key]}\n")
                    keys_written.add(key)
                else:
                    env_lines.append(line)

    # Append any keys not already present
    for k, v in new_values.items():
        if k not in keys_written:
            env_lines.append(f"{k}={v}\n")

    with open(env_path, "w") as f:
        f.writelines(env_lines)

    # ── Hot-reload into Flask config (no restart needed) ───────────────────
    app.config["MAIL_USERNAME"] = username
    app.config["MAIL_PASSWORD"] = password
    app.config["MAIL_SERVER"]   = server
    app.config["MAIL_PORT"]     = port

    logger.info(f"Email config updated by {current_user.email} — sender: {username}")
    return jsonify({"success": True, "message": "Email configuration saved successfully!"})


@app.route("/api/test-email", methods=["POST"])
@login_required
def api_test_email():
    """Send a test email using the currently configured SMTP credentials."""
    data = request.get_json(force=True) or {}
    mail_cfg = {
        "MAIL_SERVER":   data.get("server")   or app.config.get("MAIL_SERVER",   "smtp.gmail.com"),
        "MAIL_PORT":     int(data.get("port") or app.config.get("MAIL_PORT",     587)),
        "MAIL_USERNAME": data.get("username") or app.config.get("MAIL_USERNAME", ""),
        "MAIL_PASSWORD": data.get("password") or app.config.get("MAIL_PASSWORD", ""),
    }
    to_email = data.get("to_email") or current_user.email
    ok, msg = send_test_email(mail_cfg, to_email, current_user.name)
    return jsonify({"success": ok, "message": msg})


@app.route("/api/save-twilio-config", methods=["POST"])
@login_required
def api_save_twilio_config():
    """Save Twilio credentials to .env and hot-reload."""
    data      = request.get_json(force=True)
    sid       = data.get("sid",        "").strip()
    token     = data.get("token",      "").strip()
    from_num  = data.get("from_number","").strip()

    if not sid or not token or not from_num:
        return jsonify({"success": False, "message": "All three Twilio fields are required."}), 400

    env_path  = os.path.join(os.path.dirname(__file__), ".env")
    env_lines = []
    keys_written = set()
    new_values = {
        "TWILIO_ACCOUNT_SID": sid,
        "TWILIO_AUTH_TOKEN":  token,
        "TWILIO_FROM_NUMBER": from_num,
    }

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                key = line.split("=")[0].strip()
                if key in new_values:
                    env_lines.append(f"{key}={new_values[key]}\n")
                    keys_written.add(key)
                else:
                    env_lines.append(line)

    for k, v in new_values.items():
        if k not in keys_written:
            env_lines.append(f"{k}={v}\n")

    with open(env_path, "w") as f:
        f.writelines(env_lines)

    app.config["TWILIO_ACCOUNT_SID"] = sid
    app.config["TWILIO_AUTH_TOKEN"]  = token
    app.config["TWILIO_FROM_NUMBER"] = from_num

    logger.info(f"Twilio config updated by {current_user.email}")
    return jsonify({"success": True, "message": "Twilio configuration saved!"})


@app.route("/api/test-call", methods=["POST"])
@login_required
def api_test_call():
    """Place a single test voice call to verify Twilio works."""
    data     = request.get_json(force=True) or {}
    to_num   = data.get("to_number", "").strip()
    if not to_num:
        return jsonify({"success": False, "message": "Please enter a phone number to call."}), 400

    twilio_cfg = {
        "TWILIO_ACCOUNT_SID": data.get("sid")   or app.config.get("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN":  data.get("token") or app.config.get("TWILIO_AUTH_TOKEN",  ""),
        "TWILIO_FROM_NUMBER": data.get("from_number") or app.config.get("TWILIO_FROM_NUMBER", ""),
    }
    ok, msg = make_test_call(twilio_cfg, to_num, current_user.name)
    return jsonify({"success": ok, "message": msg})

@app.route("/api/test-sms", methods=["POST"])
@login_required
def api_test_sms():
    """Send a single test SMS to verify Twilio messaging works."""
    data   = request.get_json(force=True) or {}
    to_num = data.get("to_number", "").strip()
    if not to_num:
        return jsonify({"success": False, "message": "Please enter a phone number to receive the test SMS."}), 400

    twilio_cfg = {
        "TWILIO_ACCOUNT_SID": data.get("sid")          or app.config.get("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN":  data.get("token")        or app.config.get("TWILIO_AUTH_TOKEN",  ""),
        "TWILIO_FROM_NUMBER": data.get("from_number")  or app.config.get("TWILIO_FROM_NUMBER", ""),
    }
    ok, msg = send_test_sms(twilio_cfg, to_num, current_user.name)
    return jsonify({"success": ok, "message": msg})


@app.route("/api/safe-zones", methods=["GET", "POST", "DELETE"])
@login_required
def api_safe_zones():
    if request.method == "GET":
        zones = SafeZone.query.filter_by(user_id=current_user.id).all()
        return jsonify([z.to_dict() for z in zones])

    if request.method == "POST":
        data = request.get_json(force=True)
        zone = SafeZone(
            user_id   = current_user.id,
            name      = data.get("name", "Home"),
            latitude  = data["latitude"],
            longitude = data["longitude"],
            radius_m  = data.get("radius_m", 500),
        )
        db.session.add(zone)
        db.session.commit()
        return jsonify(zone.to_dict()), 201

    if request.method == "DELETE":
        zid = request.args.get("id", type=int)
        z = SafeZone.query.filter_by(id=zid, user_id=current_user.id).first_or_404()
        db.session.delete(z)
        db.session.commit()
        return jsonify({"status": "deleted"})


@app.route("/api/admin/users")
@login_required
@admin_required
def api_admin_users():
    users = User.query.all()
    return jsonify([{
        "id":               u.id,
        "name":             u.name,
        "email":            u.email,
        "is_active_tracking": u.is_active_tracking,
        "latest_location":  u.latest_location.to_dict() if u.latest_location else None,
    } for u in users])


# ---------------------------------------------------------------------------
# Socket.IO — Real-time
# ---------------------------------------------------------------------------
@socketio.on("connect")
def on_connect():
    logger.info(f"Socket connected: {request.sid}")


@socketio.on("join_admin")
def on_join_admin(data):
    join_room("admins")
    emit("joined", {"room": "admins"})


@socketio.on("disconnect")
def on_disconnect():
    logger.info(f"Socket disconnected: {request.sid}")


# ---------------------------------------------------------------------------
# Database init + admin seed
# ---------------------------------------------------------------------------
def init_db():
    with app.app_context():
        db.create_all()
        # Create default admin if not exists
        admin = User.query.filter_by(email=app.config["ADMIN_EMAIL"]).first()
        if not admin:
            admin = User(
                name     = "Admin",
                email    = app.config["ADMIN_EMAIL"],
                is_admin = True,
            )
            admin.set_password(app.config["ADMIN_PASSWORD"])
            db.session.add(admin)
            db.session.commit()
            logger.info(f"Admin created: {app.config['ADMIN_EMAIL']}")

# Call database init immediately to ensure tables are created on Gunicorn startup
init_db()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n" + "="*55)
    print("  GPS Emergency Tracker is running!")
    print(f"  Admin login: {Config.ADMIN_EMAIL} / {Config.ADMIN_PASSWORD}")
    print("="*55 + "\n")
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)


