"""
MiniWidget — widget flutuante compacto e arrastável.
"""

from config.app_imports import (
    tk,
    Callable, Optional,
)
from ui.ui_helpers import ACTION_ICONS


# ══════════════════════════════════════════════════════════════
# 11. MINI WIDGET
# ══════════════════════════════════════════════════════════════

class MiniWidget:
    def __init__(self, root, engine, config,
                 on_cancel: Callable, on_open: Callable):
        self._root, self._engine, self._config = root, engine, config
        self._on_cancel, self._on_open = on_cancel, on_open
        self._win = None
        self._dx = self._dy = 0

    def show(self):
        if self._win and self._win.winfo_exists():
            self._win.lift(); return
        self._win = tk.Toplevel(self._root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.92)
        self._win.configure(bg="#0d0f18")
        pos = self._config.get("mini_widget_pos") or [50, 50]
        self._win.geometry(f"160x48+{pos[0]}+{pos[1]}")

        frame = tk.Frame(self._win, bg="#161923", bd=0)
        frame.pack(fill="both", expand=True, padx=1, pady=1)

        self._ico = tk.Label(frame, text="⏻", font=("Segoe UI", 14),
                             bg="#161923", fg="#4f8ef7")
        self._ico.pack(side="left", padx=(8, 2), pady=8)

        self._lbl = tk.Label(frame, text="--:--",
                             font=("Courier New", 15, "bold"),
                             bg="#161923", fg="#e8eaf6")
        self._lbl.pack(side="left", pady=8)

        for w in (frame, self._lbl, self._ico):
            w.bind("<ButtonPress-1>",   self._ds)
            w.bind("<B1-Motion>",       self._dm)
            w.bind("<ButtonRelease-1>", self._de)
        self._ico.bind("<Double-Button-1>", lambda e: self._on_open())

        menu = tk.Menu(self._win, tearoff=0, bg="#161923", fg="white",
                       activebackground="#4f8ef7")
        menu.add_command(label="Abrir",          command=self._on_open)
        menu.add_command(label="Cancelar timer", command=self._on_cancel)
        menu.add_separator()
        menu.add_command(label="Fechar widget",  command=self.hide)
        self._win.bind("<Button-3>",
                       lambda e: menu.tk_popup(e.x_root, e.y_root))
        self.update()

    def hide(self):
        if self._win and self._win.winfo_exists():
            self._config.set("mini_widget_pos",
                             [self._win.winfo_x(), self._win.winfo_y()])
            self._win.destroy(); self._win = None

    def update(self):
        if not self._win or not self._win.winfo_exists(): return
        s = self._engine.state
        if s.running:
            h   = s.remaining // 3600
            m   = (s.remaining % 3600) // 60
            sec = s.remaining % 60
            txt   = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
            icon  = ACTION_ICONS.get(s.action, "⏻")
            color = ("#f75a5a" if s.remaining <= 60 else
                     "#f7a94f" if s.remaining <= 300 else "#e8eaf6")
            self._lbl.configure(text=txt,  fg=color)
            self._ico.configure(text=icon, fg=color)
        else:
            self._lbl.configure(text="--:--", fg="#7b82a8")
            self._ico.configure(text="⏻",    fg="#4f8ef7")

    def is_visible(self):
        return bool(self._win and self._win.winfo_exists())

    def _ds(self, e): self._dx, self._dy = e.x_root, e.y_root
    def _dm(self, e):
        if not self._win: return
        dx = e.x_root - self._dx; dy = e.y_root - self._dy
        x = self._win.winfo_x() + dx; y = self._win.winfo_y() + dy
        self._win.geometry(f"+{x}+{y}"); self._dx, self._dy = e.x_root, e.y_root
    def _de(self, e):
        if self._win:
            self._config.set("mini_widget_pos",
                             [self._win.winfo_x(), self._win.winfo_y()])
