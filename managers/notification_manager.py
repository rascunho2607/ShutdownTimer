"""
NotificationManager — notificações nativas com beeps opcionais.
"""

from config.app_imports import (
    threading, time,
    HAS_PLYER, plyer_notify,
)
from core.system_controller import SystemController


# ══════════════════════════════════════════════════════════════
# 6. NOTIFICATION MANAGER
# ══════════════════════════════════════════════════════════════

class NotificationManager:
    """Notificações inteligentes: beeps opcionais, plyer sempre que disponível."""

    @staticmethod
    def send(title: str, message: str, timeout: int = 8):
        """Envia notificação nativa. Funciona mesmo com app minimizado."""
        if HAS_PLYER:
            try:
                plyer_notify.notify(title=title, message=message,
                                    app_name="ShutdownTimer", timeout=timeout)
                return
            except Exception as e:
                print(f"[Notify] plyer: {e}")

    @staticmethod
    def notify_only(title: str, message: str):
        """Somente notificação visual, sem beeps."""
        NotificationManager.send(title, message)

    @staticmethod
    def play_beeps():
        def _do():
            try:
                if SystemController.PLATFORM == "Windows":
                    import winsound
                    for freq, dur in [(880,250),(1100,250),(880,250),(1100,400)]:
                        winsound.Beep(freq, dur); time.sleep(0.1)
                else:
                    for _ in range(5): print("\a", end="", flush=True); time.sleep(0.4)
            except Exception as e: print(f"[Sound] {e}")
        threading.Thread(target=_do, daemon=True).start()

    @classmethod
    def warn(cls, title: str, message: str, sound: bool = False):
        """Envia notificação. Se sound=True, adiciona beeps."""
        cls.send(title, message)
        if sound:
            cls.play_beeps()
