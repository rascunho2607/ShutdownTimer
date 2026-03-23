"""
ProcessSelector — janela de seleção de processos do sistema.
"""

from config.app_imports import (
    tk, ctk, time,
    Callable, Dict, List, Optional,
    HAS_PSUTIL,
)
from core.system_controller import SystemController
from ui.ui_helpers import COLORS


# ══════════════════════════════════════════════════════════════
# 9. PROCESS SELECTOR  (Gerenciador de Processos)
# ══════════════════════════════════════════════════════════════

class ProcessSelector(ctk.CTkToplevel):
    """
    Janela de seleção de processos com duas abas:
      - 🖥 Aplicativos  (processos com janela visível)
      - ⚙  Processos   (todos os processos)
    """

    _proc_cache: list = []
    _cache_ts: float  = 0
    _CACHE_TTL        = 5.0

    def __init__(self, parent, selected_processes: Optional[List[str]] = None,
                 callback: Optional[Callable[[List[str]], None]] = None):
        super().__init__(parent)
        self.title("Gerenciador de Processos")
        self.geometry("720x520")
        self.configure(fg_color=COLORS["bg"])
        self.resizable(True, True)
        self.grab_set()

        self.selected    = list(selected_processes or [])
        self.callback    = callback
        self._check_vars: Dict[str, tk.BooleanVar] = {}

        self._build()
        self._load_processes()

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="⚙  Selecionar Processos",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left", padx=16)
        self._count_lbl = ctk.CTkLabel(hdr, text="",
                                       font=ctk.CTkFont(size=12),
                                       text_color=COLORS["accent"])
        self._count_lbl.pack(side="right", padx=16)

        # Tabview
        self.tabview = ctk.CTkTabview(self, fg_color=COLORS["bg"],
                                      segmented_button_fg_color=COLORS["surface"],
                                      segmented_button_selected_color=COLORS["accent"],
                                      segmented_button_unselected_color=COLORS["surface2"])
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        self._tab_apps  = self.tabview.add("🖥  Aplicativos")
        self._tab_procs = self.tabview.add("⚙  Processos")

        self._list_apps  = self._build_tab(self._tab_apps,  "apps")
        self._list_procs = self._build_tab(self._tab_procs, "procs")

        # Bottom bar
        btm = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=52)
        btm.pack(fill="x"); btm.pack_propagate(False)
        ctk.CTkButton(btm, text="✓  Confirmar", width=120, height=34,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      corner_radius=8, command=self._confirm
                      ).pack(side="right", padx=12, pady=9)
        ctk.CTkButton(btm, text="Cancelar", width=90, height=34,
                      font=ctk.CTkFont(size=13),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=8, command=self.destroy
                      ).pack(side="right", padx=(0, 6), pady=9)
        ctk.CTkButton(btm, text="↻  Atualizar", width=100, height=34,
                      font=ctk.CTkFont(size=12),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=8, command=self._load_processes
                      ).pack(side="left", padx=12, pady=9)

    def _build_tab(self, parent, tag: str) -> ctk.CTkScrollableFrame:
        search_var = tk.StringVar()
        search = ctk.CTkEntry(parent, textvariable=search_var,
                              placeholder_text="🔍  Buscar processo...",
                              height=34, font=ctk.CTkFont(size=12),
                              fg_color=COLORS["surface2"], border_color=COLORS["border"],
                              corner_radius=8, text_color=COLORS["text"])
        search.pack(fill="x", padx=8, pady=(8, 4))

        # Column headers
        cols = ctk.CTkFrame(parent, fg_color=COLORS["surface2"], corner_radius=6, height=28)
        cols.pack(fill="x", padx=8, pady=(0, 4)); cols.pack_propagate(False)
        for txt, w in [("✓", 32), ("Processo", 200), ("Janela / Status", 180),
                       ("CPU%", 60), ("Mem MB", 70)]:
            ctk.CTkLabel(cols, text=txt, width=w, font=ctk.CTkFont(size=10),
                         text_color=COLORS["text_dim2"], anchor="w"
                         ).pack(side="left", padx=4)

        frame = ctk.CTkScrollableFrame(parent, fg_color=COLORS["bg"],
                                       scrollbar_button_color=COLORS["surface2"])
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # Store refs for filtering
        setattr(self, f"_search_var_{tag}", search_var)
        setattr(self, f"_frame_{tag}", frame)
        search_var.trace_add("write",
            lambda *_: self._filter(tag))
        return frame

    def _load_processes(self):
        now = time.time()
        if now - self._cache_ts < self._CACHE_TTL and self._proc_cache:
            procs = self._proc_cache
        else:
            procs = SystemController.get_process_list()
            ProcessSelector._proc_cache = procs
            ProcessSelector._cache_ts   = now

        win_titles = SystemController.get_window_titles() if HAS_PSUTIL else {}
        self._all_procs  = procs
        self._win_titles = win_titles
        self._populate("apps",  [p for p in procs if p["name"] in win_titles])
        self._populate("procs", procs)
        self._update_count()

    def _populate(self, tag: str, procs: list):
        frame: ctk.CTkScrollableFrame = getattr(self, f"_frame_{tag}")
        for w in frame.winfo_children(): w.destroy()

        for p in procs:
            name   = p["name"]
            key    = name.lower()
            title  = self._win_titles.get(name, p.get("status", ""))

            row = ctk.CTkFrame(frame, fg_color=COLORS["surface"], corner_radius=6)
            row.pack(fill="x", pady=2)

            var = self._check_vars.setdefault(key, tk.BooleanVar(
                value=(name.lower() in [s.lower() for s in self.selected])))

            chk = ctk.CTkCheckBox(row, text="", variable=var, width=28,
                                  checkbox_width=16, checkbox_height=16,
                                  fg_color=COLORS["accent"],
                                  hover_color=COLORS["accent"],
                                  border_color=COLORS["border"],
                                  checkmark_color="white",
                                  command=self._update_count)
            chk.pack(side="left", padx=(6, 0))

            ctk.CTkLabel(row, text=name[:28], width=200,
                         font=ctk.CTkFont(size=12), anchor="w",
                         text_color=COLORS["text"]).pack(side="left", padx=4)
            ctk.CTkLabel(row, text=(title[:24] if title else "—"), width=180,
                         font=ctk.CTkFont(size=11), anchor="w",
                         text_color=COLORS["text_dim"]).pack(side="left", padx=4)
            ctk.CTkLabel(row, text=str(p["cpu"]), width=55,
                         font=ctk.CTkFont(size=11), anchor="center",
                         text_color=COLORS["text_dim"]).pack(side="left")
            ctk.CTkLabel(row, text=str(p["mem_mb"]), width=65,
                         font=ctk.CTkFont(size=11), anchor="center",
                         text_color=COLORS["text_dim"]).pack(side="left")

        setattr(self, f"_rows_{tag}", procs)

    def _filter(self, tag: str):
        query: str = getattr(self, f"_search_var_{tag}").get().lower()
        rows: list = getattr(self, f"_rows_{tag}", [])
        frame: ctk.CTkScrollableFrame = getattr(self, f"_frame_{tag}")
        for w in frame.winfo_children(): w.destroy()
        filtered = [p for p in rows if query in p["name"].lower()] if query else rows
        # re-use populate with filtered list
        old_rows = getattr(self, f"_rows_{tag}", [])
        setattr(self, f"_rows_{tag}", filtered)
        self._populate(tag, filtered)
        setattr(self, f"_rows_{tag}", old_rows)

    def _update_count(self):
        n = sum(1 for v in self._check_vars.values() if v.get())
        self._count_lbl.configure(
            text=f"{n} selecionado{'s' if n != 1 else ''}")

    def _confirm(self):
        selected = [name for name, var in self._check_vars.items() if var.get()]
        if self.callback:
            self.callback(selected)
        self.selected = selected
        self.destroy()
