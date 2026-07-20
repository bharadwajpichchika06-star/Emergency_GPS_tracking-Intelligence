# Voice Assistant — What Changed and Why

This document explains the Voice Assistant feature added to the GPS
Emergency Tracker: which files changed, why, how the pieces talk to each
other, and how to test it. **No existing feature was removed or rewritten.**
The SOS button works exactly as it did before.

---

## 1. Files touched

| File | Type | What changed |
|---|---|---|
| `static/js/voice.js` | **New** | All Voice Assistant logic (speech recognition, phrase matching, hand-off to the existing emergency system). |
| `templates/tracker.html` | Modified | Added a 🎙️ mic button next to the SOS button, a small status line, and a `<script>` tag to load `voice.js`. |
| `static/css/style.css` | Modified | Added `.btn-mic` styling + a "listening" pulse animation, appended at the end of the file. Nothing existing was edited. |
| `README.txt` | Modified | Added the feature to the feature list + a short usage note. |
| `app.py`, `emergency.py`, `models.py`, `notifier.py`, `config.py`, `static/js/tracker.js` | **Untouched** | No backend or existing frontend logic changes were needed — see §2. |

---

## 2. Why no backend changes were needed

The SOS button (`tracker.js`, `triggerSOS()`) already funnels every
emergency through one JS function:

```js
checkEmergency(lat, lon, speed, noMovementSeconds, sosTriggered)
```

which does `POST /api/emergency` with `sos_triggered: true`. The Flask
route `/api/emergency` (in `app.py`) then runs `emergency.analyze()`,
saves the `Alert` row, sends email/SMS/voice-call notifications via
`notifier.py`, and broadcasts to admins over Socket.IO.

The Voice Assistant's job is only to **decide when to call
`checkEmergency()`** — it calls the *exact same* function, with the *exact
same* arguments (`sos_triggered: true`), that the SOS button already
calls. That's why the requirement "both methods must call the same
backend emergency function" is satisfied with zero backend changes and
zero duplicated frontend logic: `voice.js` never talks to the network
directly.

```
🎙️ mic button        🆘 SOS button
       │                    │
       ▼                    ▼
 voice.js detects     tracker.js triggerSOS()
 an emergency phrase        │
       │                    │
       └────────┬───────────┘
                 ▼
     checkEmergency(lat, lon, 0, 0, true)   ← ONE shared function
                 ▼
      POST /api/emergency  (unchanged Flask route)
                 ▼
   analyze() → save Alert → email/SMS/call → Socket.IO broadcast
                 ▼
        activateEmergencyUI(result)   ← ONE shared UI function
   (alarm sound, emergency panel, spoken alert, call-contacts panel)
```

`voice.js` is loaded *after* `tracker.js` in `tracker.html`, so it can
call `checkEmergency()`, read `state.lastPosition`, and call `showToast()`
directly — these are ordinary top-level functions/variables in
`tracker.js`, and browsers share one global scope across `<script>` tags
on the same page. `voice.js` even guards this with
`typeof checkEmergency === "function"` before calling it, so it fails
gracefully (with an on-screen error) instead of throwing if it's ever
loaded on a page without `tracker.js`.

---

## 3. How speech recognition works (`static/js/voice.js`)

1. **Tap the mic button** → `toggleListening()` calls
   `recognition.start()`. `recognition` is a `SpeechRecognition` (or
   `webkitSpeechRecognition`) instance — the browser's built-in Web
   Speech API. No API key, no server round-trip for the speech-to-text
   step itself; the browser vendor's speech engine does that.
2. The browser streams microphone audio to that engine and returns a
   **text transcript** — `voice.js` never sees or stores raw audio.
3. `recognition.onresult` receives the transcript (plus up to 2
   alternative guesses, since `maxAlternatives = 3`) and passes each one
   through `detectEmergencyPhrase()`.
4. `detectEmergencyPhrase()`:
   - **Normalizes** the text: lowercase, strips punctuation, collapses
     whitespace (`"I'm in danger!"` → `"im in danger"`). This is what
     makes matching case-insensitive.
   - Checks it against the 10 supported phrases, longest first.
   - First tries an exact substring match (cheap, common case).
   - If that fails, falls back to a **word-by-word fuzzy match** using
     Levenshtein (edit) distance, so small mis-transcriptions like
     `"call plice"` (heard instead of "call police") or `"acident"`
     (heard instead of "accident") still match. This satisfies "tolerant
     of small variations" without needing an external NLP service.
5. **Match found** → `handleEmergencyDetected()` is called; recognition
   has already auto-stopped (`recognition.continuous = false` means it
   stops itself after one result, satisfying "stop listening").
6. **No match** → `handleUnrecognizedSpeech()` shows a toast, speaks
   "Unable to understand. Please try again.", and the user can tap the
   mic again.

### Supported phrases
`help me`, `sos`, `send sos`, `emergency`, `i'm in danger`, `save me`,
`call police`, `accident`, `attack`, `i need help`.

---

## 4. The emergency hand-off (`handleEmergencyDetected`)

```js
async function handleEmergencyDetected(matchedPhrase, rawTranscript) {
  // 1. Recognition already stopped itself (non-continuous mode).
  // 2. Get GPS coordinates for this alert.
  const { lat, lon } = await getLocationForVoiceCommand();
  // 3. Trigger the SAME function the SOS button uses.
  await checkEmergency(lat, lon, 0, 0, true);
  // 4. On-screen success message (see §5).
  // 5. Spoken confirmation (see §6).
}
```

`getLocationForVoiceCommand()` reuses `state.lastPosition` — the exact
same live GPS fix the SOS button would use — if GPS tracking is already
running. If tracking hasn't been started yet, it falls back to one fresh
`navigator.geolocation.getCurrentPosition()` call so a voice command
still works even before the user presses "Start Tracking". If location
can't be obtained at all, it falls back to `(0, 0)` — the same fallback
`triggerSOS()` already uses.

---

## 5. On-screen success/error messages

All voice feedback reuses the app's existing toast system
(`showToast()` from `tracker.js`) so it looks and behaves identically to
every other notification in the app — no new UI component was invented.
A small status line under the buttons (`#voice-status-text`) also echoes
what was heard, for users who have sound muted.

Handled gracefully:
- **Mic permission denied** → toast + status text; SOS button still works.
- **Speech not recognized / silence** → "No speech detected" toast +
  spoken prompt to try again.
- **Browser unsupported** (no `SpeechRecognition`) → mic button is
  disabled with an explanatory tooltip; SOS is unaffected.
- **No internet** → speech recognition itself needs connectivity; a
  `network` error from the API is caught and shown as a friendly
  "check your connection" message.
- **Unknown phrase** → toast showing exactly what was heard, so the user
  can adjust and retry.

---

## 6. Spoken feedback (Speech Synthesis)

- `"Listening..."` — spoken when recognition starts.
- `"Emergency detected. Sending your location to your emergency
  contacts."` — spoken once the shared emergency flow has been
  triggered. This is queued (not "cancel and speak") so it doesn't talk
  over the fuller spoken alert that `checkEmergency()` →
  `activateEmergencyUI()` already speaks via `tracker.js`'s existing
  `voiceAlert()` — the two are complementary, not duplicated.
- `"Unable to understand. Please try again."` — spoken on no-match or
  most error cases.

---

## 7. Testing instructions

**Browser:** use Chrome, Edge, or Safari (desktop or Android). Firefox
does not support the Web Speech API by default.

**Important:** microphone access requires a "secure origin" — `https://`
or `http://localhost`. If you open the app via a LAN IP
(`http://192.168.x.x:5000`) on your phone, the browser will block mic
access; the SOS button still works there. Test voice either on the PC
via `http://localhost:5000`, or over HTTPS.

1. **SOS button still works** — log in, go to Tracker, click SOS,
   confirm the dialog. Confirm the emergency panel, alarm sound, spoken
   alert, and "call contacts" panel all appear exactly as before.
2. **Voice assistant starts listening** — click the 🎙️ button. Grant
   microphone permission when prompted. The button should turn red and
   pulse, the status line should show "Listening...", and you should
   hear "Listening..." spoken.
3. **Voice commands trigger the same workflow** — say "Help me" (or any
   supported phrase). Confirm: the emergency panel appears, the alarm
   plays, the call-contacts panel appears, and a toast + spoken line
   confirms the voice command was recognized — the same underlying
   alert as a manual SOS.
4. **GPS location is retrieved** — start GPS tracking first (or allow a
   fresh location prompt), then trigger a voice command; check the
   "Advanced Details" lat/lon match what's used in the alert, and (if
   configured) the email/SMS include a location link.
5. **Emergency notifications are sent** — with email/Twilio configured
   in Settings, confirm the same notifications fire for a voice-triggered
   alert as for an SOS button press (check History / your inbox / phone).
6. **Voice confirmation is spoken** — listen for "Emergency detected.
   Sending your location to your emergency contacts." after the alert.
7. **Error cases:**
   - Deny mic permission → friendly "Microphone Blocked" toast, SOS
     still works.
   - Click mic, stay silent past the timeout → "No speech detected."
   - Say something unrelated (e.g. "what's the weather") → "Command Not
     Recognized" toast + "Unable to understand. Please try again."
   - Open in Firefox → mic button is disabled with an explanatory
     tooltip instead of erroring.
