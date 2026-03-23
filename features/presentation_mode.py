"""
PresentationMode — detecta apresentações e pausa/notifica timers ativos.
"""

from config.app_imports import (
    threading,
    Callable, Optional,
    HAS_PSUTIL, psutil,
)
from core.system_controller import SystemController


# ══════════════════════════════════════════════════════════════
# 5C. PRESENTATION MODE
# ══════════════════════════════════════════════════════════════

class PresentationMode:
    """
    Detects when the computer is being used for presentations and
    pauses/notifies about active timers.

    Triggers: PowerPoint slideshow, external monitor, videoconference apps,
    custom process list.
    """

    POLL = 10  # seconds between checks

    VIDEOCONF_APPS = {
        "zoom.exe", "teams.exe", "slack.exe", "webex.exe",
        "skype.exe", "meet.exe", "discord.exe",
    }

    def __init__(self, config):
        self._config = config
        self._stop   = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.on_activated:   Optional[Callable[[], None]] = None
        self.on_deactivated: Optional[Callable[[], None]] = None

    # ── Public API ────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def is_enabled(self) -> bool:
        pm = self._config.get("presentation_mode") or {}
        return bool(pm.get("enabled", False))

    def is_presentation_active(self) -> bool:
        pm = self._config.get("presentation_mode") or {}
        triggers = pm.get("triggers", {})

        if triggers.get("powerpoint", True) and self._check_powerpoint():
            return True
        if triggers.get("external_monitor", True) and self._check_external_monitor():
            return True
        if triggers.get("videoconf", True) and self._check_videoconference():
            return True
        if self._check_custom_apps(pm.get("custom_apps", [])):
            return True
        return False

    def test_detection(self) -> dict:
        """Run detection immediately and return which triggers fired."""
        pm = self._config.get("presentation_mode") or {}
        triggers = pm.get("triggers", {})
        return {
            "powerpoint":       self._check_powerpoint()      if triggers.get("powerpoint", True) else False,
            "external_monitor": self._check_external_monitor() if triggers.get("external_monitor", True) else False,
            "videoconf":        self._check_videoconference() if triggers.get("videoconf", True) else False,
            "custom_apps":      self._check_custom_apps(pm.get("custom_apps", [])),
        }

    # ── Detection methods ─────────────────────────────────

    @staticmethod
    def _check_powerpoint() -> bool:
        if not HAS_PSUTIL:
            return False
        for proc in psutil.process_iter(["name"]):
            try:
                if "powerpnt" in proc.info["name"].lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    @staticmethod
    def _check_external_monitor() -> bool:
        if SystemController.PLATFORM == "Windows":
            try:
                import ctypes
                return ctypes.windll.user32.GetSystemMetrics(80) > 1  # SM_CMONITORS
            except Exception:
                pass
        return False

    @staticmethod
    def _check_videoconference() -> bool:
        if not HAS_PSUTIL:
            return False
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"].lower() in PresentationMode.VIDEOCONF_APPS:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    @staticmethod
    def _check_custom_apps(apps: list) -> bool:
        if not HAS_PSUTIL or not apps:
            return False
        names = {a.strip().lower() for a in apps if a.strip()}
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"].lower() in names:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    # ── Background loop ───────────────────────────────────

    def _run(self):
        was_active = False
        while not self._stop.wait(self.POLL):
            try:
                if not self.is_enabled:
                    was_active = False
                    continue
                is_active = self.is_presentation_active()
                if is_active and not was_active:
                    was_active = True
                    if self.on_activated:
                        self.on_activated()
                elif not is_active and was_active:
                    was_active = False
                    if self.on_deactivated:
                        self.on_deactivated()
            except Exception as e:
                print(f"[PresentationMode] {e}")
