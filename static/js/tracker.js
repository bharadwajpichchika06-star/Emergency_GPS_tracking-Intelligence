/**
 * tracker.js — GPS tracking, Leaflet map, Socket.IO, emergency detection
 */

// ── Toast notifications ─────────────────────────────────────────────────────
function showToast(title, text, type = "info", duration = 5000) {
  const icons = { success: "✅", danger: "🚨", warning: "⚠️", info: "ℹ️" };
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || "📌"}</span>
    <div class="toast-body">
      <div class="toast-title">${title}</div>
      ${text ? `<div class="toast-text">${text}</div>` : ""}
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(toast);
  if (duration > 0) setTimeout(() => toast.remove(), duration);
  return toast;
}

// ── State ───────────────────────────────────────────────────────────────────
const state = {
  map: null,
  marker: null,
  accuracyCircle: null,
  pathLine: null,
  pathCoords: [],
  safeZoneCircles: [],
  lastPosition: null,
  lastMoveTime: Date.now(),
  trackingInterval: null,
  socket: null,
  isTracking: false,
  emergencyActive: false,
  watchId: null,
  voiceEnabled: true,
  notifEnabled: true,
};

// ── Voice Alert (Web Speech API — free, no API key) ──────────────────────────
function voiceAlert(message, repeat = 3) {
  if (!state.voiceEnabled) return;
  if (!window.speechSynthesis) return;

  window.speechSynthesis.cancel(); // stop any previous speech

  let count = 0;
  function speak() {
    if (count >= repeat) return;
    count++;
    const utt = new SpeechSynthesisUtterance(message);
    utt.lang  = "en-US";
    utt.rate  = 0.92;
    utt.pitch = 1.1;
    utt.volume = 1.0;
    // Pick a clear English voice if available
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(v =>
      v.lang.startsWith("en") && (v.name.includes("Female") || v.name.includes("Google") || v.name.includes("Samantha"))
    ) || voices.find(v => v.lang.startsWith("en")) || null;
    if (preferred) utt.voice = preferred;
    utt.onend = () => setTimeout(speak, 1200);
    window.speechSynthesis.speak(utt);
  }
  // Voices may not be loaded yet on first call
  if (window.speechSynthesis.getVoices().length === 0) {
    window.speechSynthesis.addEventListener("voiceschanged", speak, { once: true });
  } else {
    speak();
  }
}

// ── Browser Push Notifications ───────────────────────────────────────────────
async function requestNotificationPermission() {
  if (!('Notification' in window)) return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  const perm = await Notification.requestPermission();
  return perm === 'granted';
}

function showBrowserNotification(title, body, urgent = false) {
  if (!state.notifEnabled) return;
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  const icon = urgent ? '/static/favicon.ico' : '/static/favicon.ico';
  const n = new Notification(title, {
    body,
    icon,
    badge: icon,
    requireInteraction: urgent,  // stays on screen until dismissed
    silent: false,
    tag: urgent ? 'emergency' : 'tracker',
  });
  n.onclick = () => { window.focus(); n.close(); };
  if (!urgent) setTimeout(() => n.close(), 8000);
}

// ── Call Contacts Panel ──────────────────────────────────────────────────────
// contacts are injected from the template into window.EMERGENCY_CONTACTS
function renderCallPanel(reason) {
  const panel = document.getElementById("call-panel");
  if (!panel) return;

  const contacts = window.EMERGENCY_CONTACTS || [];
  if (!contacts.length) {
    panel.innerHTML = `
      <div class="card-title">📞 Call Contacts</div>
      <p style="font-size:.8rem;color:var(--text-muted)">No contacts added. <a href="/contacts" style="color:var(--accent)">Add contacts →</a></p>
    `;
    return;
  }

  let html = `<div class="card-title" style="color:var(--danger)">📞 Call Contacts Now</div>`;
  html += `<p style="font-size:.75rem;color:var(--text-muted);margin-bottom:12px">Emergency detected — tap to call immediately</p>`;

  contacts.forEach(c => {
    const initial = c.name.charAt(0).toUpperCase();
    const phone   = c.phone || '';
    const hasPhone = phone.trim() !== '';
    html += `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;
                  padding:10px 12px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);
                  border-radius:12px">
        <div style="width:36px;height:36px;border-radius:50%;flex-shrink:0;
                    background:linear-gradient(135deg,var(--danger),#dc2626);
                    display:flex;align-items:center;justify-content:center;
                    font-weight:700;font-size:.9rem;color:#fff">${initial}</div>
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;font-size:.875rem">${c.name}</div>
          <div style="font-size:.75rem;color:var(--text-muted)">${c.relation} ${hasPhone ? '· ' + phone : ''}</div>
        </div>
        ${hasPhone
          ? `<a href="tel:${phone.replace(/\s/g,'')}"
               style="display:flex;align-items:center;justify-content:center;
                      width:38px;height:38px;border-radius:50%;
                      background:linear-gradient(135deg,var(--success),#059669);
                      color:#fff;font-size:1.1rem;flex-shrink:0;text-decoration:none;
                      box-shadow:0 0 16px rgba(16,185,129,0.4);transition:.2s"
               title="Call ${c.name}" onclick="logCall('${c.name}')">
               📞
             </a>`
          : `<span style="font-size:.7rem;color:var(--text-muted);font-style:italic">No phone</span>`
        }
      </div>`;
  });

  // Also show last known location link
  const pos = state.lastPosition;
  if (pos) {
    const { latitude: lat, longitude: lon } = pos.coords;
    html += `
      <a href="https://maps.google.com/?q=${lat},${lon}" target="_blank"
         class="btn btn-outline btn-sm" style="width:100%;margin-top:4px;justify-content:center">
        🗺 Share My Location
      </a>`;
  }

  panel.innerHTML = html;
  panel.style.display = 'block';
}

window.logCall = function(name) {
  showToast('📞 Calling', `Dialing ${name}…`, 'success', 4000);
};

// ── Stop Voice ───────────────────────────────────────────────────────────────
window.stopVoice = function() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
};


// ── Map Initialization ───────────────────────────────────────────────────────
function initMap(lat = 20.5937, lon = 78.9629) {
  state.map = L.map("map", { zoomControl: false }).setView([lat, lon], 15);
  L.control.zoom({ position: "bottomright" }).addTo(state.map);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(state.map);

  // Custom marker icon
  const icon = L.divIcon({
    className: "",
    html: `<div style="
      width:22px;height:22px;border-radius:50%;
      background:linear-gradient(135deg,#6366f1,#8b5cf6);
      border:3px solid #fff;
      box-shadow:0 0 0 4px rgba(99,102,241,0.4),0 4px 12px rgba(0,0,0,0.5);
    "></div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });

  state.marker = L.marker([lat, lon], { icon }).addTo(state.map);
  state.pathLine = L.polyline([], {
    color: "#6366f1", weight: 3, opacity: 0.7, dashArray: "6, 4",
  }).addTo(state.map);
}

// ── Load Safe Zones on Map ───────────────────────────────────────────────────
async function loadSafeZones() {
  try {
    const resp = await fetch("/api/safe-zones");
    const zones = await resp.json();
    state.safeZoneCircles.forEach(c => state.map.removeLayer(c));
    state.safeZoneCircles = [];

    zones.forEach(z => {
      const circle = L.circle([z.latitude, z.longitude], {
        radius: z.radius_m,
        color: "#10b981", weight: 2,
        fillColor: "#10b981", fillOpacity: 0.07,
      }).addTo(state.map).bindPopup(`🏠 Safe Zone: ${z.name} (${z.radius_m}m radius)`);
      state.safeZoneCircles.push(circle);
    });
  } catch (e) {
    console.warn("Could not load safe zones:", e);
  }
}

// ── Update Map Position ──────────────────────────────────────────────────────
function updateMapPosition(lat, lon, accuracy = 0) {
  const latlng = [lat, lon];

  // Move marker
  state.marker.setLatLng(latlng);

  // Accuracy circle
  if (state.accuracyCircle) state.map.removeLayer(state.accuracyCircle);
  if (accuracy > 0 && accuracy < 2000) {
    state.accuracyCircle = L.circle(latlng, {
      radius: accuracy, color: "#6366f1",
      fillColor: "#6366f1", fillOpacity: 0.08, weight: 1,
    }).addTo(state.map);
  }

  // Path
  state.pathCoords.push(latlng);
  state.pathLine.setLatLngs(state.pathCoords);
  if (state.pathCoords.length === 1) {
    state.map.setView(latlng, 16);
  } else {
    state.map.panTo(latlng, { animate: true, duration: 1 });
  }
}

// ── Device Identity (persisted in localStorage) ───────────────────────────────
function getDeviceId() {
  let id = localStorage.getItem('gps_device_id');
  if (!id) {
    id = 'dev_' + Math.random().toString(36).slice(2, 10) + '_' + Date.now().toString(36);
    localStorage.setItem('gps_device_id', id);
  }
  return id;
}

function getDeviceName() {
  const ua = navigator.userAgent;
  if (/iPhone/i.test(ua))   return 'iPhone';
  if (/iPad/i.test(ua))     return 'iPad';
  if (/Android/i.test(ua))  return 'Android Phone';
  if (/Windows/i.test(ua))  return 'Windows PC';
  if (/Macintosh/i.test(ua))return 'Mac';
  if (/Linux/i.test(ua))    return 'Linux';
  return 'Browser';
}

// ── Send Location to Server ─────────────────────────────────────────────────────
async function sendLocation(lat, lon, accuracy, speed) {
  try {
    const resp = await fetch("/api/location", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        latitude:    lat,
        longitude:   lon,
        accuracy,
        speed_kmh:   speed,
        device_id:   getDeviceId(),
        device_name: getDeviceName(),
      }),
    });
    const data = await resp.json();

    // Update address display
    const addrEl = document.getElementById("current-address");
    if (addrEl && data.address) addrEl.textContent = data.address;

    // Geofence breach
    if (data.geofence_breach) {
      showToast("⚠️ Geofence Alert",
        `You are ${data.distance_m}m outside safe zone: ${data.zone}`,
        "warning", 8000);
    }
  } catch (e) {
    console.error("Location send failed:", e);
  }
}

// ── Calculate Speed ──────────────────────────────────────────────────────────
function calcSpeed(pos) {
  if (pos.coords.speed != null && pos.coords.speed >= 0) {
    return pos.coords.speed * 3.6; // m/s → km/h
  }
  if (!state.lastPosition) return 0;

  const dt = (pos.timestamp - state.lastPosition.timestamp) / 1000;
  if (dt < 1) return 0;

  const R = 6371000;
  const φ1 = state.lastPosition.coords.latitude * Math.PI / 180;
  const φ2 = pos.coords.latitude * Math.PI / 180;
  const Δφ = (pos.coords.latitude - state.lastPosition.coords.latitude) * Math.PI / 180;
  const Δλ = (pos.coords.longitude - state.lastPosition.coords.longitude) * Math.PI / 180;
  const a = Math.sin(Δφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(Δλ/2)**2;
  const dist = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return (dist / dt) * 3.6;
}

// ── Send Location to Server ──────────────────────────────────────────────────
async function sendLocation(lat, lon, accuracy, speed) {
  try {
    const resp = await fetch("/api/location", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ latitude: lat, longitude: lon, accuracy, speed_kmh: speed }),
    });
    const data = await resp.json();

    // Update address display
    const addrEl = document.getElementById("current-address");
    if (addrEl && data.address) addrEl.textContent = data.address;

    // Geofence breach
    if (data.geofence_breach) {
      showToast("⚠️ Geofence Alert",
        `You are ${data.distance_m}m outside safe zone: ${data.zone}`,
        "warning", 8000);
    }
  } catch (e) {
    console.error("Location send failed:", e);
  }
}

// ── Emergency Analysis ───────────────────────────────────────────────────────
async function checkEmergency(lat, lon, speed, noMoveSecs, sos = false) {
  try {
    const resp = await fetch("/api/emergency", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        latitude: lat, longitude: lon,
        speed_kmh: speed,
        no_movement_seconds: noMoveSecs,
        sos_triggered: sos,
      }),
    });
    const result = await resp.json();

    if (result.emergency) {
      activateEmergencyUI(result);
    }
    return result;
  } catch (e) {
    console.error("Emergency check failed:", e);
  }
}

// ── Emergency UI ─────────────────────────────────────────────────────────────
function activateEmergencyUI(result) {
  if (state.emergencyActive && !result.sos_triggered) return;
  state.emergencyActive = true;

  const panel = document.getElementById("emergency-panel");
  if (panel) {
    panel.classList.add("emergency-panel");
    panel.innerHTML = `
      <div class="card-title">🚨 Emergency Detected</div>
      <p style="color:var(--danger);font-weight:700;font-size:1.1rem">${result.reason}</p>
      <p style="color:var(--text-secondary);font-size:.85rem;margin:8px 0">
        Severity: <strong style="color:var(--warning)">${result.severity}</strong>
        &nbsp;|&nbsp; Confidence: <strong>${result.confidence}%</strong>
      </p>
      <p style="color:var(--text-secondary);font-size:.8rem">
        Emergency contacts have been notified by email.
      </p>
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" onclick="resolveEmergency()">✅ I'm Safe</button>
        <button class="btn btn-ghost btn-sm" onclick="stopVoice()" style="color:var(--text-muted)">🔇 Stop Voice</button>
      </div>
    `;
  }

  // ① Play alarm sound
  const alarm = document.getElementById("alarm-audio");
  if (alarm) alarm.play().catch(() => {});

  // ② Voice alert (Web Speech API)
  const userName = window.CURRENT_USER_NAME || 'User';
  const addr     = document.getElementById('current-address')?.textContent || 'current location';
  const msg = `Emergency Alert! ${userName} needs help. Reason: ${result.reason}. ` +
              `Severity: ${result.severity}. Please call immediately. Location: ${addr}. ` +
              `Emergency contacts have been notified.`;
  voiceAlert(msg, 2);

  // ③ Browser push notification
  showBrowserNotification(
    '🚨 EMERGENCY ALERT',
    `${userName} needs help! Reason: ${result.reason}. Confidence: ${result.confidence}%`,
    true
  );

  // ④ Show call contacts panel
  renderCallPanel(result.reason);

  // ⑤ Toast
  showToast("🚨 EMERGENCY DETECTED", result.reason, "danger", 0);
}

window.resolveEmergency = async function () {
  state.emergencyActive = false;
  const panel = document.getElementById("emergency-panel");
  if (panel) {
    panel.classList.remove("emergency-panel");
    panel.innerHTML = `<div class="card-title">🛡️ Status</div>
      <p style="color:var(--success);font-weight:600">✅ All Clear — Monitoring</p>`;
  }
  // Hide call panel
  const callPanel = document.getElementById("call-panel");
  if (callPanel) callPanel.style.display = 'none';

  const alarm = document.getElementById("alarm-audio");
  if (alarm) { alarm.pause(); alarm.currentTime = 0; }

  // Stop voice
  if (window.speechSynthesis) window.speechSynthesis.cancel();

  showToast("Alert Resolved", "You have marked yourself as safe.", "success");
};

// ── Main GPS Tracking Loop ───────────────────────────────────────────────────
function accuracyLabel(acc) {
  if (acc <= 15)  return { text: 'Excellent', color: '#10b981' };
  if (acc <= 50)  return { text: 'Good',      color: '#6366f1' };
  if (acc <= 200) return { text: 'Fair',      color: '#f59e0b' };
  if (acc <= 500) return { text: 'Poor',      color: '#f97316' };
  return            { text: 'Very Poor',      color: '#ef4444' };
}

async function fetchIPLocation() {
  // Free IP-based location as starting point (only called once on startup)
  try {
    const r = await fetch('https://ipapi.co/json/');
    const d = await r.json();
    if (d.latitude && d.longitude) {
      updateMapPosition(d.latitude, d.longitude, 5000);
      if (state.map) state.map.setView([d.latitude, d.longitude], 13);
      const addrEl = document.getElementById('current-address');
      if (addrEl) addrEl.textContent = `${d.city || ''}, ${d.region || ''}, ${d.country_name || ''} (IP estimate — not precise)`;
    }
  } catch(e) { /* silent fail */ }
}

function enableManualPinDrop() {
  if (!state.map) return;
  showToast('📍 Pin Drop Mode', 'Click anywhere on the map to set your location manually.', 'info', 6000);
  state.map.once('click', async (e) => {
    const { lat, lng } = e.latlng;
    state.manualOverride = { lat, lon: lng };
    updateMapPosition(lat, lng, 10);

    const addrEl = document.getElementById('current-address');
    if (addrEl) addrEl.textContent = 'Resolving address…';

    // Reverse geocode the clicked point
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`);
      const d = await r.json();
      if (addrEl && d.display_name) addrEl.textContent = '📍 ' + d.display_name;
    } catch(e) {}

    await sendLocation(lat, lng, 10, 0);
    showToast('📍 Location Set', `Lat: ${lat.toFixed(5)}, Lon: ${lng.toFixed(5)}`, 'success');
  });
}
window.enableManualPinDrop = enableManualPinDrop;

function startTracking() {
  if (state.isTracking) return;
  if (!navigator.geolocation) {
    showToast("GPS Not Supported", "Your browser does not support geolocation.", "danger");
    return;
  }

  state.isTracking = true;
  state.manualOverride = null;
  updateTrackingBtn(true);

  // Show IP-based location immediately while GPS warms up
  fetchIPLocation();

  showToast("Tracking Started", "Acquiring GPS signal… accuracy improves after a few seconds.", "success");

  // Low maximumAge = always request fresh position; zero timeout fallback
  const options = { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 };

  state.watchId = navigator.geolocation.watchPosition(async (pos) => {
    const { latitude: lat, longitude: lon, accuracy } = pos.coords;
    const speed = calcSpeed(pos);

    // Skip wildly inaccurate readings (worse than 1000m) — typical on desktop
    if (accuracy > 1000 && state.lastPosition) {
      const qual = accuracyLabel(accuracy);
      const accEl = document.getElementById('info-accuracy');
      if (accEl) {
        accEl.textContent = `${Math.round(accuracy)}m`;
        accEl.style.color = qual.color;
        accEl.title = qual.text;
      }
      showToast('⚠️ Low Accuracy', `GPS accuracy is ${Math.round(accuracy)}m (${qual.text}) — using last known position. For best results open on mobile.`, 'warning', 7000);
      return;
    }

    // Show accuracy quality
    const qual = accuracyLabel(accuracy);
    const accEl = document.getElementById('info-accuracy');
    if (accEl) {
      accEl.innerHTML = `${Math.round(accuracy)}m <small style="color:${qual.color};font-size:.6rem">${qual.text}</small>`;
    }

    // Warn once if accuracy is poor (200–1000m)
    if (accuracy > 200 && !state._warnedAccuracy) {
      state._warnedAccuracy = true;
      showToast('📡 Low GPS Accuracy', `Accuracy: ${Math.round(accuracy)}m. On PC this is normal. For precise tracking, open on your mobile phone or click "📍 Set Manually" on the map.`, 'warning', 10000);
    }

    updateMapPosition(lat, lon, accuracy);
    updateInfoDisplay(lat, lon, speed, accuracy);

    // Movement tracking
    const moved = state.lastPosition &&
      haversine(lat, lon, state.lastPosition.coords.latitude, state.lastPosition.coords.longitude) > 5;
    if (moved || !state.lastPosition) state.lastMoveTime = Date.now();
    state.lastPosition = pos;

    const noMoveSecs = (Date.now() - state.lastMoveTime) / 1000;

    await sendLocation(lat, lon, accuracy, speed);

    // Check emergency every 30 seconds of no movement
    if (noMoveSecs > 30 && noMoveSecs % 30 < 5) {
      await checkEmergency(lat, lon, speed, noMoveSecs);
    }

  }, (err) => {
    console.error("GPS error:", err);
    const msgs = {
      1: "Location permission denied. Please allow location access in your browser settings.",
      2: "Location unavailable. Check GPS signal or try on mobile.",
      3: "Location request timed out. Try on mobile for better GPS.",
    };
    showToast("GPS Error", msgs[err.code] || "Unknown GPS error", "danger");
    stopTracking();
  }, options);
}

function stopTracking() {
  if (state.watchId != null) {
    navigator.geolocation.clearWatch(state.watchId);
    state.watchId = null;
  }
  state.isTracking = false;
  updateTrackingBtn(false);
  showToast("Tracking Stopped", "Location monitoring paused.", "info");

  // Update server
  fetch("/api/location", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ latitude: 0, longitude: 0, stopped: true }),
  }).catch(() => {});
}

function updateTrackingBtn(active) {
  const btn = document.getElementById("tracking-btn");
  if (!btn) return;
  if (active) {
    btn.className = "btn btn-danger btn-sm";
    btn.innerHTML = `<span class="live-dot"></span> Stop Tracking`;
    btn.onclick = stopTracking;
  } else {
    btn.className = "btn btn-primary btn-sm";
    btn.innerHTML = `▶ Start Tracking`;
    btn.onclick = startTracking;
  }
}

// ── SOS Button ───────────────────────────────────────────────────────────────
window.triggerSOS = async function () {
  const confirmed = confirm("⚠️ Are you sure you want to trigger an SOS alert?\nThis will notify all your emergency contacts immediately.");
  if (!confirmed) return;

  const btn = document.getElementById("sos-btn");
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="loader"></span><br>Sending…`; }

  let lat = 0, lon = 0;
  if (state.lastPosition) {
    lat = state.lastPosition.coords.latitude;
    lon = state.lastPosition.coords.longitude;
  }

  const result = await checkEmergency(lat, lon, 0, 0, true);
  activateEmergencyUI({ ...result, reason: "Manual SOS triggered", severity: "CRITICAL", confidence: 100 });

  if (btn) {
    btn.disabled = false;
    btn.innerHTML = `<span class="sos-icon">🆘</span>SOS`;
  }
};

// ── Info Display ─────────────────────────────────────────────────────────────
function updateInfoDisplay(lat, lon, speed, accuracy) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set("info-lat",      lat.toFixed(5));
  set("info-lon",      lon.toFixed(5));
  set("info-speed",    speed.toFixed(1) + " km/h");
  set("info-accuracy", accuracy ? Math.round(accuracy) + "m" : "—");
  set("info-time",     new Date().toLocaleTimeString());
}

function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const φ1 = lat1 * Math.PI / 180, φ2 = lat2 * Math.PI / 180;
  const Δφ = (lat2 - lat1) * Math.PI / 180;
  const Δλ = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(Δφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(Δλ/2)**2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

// ── Socket.IO ────────────────────────────────────────────────────────────────
function initSocket() {
  if (typeof io === "undefined") return;
  state.socket = io();
  state.socket.on("connect", () => console.log("Socket connected"));
  state.socket.on("disconnect", () => console.log("Socket disconnected"));
}

// ── Safe Zone Add ────────────────────────────────────────────────────────────
window.addSafeZoneHere = async function () {
  if (!state.lastPosition) {
    showToast("No Location", "Start tracking first to set a safe zone at your current location.", "warning");
    return;
  }
  const name   = prompt("Safe zone name (e.g. Home, Office):", "Home");
  const radius = parseInt(prompt("Radius in metres:", "200"));
  if (!name || isNaN(radius)) return;

  const { latitude, longitude } = state.lastPosition.coords;
  const resp = await fetch("/api/safe-zones", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, latitude, longitude, radius_m: radius }),
  });
  if (resp.ok) {
    showToast("Safe Zone Added", `"${name}" set at your current location.`, "success");
    loadSafeZones();
  }
};

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  initSocket();
  loadSafeZones();

  // Auto-start if user clicks start btn
  document.getElementById("tracking-btn")?.addEventListener("click", startTracking);

  // SOS button
  document.getElementById("sos-btn")?.addEventListener("click", window.triggerSOS);
});
