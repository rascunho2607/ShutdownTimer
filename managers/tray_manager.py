"""
TrayManager — ícone na bandeja do sistema com duplo clique para reabrir janela.
"""

from config.app_imports import (
    threading,
    Optional,
    HAS_TRAY, pystray, Image, ImageDraw,
)


# ══════════════════════════════════════════════════════════════
# 7. TRAY MANAGER  (duplo clique reabre janela)
# ══════════════════════════════════════════════════════════════

class TrayManager:
    SZ = 64

    def __init__(self, app_ref):
        self._app  = app_ref
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    def _make_icon(self, active: bool) -> "Image.Image":
        img  = Image.new("RGBA", (self.SZ, self.SZ), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        bg   = "#4f8ef7" if active else "#1e2235"
        fg   = "white"   if active else "#7b82a8"
        draw.ellipse([2, 2, self.SZ-2, self.SZ-2], fill=bg)
        cx, cy, r = self.SZ//2, self.SZ//2, 16
        draw.arc([cx-r, cy-r, cx+r, cy+r], start=40, end=320, fill=fg, width=5)
        draw.line([cx, cy-r, cx, cy-4], fill=fg, width=5)
        return img

    def start(self):
        if not HAS_TRAY or self._icon: return
        menu = pystray.Menu(
            pystray.MenuItem("⏻  ShutdownTimer", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Abrir janela",
                lambda: self._app.root.after(0, self._show_window),
                default=True),      # ← item default = duplo clique
            pystray.MenuItem(
                "⧉  Widget compacto",
                lambda: self._app.root.after(0, self._app._toggle_mini_widget)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "▶ Shutdown 30min",
                lambda: self._app.root.after(0, self._quick, "shutdown", 30)),
            pystray.MenuItem(
                "▶ Shutdown 1h",
                lambda: self._app.root.after(0, self._quick, "shutdown", 60)),
            pystray.MenuItem(
                "▶ Suspender 30min",
                lambda: self._app.root.after(0, self._quick, "suspend", 30)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "⏹ Cancelar timer",
                lambda: self._app.root.after(0, self._app._cancel),
                enabled=lambda item: self._app.engine.is_running),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "✕ Sair",
                lambda: self._app.root.after(0, self._app._quit_app)),
        )
        self._icon = pystray.Icon(
            "ShutdownTimer",
            icon=self._make_icon(False),
            title="ShutdownTimer",
            menu=menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._icon:
            try: self._icon.stop()
            except Exception: pass
            self._icon = None

    def update(self, active: bool, remaining_s: int = 0):
        if not self._icon: return
        try:
            self._icon.icon = self._make_icon(active)
            if active:
                h, m = divmod(remaining_s // 60, 60)
                s    = remaining_s % 60
                t = f"{h}h{m:02d}m" if h else f"{m:02d}:{s:02d}"
                self._icon.title = f"ShutdownTimer — {t}"
            else:
                self._icon.title = "ShutdownTimer"
        except Exception: pass

    def _show_window(self):
        self._app.root.deiconify()
        self._app.root.lift()
        self._app.root.focus_force()

    def _quick(self, action: str, minutes: int):
        if self._app.engine.is_running: return
        self._app.time_var.set(str(minutes))
        self._app._select_action(action)
        self._app._start()
        self._show_window()
