"""
voice_engine.py — VoiceCommandEngine for ShutdownTimer v5.0
============================================================
Provides hands-free / eco / push-to-talk voice control and
TTS feedback.  All heavy dependencies are optional.

Required optional packages:
    pip install SpeechRecognition pyttsx3 pyaudio
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

# ── Optional imports ──────────────────────────────────────────────────────────

try:
    import speech_recognition as sr
    HAS_SPEECH = True
except ImportError:
    HAS_SPEECH = False

try:
    import pyttsx3
    HAS_TTS = True
except ImportError:
    HAS_TTS = False

try:
    import pyaudio  # noqa: F401 – only used for level meter
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_WAKE_WORDS: List[str] = ["ok timer", "hey shutdown", "computador"]

# Patterns: (compiled_regex, command_key)
# Groups inside each pattern capture numeric parameters when needed.
_RAW_PATTERNS: List[tuple] = [
    # ── Português ──────────────────────────────────────────────────────
    (r"(iniciar|começar|começa|inicia).*?(\d+).*?(minuto|minutos|min)", "start_timer"),
    (r"(desligar|shutdown).*?(\d+).*?(min)", "shutdown_in"),
    (r"(suspender|hibernar|suspende|hiberna).*?(\d+).*?(min)", "suspend_in"),
    (r"(reiniciar|reinicia|reboot).*?(\d+).*?(min)", "reboot_in"),
    (r"(cancelar|cancela|para|parar)", "cancel"),
    (r"(pausar|pausa)", "pause"),
    (r"(retomar|continua|continue)", "resume"),
    (r"(quanto tempo falta|tempo restante|status)", "status"),
    (r"(adiciona|adicionar|add|acrescenta).*?(\d+).*?(min)", "extend"),
    # ── Inglês ─────────────────────────────────────────────────────────
    (r"(start|begin).*?(\d+).*?(minute|minutes|min)", "start_timer"),
    (r"(shutdown).*?(\d+).*?(min)", "shutdown_in"),
    (r"(suspend|sleep).*?(\d+).*?(min)", "suspend_in"),
    (r"(reboot|restart).*?(\d+).*?(min)", "reboot_in"),
    (r"(cancel|stop|abort)", "cancel"),
    (r"(pause)", "pause"),
    (r"(resume|continue)", "resume"),
    (r"(how much time|time left|status)", "status"),
    (r"(add|extend).*?(\d+).*?(min)", "extend"),
]

COMMAND_PATTERNS: List[tuple] = [
    (re.compile(p, re.IGNORECASE), cmd) for p, cmd in _RAW_PATTERNS
]

# Spoken responses (TTS)
_RESPONSES: Dict[str, str] = {
    "start_timer":  "Timer iniciado por {minutes} minutos.",
    "shutdown_in":  "Desligamento agendado para {minutes} minutos.",
    "suspend_in":   "Suspensão agendada para {minutes} minutos.",
    "reboot_in":    "Reinicialização agendada para {minutes} minutos.",
    "cancel":       "Timer cancelado.",
    "pause":        "Timer pausado.",
    "resume":       "Timer retomado.",
    "status":       "Restam {remaining} minutos.",
    "extend":       "{minutes} minutos adicionados ao timer.",
    "not_found":    "Comando não reconhecido.",
    "no_timer":     "Nenhum timer ativo no momento.",
    "listening":    "Ouvindo.",
    "ready":        "ShutdownTimer pronto para comandos de voz.",
    "wake_detected":"Comando de voz detectado.",
}


# ─────────────────────────────────────────────────────────────────────────────
# VoiceCommandEngine
# ─────────────────────────────────────────────────────────────────────────────

class VoiceCommandEngine:
    """
    Background voice recognition + TTS feedback engine.

    Modes
    -----
    hands_free   — continuous listening thread (high CPU/battery)
    eco          — listens only while the app window has focus
    push_to_talk — activates for push_to_talk_duration seconds on hotkey

    Usage
    -----
    engine = VoiceCommandEngine(config, app_ref)
    engine.start()
    # … later …
    engine.stop()
    """

    PUSH_TO_TALK_DURATION = 5    # seconds mic stays open
    AMBIENT_NOISE_DURATION = 1   # seconds for calibration
    AUDIO_QUEUE_MAX = 20

    def __init__(self, config, app_ref):
        self._config   = config
        self._app      = app_ref          # ShutdownApp instance
        self._logger   = logging.getLogger("VoiceEngine")
        self._stop     = threading.Event()
        self._audio_q: queue.Queue = queue.Queue(maxsize=self.AUDIO_QUEUE_MAX)
        self._listen_thread: Optional[threading.Thread]  = None
        self._process_thread: Optional[threading.Thread] = None
        self._tts_lock = threading.Lock()

        # Mutable state
        self._ptt_active  = False
        self._ptt_timer:  Optional[threading.Timer] = None
        self._commands_today = 0
        self._last_command:  str = ""
        self._last_command_ts: str = ""

        # Status callback for UI
        self.on_status_change: Optional[Callable[[str, str], None]] = None
        # (command_key, text) callback when a command fires
        self.on_command: Optional[Callable[[str, str, Optional[int]], None]] = None

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the engine.  Returns False if speech_recognition not installed."""
        if not HAS_SPEECH:
            self._set_status("unavailable", "⚠ SpeechRecognition não instalado")
            return False
        if self._listen_thread and self._listen_thread.is_alive():
            return True   # already running

        self._stop.clear()
        self._listen_thread  = threading.Thread(
            target=self._listen_loop,  daemon=True, name="VoiceListen")
        self._process_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="VoiceProcess")
        self._listen_thread.start()
        self._process_thread.start()
        self._set_status("listening", "🟢 Ouvindo...")
        return True

    def stop(self):
        """Stop all threads."""
        self._stop.set()
        if self._ptt_timer:
            self._ptt_timer.cancel()
        # Unblock the queue consumer
        try:
            self._audio_q.put_nowait(None)
        except queue.Full:
            pass

    @property
    def is_running(self) -> bool:
        return (bool(self._listen_thread and self._listen_thread.is_alive())
                and not self._stop.is_set())

    def push_to_talk(self):
        """Activate microphone for PUSH_TO_TALK_DURATION seconds."""
        if not HAS_SPEECH:
            return
        if self._ptt_active:
            return
        self._ptt_active = True
        self._set_status("listening", "🎤 Push-to-talk ativo…")
        if self._ptt_timer:
            self._ptt_timer.cancel()
        self._ptt_timer = threading.Timer(
            self.PUSH_TO_TALK_DURATION, self._end_ptt)
        self._ptt_timer.daemon = True
        self._ptt_timer.start()

    def _end_ptt(self):
        self._ptt_active = False
        self._set_status("idle", "⚫ Push-to-talk inativo")

    def speak(self, text: str):
        """Speak text asynchronously (no-op if pyttsx3 absent)."""
        vc = self._get_vc_config()
        if not vc.get("tts_enabled", True) or not HAS_TTS:
            return
        threading.Thread(
            target=self._speak_sync, args=(text,), daemon=True).start()

    def test_microphone(self, callback: Callable[[str, float], None]):
        """
        Quick mic test. Calls callback(text, level) where:
          text  — recognised text or error description
          level — audio RMS level 0–1
        """
        if not HAS_SPEECH:
            callback("speech_recognition não instalado", 0.0)
            return
        threading.Thread(
            target=self._do_mic_test, args=(callback,), daemon=True).start()

    def get_mic_devices(self) -> List[dict]:
        """Return list of {'index': int, 'name': str} for available microphones."""
        if not HAS_PYAUDIO:
            return []
        try:
            import pyaudio
            pa    = pyaudio.PyAudio()
            mics  = []
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    mics.append({"index": i, "name": info["name"]})
            pa.terminate()
            return mics
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────
    # Listening thread
    # ─────────────────────────────────────────────────────────────

    def _listen_loop(self):
        recognizer  = sr.Recognizer()
        mic_index   = self._get_vc_config().get("microphone_index")
        mic_kwargs  = {"device_index": mic_index} if mic_index is not None else {}

        try:
            with sr.Microphone(**mic_kwargs) as source:
                recognizer.adjust_for_ambient_noise(
                    source, duration=self.AMBIENT_NOISE_DURATION)
        except Exception as e:
            self._logger.error(f"Mic init error: {e}")
            self._set_status("error", f"⚠ Erro no microfone: {e}")
            return

        while not self._stop.is_set():
            mode = self._get_vc_config().get("mode", "hands_free")

            # Eco mode: skip if app is not in focus
            if mode == "eco" and not self._is_app_focused():
                time.sleep(0.5)
                continue

            # Push-to-talk mode: only listen when ptt active
            if mode == "push_to_talk" and not self._ptt_active:
                time.sleep(0.2)
                continue

            try:
                with sr.Microphone(**mic_kwargs) as source:
                    audio = recognizer.listen(
                        source, timeout=1, phrase_time_limit=6)
                if not self._audio_q.full():
                    self._audio_q.put_nowait(audio)
            except sr.WaitTimeoutError:
                continue
            except Exception as e:
                self._logger.debug(f"Listen error: {e}")
                time.sleep(0.3)

    # ─────────────────────────────────────────────────────────────
    # Processing thread
    # ─────────────────────────────────────────────────────────────

    def _process_loop(self):
        recognizer = sr.Recognizer()
        while not self._stop.is_set():
            try:
                audio = self._audio_q.get(timeout=1.0)
                if audio is None:
                    break
                text = self._recognize(recognizer, audio)
                if text:
                    self._logger.debug(f"Recognised: {text!r}")
                    if self._check_wake_word(text):
                        command, minutes = self._extract_command(text)
                        if command:
                            self._dispatch(command, text, minutes)
                        else:
                            self.speak(_RESPONSES["not_found"])
            except queue.Empty:
                continue
            except Exception as e:
                self._logger.error(f"Process error: {e}")

    def _recognize(self, recognizer: "sr.Recognizer",
                   audio: "sr.AudioData") -> Optional[str]:
        """Try Google first; fall back to sphinx if offline."""
        try:
            return recognizer.recognize_google(audio, language="pt-BR")
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            try:
                return recognizer.recognize_sphinx(audio)
            except Exception:
                return None

    # ─────────────────────────────────────────────────────────────
    # Wake-word + command extraction
    # ─────────────────────────────────────────────────────────────

    def _check_wake_word(self, text: str) -> bool:
        text_low = text.lower()
        wake_words = self._get_vc_config().get(
            "wake_words", DEFAULT_WAKE_WORDS)
        return any(w.lower() in text_low for w in wake_words)

    def _extract_command(self, text: str) -> tuple:
        """Return (command_key, minutes_int_or_None)."""
        text_low = text.lower()
        for pattern, cmd in COMMAND_PATTERNS:
            m = pattern.search(text_low)
            if m:
                # Try to extract a numeric value from groups
                minutes: Optional[int] = None
                for g in m.groups():
                    if g and g.isdigit():
                        minutes = int(g)
                        break
                return cmd, minutes
        return None, None

    # ─────────────────────────────────────────────────────────────
    # Command dispatch → main thread
    # ─────────────────────────────────────────────────────────────

    def _dispatch(self, command: str, raw_text: str,
                  minutes: Optional[int]):
        """Route voice command to the app (must schedule on main thread)."""
        self._commands_today += 1
        self._last_command    = raw_text[:60]
        self._last_command_ts = datetime.now().strftime("%H:%M")

        app  = self._app
        eng  = getattr(app, "engine", None)
        # Capture in a name that _run() will never reassign
        _minutes_captured = minutes

        def _run():
            vc  = self._get_vc_config()
            tts = vc.get("tts_enabled", True)
            # Local mutable copy so we can default to 30 for start commands
            mins = _minutes_captured

            if command == "cancel":
                if eng and eng.is_running:
                    app._cancel()
                    if tts: self.speak(_RESPONSES["cancel"])
                else:
                    if tts: self.speak(_RESPONSES["no_timer"])

            elif command == "pause":
                if eng and eng.is_running:
                    app._pause_resume()
                    if tts: self.speak(_RESPONSES["pause"])

            elif command == "resume":
                if eng and eng.is_running:
                    app._pause_resume()
                    if tts: self.speak(_RESPONSES["resume"])

            elif command == "status":
                if eng and eng.is_running:
                    rem = eng.state.remaining // 60
                    if tts:
                        self.speak(_RESPONSES["status"].format(remaining=rem))
                else:
                    if tts: self.speak(_RESPONSES["no_timer"])

            elif command == "extend":
                if eng and eng.is_running and mins:
                    eng.extend(mins * 60)
                    if tts:
                        self.speak(_RESPONSES["extend"].format(minutes=mins))

            elif command in ("start_timer", "shutdown_in", "suspend_in",
                             "reboot_in"):
                action_map = {
                    "start_timer": None,  # use current action
                    "shutdown_in": "shutdown",
                    "suspend_in":  "suspend",
                    "reboot_in":   "reboot",
                }
                action = action_map[command]
                if not eng or eng.is_running:
                    if tts: self.speak(
                        "Timer já ativo." if eng and eng.is_running
                        else _RESPONSES["no_timer"])
                    return
                if mins is None:
                    mins = 30
                if action:
                    app._select_action(action)
                app.time_var.set(str(mins))
                app._set_mode("countdown")
                app._start()
                resp_key = command if command in _RESPONSES else "start_timer"
                if tts:
                    self.speak(
                        _RESPONSES[resp_key].format(minutes=mins))

            # Notify UI
            if self.on_command:
                self.on_command(command, raw_text, mins)
            self._set_status(
                "listening",
                f"🟢 Ouvindo... | último: «{self._last_command}»")

        # Schedule on tk main loop
        try:
            app.root.after(0, _run)
        except Exception as e:
            self._logger.error(f"Dispatch error: {e}")

    # ─────────────────────────────────────────────────────────────
    # TTS helper
    # ─────────────────────────────────────────────────────────────

    def _speak_sync(self, text: str):
        with self._tts_lock:
            try:
                vc     = self._get_vc_config()
                engine = pyttsx3.init()
                voices = engine.getProperty("voices")
                gender = vc.get("tts_voice", "female")
                if gender == "female" and len(voices) > 1:
                    engine.setProperty("voice", voices[1].id)
                elif gender == "male" and voices:
                    engine.setProperty("voice", voices[0].id)
                engine.setProperty("rate", vc.get("tts_rate", 180))
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception as e:
                self._logger.error(f"TTS error: {e}")

    # ─────────────────────────────────────────────────────────────
    # Microphone test
    # ─────────────────────────────────────────────────────────────

    def _do_mic_test(self, callback: Callable):
        try:
            recognizer = sr.Recognizer()
            mic_index  = self._get_vc_config().get("microphone_index")
            mic_kwargs = {"device_index": mic_index} if mic_index is not None else {}
            with sr.Microphone(**mic_kwargs) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)

            # Compute energy level
            level = min(1.0, recognizer.energy_threshold / 4000.0)

            # Recognise
            try:
                text = recognizer.recognize_google(audio, language="pt-BR")
            except sr.UnknownValueError:
                text = "(não entendido)"
            except sr.RequestError:
                text = "(sem internet — reconhecimento offline)"
            callback(text, level)
        except Exception as e:
            callback(f"Erro: {e}", 0.0)

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────

    def _get_vc_config(self) -> dict:
        cfg = self._config.get("voice_commands") or {}
        return cfg

    def _set_status(self, state: str, message: str):
        if self.on_status_change:
            try:
                self.on_status_change(state, message)
            except Exception:
                pass

    def _is_app_focused(self) -> bool:
        """True if the ShutdownTimer window is the active window."""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            app_hwnd = int(self._app.root.winfo_id())
            # Compare top-level window
            import ctypes.wintypes
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            return "ShutdownTimer" in buf.value
        except Exception:
            return True  # safe default
