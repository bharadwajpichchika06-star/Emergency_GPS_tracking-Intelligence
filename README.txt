============================================================
   GPS Emergency Tracker
   Real-time GPS tracking with emergency SOS alerts
============================================================

QUICK START (Windows)
─────────────────────
1. Make sure Python 3.10+ is installed
   Download: https://www.python.org/downloads/
   ⚠ During install, tick "Add Python to PATH"

2. Double-click  run.bat
   (It automatically installs all packages and starts the server)

3. Open your browser and go to:
   http://localhost:5000

4. Log in as Admin:
   Email   : admin@gpstracker.com
   Password: admin123


CONFIGURE EMAIL & SMS ALERTS
─────────────────────────────
Option A – via Settings page (easiest):
  • Log in → click Settings (⚙️)
  • Fill in Gmail SMTP credentials
  • Fill in Twilio credentials
  • Save and use the Test buttons

Option B – via .env file:
  • Copy  .env.example  →  rename to  .env
  • Fill in your credentials
  • Restart run.bat


FEATURES
─────────
✅ Real-time GPS tracking (browser geolocation)
✅ SOS emergency button
✅ Voice-activated emergency assistant (say "Help me", "SOS", etc.)
✅ Auto fall / no-movement detection
✅ Geofence safe zones with breach alerts
✅ Email alerts (Gmail SMTP)
✅ SMS alerts (Twilio)
✅ Voice call alerts (Twilio)
✅ Admin dashboard (multi-user)
✅ Location history


REQUIREMENTS
─────────────
• Python 3.10 or newer
• Internet connection (for maps, Twilio, email)
• Twilio free trial account for SMS + calls
• Gmail account with App Password for email


VOICE ASSISTANT (NEW)
──────────────────────
On the Tracker page, next to the SOS button there is a 🎙️ mic button.
Tap it and say one of: "Help me", "SOS", "Send SOS", "Emergency",
"I'm in danger", "Save me", "Call police", "Accident", "Attack",
"I need help". It triggers the exact same emergency flow as the SOS
button (notifications, alarm, spoken alert). Needs Chrome, Edge, or
Safari, and microphone permission. Full details: VOICE_ASSISTANT.md


MOBILE ACCESS (same Wi-Fi)
───────────────────────────
When you run run.bat it shows your local IP, e.g.:
   Mobile / LAN:  http://192.168.1.5:5000

Open that URL on your phone (same Wi-Fi network).

NOTE: The 🎙️ voice assistant needs microphone access, which Chrome
only grants on "secure origins" — that's https:// pages, OR
http://localhost on the same machine. It will usually be blocked on
a plain http://192.168.x.x LAN address. The SOS button is unaffected
and works everywhere. To test voice on your phone, either use
https:// (e.g. via ngrok) or test the mic on the PC itself.


STOPPING THE SERVER
────────────────────
Press  CTRL+C  in the run.bat window, or just close it.


TROUBLESHOOTING
────────────────
• "Python not found" → Install Python and tick "Add to PATH"
• SMS not received  → Number must be verified on Twilio trial account
                      https://console.twilio.com/us1/develop/phone-numbers/manage/verified
• Email not sent    → Use Gmail App Password, not your regular password
                      https://myaccount.google.com/apppasswords


============================================================
   Built with Flask, SQLite, Socket.IO, Twilio, Leaflet.js
============================================================
