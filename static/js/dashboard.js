/**
 * dashboard.js — Admin dashboard real-time updates
 */
let adminMap = null;
let adminMarkers = {};

function initAdminMap() {
  adminMap = L.map("admin-map").setView([20.5937, 78.9629], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© OpenStreetMap contributors', maxZoom: 19,
  }).addTo(adminMap);
}

function updateAdminMarker(data) {
  if (!adminMap) return;
  const { user_id, user_name, latitude, longitude, address } = data;

  const icon = L.divIcon({
    className: "",
    html: `<div style="
      width:18px;height:18px;border-radius:50%;
      background:linear-gradient(135deg,#ef4444,#dc2626);
      border:3px solid #fff;
      box-shadow:0 0 0 3px rgba(239,68,68,0.4),0 4px 8px rgba(0,0,0,0.5);
    "></div>`,
    iconSize: [18, 18], iconAnchor: [9, 9],
  });

  if (adminMarkers[user_id]) {
    adminMarkers[user_id].setLatLng([latitude, longitude])
      .bindPopup(`👤 ${user_name}<br>📍 ${address || ""}<br>⏱ ${data.timestamp}`);
  } else {
    adminMarkers[user_id] = L.marker([latitude, longitude], { icon })
      .addTo(adminMap)
      .bindPopup(`👤 ${user_name}<br>📍 ${address || ""}<br>⏱ ${data.timestamp}`);
  }
}

function initAdminSocket() {
  if (typeof io === "undefined") return;
  const socket = io();

  socket.on("connect", () => {
    socket.emit("join_admin", {});
    console.log("Admin socket connected");
  });

  socket.on("location_update", (data) => {
    updateAdminMarker(data);
    const row = document.querySelector(`tr[data-user="${data.user_id}"]`);
    if (row) {
      row.querySelector(".user-status").innerHTML = `<span class="badge badge-success"><span class="live-dot"></span> Live</span>`;
      const locCell = row.querySelector(".user-location");
      if (locCell) locCell.textContent = data.address || `${data.latitude.toFixed(4)}, ${data.longitude.toFixed(4)}`;
    }
  });

  socket.on("emergency_alert", (data) => {
    showAdminAlert(data);
    updateAdminMarker({ ...data, address: data.address });
  });
}

function showAdminAlert(data) {
  const container = document.getElementById("live-alerts");
  if (!container) return;

  const el = document.createElement("div");
  el.className = "card";
  el.style.cssText = "border-color:var(--danger);margin-bottom:12px;animation:slide-in 0.35s ease";
  el.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between">
      <span class="badge badge-danger">🚨 ${data.severity}</span>
      <small style="color:var(--text-muted)">${data.timestamp}</small>
    </div>
    <p style="margin:10px 0 4px;font-weight:700">${data.user_name}</p>
    <p style="font-size:.85rem;color:var(--text-secondary)">${data.reason}</p>
    <p style="font-size:.8rem;color:var(--text-muted);margin-top:4px">📍 ${data.address || data.latitude + ", " + data.longitude}</p>
    <a href="https://maps.google.com/?q=${data.latitude},${data.longitude}" target="_blank"
       class="btn btn-outline btn-sm" style="margin-top:10px">🗺 View on Map</a>
  `;
  container.prepend(el);
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("admin-map")) {
    initAdminMap();
    initAdminSocket();
  }
});
