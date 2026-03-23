"""
HotkeyManager — atalhos de teclado globais.
"""

from config.app_imports import (
    HAS_KEYBOARD, keyboard,
)
from config.config_manager import ConfigManager


# ══════════════════════════════════════════════════════════════
# 8. HOTKEY MANAGER
# ══════════════════════════════════════════════════════════════

class HotkeyManager:
    def __init__(self): self._enabled = False

    def setup(self, cfg: ConfigManager, app):
        self.clear()
        if not HAS_KEYBOARD or not cfg.get("hotkeys_enabled"): return
        try:
            keyboard.add_hotkey(cfg.get("hotkey_start"),
                                lambda: app.root.after(0, app._hotkey_start))
            keyboard.add_hotkey(cfg.get("hotkey_cancel"),
                                lambda: app.root.after(0, app._cancel))
            keyboard.add_hotkey(cfg.get("hotkey_widget"),
                                lambda: app.root.after(0, app._toggle_mini_widget))
            self._enabled = True
        except Exception as e: print(f"[Hotkeys] {e}")

    def clear(self):
        if HAS_KEYBOARD and self._enabled:
            try: keyboard.unhook_all_hotkeys()
            except Exception: pass
        self._enabled = False
