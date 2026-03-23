"""
UI Helpers — Tooltip, add_tooltip, e constantes de temas/cores/ações.
"""

from config.app_imports import (
    tk,
    Optional,
)


# ══════════════════════════════════════════════════════════════
# 5B. TOOLTIP
# ══════════════════════════════════════════════════════════════

class Tooltip:
    """
    Tooltip reutilizável para widgets tkinter/customtkinter.
    Aparece após 500 ms de hover e desaparece ao mover o cursor.

    Uso:
        Tooltip(widget, "Texto do tooltip")
    """

    _DELAY_MS   = 500
    _BG         = "#1e2235"
    _FG         = "#c8cfe8"
    _BORDER     = "#4f8ef7"
    _FONT       = ("Segoe UI", 10)
    _MAX_WIDTH  = 260   # pixels

    def __init__(self, widget: tk.BaseWidget, text: str):
        self._widget  = widget
        self._text    = text
        self._win:    Optional[tk.Toplevel] = None
        self._job:    Optional[str]         = None

        widget.bind("<Enter>",   self._on_enter,  add="+")
        widget.bind("<Leave>",   self._on_leave,  add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_enter(self, _event=None):
        self._cancel()
        self._job = self._widget.after(self._DELAY_MS, self._show)

    def _on_leave(self, _event=None):
        self._cancel()
        self._hide()

    def _on_destroy(self, _event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._job:
            try: self._widget.after_cancel(self._job)
            except Exception: pass
            self._job = None

    def _show(self):
        if self._win: return
        x = self._widget.winfo_rootx() + 8
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4

        self._win = tk.Toplevel(self._widget)
        self._win.wm_overrideredirect(True)
        self._win.wm_geometry(f"+{x}+{y}")
        self._win.attributes("-topmost", True)

        # Outer border frame
        outer = tk.Frame(self._win, bg=self._BORDER, bd=0)
        outer.pack(ipadx=1, ipady=1)

        inner = tk.Frame(outer, bg=self._BG, bd=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        lbl = tk.Label(
            inner, text=self._text,
            font=self._FONT,
            bg=self._BG, fg=self._FG,
            justify="left", wraplength=self._MAX_WIDTH,
            padx=10, pady=6)
        lbl.pack()

    def _hide(self):
        if self._win:
            try: self._win.destroy()
            except Exception: pass
            self._win = None


def add_tooltip(widget: tk.BaseWidget, text: str) -> "Tooltip":
    """Função helper de conveniência: cria e retorna um Tooltip."""
    return Tooltip(widget, text)


# ══════════════════════════════════════════════════════════════
# 10. CONSTANTS
# ══════════════════════════════════════════════════════════════

THEMES = {
    "dark": {
        "bg":           "#0d0f18",
        "surface":      "#161923",
        "surface2":     "#1e2235",
        "surface3":     "#252a40",
        "accent":       "#4f8ef7",
        "accent_hover": "#3a7aee",
        "accent2":      "#7c5cf7",
        "danger":       "#f75a5a",
        "warning":      "#f7a94f",
        "success":      "#4ff78e",
        "text":         "#e8eaf6",
        "text_dim":     "#7b82a8",
        "text_dim2":    "#4a5070",
        "border":       "#2a2f4a",
    },
    "light": {
        "bg":           "#f8fafc",
        "surface":      "#ffffff",
        "surface2":     "#f1f5f9",
        "surface3":     "#e2e8f0",
        "accent":       "#2563eb",
        "accent_hover": "#1d4ed8",
        "accent2":      "#7c3aed",
        "danger":       "#dc2626",
        "warning":      "#f59e0b",
        "success":      "#10b981",
        "text":         "#0f172a",
        "text_dim":     "#475569",
        "text_dim2":    "#64748b",
        "border":       "#cbd5e1",
    },
}

COLORS = dict(THEMES["dark"])

ACTION_ICONS  = {
    "shutdown": "⏻", "suspend": "🌙", "reboot": "↺", "lock": "🔒"}
ACTION_LABELS = {
    "shutdown": "Desligar", "suspend": "Suspender",
    "reboot":   "Reiniciar",  "lock":   "Bloquear"}

DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
