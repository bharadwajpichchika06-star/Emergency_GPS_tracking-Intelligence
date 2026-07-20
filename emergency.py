"""
emergency.py — Rule-based emergency detection engine.
No external AI API required. Plug in Groq/OpenAI later by swapping analyze().
"""
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt


# ---------------------------------------------------------------------------
# Haversine distance (metres)
# ---------------------------------------------------------------------------
def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000  # Earth radius in metres
    φ1, φ2 = radians(lat1), radians(lat2)
    Δφ = radians(lat2 - lat1)
    Δλ = radians(lon2 - lon1)
    a = sin(Δφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(Δλ / 2) ** 2
    return 2 * R * asin(sqrt(a))


# ---------------------------------------------------------------------------
# Main emergency analysis function
# ---------------------------------------------------------------------------
def analyze(
    speed_kmh: float,
    no_movement_seconds: float,
    sos_triggered: bool = False,
    fall_detected: bool = False,
    battery_low: bool = False,
) -> dict:
    """
    Returns:
        {
            "emergency": bool,
            "confidence": int (0-100),
            "reason": str,
            "severity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
        }
    """
    # Manual SOS — always critical
    if sos_triggered:
        return {
            "emergency": True,
            "confidence": 100,
            "reason": "Manual SOS button pressed by user",
            "severity": "CRITICAL",
        }

    # Fall + no movement — very likely emergency
    if fall_detected and speed_kmh < 2:
        return {
            "emergency": True,
            "confidence": 95,
            "reason": "Fall detected with no subsequent movement",
            "severity": "HIGH",
        }

    # Prolonged no movement (> 5 min) — high concern
    if no_movement_seconds > 300 and speed_kmh < 1:
        return {
            "emergency": True,
            "confidence": 85,
            "reason": f"No movement detected for {int(no_movement_seconds // 60)} minutes",
            "severity": "HIGH",
        }

    # Moderate no movement (> 2 min)
    if no_movement_seconds > 120 and speed_kmh < 1:
        return {
            "emergency": True,
            "confidence": 70,
            "reason": f"No movement detected for {int(no_movement_seconds // 60)} minutes",
            "severity": "MEDIUM",
        }

    # Battery low + stationary — possible incapacitation
    if battery_low and speed_kmh < 1 and no_movement_seconds > 60:
        return {
            "emergency": True,
            "confidence": 60,
            "reason": "Device battery low and user appears stationary",
            "severity": "MEDIUM",
        }

    # Fall only — low concern (might have just sat down)
    if fall_detected:
        return {
            "emergency": False,
            "confidence": 40,
            "reason": "Possible fall detected — monitoring",
            "severity": "LOW",
        }

    return {
        "emergency": False,
        "confidence": 0,
        "reason": "Normal activity detected",
        "severity": "LOW",
    }


# ---------------------------------------------------------------------------
# Geofence check
# ---------------------------------------------------------------------------
def check_geofence(user_lat, user_lon, safe_zones) -> dict:
    """
    Returns geofence breach info if user is outside ALL active safe zones.
    """
    if not safe_zones:
        return {"breach": False, "zone": None}

    for zone in safe_zones:
        dist = haversine_m(user_lat, user_lon, zone.latitude, zone.longitude)
        if dist <= zone.radius_m:
            return {"breach": False, "zone": zone.name, "distance_m": dist}

    # Outside all zones
    nearest = min(
        safe_zones,
        key=lambda z: haversine_m(user_lat, user_lon, z.latitude, z.longitude)
    )
    dist = haversine_m(user_lat, user_lon, nearest.latitude, nearest.longitude)
    return {
        "breach": True,
        "zone": nearest.name,
        "distance_m": round(dist),
    }
