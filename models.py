from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import bcrypt

db = SQLAlchemy()

# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    phone         = db.Column(db.String(20), default="")
    is_admin      = db.Column(db.Boolean, default=False)
    is_active_tracking = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    locations  = db.relationship("Location",          backref="user", lazy=True, cascade="all, delete-orphan")
    contacts   = db.relationship("EmergencyContact",  backref="user", lazy=True, cascade="all, delete-orphan")
    alerts     = db.relationship("Alert",             backref="user", lazy=True, cascade="all, delete-orphan")
    safe_zones = db.relationship("SafeZone",          backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    @property
    def latest_location(self):
        return (Location.query
                .filter_by(user_id=self.id)
                .order_by(Location.timestamp.desc())
                .first())

    @property
    def device_latest_locations(self):
        """Return the most-recent Location row per unique device_id."""
        from sqlalchemy import func
        # Sub-query: max id per device for this user
        sub = (db.session.query(
                   func.max(Location.id).label("max_id")
               )
               .filter(Location.user_id == self.id)
               .group_by(Location.device_id)
               .subquery())
        return (Location.query
                .join(sub, Location.id == sub.c.max_id)
                .order_by(Location.timestamp.desc())
                .all())

    def __repr__(self):
        return f"<User {self.email}>"


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
class Location(db.Model):
    __tablename__ = "locations"

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    latitude         = db.Column(db.Float, nullable=False)
    longitude        = db.Column(db.Float, nullable=False)
    accuracy         = db.Column(db.Float, default=0)
    speed_kmh        = db.Column(db.Float, default=0)
    address          = db.Column(db.String(300), default="")
    timestamp        = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    device_id        = db.Column(db.String(64),  default="", index=True)   # unique per browser/app session
    device_name      = db.Column(db.String(100), default="")               # e.g. "iPhone", "Chrome on Windows"

    def to_dict(self):
        return {
            "id":          self.id,
            "latitude":    self.latitude,
            "longitude":   self.longitude,
            "accuracy":    self.accuracy,
            "speed_kmh":   self.speed_kmh,
            "address":     self.address,
            "timestamp":   self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "device_id":   self.device_id,
            "device_name": self.device_name,
        }


# ---------------------------------------------------------------------------
# Emergency Contact
# ---------------------------------------------------------------------------
class EmergencyContact(db.Model):
    __tablename__ = "emergency_contacts"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(150), nullable=False)
    phone      = db.Column(db.String(20), default="")
    relation   = db.Column(db.String(50), default="Contact")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":       self.id,
            "name":     self.name,
            "email":    self.email,
            "phone":    self.phone,
            "relation": self.relation,
        }


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------
class Alert(db.Model):
    __tablename__ = "alerts"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    alert_type  = db.Column(db.String(50), default="EMERGENCY")   # EMERGENCY | SOS | GEOFENCE | TEST
    latitude    = db.Column(db.Float, nullable=True)
    longitude   = db.Column(db.Float, nullable=True)
    address     = db.Column(db.String(300), default="")
    message     = db.Column(db.String(500), default="")
    confidence  = db.Column(db.Integer, default=0)
    resolved    = db.Column(db.Boolean, default=False)
    notified    = db.Column(db.Boolean, default=False)
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id":          self.id,
            "user_id":     self.user_id,
            "alert_type":  self.alert_type,
            "latitude":    self.latitude,
            "longitude":   self.longitude,
            "address":     self.address,
            "message":     self.message,
            "confidence":  self.confidence,
            "resolved":    self.resolved,
            "notified":    self.notified,
            "timestamp":   self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        }


# ---------------------------------------------------------------------------
# Safe Zone
# ---------------------------------------------------------------------------
class SafeZone(db.Model):
    __tablename__ = "safe_zones"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name       = db.Column(db.String(100), default="Home")
    latitude   = db.Column(db.Float, nullable=False)
    longitude  = db.Column(db.Float, nullable=False)
    radius_m   = db.Column(db.Float, default=500)
    active     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":        self.id,
            "name":      self.name,
            "latitude":  self.latitude,
            "longitude": self.longitude,
            "radius_m":  self.radius_m,
            "active":    self.active,
        }
