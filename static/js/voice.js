/**
 * voice.js — Voice Assistant for GPS Emergency Tracker
 * =====================================================
 *
 * WHY THIS FILE EXISTS
 * ---------------------
 * The tracker page already has a working SOS button (see tracker.js:
 * `triggerSOS()`), which calls `checkEmergency()` → POST /api/emergency →
 * the same backend logic used everywhere else in the app (emergency.py's
 * `analyze()`, alert saving, email/SMS/call notifications, Socket.IO
 * broadcast, alarm sound, on-screen panel, spoken alert).
 *
 * This file adds a SECOND way to trigger that exact same flow: speaking an
 * emergency phrase into the microphone. It does NOT re-implement any of the
 * emergency logic. It only:
 *   1. Listens to the microphone using the browser's Web Speech API.
 *   2. Detects whether the recognized text matches an emergency phrase.
 *   3. If it does, calls the SAME `checkEmergency()` function tracker.js
 *      already defines — nothing about the backend call, notification
 *      logic, or emergency panel is duplicated here.
 *
 * HOW THE FRONTEND TALKS TO THE BACKEND (for this feature)
 * ----------------------------------------------------------
 * This file makes NO direct fetch() calls of its own. Once a voice command
 * is recognized as an emergency phrase, it hands off to
 * `checkEmergency(lat, lon, speed, noMoveSeconds, sosTriggered)` — a
 * function already defined in tracker.js — exactly the way the SOS button
 * does. That function performs:
 *     POST /api/emergency  { latitude, longitude, speed_kmh,
 *                             no_movement_seconds, sos_triggered: true }
 * The Flask route `/api/emergency` (app.py) runs the same `analyze()` rule
 * engine, saves the Alert row, sends email/SMS/voice-call notifications,
 * and broadcasts to admins over Socket.IO — identically to a manual SOS
 * button press. No backend code was changed to support voice commands.
 *
 * HOW SPEECH RECOGNITION WORKS HERE
 * -----------------------------------
 * The browser's built-in SpeechRecognition API (Web Speech API) is used:
 *   - It's started when the user taps the mic button.
 *   - The browser streams microphone audio to the browser's speech engine
 *     and returns a text transcript (this file never touches raw audio).
 *   - `recognition.onresult` receives that transcript (plus a couple of
 *     alternative guesses) and passes each one through
 *     `detectEmergencyPhrase()`, which normalizes the text (lowercase,
 *     punctuation stripped) and checks it against the supported emergency
 *     phrases, tolerating small mis-transcriptions using a Levenshtein
 *     ("edit distance") comparison on a word-by-word basis.
 *   - If nothing matches, the user is told via voice + on-screen text and
 *     can simply tap the mic again.
 *
 * HOW A VOICE COMMAND REACHES THE EXISTING EMERGENCY SYSTEM
 * ------------------------------------------------------------
 * detectEmergencyPhrase() match  →  handleEmergencyDetected()
 *   → getLocationForVoiceCommand()   (GPS, reusing tracker.js's live fix
 *                                      when available, otherwise a fresh
 *                                      one-off navigator.geolocation call)
 *   → checkEmergency(lat, lon, 0, 0, true)   ← THE SAME FUNCTION THE SOS
 *                                               BUTTON CALLS. This alone
 *                                               triggers the shared
 *                                               notify / save / alarm /
 *                                               on-screen-panel pipeline.
 *   → on-screen success toast + spoken confirmation (voice-specific,
 *     additive — it does not replace anything the shared flow already
 *     shows or speaks).
 */

(function () {
  "use strict";

  // ── Supported emergency voice commands ──────────────────────────────────
  // Case-insensitive; matched against a normalized transcript with a small
  // tolerance for mis-heard words (see detectEmergencyPhrase()).
  const EMERGENCY_PHRASES = [
    "help me",
    "sos",
    "send sos",
    "emergency",
    "i'm in danger",
    "save me",
    "call police",
    "accident",
    "attack",
    "i need help",
  ];

  // Checked longest-phrase-first so that e.g. "send sos" is reported instead
  // of just "sos" when both are technically present in the transcript —
  // purely cosmetic (both trigger the identical emergency flow below), but
  // it makes the recognized-command feedback shown to the user more precise.
  const PHRASES_BY_SPECIFICITY = [...EMERGENCY_PHRASES].sort(
    (a, b) => b.split(" ").length - a.split(" ").length
  );

  // Module state — deliberately separate from tracker.js's `state` object
  // (which owns GPS/emergency state); this file only tracks mic UI state.
  const voice = {
    recognition: null,
    isListening: false,
    supported: false,
  };

  // ── Small DOM/UI helpers ─────────────────────────────────────────────────
  function updateVoiceStatus(text) {
    const el = document.getElementById("voice-status-text");
    if (el) el.textContent = text || "";
  }

  function setMicButtonListening(active) {
    const micBtn = document.getElementById("mic-btn");
    const micIcon = document.getElementById("mic-icon");
    if (!micBtn) return;
    if (active) {
      micBtn.classList.add("listening");
      micBtn.title = "Listening… tap to stop";
      if (micIcon) micIcon.textContent = "🔴";
    } else {
      micBtn.classList.remove("listening");
      micBtn.title = 'Tap and say: "Help me", "SOS", "Emergency", "Call police"...';
      if (micIcon) micIcon.textContent = "🎙️";
    }
  }

  // Reuses the app's existing toast system (tracker.js) when present, so
  // voice feedback looks and behaves identically to every other toast in
  // the app instead of inventing a new notification style.
  function notify(title, text, type, duration) {
    if (typeof showToast === "function") {
      showToast(title, text, type, duration);
    }
  }

  // ── Speech synthesis for the assistant's OWN short prompts ─────────────
  // These are intentionally separate from tracker.js's `voiceAlert()`
  // (which is tuned for the full, repeated emergency siren-style alert).
  //
  // `speakNow()` cancels any assistant speech in progress — used for quick
  // status prompts ("Listening...", error messages) where nothing else
  // important should be talking at the same time.
  //
  // `queueAssistantSpeech()` does NOT cancel — used only for the post-
  // emergency confirmation, so it queues politely after the shared
  // emergency alert (triggered inside checkEmergency -> activateEmergencyUI)
  // instead of talking over it.
  function queueAssistantSpeech(text) {
    if (!window.speechSynthesis) return;
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang = "en-US";
    utt.rate = 0.95;
    utt.pitch = 1.0;
    window.speechSynthesis.speak(utt);
  }

  function speakNow(text) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    queueAssistantSpeech(text);
  }

  // ── Text normalization + fuzzy phrase matching ──────────────────────────
  // Lowercases, strips punctuation (so "I'm" -> "im", "S.O.S" -> "sos"),
  // and collapses whitespace, so matching is case-insensitive and ignores
  // punctuation differences between what was said and how it's spelled.
  function normalize(text) {
    return text
      .toLowerCase()
      .replace(/[^\w\s]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  // Classic edit-distance algorithm — used to tolerate small speech-to-text
  // mistakes (e.g. "danjer" heard instead of "danger").
  function levenshtein(a, b) {
    const m = a.length;
    const n = b.length;
    if (m === 0) return n;
    if (n === 0) return m;

    const dp = new Array(m + 1);
    for (let i = 0; i <= m; i++) dp[i] = new Array(n + 1).fill(0);
    for (let i = 0; i <= m; i++) dp[i][0] = i;
    for (let j = 0; j <= n; j++) dp[0][j] = j;

    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        if (a[i - 1] === b[j - 1]) {
          dp[i][j] = dp[i - 1][j - 1];
        } else {
          dp[i][j] = 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
        }
      }
    }
    return dp[m][n];
  }

  // Two words "match" if identical, or close enough that they were likely
  // the same word mis-heard by the speech engine. Very short words (<=3
  // chars) require an exact match to avoid false positives like "sos" vs
  // "so".
  function wordsFuzzyMatch(wordA, wordB) {
    if (wordA === wordB) return true;
    const maxLen = Math.max(wordA.length, wordB.length);
    if (maxLen <= 3) return false;
    const tolerance = maxLen <= 5 ? 1 : 2;
    return levenshtein(wordA, wordB) <= tolerance;
  }

  // Slides the phrase's words across the transcript's words looking for a
  // contiguous run where every word fuzzy-matches — this is what gives us
  // tolerance for small variations without requiring an exact substring.
  function phraseFuzzyIncluded(transcriptWords, phraseWords) {
    if (phraseWords.length > transcriptWords.length) return false;
    for (let start = 0; start <= transcriptWords.length - phraseWords.length; start++) {
      let allMatch = true;
      for (let k = 0; k < phraseWords.length; k++) {
        if (!wordsFuzzyMatch(transcriptWords[start + k], phraseWords[k])) {
          allMatch = false;
          break;
        }
      }
      if (allMatch) return true;
    }
    return false;
  }

  // Returns the matched phrase (one of EMERGENCY_PHRASES) or null.
  function detectEmergencyPhrase(rawTranscript) {
    const norm = normalize(rawTranscript);
    if (!norm) return null;
    const transcriptWords = norm.split(" ");

    for (const phrase of PHRASES_BY_SPECIFICITY) {
      const normPhrase = normalize(phrase);
      // Fast path: exact substring match (handles the common case cheaply).
      if (norm.includes(normPhrase)) return phrase;
      // Fallback: word-by-word fuzzy match, tolerant of small mis-hearings.
      if (phraseFuzzyIncluded(transcriptWords, normPhrase.split(" "))) return phrase;
    }
    return null;
  }

  // ── GPS location for a voice-triggered emergency ────────────────────────
  // Reuses the live GPS fix tracker.js already maintains (`state.lastPosition`)
  // whenever tracking is active — the exact same coordinates the SOS button
  // would use. If tracking hasn't been started yet, falls back to a single
  // fresh navigator.geolocation request so a voice command still works even
  // before the user has pressed "Start Tracking".
  function getLocationForVoiceCommand() {
    return new Promise((resolve) => {
      if (typeof state !== "undefined" && state.lastPosition) {
        resolve({
          lat: state.lastPosition.coords.latitude,
          lon: state.lastPosition.coords.longitude,
        });
        return;
      }

      if (!navigator.geolocation) {
        resolve({ lat: 0, lon: 0 });
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
        () => resolve({ lat: 0, lon: 0 }), // permission denied/unavailable — same fallback the SOS button uses
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 10000 }
      );
    });
  }

  // ── Emergency phrase detected — hand off to the EXISTING emergency flow ─
  async function handleEmergencyDetected(matchedPhrase, rawTranscript) {
    updateVoiceStatus(`Heard: "${rawTranscript}"`);

    const micBtn = document.getElementById("mic-btn");
    if (micBtn) micBtn.disabled = true;

    try {
      // Retrieve GPS location for this alert.
      const { lat, lon } = await getLocationForVoiceCommand();

      // Trigger the SAME backend emergency function the SOS button uses.
      // checkEmergency() is defined once in tracker.js and is reused here
      // unchanged — it POSTs to /api/emergency, and if the backend reports
      // an emergency it already: saves the Alert, sends email/SMS/call
      // notifications, plays the alarm, shows the emergency panel, speaks
      // the full alert, and shows the "call contacts" panel.
      if (typeof checkEmergency === "function") {
        await checkEmergency(lat, lon, 0, 0, true);
      } else {
        console.error("voice.js: checkEmergency() is not available — is tracker.js loaded?");
        notify("Voice Assistant Error", "Could not reach the emergency system.", "danger", 6000);
      }

      // On-screen success message for the voice interaction specifically
      // (additive to, not a replacement for, the shared emergency panel).
      notify(
        "🎙️ Voice Emergency Triggered",
        `Command recognized: "${matchedPhrase}" — your emergency contacts are being notified.`,
        "success",
        7000
      );
      updateVoiceStatus(`Voice command "${matchedPhrase}" triggered an emergency alert.`);

      // Spoken confirmation. Queued (not cancel-and-speak) so it doesn't
      // talk over the fuller spoken alert the shared flow just started.
      queueAssistantSpeech("Emergency detected. Sending your location to your emergency contacts.");
    } finally {
      if (micBtn) micBtn.disabled = false;
    }
  }

  // ── No emergency phrase recognized ───────────────────────────────────────
  function handleUnrecognizedSpeech(rawTranscript) {
    updateVoiceStatus(`Heard: "${rawTranscript}" — no emergency phrase recognized.`);
    notify(
      "🎙️ Command Not Recognized",
      `Heard: "${rawTranscript}". Try "Help me", "SOS", or "Emergency".`,
      "warning",
      6000
    );
    speakNow("Unable to understand. Please try again.");
  }

  // ── Recognition lifecycle / error handling ──────────────────────────────
  function attachRecognitionHandlers(recognition) {
    recognition.onstart = function () {
      voice.isListening = true;
      setMicButtonListening(true);
      updateVoiceStatus("Listening...");
      speakNow("Listening...");
    };

    recognition.onend = function () {
      voice.isListening = false;
      setMicButtonListening(false);
    };

    recognition.onresult = function (event) {
      const alternatives = event.results[0];
      let matchedPhrase = null;
      let bestTranscript = alternatives[0].transcript;

      // Check every alternative transcript the recognizer offers — a
      // command might match on the 2nd/3rd guess even if the top guess
      // was garbled.
      for (let i = 0; i < alternatives.length; i++) {
        const transcript = alternatives[i].transcript;
        const phrase = detectEmergencyPhrase(transcript);
        if (phrase) {
          matchedPhrase = phrase;
          bestTranscript = transcript;
          break;
        }
      }

      if (matchedPhrase) {
        handleEmergencyDetected(matchedPhrase, bestTranscript);
      } else {
        handleUnrecognizedSpeech(bestTranscript);
      }
    };

    recognition.onerror = function (event) {
      console.warn("Speech recognition error:", event.error);
      switch (event.error) {
        case "not-allowed":
        case "permission-denied":
          updateVoiceStatus("Microphone permission denied.");
          notify(
            "🎙️ Microphone Blocked",
            "Please allow microphone access in your browser settings to use voice commands.",
            "danger",
            7000
          );
          break;
        case "no-speech":
          updateVoiceStatus("No speech detected.");
          notify("🎙️ No Speech Detected", "I didn't hear anything. Tap the mic and try again.", "warning", 5000);
          speakNow("I did not hear anything. Please try again.");
          break;
        case "audio-capture":
          updateVoiceStatus("No microphone found.");
          notify("🎙️ No Microphone", "No microphone was found on this device.", "danger", 6000);
          break;
        case "network":
          updateVoiceStatus("Network error — check your internet connection.");
          notify(
            "🎙️ Connection Issue",
            "Voice recognition needs an internet connection. Please check your connection and try again.",
            "danger",
            6000
          );
          break;
        case "aborted":
          // Caused by us calling recognition.stop() — not a real error.
          break;
        default:
          updateVoiceStatus("Voice recognition error. Please try again.");
          notify("🎙️ Voice Error", "Something went wrong with voice recognition. Please try again.", "warning", 5000);
          speakNow("Unable to understand. Please try again.");
      }
    };
  }

  // ── Mic button click handler ─────────────────────────────────────────────
  function toggleListening() {
    if (!voice.supported) {
      notify(
        "🎙️ Not Supported",
        "Voice commands need Chrome, Edge, or Safari. Please use the SOS button instead.",
        "warning",
        6000
      );
      return;
    }
    if (voice.isListening) {
      voice.recognition.stop();
      return;
    }
    try {
      voice.recognition.start();
    } catch (err) {
      // Thrown if start() is called while a recognition session is already
      // starting up — safe to ignore.
      console.warn("voice.js: could not start recognition:", err);
    }
  }

  // ── Setup ─────────────────────────────────────────────────────────────────
  function initVoiceAssistant() {
    const micBtn = document.getElementById("mic-btn");
    if (!micBtn) return; // This page has no voice assistant UI — nothing to do.

    const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognitionCtor) {
      voice.supported = false;
      micBtn.disabled = true;
      micBtn.title = "Voice commands are not supported in this browser. Try Chrome, Edge, or Safari.";
      updateVoiceStatus("Voice commands are not supported in this browser.");
      return;
    }

    voice.supported = true;
    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "en-US";
    recognition.continuous = false; // one phrase per tap, then auto-stop
    recognition.interimResults = false;
    recognition.maxAlternatives = 3;

    attachRecognitionHandlers(recognition);
    voice.recognition = recognition;

    micBtn.addEventListener("click", toggleListening);
  }

  document.addEventListener("DOMContentLoaded", initVoiceAssistant);
})();
