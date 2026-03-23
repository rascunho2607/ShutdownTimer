from config.app_imports import (
    os, sys, json, csv, threading, subprocess, time, uuid,
    Path, datetime, timedelta,
    Any, Callable, Dict, List, Optional,
    tk, ctk, messagebox, filedialog,
    HAS_TRAY, HAS_PLYER, HAS_PSUTIL, HAS_KEYBOARD, HAS_MATPLOTLIB,
    HAS_PIL_SHARE, HAS_CRYPTO,
    HAS_VOICE, VoiceCommandEngine,
    HAS_EMAIL, EmailNotifier, EMAIL_PROVIDERS,
    HAS_ENERGY, EnergySaver, get_available_plans,
    HAS_CALENDAR, CalendarManager, BrasilAPISource, ICSSource,
    GoogleCalendarSource, BRASIL_STATES, HAS_GOOGLE_CAL, HAS_REQUESTS, HAS_ICALENDAR,
    HAS_PLUGINS, PluginManager, STORE_CATALOG, STORE_CATEGORIES, PERMISSION_LABELS,
    HAS_PRES_ENHANCED, PresentationModeEnhanced, PresentationDecider, DEFAULT_WEIGHTS,
)
try:
    from config.app_imports import FigureCanvasTkAgg, plt
except ImportError:
    FigureCanvasTkAgg = None
    plt = None
from core.system_controller import SystemController
from core.timer_engine import TimerState, TimerEngine, Condition, ConditionMonitor, ScheduledAction, SchedulerMonitor
from core.smart_engine import SmartModeEngine
from ui.ui_helpers import Tooltip, add_tooltip, THEMES, COLORS, ACTION_ICONS, ACTION_LABELS, DAYS_PT
from config.config_manager import ConfigManager
from managers.notification_manager import NotificationManager
from managers.tray_manager import TrayManager
from managers.hotkey_manager import HotkeyManager
from ui.process_selector import ProcessSelector
from features.presentation_mode import PresentationMode
from features.share_generator import ShareGenerator
from ui.plugin_windows import PluginSettingsWindow, PluginUIWindow
from ui.mini_widget import MiniWidget

class ShutdownApp:
    """Interface principal com 5 abas: Timer · Programação · Condicional · Relatórios · Opções"""

    def __init__(self, root: ctk.CTk):
        self.root       = root
        self.config     = ConfigManager()
        self.engine     = TimerEngine()
        self.cond_mon   = ConditionMonitor()
        self.scheduler  = SchedulerMonitor()
        self.smart      = SmartModeEngine()
        self.notif      = NotificationManager()
        self.tray       = TrayManager(self)
        self.hotkeys    = HotkeyManager()
        self.presentation = PresentationMode(self.config)
        self.share      = ShareGenerator(self.config)
        self.mini: Optional[MiniWidget] = None

        # ── Feature 3.x: New Ecosystem Modules ───────────────────
        # Feature 3.3 — Presentation Mode Enhanced
        if HAS_PRES_ENHANCED:
            self.pres_enhanced: Optional[PresentationModeEnhanced] = \
                PresentationModeEnhanced(self.config)
        else:
            self.pres_enhanced = None

        # Feature 3.2 — Calendar Integration
        if HAS_CALENDAR:
            self.calendar_mgr: Optional[CalendarManager] = \
                CalendarManager(self.config)
        else:
            self.calendar_mgr = None

        # Feature 3.1 — Plugin Manager
        if HAS_PLUGINS:
            self.plugin_mgr: Optional[PluginManager] = \
                PluginManager(self)
        else:
            self.plugin_mgr = None

        # ── Feature modules ───────────────────────────────────────
        self.voice: Optional["VoiceCommandEngine"] = (
            VoiceCommandEngine(self.config, self) if HAS_VOICE else None)
        self.email_notif: Optional["EmailNotifier"] = (
            EmailNotifier(self.config) if HAS_EMAIL else None)
        self.energy: Optional["EnergySaver"] = (
            EnergySaver(self.config) if HAS_ENERGY else None)

        self._gamer_id:     Optional[str] = None
        self._countdown_id: Optional[str] = None
        self._widget_tick:  Optional[str] = None
        self._cond_active = False
        self._sched_actions: List[ScheduledAction] = []
        self._presentation_active = False

        self._setup_callbacks()
        self._build_window()
        self._build_ui()
        self._apply_config()
        self._auto_add_plugin_tabs()   # ← abas de plugins já carregados

        self.tray.start()
        self.hotkeys.setup(self.config, self)
        self.mini = MiniWidget(self.root, self.engine, self.config,
                               on_cancel=self._cancel,
                               on_open=self._show_window)
        self._widget_loop()

        # Start scheduler
        self._sched_actions = self.config.get_scheduled_actions()
        self.scheduler.start(lambda: self._sched_actions)

        # Start Smart Mode if previously enabled
        if self.config.get("smart_mode"):
            self._apply_smart_config()
            self.smart.start()

        # Start Presentation Mode if previously enabled
        pm_cfg = self.config.get("presentation_mode") or {}
        if pm_cfg.get("enabled", False):
            if self.pres_enhanced:
                self.pres_enhanced.start()
            else:
                self.presentation.start()

        # Start Presentation check loop
        self._presentation_loop()

        # Auto-start Voice Commands if previously enabled
        vc_cfg = self.config.get("voice_commands") or {}
        if vc_cfg.get("enabled", False) and self.voice:
            self.voice.start()

    # ── Callbacks ─────────────────────────────────────────

    def _setup_callbacks(self):
        after = self.root.after
        self.engine.on_tick      = lambda s: after(0, self._on_tick,      s)
        self.engine.on_finished  = lambda:   after(0, self._on_finished)
        self.engine.on_cancelled = lambda:   after(0, self._on_cancelled)
        self.engine.on_warning   = lambda s: after(0, self._on_warning,   s)
        self.engine.on_paused    = lambda p: after(0, self._on_paused,    p)
        self.cond_mon.on_condition_met = lambda a, d: after(
            0, self._on_condition_met, a, d)
        self.scheduler.on_fire = lambda sa: after(0, self._on_scheduled_fire, sa)
        self.smart.on_action     = lambda a, r: after(0, self._on_smart_action,     a, r)
        self.smart.on_suggestion = lambda k, m: after(0, self._on_smart_suggestion, k, m)
        self.smart.on_status     = lambda s:    after(0, self._on_smart_status,     s)

        # ── Feature module callbacks ───────────────────────────────
        if self.voice:
            self.voice.on_status_change = lambda state, msg: after(
                0, self._on_voice_status, state, msg)
            self.voice.on_command = lambda cmd, txt, mins: after(
                0, self._on_voice_command, cmd, txt, mins)
        if self.energy:
            self.energy.on_plan_change = lambda key, reason: after(
                0, self._on_energy_plan_change, key, reason)
            self.energy.on_message = lambda msg: after(
                0, self._on_energy_message, msg)

        # ── Plugin Manager callbacks ───────────────────────────────
        if self.plugin_mgr:
            self.plugin_mgr.on_plugin_loaded   = lambda pid: after(
                0, self._on_plugin_loaded_ui, pid)
            self.plugin_mgr.on_plugin_unloaded = lambda pid: after(
                0, self._on_plugin_unloaded_ui, pid)

    # ── Janela ────────────────────────────────────────────

    def _build_window(self):
        theme = self.config.get("theme") or "dark"
        ctk_mode = "Light" if theme == "light" else "Dark"
        if theme == "system":
            ctk_mode = "System"
        ctk.set_appearance_mode(ctk_mode)
        ctk.set_default_color_theme("blue")
        COLORS.update(THEMES.get(theme, THEMES["dark"]))
        W, H = 620, 720
        self.root.title("ShutdownTimer")
        self.root.geometry(f"{W}x{H}")
        self.root.resizable(True, False)
        self.root.minsize(540, 720)
        self.root.configure(fg_color=COLORS["bg"])
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - W) // 2
        y = (self.root.winfo_screenheight() - H) // 2
        self.root.geometry(f"{W}x{H}+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if HAS_TRAY:
            self.root.bind("<Unmap>", self._on_minimize)

    # ── Build UI ──────────────────────────────────────────

    def _build_ui(self):
        # ── Header ───────────────────────────────────────────
        hdr = ctk.CTkFrame(self.root, fg_color=COLORS["surface"],
                           corner_radius=0, height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        # Hamburger button (☰) — leftmost
        self._menu_open = False
        self._hamburger_btn = ctk.CTkButton(
            hdr, text="☰", width=40, height=36,
            font=ctk.CTkFont(size=20),
            fg_color="transparent", hover_color=COLORS["surface2"],
            text_color=COLORS["text"], corner_radius=6,
            command=self._toggle_sidebar)
        self._hamburger_btn.pack(side="left", padx=(8, 0))

        # Title — just after hamburger
        self._nav_title_lbl = ctk.CTkLabel(
            hdr, text="⏻  ShutdownTimer",
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
            text_color=COLORS["text"])
        self._nav_title_lbl.pack(side="left", padx=10)

        hdr_r = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_r.pack(side="right", padx=10)
        ctk.CTkButton(hdr_r, text="⧉", width=32, height=28,
                      font=ctk.CTkFont(size=14),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=6, text_color=COLORS["text_dim"],
                      command=self._toggle_mini_widget).pack(side="right", padx=2)
        ctk.CTkLabel(hdr, text=f"🖥  {SystemController.PLATFORM}",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="right", padx=4)

        # ── Body: sidebar overlay + content ──────────────────
        self._body = ctk.CTkFrame(self.root, fg_color=COLORS["bg"],
                                  corner_radius=0)
        self._body.pack(fill="both", expand=True)

        # Content area (full width, pages stacked with place())
        self._content = ctk.CTkFrame(self._body, fg_color=COLORS["bg"],
                                     corner_radius=0)
        self._content.pack(fill="both", expand=True)

        # Sidebar drawer container — plain tk.Frame so place(width=) works
        # CTkFrame is placed inside it and fills completely
        self._sidebar_container = tk.Frame(
            self._body, bg=COLORS["surface"], width=220)
        self._sidebar = ctk.CTkFrame(
            self._sidebar_container,
            fg_color=COLORS["surface"],
            corner_radius=0)
        self._sidebar.pack(fill="both", expand=True)
        # Don't place the container yet — shown via _open_sidebar()

        # Invisible overlay to dismiss sidebar on click-outside
        self._sidebar_overlay = tk.Frame(
            self._body, bg=COLORS["bg"], cursor="arrow")

        # ── Build pages (plain CTkFrame children of _content) ─
        self._pages: dict = {}
        self._page_order: list = []
        self._plugin_pages: dict = {}  # plugin_id -> (full_name, page_frame)

        nav_items = [
            ("timer",   "⏱",  "Timer"),
            ("sched",   "📅", "Programação"),
            ("cond",    "🎯", "Condicional"),
            ("report",  "📊", "Relatórios"),
            ("plugins", "🔌", "Plugins"),
            ("opts",    "⚙",  "Opções"),
        ]
        for key, icon, label in nav_items:
            page = ctk.CTkFrame(self._content, fg_color=COLORS["bg"],
                                corner_radius=0)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._pages[key] = page
            self._page_order.append((key, icon, label))

        # Assign legacy tab references expected by build methods
        self._tab_timer   = self._pages["timer"]
        self._tab_sched   = self._pages["sched"]
        self._tab_cond    = self._pages["cond"]
        self._tab_report  = self._pages["report"]
        self._tab_plugins = self._pages["plugins"]
        self._tab_opts    = self._pages["opts"]

        # Compat adapter for plugin tab methods that reference self.tabs
        self.tabs = self._TabsAdapter(self)

        # Build sidebar nav buttons list (populated in _build_sidebar)
        self._nav_buttons: dict = {}
        self._build_sidebar_nav()

        self._build_tab_timer()
        self._build_tab_scheduling()
        self._build_tab_conditional()
        self._build_tab_reports()
        self._build_tab_plugins()
        self._build_tab_options()

        # Show timer page first
        self._show_page("timer")

    # ── Sidebar helpers ───────────────────────────────────

    def _build_sidebar_nav(self):
        """Populates the sidebar with navigation buttons."""
        for w in self._sidebar.winfo_children():
            w.destroy()

        # Sidebar header
        hdr = ctk.CTkFrame(self._sidebar, fg_color=COLORS["surface2"],
                           corner_radius=0, height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="Menu",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=COLORS["text"]).pack(side="left", padx=16)
        ctk.CTkButton(hdr, text="✕", width=32, height=32,
                      font=ctk.CTkFont(size=13),
                      fg_color="transparent",
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"],
                      corner_radius=6,
                      command=self._close_sidebar).pack(side="right", padx=8)

        sep = ctk.CTkFrame(self._sidebar, fg_color=COLORS["border"],
                           height=1, corner_radius=0)
        sep.pack(fill="x")

        nav_frame = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        nav_frame.pack(fill="both", expand=True, padx=6, pady=8)

        self._nav_buttons = {}
        all_items = list(self._page_order)
        # Also include plugin pages
        for pid, (full_name, _page) in self._plugin_pages.items():
            icon_part = full_name.split("  ")[0] if "  " in full_name else "🔌"
            lbl_part  = full_name.split("  ", 1)[1] if "  " in full_name else full_name
            all_items.append((f"plugin_{pid}", icon_part, lbl_part))

        for key, icon, label in all_items:
            btn = ctk.CTkButton(
                nav_frame,
                text=f"{icon}  {label}",
                height=40, anchor="w",
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                hover_color=COLORS["surface2"],
                text_color=COLORS["text"],
                corner_radius=8,
                command=lambda k=key: self._nav_select(k))
            btn.pack(fill="x", pady=2)
            self._nav_buttons[key] = btn

    def _toggle_sidebar(self):
        if self._menu_open:
            self._close_sidebar()
        else:
            self._open_sidebar()

    def _open_sidebar(self):
        self._menu_open = True
        # Place overlay first (covers content, catches outside clicks)
        self._sidebar_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._sidebar_overlay.bind("<Button-1>", lambda e: self._close_sidebar())
        self._sidebar_overlay.lift()
        # Place sidebar container — tk.Frame accepts width= in place()
        self._sidebar_container.place(x=0, y=0, width=220, relheight=1)
        self._sidebar_container.lift()
        self._hamburger_btn.configure(text="✕")

    def _close_sidebar(self):
        self._menu_open = False
        self._sidebar_container.place_forget()
        self._sidebar_overlay.place_forget()
        self._hamburger_btn.configure(text="☰")

    def _nav_select(self, key: str):
        self._close_sidebar()
        if key.startswith("plugin_"):
            pid = key[len("plugin_"):]
            if pid in self._plugin_pages:
                self._plugin_pages[pid][1].lift()
            return
        self._show_page(key)

    def _show_page(self, key: str):
        """Raises the requested page to the top and updates header title."""
        if key not in self._pages:
            return
        self._pages[key].lift()
        # Update header title label
        for pk, icon, label in self._page_order:
            if pk == key:
                self._nav_title_lbl.configure(text=f"{icon}  {label}")
                break
        # Highlight active nav button
        for k, btn in self._nav_buttons.items():
            is_active = (k == key)
            btn.configure(
                fg_color=COLORS["accent"] if is_active else "transparent",
                text_color="white" if is_active else COLORS["text"])

    # ── Compat shim: self.tabs API used by plugin tab methods ─
    # Plugin methods call self.tabs.add / self.tabs.set / self.tabs.delete
    # We provide a thin adapter object instead.
    class _TabsAdapter:
        """Mimics the CTkTabview API used by plugin tab helpers."""
        def __init__(self, app: "ShutdownApp"):
            self._app = app
            self._tab_dict: dict = {}

        def add(self, full_name: str) -> ctk.CTkFrame:
            app = self._app
            page = ctk.CTkFrame(app._content, fg_color=COLORS["bg"],
                                corner_radius=0)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._tab_dict[full_name] = page
            # Register in plugin_pages dict (use full_name as key too)
            # We'll use full_name as pid proxy here
            app._plugin_pages[full_name] = (full_name, page)
            app._build_sidebar_nav()
            return page

        def set(self, full_name: str):
            app = self._app
            if full_name in self._tab_dict:
                self._tab_dict[full_name].lift()
                app._nav_title_lbl.configure(text=full_name)
            elif full_name in app._pages:
                app._show_page(full_name)

        def delete(self, full_name: str):
            app = self._app
            if full_name in self._tab_dict:
                self._tab_dict[full_name].destroy()
                del self._tab_dict[full_name]
            if full_name in app._plugin_pages:
                del app._plugin_pages[full_name]
            app._build_sidebar_nav()

    # ══════════════════════════════════════════════════════
    # ABA: TIMER
    # ══════════════════════════════════════════════════════

    def _build_tab_timer(self):
        scroll = ctk.CTkScrollableFrame(
            self._tab_timer, fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["surface2"],
            scrollbar_button_hover_color=COLORS["surface3"])
        scroll.pack(fill="both", expand=True)
        self._timer_body = scroll

        self._build_mode_selector(scroll)
        self._build_presets(scroll)
        self._build_time_input(scroll)
        self._build_action_selector(scroll)
        self._build_timer_display(scroll)
        self._build_timer_controls(scroll)

    def _build_mode_selector(self, parent):
        f = self._card(parent, "Modo")
        self.mode_var = ctk.StringVar(value=self.config.get("schedule_mode"))
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 14))
        self._mode_btns: dict = {}
        for key, lbl in [("countdown", "⏱  Contagem regressiva"),
                         ("schedule",  "🕐  Horário específico")]:
            btn = ctk.CTkButton(
                row, text=lbl, width=190, height=34,
                font=ctk.CTkFont(size=13), corner_radius=8,
                fg_color=COLORS["surface2"], hover_color=COLORS["accent"],
                text_color=COLORS["text"],
                command=lambda k=key: self._set_mode(k))
            btn.pack(side="left", padx=(0, 6))
            self._mode_btns[key] = btn

    def _build_presets(self, parent):
        f = self._card(parent, "Presets rápidos")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 14))
        for m in self.config.get("presets"):
            lbl = f"{m}min" if m < 60 else f"{m // 60}h"
            ctk.CTkButton(
                row, text=lbl, width=68, height=30,
                font=ctk.CTkFont(size=12), corner_radius=7,
                fg_color=COLORS["surface2"], hover_color=COLORS["accent"],
                text_color=COLORS["text"],
                command=lambda v=m: self._apply_preset(v)
            ).pack(side="left", padx=(0, 6))

    def _build_time_input(self, parent):
        f = self._card(parent, "")
        self._cd_frame = ctk.CTkFrame(f, fg_color="transparent")
        self._cd_frame.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(self._cd_frame, text="Tempo (minutos)",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(anchor="w", pady=(0, 6))
        self.time_var = tk.StringVar(value=str(self.config.get("last_minutes")))
        self.time_entry = ctk.CTkEntry(
            self._cd_frame, textvariable=self.time_var,
            placeholder_text="Ex: 30", height=44,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["text"], fg_color=COLORS["surface2"],
            border_color=COLORS["border"], corner_radius=8)
        self.time_entry.pack(fill="x", pady=(0, 4))
        self.time_entry.bind("<KeyRelease>", self._validate_live)

        self._sc_frame = ctk.CTkFrame(f, fg_color="transparent")
        ctk.CTkLabel(self._sc_frame, text="Executar às",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(anchor="w", pady=(0, 6))
        sr = ctk.CTkFrame(self._sc_frame, fg_color="transparent")
        sr.pack(fill="x")
        self.sched_h = tk.StringVar(value=str(self.config.get("schedule_hour")).zfill(2))
        self.sched_m = tk.StringVar(value=str(self.config.get("schedule_minute")).zfill(2))
        for var, ph in [(self.sched_h, "HH"), (self.sched_m, "MM")]:
            ctk.CTkEntry(sr, textvariable=var, placeholder_text=ph,
                         width=72, height=44,
                         font=ctk.CTkFont(size=22, weight="bold"),
                         text_color=COLORS["text"], fg_color=COLORS["surface2"],
                         border_color=COLORS["border"], corner_radius=8
                         ).pack(side="left", padx=(0, 6))
            if ph == "HH":
                ctk.CTkLabel(sr, text=":",
                             font=ctk.CTkFont(size=28, weight="bold"),
                             text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 6))
        self._sched_info = ctk.CTkLabel(self._sc_frame, text="",
                                        font=ctk.CTkFont(size=11),
                                        text_color=COLORS["text_dim"])
        self._sched_info.pack(anchor="w", pady=(4, 0))
        for v in (self.sched_h, self.sched_m):
            v.trace_add("write", lambda *_: self._update_sched_info())
        ctk.CTkFrame(f, fg_color="transparent", height=8).pack()

    def _build_action_selector(self, parent):
        f = self._card(parent, "Ação")
        self.action_var = ctk.StringVar(value=self.config.get("last_action"))
        grid = ctk.CTkFrame(f, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(14, 14))
        self._action_buttons: dict = {}
        for idx, (key, label) in enumerate(ACTION_LABELS.items()):
            btn = ctk.CTkButton(
                grid, text=f"{ACTION_ICONS[key]}  {label}",
                width=190, height=36, font=ctk.CTkFont(size=13), corner_radius=8,
                fg_color=COLORS["surface2"], hover_color=COLORS["accent"],
                text_color=COLORS["text"],
                command=lambda k=key: self._select_action(k))
            r, c = divmod(idx, 2)
            btn.grid(row=r, column=c,
                     padx=(0, 8) if c == 0 else 0,
                     pady=(0, 8) if r == 0 else 0)
            self._action_buttons[key] = btn

    def _build_timer_display(self, parent):
        f = self._card(parent, "")
        self.progress_bar = ctk.CTkProgressBar(
            f, height=6, fg_color=COLORS["surface2"],
            progress_color=COLORS["accent"], corner_radius=3)
        self.progress_bar.pack(fill="x", padx=16, pady=(14, 6))
        self.progress_bar.set(0)

        self.timer_label = ctk.CTkLabel(
            f, text="--:--",
            font=ctk.CTkFont("Courier New", 52, "bold"),
            text_color=COLORS["text_dim"])
        self.timer_label.pack()

        self.status_label = ctk.CTkLabel(
            f, text="Aguardando início",
            font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"])
        self.status_label.pack(pady=(2, 8))

        # +5 min button row
        row5 = ctk.CTkFrame(f, fg_color="transparent")
        row5.pack(fill="x", padx=16, pady=(0, 4))
        self.extend5_btn = ctk.CTkButton(
            row5, text="+5 min", width=80, height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
            text_color=COLORS["text_dim"], corner_radius=8, state="disabled",
            command=self._extend_5min)
        self.extend5_btn.pack(side="left")
        add_tooltip(self.extend5_btn,
            "Adiciona 5 minutos ao timer atual. "
            "Disponível apenas enquanto o timer estiver rodando.")
        ctk.CTkLabel(row5, text="estende o timer em 5 min",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left", padx=8)

        self.start_btn = ctk.CTkButton(
            f, text="▶  Iniciar", height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color="white", corner_radius=10,
            command=self._start_or_stop)
        self.start_btn.pack(fill="x", padx=16, pady=(2, 2))
        add_tooltip(self.start_btn,
            "Inicia o timer com o tempo e ação selecionados. "
            "Clique novamente para cancelar.")

        self.pause_btn = ctk.CTkButton(
            f, text="⏸  Pausar", height=36, font=ctk.CTkFont(size=13),
            fg_color=COLORS["surface"], hover_color=COLORS["surface2"],
            text_color=COLORS["text_dim"], corner_radius=8, state="disabled",
            command=self._pause_resume)
        self.pause_btn.pack(fill="x", padx=16, pady=(2, 14))
        add_tooltip(self.pause_btn,
            "Pausa ou retoma a contagem regressiva. "
            "O timer continua de onde parou.")

    def _build_timer_controls(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=(0, 20))
        w_btn = ctk.CTkButton(
            f, text="⧉  Widget flutuante", height=36,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["surface"], hover_color=COLORS["surface2"],
            text_color=COLORS["text_dim"], corner_radius=8,
            command=self._toggle_mini_widget)
        w_btn.pack(fill="x")
        add_tooltip(w_btn,
            "Exibe um mini-widget flutuante always-on-top com o timer. "
            "Arraste-o para qualquer posição. "
            "Clique com o botão direito para mais opções.")

    # ══════════════════════════════════════════════════════
    # ABA: PROGRAMAÇÃO
    # ══════════════════════════════════════════════════════

    def _build_tab_scheduling(self):
        top = ctk.CTkFrame(self._tab_sched, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(top, text="Ações programadas por dia da semana",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")
        ctk.CTkButton(top, text="➕  Nova", width=90, height=30,
                      font=ctk.CTkFont(size=12),
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      corner_radius=8, command=self._new_schedule
                      ).pack(side="right")

        self._sched_list_frame = ctk.CTkScrollableFrame(
            self._tab_sched, fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["surface2"])
        self._sched_list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._refresh_schedule_list()

    def _refresh_schedule_list(self):
        for w in self._sched_list_frame.winfo_children():
            w.destroy()
        actions = self._sched_actions
        if not actions:
            ctk.CTkLabel(self._sched_list_frame,
                         text="Nenhuma ação programada.\nClique em ➕ Nova para criar.",
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_dim2"]).pack(pady=40)
            return
        for sa in actions:
            self._sched_card(self._sched_list_frame, sa)

    def _sched_card(self, parent, sa: ScheduledAction):
        card = ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=10)
        card.pack(fill="x", pady=4, padx=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))

        en_var = ctk.BooleanVar(value=sa.enabled)
        ctk.CTkSwitch(top, text="", variable=en_var, width=40,
                      button_color=COLORS["accent"],
                      progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False,
                      command=lambda: self._toggle_schedule(sa, en_var.get())
                      ).pack(side="left")

        icon = ACTION_ICONS.get(sa.action, "⏻")
        label_txt = ACTION_LABELS.get(sa.action, sa.action)
        ctk.CTkLabel(top, text=f"{icon}  {sa.name}",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left", padx=8)
        ctk.CTkLabel(top, text=label_txt,
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(side="left")

        # Edit / Delete buttons
        ctk.CTkButton(top, text="✎", width=28, height=26,
                      font=ctk.CTkFont(size=12),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=6, text_color=COLORS["text_dim"],
                      command=lambda: self._edit_schedule(sa)
                      ).pack(side="right", padx=(4, 0))
        ctk.CTkButton(top, text="✕", width=28, height=26,
                      font=ctk.CTkFont(size=12),
                      fg_color=COLORS["surface2"], hover_color=COLORS["danger"],
                      corner_radius=6, text_color=COLORS["danger"],
                      command=lambda: self._delete_schedule(sa)
                      ).pack(side="right")

        # Days + time row
        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(0, 10))
        time_str = f"{sa.hour:02d}:{sa.minute:02d}"
        ctk.CTkLabel(bottom, text=f"🕐  {time_str}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["accent"]).pack(side="left", padx=(0, 12))
        for d in range(7):
            is_on = d in sa.days
            ctk.CTkLabel(bottom,
                         text=DAYS_PT[d],
                         width=32, height=22,
                         font=ctk.CTkFont(size=10),
                         corner_radius=5,
                         fg_color=COLORS["accent"] if is_on else COLORS["surface2"],
                         text_color="white" if is_on else COLORS["text_dim2"]
                         ).pack(side="left", padx=2)

        if sa.last_run:
            ts = sa.last_run[:16].replace("T", " ")
            ctk.CTkLabel(card, text=f"Última execução: {ts}",
                         font=ctk.CTkFont(size=10),
                         text_color=COLORS["text_dim2"]).pack(anchor="e", padx=12, pady=(0, 6))

    def _new_schedule(self):
        self._sched_form(None)

    def _edit_schedule(self, sa: ScheduledAction):
        self._sched_form(sa)

    def _sched_form(self, sa: Optional[ScheduledAction]):
        """Formulário de criação/edição de agendamento."""
        is_new = sa is None
        win = ctk.CTkToplevel(self.root)
        win.title("Nova programação" if is_new else "Editar programação")
        win.geometry("420x520")
        win.configure(fg_color=COLORS["bg"]); win.grab_set()

        scroll = ctk.CTkScrollableFrame(win, fg_color=COLORS["bg"])
        scroll.pack(fill="both", expand=True)

        def lbl(text):
            ctk.CTkLabel(scroll, text=text, font=ctk.CTkFont(size=11),
                         text_color=COLORS["text_dim"]).pack(anchor="w", padx=16, pady=(8, 2))

        lbl("Nome")
        name_var = tk.StringVar(value=sa.name if sa else "Minha programação")
        ctk.CTkEntry(scroll, textvariable=name_var, height=36,
                     font=ctk.CTkFont(size=13),
                     fg_color=COLORS["surface2"], border_color=COLORS["border"],
                     corner_radius=8, text_color=COLORS["text"]
                     ).pack(fill="x", padx=16)

        lbl("Ação")
        action_var = ctk.StringVar(value=sa.action if sa else "shutdown")
        act_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        act_frame.pack(fill="x", padx=16, pady=(0, 4))
        act_btns = {}
        for key, label in ACTION_LABELS.items():
            btn = ctk.CTkButton(act_frame,
                text=f"{ACTION_ICONS[key]}  {label}",
                width=88, height=30, font=ctk.CTkFont(size=12), corner_radius=7,
                fg_color=COLORS["surface2"], hover_color=COLORS["accent"],
                text_color=COLORS["text"],
                command=lambda k=key: _sel_action(k))
            btn.pack(side="left", padx=(0, 4))
            act_btns[key] = btn

        def _sel_action(k):
            action_var.set(k)
            for ak, ab in act_btns.items():
                ab.configure(fg_color=COLORS["accent"] if ak == k else COLORS["surface2"],
                             text_color="white" if ak == k else COLORS["text"])
        _sel_action(action_var.get())

        lbl("Horário")
        time_row = ctk.CTkFrame(scroll, fg_color="transparent")
        time_row.pack(fill="x", padx=16)
        h_var = tk.StringVar(value=f"{sa.hour:02d}" if sa else "23")
        m_var = tk.StringVar(value=f"{sa.minute:02d}" if sa else "00")
        for var, ph in [(h_var, "HH"), (m_var, "MM")]:
            ctk.CTkEntry(time_row, textvariable=var, placeholder_text=ph,
                         width=64, height=40,
                         font=ctk.CTkFont(size=18, weight="bold"),
                         fg_color=COLORS["surface2"], border_color=COLORS["border"],
                         corner_radius=8, text_color=COLORS["text"]
                         ).pack(side="left", padx=(0, 4))
            if ph == "HH":
                ctk.CTkLabel(time_row, text=":",
                             font=ctk.CTkFont(size=24, weight="bold"),
                             text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 4))

        lbl("Dias da semana")
        days_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        days_frame.pack(fill="x", padx=16, pady=(0, 4))
        day_vars = []
        existing_days = sa.days if sa else list(range(7))
        for d in range(7):
            var = tk.BooleanVar(value=d in existing_days)
            day_vars.append(var)
            btn_ref = [None]
            def mk_toggle(dv=var, di=d, br=btn_ref):
                def tog():
                    dv.set(not dv.get())
                    br[0].configure(
                        fg_color=COLORS["accent"] if dv.get() else COLORS["surface2"],
                        text_color="white" if dv.get() else COLORS["text_dim"])
                return tog
            b = ctk.CTkButton(days_frame, text=DAYS_PT[d],
                              width=48, height=30, font=ctk.CTkFont(size=11),
                              corner_radius=7,
                              fg_color=COLORS["accent"] if d in existing_days else COLORS["surface2"],
                              hover_color=COLORS["accent"],
                              text_color="white" if d in existing_days else COLORS["text_dim"],
                              command=mk_toggle())
            b.pack(side="left", padx=2)
            btn_ref[0] = b

        en_var = ctk.BooleanVar(value=sa.enabled if sa else True)
        ctk.CTkSwitch(scroll, text=" Ativada",
                      variable=en_var, font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_dim"],
                      button_color=COLORS["accent"],
                      progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False
                      ).pack(anchor="w", padx=16, pady=(10, 4))

        def save():
            try:
                h = int(h_var.get()); m = int(m_var.get())
                assert 0 <= h <= 23 and 0 <= m <= 59
            except Exception:
                messagebox.showerror("Horário inválido",
                    "Digite um horário válido (HH:MM).", parent=win)
                return
            days = [d for d, v in enumerate(day_vars) if v.get()]
            if not days:
                messagebox.showwarning("Dias", "Selecione ao menos um dia.", parent=win)
                return
            if is_new:
                self._sched_actions.append(ScheduledAction(
                    id=str(uuid.uuid4()), enabled=en_var.get(),
                    action=action_var.get(), days=days,
                    hour=h, minute=m, last_run=None, name=name_var.get()))
            else:
                sa.name    = name_var.get()
                sa.action  = action_var.get()
                sa.days    = days
                sa.hour    = h; sa.minute = m
                sa.enabled = en_var.get()
            self.config.save_scheduled_actions(self._sched_actions)
            self._refresh_schedule_list()
            win.destroy()

        ctk.CTkButton(scroll, text="💾  Salvar", height=40,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      corner_radius=8, command=save
                      ).pack(fill="x", padx=16, pady=12)

    def _delete_schedule(self, sa: ScheduledAction):
        if not messagebox.askyesno("Excluir",
                f"Excluir '{sa.name}'?"):
            return
        self._sched_actions = [x for x in self._sched_actions if x.id != sa.id]
        self.config.save_scheduled_actions(self._sched_actions)
        self._refresh_schedule_list()

    def _toggle_schedule(self, sa: ScheduledAction, enabled: bool):
        sa.enabled = enabled
        self.config.save_scheduled_actions(self._sched_actions)
        self._refresh_schedule_list()

    def _on_scheduled_fire(self, sa: ScheduledAction):
        label = ACTION_LABELS.get(sa.action, sa.action)
        self.notif.send(f"📅  {sa.name}",
                        f"{label} em 15 segundos (agendamento recorrente).")
        cancelled = self._show_countdown_dialog(sa.action,
                                                f"{sa.name}  — {label}")
        if not cancelled:
            self.config.add_history(sa.action, 0, completed=True)
            SystemController.execute(sa.action)
        self.config.save_scheduled_actions(self._sched_actions)
        self._refresh_schedule_list()

    # ══════════════════════════════════════════════════════
    # ABA: CONDICIONAL
    # ══════════════════════════════════════════════════════

    def _build_tab_conditional(self):
        top = ctk.CTkFrame(self._tab_cond, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(top,
                     text="Desligar automaticamente quando uma condição for satisfeita",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(anchor="w")

        if not HAS_PSUTIL:
            ctk.CTkFrame(self._tab_cond,
                         fg_color=COLORS["surface"], corner_radius=10,
                         height=60).pack(fill="x", padx=16, pady=8)
            ctk.CTkLabel(self._tab_cond,
                         text="⚠  Instale psutil para usar o shutdown condicional\n"
                              "pip install psutil",
                         font=ctk.CTkFont(size=12), text_color=COLORS["warning"]
                         ).pack(pady=20)
            self.cond_start_btn = None
            return

        # Ação condicional
        cf = self._card(self._tab_cond, "Ação ao detectar condição")
        self.cond_action_var = ctk.StringVar(value=self.config.get("cond_action"))
        act_frame = ctk.CTkFrame(cf, fg_color="transparent")
        act_frame.pack(fill="x", padx=16, pady=(12, 12))
        self._cond_act_btns = {}
        for key, label in ACTION_LABELS.items():
            btn = ctk.CTkButton(
                act_frame, text=f"{ACTION_ICONS[key]}  {label}",
                width=105, height=34, font=ctk.CTkFont(size=12), corner_radius=8,
                fg_color=COLORS["surface2"], hover_color=COLORS["accent2"],
                text_color=COLORS["text"],
                command=lambda k=key: self._sel_cond_action(k))
            btn.pack(side="left", padx=(0, 6))
            self._cond_act_btns[key] = btn
        self._sel_cond_action(self.cond_action_var.get())

        # Condição: CPU
        saved = {c.get("kind",""): c for c in self.config.get("conditions")}
        self._cond_vars: Dict[str, tuple] = {}

        items = [
            ("cpu_low",        "🖥  CPU cair abaixo de", "10", "% por 30s",
             "Executa a ação quando o uso de CPU ficar abaixo deste valor por "
             "30 segundos consecutivos. Ideal para aguardar o fim de renders ou encodes."),
            ("process_closed", "⚙  Processo fechar:",    "",   "(ex: blender.exe)",
             "Executa a ação quando o processo especificado for encerrado. "
             "Útil para desligar após finalizar Blender, Handbrake, etc."),
            ("download_done",  "📥  Download terminar",  "",   "",
             "Monitora o tráfego de rede. Quando a taxa cair drasticamente "
             "após um período de alta atividade, considera que o download terminou."),
            ("idle",           "🪑  Inativo por",         "30", "min",
             "Executa a ação após este tempo sem atividade de mouse ou teclado. "
             "Bom para desligar automaticamente quando você esquece o PC ligado."),
        ]
        for kind, prefix, default_val, suffix, tip in items:
            sv   = saved.get(kind, {})
            card = ctk.CTkFrame(self._tab_cond,
                                fg_color=COLORS["surface"], corner_radius=10)
            card.pack(fill="x", padx=16, pady=(0, 8))

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=12)

            chk = ctk.BooleanVar(value=sv.get("enabled", False))
            par = tk.StringVar(value=sv.get("param", default_val))

            cb = ctk.CTkCheckBox(row, text=prefix, variable=chk,
                            font=ctk.CTkFont(size=13), text_color=COLORS["text"],
                            checkbox_width=18, checkbox_height=18,
                            checkmark_color="white",
                            hover_color=COLORS["accent2"],
                            border_color=COLORS["border"],
                            fg_color=COLORS["accent2"]
                            )
            cb.pack(side="left", padx=(0, 8))
            add_tooltip(cb, tip)

            if kind == "process_closed":
                # Use process selector button
                proc_lbl = ctk.CTkLabel(row, textvariable=par,
                                        font=ctk.CTkFont(size=11),
                                        text_color=COLORS["text_dim"],
                                        width=140, anchor="w")
                proc_lbl.pack(side="left", padx=(0, 6))
                ctk.CTkButton(row, text="⚙", width=30, height=24,
                              font=ctk.CTkFont(size=11),
                              fg_color=COLORS["surface2"],
                              hover_color=COLORS["surface3"],
                              corner_radius=6, text_color=COLORS["text_dim"],
                              command=lambda p=par: self._pick_process_cond(p)
                              ).pack(side="left")
            elif default_val:
                ctk.CTkEntry(row, textvariable=par, width=56, height=26,
                             font=ctk.CTkFont(size=12),
                             fg_color=COLORS["surface2"],
                             border_color=COLORS["border"],
                             corner_radius=6, text_color=COLORS["text"]
                             ).pack(side="left", padx=(0, 6))
                if suffix:
                    ctk.CTkLabel(row, text=suffix, font=ctk.CTkFont(size=11),
                                 text_color=COLORS["text_dim2"]).pack(side="left")

            self._cond_vars[kind] = (chk, par)

        # Monitor button + status
        self._cond_status_lbl = ctk.CTkLabel(
            self._tab_cond, text="",
            font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"])
        self._cond_status_lbl.pack(pady=(4, 2))

        self.cond_start_btn = ctk.CTkButton(
            self._tab_cond, text="▶  Ativar monitoramento",
            height=42, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent2"], hover_color="#6a4ce0",
            text_color="white", corner_radius=10,
            command=self._toggle_conditional)
        self.cond_start_btn.pack(fill="x", padx=16, pady=(4, 16))
        add_tooltip(self.cond_start_btn,
            "Inicia o monitoramento das condições habilitadas acima. "
            "Quando uma condição for satisfeita, a ação será executada "
            "após um aviso de 15 segundos.")

    def _sel_cond_action(self, key: str):
        self.cond_action_var.set(key)
        for k, btn in self._cond_act_btns.items():
            btn.configure(
                fg_color=COLORS["accent2"] if k == key else COLORS["surface2"],
                text_color="white" if k == key else COLORS["text"])

    def _pick_process_cond(self, par_var: tk.StringVar):
        current = [p.strip() for p in par_var.get().split(",") if p.strip()]
        def cb(selected):
            par_var.set(", ".join(selected))
        ProcessSelector(self.root, selected_processes=current, callback=cb)

    # ══════════════════════════════════════════════════════
    # ABA: RELATÓRIOS
    # ══════════════════════════════════════════════════════

    def _build_tab_reports(self):
        scroll = ctk.CTkScrollableFrame(
            self._tab_report, fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["surface2"])
        scroll.pack(fill="both", expand=True)
        self._report_body = scroll
        self._build_stats_cards(scroll)
        self._build_charts(scroll)
        self._build_history_table(scroll)

    def _build_stats_cards(self, parent):
        s      = self.config.get("stats") or {}
        total  = s.get("total_completed", 0)
        mins   = s.get("total_minutes", 0)
        kwh    = round(mins * 0.05 / 60, 1)          # ~50W estimado
        co2    = round(kwh * 0.5, 1)                  # ~0.5 kg/kWh

        cards_data = [
            ("⚡", "Ações concluídas", str(total),    COLORS["accent"]),
            ("⏱",  "Minutos agendados", str(mins),    COLORS["accent2"]),
            ("💡", "Energia estimada",  f"~{kwh} kWh", COLORS["warning"]),
            ("🌿", "CO₂ evitado",       f"~{co2} kg",  COLORS["success"]),
        ]
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(f, text="Resumo", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 8))
        grid = ctk.CTkFrame(f, fg_color="transparent")
        grid.pack(fill="x")
        for col, (icon, lbl, val, col_) in enumerate(cards_data):
            card = ctk.CTkFrame(grid, fg_color=COLORS["surface"], corner_radius=10)
            card.grid(row=0, column=col, padx=(0, 8) if col < 3 else 0, sticky="ew")
            grid.grid_columnconfigure(col, weight=1)
            ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=22)
                         ).pack(pady=(12, 0))
            ctk.CTkLabel(card, text=val,
                         font=ctk.CTkFont(size=18, weight="bold"),
                         text_color=col_).pack()
            ctk.CTkLabel(card, text=lbl, font=ctk.CTkFont(size=10),
                         text_color=COLORS["text_dim2"]).pack(pady=(0, 10))

    def _build_charts(self, parent):
        if not HAS_MATPLOTLIB:
            card = ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=10)
            card.pack(fill="x", padx=16, pady=8)
            ctk.CTkLabel(card,
                         text="📊  Instale matplotlib para ver gráficos\n"
                              "pip install matplotlib",
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["warning"]).pack(pady=20)
            return

        s      = self.config.get("stats") or {}
        by_a   = s.get("by_action", {})
        history = self.config.get("history") or []

        if not by_a and not history:
            return

        plt.style.use("dark_background")

        # -- Pie chart: ações por tipo --
        if by_a:
            fig1, ax1 = plt.subplots(figsize=(4.5, 3))
            fig1.patch.set_facecolor("#161923")
            ax1.set_facecolor("#161923")
            labels = [ACTION_LABELS.get(k, k) for k in by_a]
            sizes  = list(by_a.values())
            colors = ["#4f8ef7", "#7c5cf7", "#f7a94f", "#4ff78e"]
            ax1.pie(sizes, labels=labels, colors=colors[:len(sizes)],
                    autopct="%1.0f%%", startangle=140,
                    textprops={"color": "#e8eaf6", "fontsize": 9})
            ax1.set_title("Ações por tipo",
                          color="#e8eaf6", fontsize=11, pad=8)
            fig1.tight_layout()

            card1 = ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=10)
            card1.pack(fill="x", padx=16, pady=(0, 8))
            ctk.CTkLabel(card1, text="Distribuição de ações",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=COLORS["text"]).pack(anchor="w", padx=12, pady=(10, 0))
            canvas1 = FigureCanvasTkAgg(fig1, master=card1)
            canvas1.draw()
            canvas1.get_tk_widget().pack(fill="x", padx=8, pady=8)
            plt.close(fig1)

        # -- Bar chart: ações por dia da semana (últimos 30 dias) --
        if history:
            day_counts = [0] * 7
            cutoff = (datetime.now() - timedelta(days=30)).isoformat()
            for e in history:
                if e.get("timestamp", "") < cutoff: continue
                if not e.get("completed"): continue
                try:
                    d = datetime.fromisoformat(e["timestamp"]).weekday()
                    day_counts[d] += 1
                except Exception:
                    pass

            if any(day_counts):
                fig2, ax2 = plt.subplots(figsize=(4.5, 2.8))
                fig2.patch.set_facecolor("#161923")
                ax2.set_facecolor("#161923")
                bars = ax2.bar(DAYS_PT, day_counts, color="#4f8ef7", width=0.6)
                for bar in bars:
                    if bar.get_height() > 0:
                        ax2.text(bar.get_x() + bar.get_width() / 2,
                                 bar.get_height() + 0.05,
                                 str(int(bar.get_height())),
                                 ha="center", va="bottom",
                                 color="#e8eaf6", fontsize=8)
                ax2.set_title("Ações por dia (últimos 30 dias)",
                              color="#e8eaf6", fontsize=11)
                ax2.tick_params(colors="#7b82a8")
                ax2.spines["bottom"].set_color("#2a2f4a")
                ax2.spines["left"].set_color("#2a2f4a")
                ax2.spines["top"].set_visible(False)
                ax2.spines["right"].set_visible(False)
                fig2.tight_layout()

                card2 = ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=10)
                card2.pack(fill="x", padx=16, pady=(0, 8))
                ctk.CTkLabel(card2, text="Frequência semanal",
                             font=ctk.CTkFont(size=12, weight="bold"),
                             text_color=COLORS["text"]).pack(anchor="w", padx=12, pady=(10, 0))
                canvas2 = FigureCanvasTkAgg(fig2, master=card2)
                canvas2.draw()
                canvas2.get_tk_widget().pack(fill="x", padx=8, pady=8)
                plt.close(fig2)

    def _build_history_table(self, parent):
        hdr_frame = ctk.CTkFrame(parent, fg_color="transparent")
        hdr_frame.pack(fill="x", padx=16, pady=(8, 4))
        ctk.CTkLabel(hdr_frame, text="Histórico de ações",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")

        btn_frame = ctk.CTkFrame(hdr_frame, fg_color="transparent")
        btn_frame.pack(side="right")
        ctk.CTkButton(btn_frame, text="📄 CSV", width=64, height=28,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=7, command=lambda: self._export_history("csv")
                      ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_frame, text="{} JSON", width=70, height=28,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=7, command=lambda: self._export_history("json")
                      ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_frame, text="🗑 Limpar", width=74, height=28,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["danger"],
                      text_color=COLORS["danger"], corner_radius=7,
                      command=self._clear_history
                      ).pack(side="left")

        # Filter
        flt = ctk.CTkFrame(parent, fg_color="transparent")
        flt.pack(fill="x", padx=16, pady=(0, 4))
        self._hist_filter = tk.StringVar()
        ctk.CTkEntry(flt, textvariable=self._hist_filter,
                     placeholder_text="🔍  Filtrar por ação ou data...",
                     height=30, font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface2"], border_color=COLORS["border"],
                     corner_radius=7, text_color=COLORS["text"]
                     ).pack(fill="x")
        self._hist_filter.trace_add("write", lambda *_: self._refresh_history())

        self._hist_frame = ctk.CTkScrollableFrame(
            parent, fg_color=COLORS["bg"], height=200,
            scrollbar_button_color=COLORS["surface2"])
        self._hist_frame.pack(fill="x", padx=16, pady=(0, 16))
        self._refresh_history()

    def _refresh_history(self):
        for w in self._hist_frame.winfo_children(): w.destroy()
        history = self.config.get("history") or []
        query   = self._hist_filter.get().lower() if hasattr(self, "_hist_filter") else ""
        for e in history:
            action = e.get("action", "")
            ts     = e.get("timestamp", "")[:16].replace("T", " ")
            if query and query not in action.lower() and query not in ts:
                continue
            label  = ACTION_LABELS.get(action, action)
            done   = e.get("completed", False)
            color  = COLORS["success"] if done else COLORS["danger"]
            mark   = "✓" if done else "✗"
            row = ctk.CTkFrame(self._hist_frame,
                               fg_color=COLORS["surface"], corner_radius=6)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row,
                text=f"{mark}  {label} ({e.get('minutes','?')}min)  —  {ts}",
                font=ctk.CTkFont(size=11), text_color=color, anchor="w"
                ).pack(anchor="w", padx=10, pady=6)

    def _clear_history(self):
        if messagebox.askyesno("Limpar histórico",
                "Apagar todo o histórico? Esta ação não pode ser desfeita."):
            self.config.data["history"] = []
            self.config.save()
            self._refresh_history()

    # ══════════════════════════════════════════════════════
    # ABA: PLUGINS
    # ══════════════════════════════════════════════════════

    def _build_tab_plugins(self):
        outer = ctk.CTkScrollableFrame(
            self._tab_plugins, fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["surface2"],
            scrollbar_button_hover_color=COLORS["surface3"])
        outer.pack(fill="both", expand=True)

        if not HAS_PLUGINS:
            ctk.CTkLabel(outer,
                text="⚠  plugin_manager.py não encontrado.\n"
                     "Coloque o arquivo na mesma pasta do ShutdownApp.py.",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["warning"]).pack(pady=40)
            return

        # ── Toolbar ───────────────────────────────────────
        tb = ctk.CTkFrame(outer, fg_color=COLORS["surface"],
                          corner_radius=8)
        tb.pack(fill="x", padx=10, pady=(8, 4))
        self._plugin_search_var = ctk.StringVar()
        ctk.CTkEntry(
            tb, textvariable=self._plugin_search_var,
            placeholder_text="🔍 Pesquisar plugins instalados...",
            height=30, font=ctk.CTkFont(size=12),
            fg_color=COLORS["surface2"], text_color=COLORS["text"],
            border_color=COLORS["border"]).pack(
                side="left", fill="x", expand=True, padx=(10, 8), pady=8)

        for txt, cmd, tip in [
            ("📋 Log",          self._plugin_open_log,      "Abrir log de plugins em janela separada"),
            ("📂 Instalar ZIP", self._plugin_install_zip,   "Instalar plugin a partir de um arquivo .zip"),
            ("� Instalar Pasta", self._plugin_install_folder, "Instalar plugin a partir de uma pasta"),
            ("�🔄 Atualizar",    self._plugin_refresh,        "Recarregar lista de plugins instalados"),
        ]:
            _b = ctk.CTkButton(
                tb, text=txt, height=30, width=120,
                font=ctk.CTkFont(size=11),
                fg_color=COLORS["surface2"],
                hover_color=COLORS["surface3"],
                text_color=COLORS["text_dim"],
                corner_radius=7, command=cmd
            )
            _b.pack(side="right", padx=(0, 6), pady=8)
            add_tooltip(_b, tip)

        # Sandbox toggle
        plug_cfg = self.config.get("plugins") or {}
        self._plugin_sandbox_var = ctk.BooleanVar(
            value=plug_cfg.get("sandbox_enabled", True))
        _sandbox_sw = ctk.CTkSwitch(
            tb, text="Sandbox",
            variable=self._plugin_sandbox_var,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            button_color=COLORS["accent2"],
            progress_color=COLORS["accent2"],
            width=48,
            command=self._plugin_save_settings
        )
        _sandbox_sw.pack(side="right", padx=(0, 10))
        add_tooltip(_sandbox_sw,
                    "Executa plugins em processo isolado (mais seguro, um pouco mais lento)")

        # ── Plugins instalados ────────────────────────────
        installed_hdr = ctk.CTkFrame(outer, fg_color="transparent")
        installed_hdr.pack(fill="x", padx=10, pady=(4, 2))
        ctk.CTkLabel(installed_hdr, text="Plugins Instalados",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")
        ctk.CTkLabel(installed_hdr,
                     text=f"📂 {PluginManager.get_plugins_dir()}",
                     font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_dim2"]).pack(side="right")

        self._plugin_list_frame = ctk.CTkFrame(
            outer, fg_color=COLORS["surface"], corner_radius=8)
        self._plugin_list_frame.pack(fill="x", padx=10, pady=(0, 6))

        self._build_installed_plugins_list()

        # ── Loja de Plugins ───────────────────────────────
        store_hdr = ctk.CTkFrame(outer, fg_color="transparent")
        store_hdr.pack(fill="x", padx=10, pady=(10, 2))
        ctk.CTkLabel(store_hdr, text="🛒 Loja de Plugins",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")
        ctk.CTkLabel(store_hdr, text="(catálogo da comunidade)",
                     font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_dim2"]).pack(side="left", padx=8)

        # Filtro de categoria
        cat_row = ctk.CTkFrame(outer, fg_color="transparent")
        cat_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(cat_row, text="Categoria:",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 8))
        self._store_cat_var = ctk.StringVar(value="Todos")
        ctk.CTkOptionMenu(
            cat_row, values=STORE_CATEGORIES,
            variable=self._store_cat_var,
            width=140, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=COLORS["surface2"],
            button_color=COLORS["surface3"],
            text_color=COLORS["text_dim"],
            command=lambda _: self._build_store_list()
        ).pack(side="left")

        self._store_search_var = ctk.StringVar()
        ctk.CTkEntry(
            cat_row, textvariable=self._store_search_var,
            placeholder_text="Pesquisar...",
            height=28, font=ctk.CTkFont(size=11),
            fg_color=COLORS["surface2"], text_color=COLORS["text"],
            border_color=COLORS["border"]).pack(
                side="left", fill="x", expand=True, padx=(8, 0))
        ctk.CTkButton(
            cat_row, text="🔍", width=32, height=28,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["surface2"],
            hover_color=COLORS["surface3"],
            text_color=COLORS["text_dim"],
            command=self._build_store_list
        ).pack(side="left", padx=(4, 0))

        self._store_list_frame = ctk.CTkFrame(
            outer, fg_color=COLORS["surface"], corner_radius=8)
        self._store_list_frame.pack(fill="x", padx=10, pady=(0, 6))

        self._build_store_list()

    def _build_installed_plugins_list(self):
        """Reconstrói a lista de plugins instalados."""
        for w in self._plugin_list_frame.winfo_children():
            w.destroy()

        manifests = self.plugin_mgr.discover() if self.plugin_mgr else []
        q = self._plugin_search_var.get().lower() if \
            hasattr(self, "_plugin_search_var") else ""
        if q:
            manifests = [m for m in manifests
                         if q in m.get("name", "").lower()
                         or q in m.get("description", "").lower()]

        if not manifests:
            ctk.CTkLabel(
                self._plugin_list_frame,
                text="Nenhum plugin instalado. Instale via ZIP ou pela loja.",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_dim2"]
            ).pack(pady=16)
            return

        plug_cfg    = self.config.get("plugins") or {}
        enabled_ids = set(plug_cfg.get("enabled_plugins", []))

        for mf in manifests:
            pid     = mf.get("id", "?")
            is_en   = pid in enabled_ids
            is_load = self.plugin_mgr.is_loaded(pid)
            has_params = bool(mf.get("parameters"))
            has_ui     = bool(mf.get("ui"))

            card = ctk.CTkFrame(
                self._plugin_list_frame,
                fg_color=COLORS["surface2"], corner_radius=6)
            card.pack(fill="x", padx=8, pady=4)

            info = ctk.CTkFrame(card, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True,
                      padx=(10, 4), pady=8)

            # ── Nome + estado ────────────────────────────────
            name_row = ctk.CTkFrame(info, fg_color="transparent")
            name_row.pack(fill="x")
            ctk.CTkLabel(
                name_row,
                text=f"🔌  {mf.get('name', pid)}  v{mf.get('version','')}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLORS["text"]
            ).pack(side="left")
            dot_color = COLORS["success"] if is_load else COLORS["text_dim2"]
            ctk.CTkLabel(
                name_row,
                text="● carregado" if is_load else "○ não carregado",
                font=ctk.CTkFont(size=10),
                text_color=dot_color
            ).pack(side="left", padx=8)

            # ── Descrição ────────────────────────────────────
            ctk.CTkLabel(
                info,
                text=mf.get("description", ""),
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_dim"],
                wraplength=260, justify="left"
            ).pack(anchor="w")

            # ── Permissões ───────────────────────────────────
            perms = mf.get("permissions", [])
            if perms:
                if HAS_PLUGINS:
                    perm_labels = [PERMISSION_LABELS.get(p, (p, ""))[0]
                                   for p in perms]
                else:
                    perm_labels = perms
                ctk.CTkLabel(
                    info,
                    text="Permissões: " + ", ".join(perm_labels),
                    font=ctk.CTkFont(size=9),
                    text_color=COLORS["warning"]
                ).pack(anchor="w")

            # ── Linha de ações rápidas (config / UI) ─────────
            action_row = ctk.CTkFrame(info, fg_color="transparent")
            action_row.pack(anchor="w", pady=(4, 0))

            if has_params:
                cfg_btn = ctk.CTkButton(
                    action_row,
                    text="⚙  Configurações",
                    width=120, height=26,
                    font=ctk.CTkFont(size=11),
                    fg_color=COLORS["surface3"],
                    hover_color=COLORS["accent"],
                    text_color=COLORS["text_dim"],
                    command=lambda p=pid, m=mf:
                        self._plugin_open_settings(p, m)
                )
                cfg_btn.pack(side="left", padx=(0, 6))
                add_tooltip(cfg_btn,
                    "Abrir janela de configuração deste plugin")

            if has_ui:
                ui_def  = mf.get("ui", {})
                ui_type = ui_def.get("type", "window")
                ui_icon = ui_def.get("icon", "🪟")
                ui_lbl  = (f"{ui_icon}  Abrir Aba"
                           if ui_type == "tab"
                           else f"{ui_icon}  Abrir Janela")
                ui_btn = ctk.CTkButton(
                    action_row,
                    text=ui_lbl,
                    width=120, height=26,
                    font=ctk.CTkFont(size=11),
                    fg_color=COLORS["surface3"],
                    hover_color=COLORS["accent2"],
                    text_color=COLORS["text_dim"],
                    command=lambda p=pid, m=mf:
                        self._plugin_open_ui(p, m)
                )
                ui_btn.pack(side="left")
                add_tooltip(ui_btn, "Abrir a interface do plugin")

            # ── Botões laterais (toggle + remover) ───────────
            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.pack(side="right", padx=(0, 8), pady=8)

            en_var = ctk.BooleanVar(value=is_en)
            sw = ctk.CTkSwitch(
                btns, text="", variable=en_var, width=38,
                button_color=COLORS["accent2"],
                progress_color=COLORS["accent2"],
                command=lambda p=pid, v=en_var:
                    self._plugin_toggle(p, v.get())
            )
            sw.pack()
            ctk.CTkLabel(btns, text="ativo",
                         font=ctk.CTkFont(size=9),
                         text_color=COLORS["text_dim2"]).pack()
            add_tooltip(sw, "Ativar/desativar este plugin")

            rem_btn = ctk.CTkButton(
                btns, text="🗑", width=28, height=26,
                font=ctk.CTkFont(size=12),
                fg_color=COLORS["surface3"],
                hover_color=COLORS["danger"],
                text_color=COLORS["text_dim"],
                command=lambda p=pid, n=mf.get("name", pid):
                    self._plugin_remove(p, n)
            )
            rem_btn.pack(pady=(4, 0))
            add_tooltip(rem_btn, "Remover plugin permanentemente")

    def _build_store_list(self):
        """Reconstrói a lista da loja."""
        for w in self._store_list_frame.winfo_children():
            w.destroy()

        cat   = self._store_cat_var.get() if hasattr(self, "_store_cat_var") else "Todos"
        query = self._store_search_var.get() if hasattr(self, "_store_search_var") else ""
        items = PluginManager.get_store_catalog(cat, query) if HAS_PLUGINS else []

        if not items:
            ctk.CTkLabel(
                self._store_list_frame,
                text="Nenhum plugin encontrado para este filtro.",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_dim2"]
            ).pack(pady=12)
            return

        installed_ids = {m.get("id") for m in
                         (self.plugin_mgr.discover() if self.plugin_mgr else [])}

        for item in items:
            pid = item.get("id", "?")
            card = ctk.CTkFrame(
                self._store_list_frame,
                fg_color=COLORS["surface2"], corner_radius=6)
            card.pack(fill="x", padx=8, pady=4)

            info = ctk.CTkFrame(card, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True,
                      padx=(10, 4), pady=6)

            top = ctk.CTkFrame(info, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(
                top,
                text=f"{item.get('name', pid)}  v{item.get('version','')}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLORS["text"]
            ).pack(side="left")
            ctk.CTkLabel(
                top,
                text=f"⭐ {item.get('stars',0):.1f}  "
                     f"↓ {item.get('downloads',0)}",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_dim2"]
            ).pack(side="right")

            ctk.CTkLabel(
                top,
                text=f"  [{item.get('category','')}]",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["accent2"]
            ).pack(side="left", padx=4)

            ctk.CTkLabel(
                info,
                text=item.get("description", ""),
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_dim"],
                wraplength=270, justify="left"
            ).pack(anchor="w")

            perms = item.get("permissions", [])
            if perms:
                ctk.CTkLabel(
                    info,
                    text="Permissões: " + ", ".join(perms),
                    font=ctk.CTkFont(size=9),
                    text_color=COLORS["warning"]
                ).pack(anchor="w")

            # Tags
            tags_row = ctk.CTkFrame(info, fg_color="transparent")
            tags_row.pack(anchor="w")
            for tag in item.get("tags", [])[:4]:
                ctk.CTkLabel(
                    tags_row,
                    text=f"#{tag}",
                    font=ctk.CTkFont(size=9),
                    text_color=COLORS["text_dim2"]
                ).pack(side="left", padx=(0, 4))

            # Instalar btn
            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.pack(side="right", padx=(0, 10), pady=6)
            is_installed = pid in installed_ids
            ctk.CTkButton(
                btns,
                text="✅ Instalado" if is_installed else "⬇ Instalar",
                width=90, height=28,
                font=ctk.CTkFont(size=11),
                state="disabled" if is_installed else "normal",
                fg_color=COLORS["surface3"] if is_installed else COLORS["accent2"],
                hover_color=COLORS["accent"],
                text_color="white",
                command=lambda i=item: self._plugin_store_info(i)
            ).pack()

    def _plugin_toggle(self, plugin_id: str, enable: bool):
        if self.plugin_mgr:
            self.plugin_mgr.set_enabled(plugin_id, enable)

        # Add or remove tab for plugins with ui.type == "tab"
        if self.plugin_mgr:
            manifest = self.plugin_mgr._find_manifest(plugin_id)
            if manifest:
                ui_def = manifest.get("ui", {})
                if ui_def.get("type") == "tab":
                    if enable and self.plugin_mgr.is_loaded(plugin_id):
                        self._plugin_add_tab(plugin_id, manifest)
                    elif not enable:
                        self._plugin_remove_tab(plugin_id, manifest)

        # Reconstrói apenas a lista de instalados para refletir status "carregado"
        self._build_installed_plugins_list()

    def _plugin_remove(self, plugin_id: str, name: str):
        if not messagebox.askyesno("Remover Plugin",
                f"Remover '{name}'?\nEsta ação não pode ser desfeita."):
            return
        if self.plugin_mgr:
            ok, msg = self.plugin_mgr.remove_plugin(plugin_id)
            if not ok:
                messagebox.showerror("Erro", msg)
        self._build_installed_plugins_list()
        self._plugin_log_refresh()

    def _plugin_install_zip(self):
        path = filedialog.askopenfilename(
            title="Instalar Plugin (.zip)",
            filetypes=[("Plugin ZIP", "*.zip"),
                       ("Todos", "*.*")])
        if not path or not self.plugin_mgr:
            return
        ok, msg = self.plugin_mgr.install_from_path(path)
        if ok:
            messagebox.showinfo("Plugin Instalado", msg)
            self._build_installed_plugins_list()
        else:
            messagebox.showerror("Erro ao Instalar", msg)

    def _plugin_install_folder(self):
        """Instala plugin a partir de uma pasta (copia para o diretório de plugins)."""
        path = filedialog.askdirectory(
            title="Selecionar pasta do plugin",
            mustexist=True)
        if not path or not self.plugin_mgr:
            return
        from pathlib import Path as _Path
        folder = _Path(path)
        # Valida se tem plugin.json
        if not (folder / "plugin.json").exists():
            messagebox.showerror(
                "Pasta inválida",
                "A pasta selecionada não contém um arquivo plugin.json.\n"
                "Selecione a pasta raiz do plugin.")
            return
        ok, msg = self.plugin_mgr.install_from_path(folder)
        if ok:
            messagebox.showinfo("Plugin Instalado", f"✅ {msg}")
            self._build_installed_plugins_list()
        else:
            messagebox.showerror("Erro ao Instalar", msg)

    def _plugin_open_log(self):
        """Abre o log de plugins em uma janela separada e independente."""
        # Reutiliza janela existente se ainda aberta
        if hasattr(self, "_plugin_log_win") and self._plugin_log_win.winfo_exists():
            self._plugin_log_win.lift()
            self._plugin_log_win.focus_set()
            self._plugin_log_refresh()
            return

        win = ctk.CTkToplevel(self.root)
        win.title("📋 Log de Plugins")
        win.geometry("700x420")
        win.resizable(True, True)
        self._plugin_log_win = win

        # Toolbar
        tb = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=0)
        tb.pack(fill="x", padx=0, pady=0)
        ctk.CTkLabel(tb, text="📋 Log de Plugins",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            tb, text="🗑 Limpar", width=80, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=COLORS["surface2"],
            hover_color=COLORS["surface3"],
            text_color=COLORS["text_dim"],
            command=self._plugin_log_clear
        ).pack(side="right", padx=(0, 8), pady=8)
        ctk.CTkButton(
            tb, text="🔄 Atualizar", width=90, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=COLORS["surface2"],
            hover_color=COLORS["surface3"],
            text_color=COLORS["text_dim"],
            command=self._plugin_log_refresh
        ).pack(side="right", padx=(0, 4), pady=8)

        # Textbox
        self._plugin_log_text = ctk.CTkTextbox(
            win, height=360,
            fg_color=COLORS["surface"],
            text_color=COLORS["text_dim"],
            font=ctk.CTkFont("Courier New", 10),
            state="disabled")
        self._plugin_log_text.pack(fill="both", expand=True,
                                   padx=8, pady=(4, 8))

        self._plugin_log_refresh()

        # Auto-refresh a cada 3 s enquanto janela aberta
        def _auto():
            try:
                if win.winfo_exists():
                    self._plugin_log_refresh()
                    win.after(3000, _auto)
            except Exception:
                pass
        win.after(3000, _auto)

    def _plugin_log_refresh(self):
        """Atualiza conteúdo do textbox de log (se existir)."""
        if not hasattr(self, "_plugin_log_text"):
            return
        try:
            if not self._plugin_log_text.winfo_exists():
                return
        except Exception:
            return
        entries = self.plugin_mgr.get_log_entries(200) if self.plugin_mgr else []
        self._plugin_log_text.configure(state="normal")
        self._plugin_log_text.delete("1.0", "end")
        self._plugin_log_text.insert("end", "\n".join(entries) or "(sem entradas de log)")
        self._plugin_log_text.see("end")
        self._plugin_log_text.configure(state="disabled")

    def _plugin_log_clear(self):
        """Limpa fila de log."""
        if self.plugin_mgr:
            try:
                self.plugin_mgr._log_queue.queue.clear()
            except Exception:
                pass
        self._plugin_log_refresh()

    def _plugin_refresh(self):
        self._build_installed_plugins_list()

    def _plugin_save_settings(self):
        plug_cfg = dict(self.config.get("plugins") or {})
        plug_cfg["sandbox_enabled"] = self._plugin_sandbox_var.get()
        self.config.set("plugins", plug_cfg)
        self.config.save()

    def _plugin_open_settings(self, plugin_id: str, manifest: dict):
        """Abre a janela de configuração de parâmetros do plugin."""
        if not self.plugin_mgr:
            return
        # Reutiliza janela já aberta para o mesmo plugin
        win_attr = f"_plugin_cfg_win_{plugin_id}"
        existing = getattr(self, win_attr, None)
        if existing and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        win = PluginSettingsWindow(self.root, self.plugin_mgr, manifest)
        setattr(self, win_attr, win)

    def _plugin_open_ui(self, plugin_id: str, manifest: dict):
        """
        Abre a UI própria do plugin.

        Se ``ui.type == "tab"``, tenta adicionar uma aba dinâmica na janela
        principal; se ``ui.type == "window"``, abre janela separada.
        """
        if not self.plugin_mgr:
            return
        ui_def  = manifest.get("ui", {})
        ui_type = ui_def.get("type", "window")

        if ui_type == "tab":
            self._plugin_add_tab(plugin_id, manifest)
        else:
            # Janela separada
            win_attr = f"_plugin_ui_win_{plugin_id}"
            existing = getattr(self, win_attr, None)
            if existing:
                try:
                    if existing.winfo_exists():
                        existing.lift()
                        existing.focus_set()
                        return
                except Exception:
                    pass
            win = PluginUIWindow(self.root, self.plugin_mgr, manifest)
            setattr(self, win_attr, win)

    def _plugin_add_tab(self, plugin_id: str, manifest: dict):
        """Adiciona (ou foca) uma aba dinâmica de plugin na janela principal."""
        ui_def   = manifest.get("ui", {})
        icon     = ui_def.get("icon", "🔌")
        tab_name = ui_def.get("tab_name",
                               manifest.get("name", plugin_id))
        full_name = f"{icon}  {tab_name}"

        # Verifica se aba já existe
        try:
            existing_tabs = self.tabs._tab_dict  # internal CTkTabview dict
            if full_name in existing_tabs:
                self.tabs.set(full_name)
                return
        except Exception:
            pass

        try:
            new_tab = self.tabs.add(full_name)
            # Constrói widget de UI do plugin dentro da aba
            widget = self.plugin_mgr.build_plugin_ui_window(plugin_id, new_tab)
            if widget is None:
                ctk.CTkLabel(
                    new_tab,
                    text=f"⚠  UI do plugin '{manifest.get('name', plugin_id)}'\nnão pôde ser carregada.",
                    font=ctk.CTkFont(size=12),
                    text_color=COLORS["warning"]
                ).pack(expand=True, pady=40)
            elif hasattr(widget, "pack"):
                widget.pack(fill="both", expand=True)
            self.tabs.set(full_name)
        except Exception as e:
            messagebox.showerror(
                "Erro ao abrir aba do plugin",
                f"Não foi possível adicionar a aba:\n{e}",
                parent=self.root)

    def _plugin_remove_tab(self, plugin_id: str, manifest: dict):
        """Remove a aba dinâmica de um plugin (se existir)."""
        ui_def    = manifest.get("ui", {})
        icon      = ui_def.get("icon", "🔌")
        tab_name  = ui_def.get("tab_name", manifest.get("name", plugin_id))
        full_name = f"{icon}  {tab_name}"
        try:
            if full_name in self.tabs._tab_dict:
                self.tabs.delete(full_name)
        except Exception:
            pass

    def _auto_add_plugin_tabs(self):
        """Adiciona abas para todos os plugins carregados que declaram ui.type==tab."""
        if not self.plugin_mgr:
            return
        for manifest in self.plugin_mgr.discover():
            pid    = manifest.get("id", "")
            ui_def = manifest.get("ui", {})
            if ui_def.get("type") == "tab" and self.plugin_mgr.is_loaded(pid):
                self._plugin_add_tab(pid, manifest)

    def _on_plugin_loaded_ui(self, plugin_id: str):
        """Callback chamado quando um plugin é carregado — adiciona aba se necessário."""
        if not self.plugin_mgr:
            return
        manifest = self.plugin_mgr._find_manifest(plugin_id)
        if manifest is None:
            return
        ui_def = manifest.get("ui", {})
        if ui_def.get("type") == "tab":
            self._plugin_add_tab(plugin_id, manifest)
        # Atualiza lista de plugins instalados
        self._build_installed_plugins_list()

    def _on_plugin_unloaded_ui(self, plugin_id: str):
        """Callback chamado quando um plugin é descarregado — remove aba se existia."""
        if not self.plugin_mgr:
            return
        manifest = self.plugin_mgr._find_manifest(plugin_id)
        if manifest is None:
            return
        ui_def = manifest.get("ui", {})
        if ui_def.get("type") == "tab":
            self._plugin_remove_tab(plugin_id, manifest)
        # Atualiza lista de plugins instalados
        self._build_installed_plugins_list()

    def _plugin_store_info(self, item: dict):
        """Mostra dialog com info do plugin e permissões antes de instalar."""
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(f"Plugin: {item.get('name','')}")
        dlg.geometry("440x380")
        dlg.resizable(False, False)
        dlg.grab_set()

        ctk.CTkLabel(dlg,
            text=f"🔌 {item.get('name','')}  v{item.get('version','')}",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text"]).pack(pady=(16, 4))
        ctk.CTkLabel(dlg,
            text=f"por {item.get('author','')}  |  {item.get('category','')}",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"]).pack()
        ctk.CTkLabel(dlg,
            text=item.get("description", ""),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text"],
            wraplength=380, justify="center").pack(pady=(10, 6))

        if item.get("permissions"):
            ctk.CTkLabel(dlg,
                text="⚠  Este plugin solicita as seguintes permissões:",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLORS["warning"]).pack(pady=(6, 2))
            for p in item["permissions"]:
                lbl, desc = PERMISSION_LABELS.get(p, (p, ""))
                ctk.CTkLabel(dlg,
                    text=f"  {lbl} — {desc}",
                    font=ctk.CTkFont(size=11),
                    text_color=COLORS["text_dim"]).pack(anchor="w", padx=30)

        ctk.CTkLabel(dlg,
            text=f"\nA instalação real requer baixar o arquivo .zip\n"
                 f"(catálogo demonstrativo — sem download automático)",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_dim2"],
            justify="center").pack(pady=8)

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(pady=8)
        ctk.CTkButton(btn_row, text="⬇ Instalar ZIP",
                      width=120, height=32,
                      fg_color=COLORS["accent2"],
                      hover_color=COLORS["accent"],
                      text_color="white",
                      command=lambda: (dlg.destroy(),
                                       self._plugin_install_zip())
                     ).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="Fechar",
                      width=80, height=32,
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"],
                      command=dlg.destroy
                     ).pack(side="left")

    # ══════════════════════════════════════════════════════
    # ABA: OPÇÕES
    # ══════════════════════════════════════════════════════

    def _build_tab_options(self):
        scroll = ctk.CTkScrollableFrame(
            self._tab_opts, fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["surface2"],
            scrollbar_button_hover_color=COLORS["surface3"])
        scroll.pack(fill="both", expand=True)

        # ── Geral ─────────────────────────────────────────
        f = self._card(scroll, "Geral")
        self.autostart_var = ctk.BooleanVar(value=self.config.get("autostart"))
        sw_auto = self._switch(f, "🚀  Iniciar com o sistema", self.autostart_var,
                     cmd=self._toggle_autostart)
        add_tooltip(sw_auto,
            "Inicia o ShutdownTimer automaticamente quando o Windows/Linux iniciar.")

        self.prevent_sleep_var = ctk.BooleanVar(
            value=self.config.get("prevent_sleep"))
        sw_sleep = self._switch(
            f, "⛔  Impedir hibernação durante o timer",
            self.prevent_sleep_var,
            cmd=lambda: self.config.set("prevent_sleep",
                                        self.prevent_sleep_var.get()))
        add_tooltip(sw_sleep,
            "Impede que o Windows entre em hibernação ou suspensão enquanto "
            "o timer estiver contando. Restaurado automaticamente ao finalizar.")

        # ── Smart Mode ────────────────────────────────────
        fsm = self._card(scroll, "Smart Mode")

        sm_top = ctk.CTkFrame(fsm, fg_color="transparent")
        sm_top.pack(fill="x", padx=16, pady=(12, 4))

        self.smart_mode_var = ctk.BooleanVar(value=self.config.get("smart_mode"))
        sm_sw = ctk.CTkSwitch(
            sm_top,
            text=" 🧠  Smart Mode",
            variable=self.smart_mode_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
            button_color=COLORS["accent2"],
            progress_color=COLORS["accent2"],
            onvalue=True, offvalue=False,
            command=self._toggle_smart_mode)
        sm_sw.pack(side="left")
        add_tooltip(sm_sw,
            "Gerencia automaticamente desligamento, suspensão e hibernação "
            "com base na atividade do sistema e nos hábitos de uso aprendidos. "
            "Inclui proteção de CPU, proteção de download e análise de padrões horários.")

        self._smart_status_lbl = ctk.CTkLabel(
            sm_top, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"])
        self._smart_status_lbl.pack(side="right")

        ctk.CTkLabel(fsm,
            text="Gerenciamento inteligente de energia que aprende os hábitos "
                 "de uso do computador.",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim2"],
            wraplength=440, justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # Sub-opções do Smart Mode (com tooltips)
        sm_opts = ctk.CTkFrame(fsm, fg_color=COLORS["surface2"], corner_radius=8)
        sm_opts.pack(fill="x", padx=16, pady=(0, 6))

        # CPU threshold
        cpu_row = ctk.CTkFrame(sm_opts, fg_color="transparent")
        cpu_row.pack(fill="x", padx=12, pady=(10, 4))
        cpu_lbl = ctk.CTkLabel(cpu_row, text="🖥  Proteção de CPU — pausar se CPU ≥",
                               font=ctk.CTkFont(size=12),
                               text_color=COLORS["text_dim"])
        cpu_lbl.pack(side="left")
        add_tooltip(cpu_lbl,
            "Evita desligamento automático se o uso de CPU estiver acima "
            "deste valor. Útil durante renders, backups e compilações.")
        self._sm_cpu_var = tk.StringVar(
            value=str(self.config.get("smart_cpu_threshold")))
        cpu_entry = ctk.CTkEntry(cpu_row, textvariable=self._sm_cpu_var,
                                 width=46, height=26,
                                 font=ctk.CTkFont(size=11),
                                 fg_color=COLORS["surface3"],
                                 border_color=COLORS["border"],
                                 corner_radius=5, text_color=COLORS["text"])
        cpu_entry.pack(side="left", padx=6)
        add_tooltip(cpu_entry,
            "Percentual de CPU (0-100). Padrão: 15%.")
        ctk.CTkLabel(cpu_row, text="%",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left")

        # Net threshold
        net_row = ctk.CTkFrame(sm_opts, fg_color="transparent")
        net_row.pack(fill="x", padx=12, pady=(0, 4))
        net_lbl = ctk.CTkLabel(net_row,
                               text="📥  Proteção de download — bloquear se rede ≥",
                               font=ctk.CTkFont(size=12),
                               text_color=COLORS["text_dim"])
        net_lbl.pack(side="left")
        add_tooltip(net_lbl,
            "Evita desligamento enquanto downloads ou transferências de rede "
            "estiverem ativos. O sistema aguarda a taxa cair abaixo do limite.")
        self._sm_net_var = tk.StringVar(
            value=str(self.config.get("smart_net_threshold_kb")))
        net_entry = ctk.CTkEntry(net_row, textvariable=self._sm_net_var,
                                 width=56, height=26,
                                 font=ctk.CTkFont(size=11),
                                 fg_color=COLORS["surface3"],
                                 border_color=COLORS["border"],
                                 corner_radius=5, text_color=COLORS["text"])
        net_entry.pack(side="left", padx=6)
        add_tooltip(net_entry,
            "Taxa de rede em KB/s. Padrão: 100 KB/s.")
        ctk.CTkLabel(net_row, text="KB/s",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left")

        # Idle thresholds
        idle_row = ctk.CTkFrame(sm_opts, fg_color="transparent")
        idle_row.pack(fill="x", padx=12, pady=(0, 4))
        idle_lbl = ctk.CTkLabel(idle_row,
                                text="🪑  Suspender após",
                                font=ctk.CTkFont(size=12),
                                text_color=COLORS["text_dim"])
        idle_lbl.pack(side="left")
        add_tooltip(idle_lbl,
            "Suspende o computador após este tempo sem atividade de "
            "mouse/teclado. Preserva a sessão.")
        self._sm_suspend_var = tk.StringVar(
            value=str(self.config.get("smart_idle_suspend_min")))
        ctk.CTkEntry(idle_row, textvariable=self._sm_suspend_var,
                     width=46, height=26,
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface3"], border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]
                     ).pack(side="left", padx=6)
        ctk.CTkLabel(idle_row, text="min · Desligar após",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._sm_shutdown_var = tk.StringVar(
            value=str(self.config.get("smart_idle_shutdown_min")))
        sh_entry = ctk.CTkEntry(idle_row, textvariable=self._sm_shutdown_var,
                                width=46, height=26,
                                font=ctk.CTkFont(size=11),
                                fg_color=COLORS["surface3"],
                                border_color=COLORS["border"],
                                corner_radius=5, text_color=COLORS["text"])
        sh_entry.pack(side="left", padx=6)
        add_tooltip(sh_entry,
            "Desliga o computador após este tempo de inatividade — apenas "
            "se o Smart Mode prever que o usuário não voltará em breve.")
        ctk.CTkLabel(idle_row, text="min de inatividade",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left")

        # Reboot suggestion
        reboot_row = ctk.CTkFrame(sm_opts, fg_color="transparent")
        reboot_row.pack(fill="x", padx=12, pady=(0, 10))
        rb_lbl = ctk.CTkLabel(reboot_row,
                              text="🔄  Sugerir reinicialização após",
                              font=ctk.CTkFont(size=12),
                              text_color=COLORS["text_dim"])
        rb_lbl.pack(side="left")
        add_tooltip(rb_lbl,
            "Se o sistema estiver ligado por mais dias do que este limite, "
            "o Smart Mode sugere uma reinicialização para melhorar a estabilidade.")
        self._sm_uptime_var = tk.StringVar(
            value=str(self.config.get("smart_uptime_reboot_d")))
        ctk.CTkEntry(reboot_row, textvariable=self._sm_uptime_var,
                     width=40, height=26,
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface3"], border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]
                     ).pack(side="left", padx=6)
        ctk.CTkLabel(reboot_row, text="dias ligado",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left")

        # Save smart config button
        ctk.CTkButton(fsm, text="💾  Salvar configurações do Smart Mode",
                      height=32, font=ctk.CTkFont(size=12),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"], corner_radius=8,
                      command=self._save_smart_config
                      ).pack(fill="x", padx=16, pady=(0, 6))

        # Hábitos button
        ctk.CTkButton(fsm, text="📊  Ver hábitos aprendidos",
                      height=32, font=ctk.CTkFont(size=12),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"], corner_radius=8,
                      command=self._show_smart_habits
                      ).pack(fill="x", padx=16, pady=(0, 12))

        # ── Som e notificações ────────────────────────────
        f2 = self._card(scroll, "Som e notificações")
        self.sound_var = ctk.BooleanVar(value=self.config.get("sound_warning"))
        sw_sound = self._switch(f2, "🔔  Beeps de aviso antes da ação", self.sound_var)
        add_tooltip(sw_sound,
            "Emite beeps sonoros nos avisos de 5 min e 1 min antes da ação. "
            "Quando desligado, apenas notificações visuais são enviadas.")
        if not HAS_PLYER:
            ctk.CTkLabel(f2, text="⚠  pip install plyer  para notificações nativas",
                         font=ctk.CTkFont(size=10),
                         text_color=COLORS["warning"]).pack(anchor="w", padx=16, pady=(0, 8))

        # ── Atalhos ───────────────────────────────────────
        f3 = self._card(scroll, "Atalhos globais de teclado")
        self.hotkeys_var = ctk.BooleanVar(value=self.config.get("hotkeys_enabled"))
        hkr = ctk.CTkFrame(f3, fg_color="transparent")
        hkr.pack(fill="x", padx=16, pady=(8, 4))
        ctk.CTkSwitch(hkr, text=" ⌨  Habilitar atalhos globais",
                      variable=self.hotkeys_var, font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_dim"],
                      button_color=COLORS["accent"], progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False,
                      command=lambda: (
                          self.config.set("hotkeys_enabled", self.hotkeys_var.get()),
                          self.hotkeys.setup(self.config, self)
                      )).pack(side="left")
        add_tooltip(hkr,
            "Ativa atalhos de teclado globais que funcionam mesmo com o "
            "app minimizado. Requer 'pip install keyboard'.")
        if not HAS_KEYBOARD:
            ctk.CTkLabel(hkr, text="(pip install keyboard)",
                         font=ctk.CTkFont(size=10),
                         text_color=COLORS["text_dim2"]).pack(side="right")

        for key, label in [("hotkey_start",  "Iniciar timer"),
                            ("hotkey_cancel", "Cancelar timer"),
                            ("hotkey_widget", "Widget")]:
            row = ctk.CTkFrame(f3, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(0, 6))
            ctk.CTkLabel(row, text=f"{label}:", width=100,
                         font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
                         anchor="w").pack(side="left")
            var = tk.StringVar(value=self.config.get(key))
            entry = ctk.CTkEntry(row, textvariable=var, width=160, height=28,
                                 font=ctk.CTkFont(size=11),
                                 fg_color=COLORS["surface2"],
                                 border_color=COLORS["border"],
                                 corner_radius=6, text_color=COLORS["text"])
            entry.pack(side="left", padx=(0, 8))
            entry.bind("<FocusOut>", lambda e, k=key, v=var: (
                self.config.set(k, v.get()),
                self.hotkeys.setup(self.config, self)))

        ctk.CTkFrame(f3, fg_color="transparent", height=8).pack()

        # ── Modo Gamer ────────────────────────────────────
        f4 = self._card(scroll, "Modo Gamer")
        self.gamer_var = ctk.BooleanVar(value=self.config.get("gamer_mode"))
        gr = ctk.CTkFrame(f4, fg_color="transparent")
        gr.pack(fill="x", padx=16, pady=(10, 6))
        gamer_sw = ctk.CTkSwitch(gr, text=" 🎮  Pausar timer quando jogo ativo",
                      variable=self.gamer_var, font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_dim"],
                      button_color=COLORS["accent"], progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False)
        gamer_sw.pack(side="left")
        add_tooltip(gamer_sw,
            "Pausa automaticamente o timer quando detecta um jogo em fullscreen "
            "ou um processo da lista monitorada em execução. Retoma quando o "
            "jogo é fechado.")
        ctk.CTkButton(gr, text="⚙  Processos", width=100, height=28,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=6, text_color=COLORS["text_dim"],
                      command=self._gamer_settings).pack(side="right")

        # Show selected processes count
        procs = self.config.get("gamer_processes") or []
        self._gamer_proc_lbl = ctk.CTkLabel(
            f4, text=self._gamer_proc_text(procs),
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim2"])
        self._gamer_proc_lbl.pack(anchor="w", padx=16, pady=(0, 6))

        idle_row = ctk.CTkFrame(f4, fg_color="transparent")
        idle_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(idle_row, text="Inatividade para pausar (seg):",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._gamer_idle_var = tk.StringVar(
            value=str(self.config.get("gamer_idle_threshold")))
        ctk.CTkEntry(idle_row, textvariable=self._gamer_idle_var,
                     width=56, height=28, font=ctk.CTkFont(size=12),
                     fg_color=COLORS["surface2"], border_color=COLORS["border"],
                     corner_radius=6, text_color=COLORS["text"]
                     ).pack(side="left", padx=8)
        ctk.CTkButton(idle_row, text="Salvar", width=56, height=28,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=6, text_color=COLORS["text_dim"],
                      command=self._save_gamer_idle).pack(side="left")

        # ── Timer adaptativo ──────────────────────────────
        f5 = self._card(scroll, "Timer adaptativo")
        self.adaptive_var = ctk.BooleanVar(value=self.config.get("adaptive_enabled"))
        ar = ctk.CTkFrame(f5, fg_color="transparent")
        ar.pack(fill="x", padx=16, pady=(10, 6))
        adapt_sw = ctk.CTkSwitch(ar, text=" 🖱  Detectar atividade e estender timer",
                      variable=self.adaptive_var, font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_dim"],
                      button_color=COLORS["accent"], progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False)
        adapt_sw.pack(side="left")
        add_tooltip(adapt_sw,
            "Se o timer estiver nos últimos 2 minutos e houver atividade de "
            "mouse/teclado, o timer é automaticamente estendido pelo valor "
            "configurado. Evita desligar o PC enquanto você está usando.")
        self.adaptive_ext = tk.StringVar(
            value=str(self.config.get("adaptive_extend_min")))
        ctk.CTkEntry(ar, textvariable=self.adaptive_ext, width=46, height=24,
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface2"], border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]).pack(side="right")
        ctk.CTkLabel(ar, text="min", font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(side="right", padx=2)
        ctk.CTkFrame(f5, fg_color="transparent", height=8).pack()

        # ── Tema da interface ─────────────────────────────
        f_theme = self._card(scroll, "☀️ Tema da Interface")
        theme_row = ctk.CTkFrame(f_theme, fg_color="transparent")
        theme_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(theme_row, text="Tema atual:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._theme_var = ctk.StringVar(
            value=self.config.get("theme") or "dark")
        for opt, lbl in [("dark",   "🌙 Escuro"),
                         ("light",  "☀️ Claro"),
                         ("system", "🖥️ Automático")]:
            ctk.CTkRadioButton(
                theme_row, text=lbl, variable=self._theme_var, value=opt,
                font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
            ).pack(side="left", padx=(12, 0))
        apply_btn = ctk.CTkButton(
            f_theme, text="✓  Aplicar tema", height=30,
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
            text_color=COLORS["text_dim"], corner_radius=8,
            command=lambda: self._apply_theme(self._theme_var.get()))
        apply_btn.pack(fill="x", padx=16, pady=(6, 12))
        add_tooltip(apply_btn,
            "Automático segue o tema claro/escuro configurado no Windows 10/11. "
            "O app precisa ser reiniciado para aplicar o tema completamente.")

        # ── Exportar/Importar configurações ──────────────
        f_ei = self._card(scroll, "📤 Exportar/Importar Configurações")

        # Encryption option
        enc_row = ctk.CTkFrame(f_ei, fg_color="transparent")
        enc_row.pack(fill="x", padx=16, pady=(12, 4))
        self._export_encrypt_var = ctk.BooleanVar(value=False)
        enc_sw = ctk.CTkSwitch(enc_row,
                               text=" 🔒  Criptografar com senha",
                               variable=self._export_encrypt_var,
                               font=ctk.CTkFont(size=12),
                               text_color=COLORS["text_dim"],
                               button_color=COLORS["accent"],
                               progress_color=COLORS["accent"],
                               onvalue=True, offvalue=False)
        enc_sw.pack(side="left")
        if not HAS_CRYPTO:
            ctk.CTkLabel(enc_row, text="(pip install cryptography)",
                         font=ctk.CTkFont(size=10),
                         text_color=COLORS["text_dim2"]).pack(side="left", padx=8)
            enc_sw.configure(state="disabled")
        add_tooltip(enc_sw,
            "Protege o arquivo com senha AES-256. "
            "Útil para backups em nuvem.\n"
            "Requer: pip install cryptography")

        # Password fields
        pwd_frame = ctk.CTkFrame(f_ei, fg_color="transparent")
        pwd_frame.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(pwd_frame, text="Senha:", width=80,
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._export_pwd_var = tk.StringVar()
        ctk.CTkEntry(pwd_frame, textvariable=self._export_pwd_var,
                     show="*", width=160, height=28,
                     font=ctk.CTkFont(size=12),
                     fg_color=COLORS["surface2"],
                     border_color=COLORS["border"],
                     corner_radius=6, text_color=COLORS["text"]
                     ).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(pwd_frame, text="Confirmar:", width=80,
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._export_pwd2_var = tk.StringVar()
        ctk.CTkEntry(pwd_frame, textvariable=self._export_pwd2_var,
                     show="*", width=160, height=28,
                     font=ctk.CTkFont(size=12),
                     fg_color=COLORS["surface2"],
                     border_color=COLORS["border"],
                     corner_radius=6, text_color=COLORS["text"]
                     ).pack(side="left")

        # Export buttons
        exp_row = ctk.CTkFrame(f_ei, fg_color="transparent")
        exp_row.pack(fill="x", padx=16, pady=(4, 4))
        for scope, lbl in [("full",       "📥 Exportar tudo"),
                            ("schedules", "📅 Só agendamentos"),
                            ("conditions","🎯 Só condições")]:
            ctk.CTkButton(exp_row, text=lbl, width=148, height=30,
                          font=ctk.CTkFont(size=11),
                          fg_color=COLORS["surface2"],
                          hover_color=COLORS["surface3"],
                          corner_radius=7, text_color=COLORS["text_dim"],
                          command=lambda s=scope: self._export_config_dialog(s)
                         ).pack(side="left", padx=(0, 6))

        ctk.CTkFrame(f_ei, fg_color=COLORS["border"], height=1).pack(
            fill="x", padx=16, pady=8)

        # Import section
        imp_row = ctk.CTkFrame(f_ei, fg_color="transparent")
        imp_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(imp_row, text="Senha para descriptografar:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._import_pwd_var = tk.StringVar()
        ctk.CTkEntry(imp_row, textvariable=self._import_pwd_var,
                     show="*", width=140, height=28,
                     font=ctk.CTkFont(size=12),
                     fg_color=COLORS["surface2"],
                     border_color=COLORS["border"],
                     corner_radius=6, text_color=COLORS["text"]
                     ).pack(side="left", padx=8)

        imp_btns = ctk.CTkFrame(f_ei, fg_color="transparent")
        imp_btns.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkButton(imp_btns, text="📤 Importar...", width=130, height=30,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      corner_radius=7, text_color="white",
                      command=lambda: self._import_config_dialog(merge=False)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(imp_btns, text="🔀 Mesclar...", width=120, height=30,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=lambda: self._import_config_dialog(merge=True)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(imp_btns, text="🔍 Visualizar", width=120, height=30,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=self._preview_import_dialog
                     ).pack(side="left")

        # Backup restore
        bd = self.config.get_backup_date()
        backup_lbl = f"Último backup automático: {bd}" if bd else "Sem backup automático"
        backup_row = ctk.CTkFrame(f_ei, fg_color="transparent")
        backup_row.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(backup_row, text=backup_lbl,
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left")
        ctk.CTkButton(backup_row, text="↩ Restaurar backup",
                      width=150, height=28,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=self._restore_backup_dialog
                     ).pack(side="right")

        # ── Compartilhamento Social ───────────────────────
        f_share = self._card(scroll, "📊 Compartilhamento Social")
        stats   = self.share.get_stats()

        # Layout selector
        lay_row = ctk.CTkFrame(f_share, fg_color="transparent")
        lay_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(lay_row, text="Layout:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._share_layout_var = ctk.StringVar(value="minimal")
        for val, lbl in [("minimal", "Minimalista"), ("gamer", "Gamer")]:
            ctk.CTkRadioButton(lay_row, text=lbl,
                               variable=self._share_layout_var, value=val,
                               font=ctk.CTkFont(size=12),
                               text_color=COLORS["text_dim"],
                               fg_color=COLORS["accent"],
                               hover_color=COLORS["accent_hover"],
                              ).pack(side="left", padx=(10, 0))

        # Include checkboxes
        inc_row = ctk.CTkFrame(f_share, fg_color="transparent")
        inc_row.pack(fill="x", padx=16, pady=(0, 4))
        self._share_ach_var  = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(inc_row, text="Conquistas",
                        variable=self._share_ach_var,
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_dim"],
                        fg_color=COLORS["accent"],
                        checkbox_width=16, checkbox_height=16,
                        checkmark_color="white",
                        border_color=COLORS["border"],
                        hover_color=COLORS["accent"]
                       ).pack(side="left")

        # Custom text
        ctk.CTkLabel(f_share, text="Texto personalizado (opcional):",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(
                         anchor="w", padx=16, pady=(4, 2))
        self._share_custom_text = ctk.CTkTextbox(
            f_share, height=40,
            fg_color=COLORS["surface2"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=11),
            border_color=COLORS["border"],
            corner_radius=6)
        self._share_custom_text.pack(fill="x", padx=16, pady=(0, 6))

        # Quick stats preview
        summary = (f"  ⏱ {stats['minutes']} min  •  "
                   f"🌿 {stats['co2']} kg CO₂  •  "
                   f"💡 {stats['kwh']} kWh  •  {stats['money']}")
        ctk.CTkLabel(f_share, text=summary,
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(
                         anchor="w", padx=16, pady=(0, 6))

        # Action buttons
        sh_btns = ctk.CTkFrame(f_share, fg_color="transparent")
        sh_btns.pack(fill="x", padx=16, pady=(0, 4))
        for lbl, cmd in [
            ("▶ Gerar",        self._generate_share_card),
            ("💾 Salvar PNG",   self._save_share_card),
            ("📋 Copiar img",   self._copy_share_card),
            ("📋 Copiar texto", self._copy_share_text),
        ]:
            ctk.CTkButton(sh_btns, text=lbl, width=115, height=30,
                          font=ctk.CTkFont(size=11),
                          fg_color=COLORS["surface2"],
                          hover_color=COLORS["surface3"],
                          corner_radius=7, text_color=COLORS["text_dim"],
                          command=cmd
                         ).pack(side="left", padx=(0, 6))

        if not HAS_PIL_SHARE:
            ctk.CTkLabel(f_share,
                         text="⚠  pip install Pillow  para gerar imagens",
                         font=ctk.CTkFont(size=10),
                         text_color=COLORS["warning"]).pack(
                             anchor="w", padx=16, pady=(0, 4))

        self._share_preview_lbl = ctk.CTkLabel(
            f_share, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"])
        self._share_preview_lbl.pack(anchor="w", padx=16, pady=(0, 10))

        # ── Modo Apresentação (Enhanced) ──────────────────────────
        f_pres   = self._card(scroll, "🎭 Modo Apresentação")
        pm_cfg   = self.config.get("presentation_mode") or {}
        triggers = pm_cfg.get("triggers", {})
        weights  = pm_cfg.get("trigger_weights", {})

        pres_top = ctk.CTkFrame(f_pres, fg_color="transparent")
        pres_top.pack(fill="x", padx=16, pady=(12, 6))
        self.pres_mode_var = ctk.BooleanVar(value=pm_cfg.get("enabled", False))
        pres_sw = ctk.CTkSwitch(
            pres_top, text=" 🎭  Ativar Modo Apresentação",
            variable=self.pres_mode_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
            button_color=COLORS["accent2"], progress_color=COLORS["accent2"],
            onvalue=True, offvalue=False,
            command=self._toggle_presentation_mode)
        pres_sw.pack(side="left")
        add_tooltip(pres_sw,
            "Pausa ou notifica quando detecta apresentação ativa. "
            "Suporta 6 gatilhos independentes com pontuação ponderada.")

        pres_badge = ctk.CTkLabel(
            pres_top,
            text="● inativo" if not pm_cfg.get("enabled") else "● monitorando",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"])
        pres_badge.pack(side="right")
        self._pres_status_badge = pres_badge

        # ── Gatilhos com pesos ─────────────────────────────────────
        trg_outer = ctk.CTkFrame(f_pres, fg_color=COLORS["surface2"],
                                  corner_radius=8)
        trg_outer.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(trg_outer, text="Gatilhos  (✔ = habilitado  |  peso = importância)",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(
                         anchor="w", padx=10, pady=(8, 2))

        self._pres_pp_var  = ctk.BooleanVar(value=triggers.get("powerpoint",       True))
        self._pres_ext_var = ctk.BooleanVar(value=triggers.get("external_monitor", True))
        self._pres_vc_var  = ctk.BooleanVar(value=triggers.get("videoconf",        True))
        self._pres_fs_var  = ctk.BooleanVar(value=triggers.get("fullscreen_idle",  False))
        self._pres_mic_var = ctk.BooleanVar(value=triggers.get("microphone",       False))

        self._pres_weight_vars: dict = {}

        _trg_defs = [
            ("powerpoint",       self._pres_pp_var,  "PowerPoint slideshow",             "🖥"),
            ("external_monitor", self._pres_ext_var, "Monitor externo/projetor",         "🔌"),
            ("videoconf",        self._pres_vc_var,  "Videoconferência (Zoom/Teams...)", "📹"),
            ("fullscreen_idle",  self._pres_fs_var,  "Tela cheia + sem interação",       "⬛"),
            ("microphone",       self._pres_mic_var, "Microfone em uso",                 "🎙"),
        ]

        for tid, bvar, tlabel, icon in _trg_defs:
            row = ctk.CTkFrame(trg_outer, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)
            ctk.CTkCheckBox(
                row, text=f"{icon}  {tlabel}",
                variable=bvar,
                font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
                fg_color=COLORS["accent2"], checkbox_width=15,
                checkbox_height=15, checkmark_color="white",
                border_color=COLORS["border"], hover_color=COLORS["accent2"]
            ).pack(side="left")
            # Peso slider
            w_default = float(weights.get(tid, DEFAULT_WEIGHTS.get(tid, 0.8)))
            w_var = ctk.DoubleVar(value=w_default)
            self._pres_weight_vars[tid] = w_var
            w_lbl = ctk.CTkLabel(row, text=f"peso {w_default:.2f}",
                                  font=ctk.CTkFont(size=10),
                                  text_color=COLORS["text_dim2"], width=60)
            w_lbl.pack(side="right", padx=(4, 6))
            sl = ctk.CTkSlider(row, variable=w_var,
                               from_=0.1, to=1.0, width=90,
                               button_color=COLORS["accent2"],
                               progress_color=COLORS["accent2"],
                               fg_color=COLORS["surface3"])
            sl.pack(side="right", padx=(0, 4))
            sl.configure(command=lambda v, lbl=w_lbl, t=tid:
                         lbl.configure(text=f"peso {float(v):.2f}"))

        ctk.CTkFrame(trg_outer, fg_color="transparent", height=4).pack()

        # ── Limiar de decisão ──────────────────────────────────────
        thr_row = ctk.CTkFrame(f_pres, fg_color="transparent")
        thr_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(thr_row, text="Limiar de ativação:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        thr_default = float(pm_cfg.get("decision_threshold", 0.60))
        self._pres_threshold_var = ctk.DoubleVar(value=thr_default)
        thr_lbl = ctk.CTkLabel(thr_row,
                                text=f"{thr_default:.0%}",
                                font=ctk.CTkFont(size=12),
                                text_color=COLORS["accent2"], width=44)
        thr_lbl.pack(side="right")
        thr_sl = ctk.CTkSlider(thr_row, variable=self._pres_threshold_var,
                               from_=0.1, to=1.0, width=120,
                               button_color=COLORS["accent2"],
                               progress_color=COLORS["accent2"],
                               fg_color=COLORS["surface2"])
        thr_sl.pack(side="right", padx=(0, 6))
        thr_sl.configure(command=lambda v:
                         thr_lbl.configure(text=f"{float(v):.0%}"))
        add_tooltip(thr_sl,
            "Porcentagem mínima de confiança para ativar modo apresentação.\n"
            "Mais baixo = ativa mais facilmente. Padrão: 60%.")

        # ── Apps personalizados ────────────────────────────────────
        ctk.CTkLabel(f_pres, text="Processos personalizados (nome.exe, um por linha):",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(
                         anchor="w", padx=16, pady=(4, 2))
        self._pres_apps_text = ctk.CTkTextbox(
            f_pres, height=55,
            fg_color=COLORS["surface2"], text_color=COLORS["text"],
            font=ctk.CTkFont("Courier New", 10),
            border_color=COLORS["border"], corner_radius=6)
        self._pres_apps_text.pack(fill="x", padx=16, pady=(0, 4))
        for app in pm_cfg.get("custom_apps", []):
            name = app if isinstance(app, str) else app.get("name", "")
            if name:
                self._pres_apps_text.insert("end", name + "\n")

        # ── Ação ao detectar ──────────────────────────────────────
        act_row = ctk.CTkFrame(f_pres, fg_color="transparent")
        act_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(act_row, text="Ação:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._pres_action_var = ctk.StringVar(value=pm_cfg.get("action", "pause"))
        for val, lbl in [("pause", "Pausar timer"),
                         ("notify_only", "Apenas notificar")]:
            ctk.CTkRadioButton(act_row, text=lbl,
                               variable=self._pres_action_var, value=val,
                               font=ctk.CTkFont(size=12),
                               text_color=COLORS["text_dim"],
                               fg_color=COLORS["accent2"],
                               hover_color=COLORS["accent2"],
                              ).pack(side="left", padx=(10, 0))

        opts_row = ctk.CTkFrame(f_pres, fg_color="transparent")
        opts_row.pack(fill="x", padx=16, pady=(0, 4))
        self._pres_notify_var = ctk.BooleanVar(
            value=pm_cfg.get("show_notifications", True))
        self._pres_resume_var = ctk.BooleanVar(
            value=pm_cfg.get("resume_on_exit", True))
        for var, text in [
            (self._pres_notify_var, "Mostrar notificação"),
            (self._pres_resume_var, "Retomar ao encerrar"),
        ]:
            ctk.CTkCheckBox(opts_row, text=f"  {text}",
                            variable=var,
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS["text_dim"],
                            fg_color=COLORS["accent2"],
                            checkbox_width=15, checkbox_height=15,
                            checkmark_color="white",
                            border_color=COLORS["border"],
                            hover_color=COLORS["accent2"]
                           ).pack(side="left", padx=(0, 12))

        # ── Botões ────────────────────────────────────────────────
        pres_btns = ctk.CTkFrame(f_pres, fg_color="transparent")
        pres_btns.pack(fill="x", padx=16, pady=(2, 4))
        ctk.CTkButton(pres_btns, text="💾 Salvar",
                      width=100, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["accent2"], hover_color=COLORS["accent"],
                      corner_radius=7, text_color="white",
                      command=self._save_presentation_config
                     ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(pres_btns, text="🔬 Diagnóstico completo",
                      width=180, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=self._test_presentation_detection
                     ).pack(side="left")

        if not HAS_PSUTIL:
            ctk.CTkLabel(f_pres,
                         text="⚠  pip install psutil  para detecção de processos",
                         font=ctk.CTkFont(size=10),
                         text_color=COLORS["warning"]).pack(
                             anchor="w", padx=16, pady=(2, 2))

        # ── Painel de diagnóstico em tempo real ───────────────────
        diag_frame = ctk.CTkFrame(f_pres, fg_color=COLORS["surface2"],
                                   corner_radius=8)
        diag_frame.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(diag_frame, text="Diagnóstico em Tempo Real",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=COLORS["text_dim2"]).pack(anchor="w", padx=8, pady=(6, 2))
        self._pres_diag_text = ctk.CTkTextbox(
            diag_frame, height=80,
            fg_color=COLORS["surface3"],
            text_color=COLORS["text_dim"],
            font=ctk.CTkFont("Courier New", 9),
            state="disabled")
        self._pres_diag_text.pack(fill="x", padx=6, pady=(0, 6))

        self._pres_status_lbl = ctk.CTkLabel(
            f_pres, text="🟢 Aguardando diagnóstico...",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"])
        self._pres_status_lbl.pack(anchor="w", padx=16, pady=(0, 6))

        # ── Seção Calendário ──────────────────────────────────────
        f_cal = self._card(scroll, "📅 Integração com Calendário")
        cal_cfg = self.config.get("calendar_integration") or {}

        cal_top = ctk.CTkFrame(f_cal, fg_color="transparent")
        cal_top.pack(fill="x", padx=16, pady=(12, 6))
        self._cal_enabled_var = ctk.BooleanVar(value=cal_cfg.get("enabled", False))
        cal_sw = ctk.CTkSwitch(
            cal_top, text=" 📅  Integração com Calendário",
            variable=self._cal_enabled_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
            button_color=COLORS["accent2"], progress_color=COLORS["accent2"],
            onvalue=True, offvalue=False,
            command=self._toggle_calendar_integration)
        cal_sw.pack(side="left")
        add_tooltip(cal_sw,
            "Bloqueia ou avisa quando há feriados/eventos no calendário.")

        # Fontes de calendário
        src_frame = ctk.CTkFrame(f_cal, fg_color=COLORS["surface2"],
                                  corner_radius=8)
        src_frame.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(src_frame, text="Fontes de Dados:",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(
                         anchor="w", padx=10, pady=(8, 2))

        sources_cfg = cal_cfg.get("sources", {})

        # Brasil API
        brasil_cfg = sources_cfg.get("brasil_api", {})
        br_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        br_row.pack(fill="x", padx=8, pady=2)
        self._cal_brasil_var = ctk.BooleanVar(
            value=brasil_cfg.get("enabled", False))
        ctk.CTkCheckBox(
            br_row, text="🇧🇷  Feriados Nacionais (BrasilAPI)",
            variable=self._cal_brasil_var,
            font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
            fg_color=COLORS["accent2"], checkbox_width=15,
            checkbox_height=15, checkmark_color="white",
            border_color=COLORS["border"], hover_color=COLORS["accent2"]
        ).pack(side="left")
        if not HAS_REQUESTS:
            ctk.CTkLabel(br_row, text="(pip install requests)",
                         font=ctk.CTkFont(size=9),
                         text_color=COLORS["warning"]).pack(side="left", padx=6)

        # Estado
        st_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        st_row.pack(fill="x", padx=24, pady=(0, 4))
        ctk.CTkLabel(st_row, text="Estado (opcional):",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left", padx=(0, 6))
        state_opts = ["(nenhum)"] + sorted(BRASIL_STATES.keys())
        cur_state  = brasil_cfg.get("state", "") or "(nenhum)"
        self._cal_state_var = ctk.StringVar(value=cur_state)
        ctk.CTkOptionMenu(
            st_row, values=state_opts,
            variable=self._cal_state_var,
            width=100, height=26,
            font=ctk.CTkFont(size=11),
            fg_color=COLORS["surface2"],
            button_color=COLORS["surface3"],
            text_color=COLORS["text_dim"],
        ).pack(side="left")

        # Google Calendar
        gcal_cfg = sources_cfg.get("google", {})
        gc_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        gc_row.pack(fill="x", padx=8, pady=2)
        self._cal_google_var = ctk.BooleanVar(
            value=gcal_cfg.get("enabled", False))
        ctk.CTkCheckBox(
            gc_row, text="🔵  Google Calendar (OAuth2)",
            variable=self._cal_google_var,
            font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
            fg_color=COLORS["accent2"], checkbox_width=15,
            checkbox_height=15, checkmark_color="white",
            border_color=COLORS["border"], hover_color=COLORS["accent2"]
        ).pack(side="left")
        if not HAS_GOOGLE_CAL:
            ctk.CTkLabel(gc_row,
                         text="(pip install google-api-python-client google-auth-oauthlib)",
                         font=ctk.CTkFont(size=9),
                         text_color=COLORS["warning"]).pack(side="left", padx=6)

        # client_secret path
        cs_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        cs_row.pack(fill="x", padx=24, pady=(0, 2))
        ctk.CTkLabel(cs_row, text="client_secret.json:",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left", padx=(0, 6))
        self._cal_secret_var = ctk.StringVar(
            value=gcal_cfg.get("client_secret_path", ""))
        ctk.CTkEntry(cs_row, textvariable=self._cal_secret_var,
                     placeholder_text="Caminho para client_secret.json",
                     height=26, font=ctk.CTkFont(size=10),
                     fg_color=COLORS["surface3"],
                     text_color=COLORS["text_dim"],
                     border_color=COLORS["border"]).pack(
                         side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(cs_row, text="📂", width=28, height=26,
                      font=ctk.CTkFont(size=12),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"],
                      command=self._cal_browse_secret).pack(side="left")

        gc_auth_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        gc_auth_row.pack(fill="x", padx=24, pady=(0, 6))
        self._cal_google_status = ctk.CTkLabel(
            gc_auth_row, text="⬜ Não autenticado",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim2"])
        self._cal_google_status.pack(side="left")
        ctk.CTkButton(gc_auth_row, text="🔑 Conectar",
                      width=90, height=26,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["accent2"],
                      hover_color=COLORS["accent"],
                      text_color="white", corner_radius=6,
                      command=self._cal_google_authenticate
                     ).pack(side="right")
        ctk.CTkButton(gc_auth_row, text="Desconectar",
                      width=90, height=26,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"], corner_radius=6,
                      command=self._cal_google_disconnect
                     ).pack(side="right", padx=(0, 4))

        # ICS
        ics_cfg = sources_cfg.get("ics", {})
        ics_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        ics_row.pack(fill="x", padx=8, pady=2)
        self._cal_ics_var = ctk.BooleanVar(value=ics_cfg.get("enabled", False))
        ctk.CTkCheckBox(
            ics_row, text="📄  Arquivo / URL .ics",
            variable=self._cal_ics_var,
            font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
            fg_color=COLORS["accent2"], checkbox_width=15,
            checkbox_height=15, checkmark_color="white",
            border_color=COLORS["border"], hover_color=COLORS["accent2"]
        ).pack(side="left")
        if not HAS_ICALENDAR:
            ctk.CTkLabel(ics_row,
                         text="(pip install icalendar)",
                         font=ctk.CTkFont(size=9),
                         text_color=COLORS["warning"]).pack(side="left", padx=6)

        ics_path_row = ctk.CTkFrame(src_frame, fg_color="transparent")
        ics_path_row.pack(fill="x", padx=24, pady=(0, 6))
        ctk.CTkLabel(ics_path_row, text="Arquivo/URL:",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="left", padx=(0, 6))
        self._cal_ics_path_var = ctk.StringVar(
            value=ics_cfg.get("path", "") or ics_cfg.get("url", ""))
        ctk.CTkEntry(ics_path_row, textvariable=self._cal_ics_path_var,
                     placeholder_text="Caminho .ics ou https://...",
                     height=26, font=ctk.CTkFont(size=10),
                     fg_color=COLORS["surface3"],
                     text_color=COLORS["text_dim"],
                     border_color=COLORS["border"]).pack(
                         side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(ics_path_row, text="📂", width=28, height=26,
                      font=ctk.CTkFont(size=12),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"],
                      command=self._cal_browse_ics).pack(side="left")

        ctk.CTkFrame(src_frame, fg_color="transparent", height=4).pack()

        # Comportamento
        beh_frame = ctk.CTkFrame(f_cal, fg_color="transparent")
        beh_frame.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(beh_frame, text="Comportamento em dias especiais:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._cal_behavior_var = ctk.StringVar(
            value=cal_cfg.get("behavior", "disable_auto"))
        for val, lbl in [("disable_auto",  "Desativar ação automática"),
                         ("notify_only",   "Apenas notificar"),
                         ("ask_user",      "Perguntar")]:
            ctk.CTkRadioButton(f_cal, text=f"  {lbl}",
                               variable=self._cal_behavior_var, value=val,
                               font=ctk.CTkFont(size=12),
                               text_color=COLORS["text_dim"],
                               fg_color=COLORS["accent2"],
                               hover_color=COLORS["accent2"]
                              ).pack(anchor="w", padx=24, pady=1)

        self._cal_notify_var = ctk.BooleanVar(value=cal_cfg.get("notify", True))
        ctk.CTkCheckBox(f_cal,
                        text="  Notificar quando dia especial detectado",
                        variable=self._cal_notify_var,
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_dim"],
                        fg_color=COLORS["accent2"],
                        checkbox_width=15, checkbox_height=15,
                        checkmark_color="white",
                        border_color=COLORS["border"],
                        hover_color=COLORS["accent2"]
                       ).pack(anchor="w", padx=16, pady=(4, 2))

        # Próximos dias especiais
        ctk.CTkLabel(f_cal, text="Próximos dias especiais:",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(
                         anchor="w", padx=16, pady=(6, 2))
        self._cal_upcoming_text = ctk.CTkTextbox(
            f_cal, height=70,
            fg_color=COLORS["surface2"],
            text_color=COLORS["text_dim"],
            font=ctk.CTkFont("Courier New", 10),
            state="disabled")
        self._cal_upcoming_text.pack(fill="x", padx=16, pady=(0, 4))

        cal_btns = ctk.CTkFrame(f_cal, fg_color="transparent")
        cal_btns.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkButton(cal_btns, text="💾 Salvar",
                      width=100, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["accent2"], hover_color=COLORS["accent"],
                      corner_radius=7, text_color="white",
                      command=self._save_calendar_config
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(cal_btns, text="🔄 Sincronizar",
                      width=110, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=self._cal_sync
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(cal_btns, text="🗑 Limpar cache",
                      width=110, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=self._cal_clear_cache
                     ).pack(side="left")

        self._cal_status_lbl = ctk.CTkLabel(
            f_cal, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"])
        self._cal_status_lbl.pack(anchor="w", padx=16, pady=(0, 10))

        # ── Comandos de Voz ───────────────────────────────
        f_voice = self._card(scroll, "🎤 Comandos de Voz")
        vc_cfg  = self.config.get("voice_commands") or {}

        vc_top = ctk.CTkFrame(f_voice, fg_color="transparent")
        vc_top.pack(fill="x", padx=16, pady=(12, 4))
        self.voice_enabled_var = ctk.BooleanVar(value=vc_cfg.get("enabled", False))
        vc_sw = ctk.CTkSwitch(
            vc_top, text=" 🎤  Comandos de Voz",
            variable=self.voice_enabled_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
            button_color=COLORS["accent2"], progress_color=COLORS["accent2"],
            onvalue=True, offvalue=False,
            command=self._toggle_voice_commands)
        vc_sw.pack(side="left")
        self._voice_status_lbl = ctk.CTkLabel(
            vc_top, text="● inativo",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"])
        self._voice_status_lbl.pack(side="right")

        if not HAS_VOICE:
            ctk.CTkLabel(f_voice,
                text="⚠  pip install SpeechRecognition pyttsx3 pyaudio",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["warning"]).pack(anchor="w", padx=16, pady=(0, 8))
        else:
            # Mode row
            mode_row = ctk.CTkFrame(f_voice, fg_color="transparent")
            mode_row.pack(fill="x", padx=16, pady=(4, 4))
            ctk.CTkLabel(mode_row, text="Modo:",
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_dim"]).pack(side="left")
            self._vc_mode_var = ctk.StringVar(value=vc_cfg.get("mode", "eco"))
            for val, lbl in [("hands_free", "🟢 Sempre ativo"),
                              ("eco",        "⚡ Eco"),
                              ("push_to_talk","🔘 Push-to-talk")]:
                ctk.CTkRadioButton(
                    mode_row, text=lbl, variable=self._vc_mode_var, value=val,
                    font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"],
                    fg_color=COLORS["accent2"], hover_color=COLORS["accent2"],
                    command=self._save_voice_config
                ).pack(side="left", padx=(10, 0))

            # Wake words
            ww_row = ctk.CTkFrame(f_voice, fg_color="transparent")
            ww_row.pack(fill="x", padx=16, pady=(0, 4))
            ctk.CTkLabel(ww_row, text="Palavras de ativação:",
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_dim"]).pack(side="left")
            self._vc_wake_var = tk.StringVar(
                value=", ".join(vc_cfg.get("wake_words",
                                           ["ok timer", "hey shutdown"])))
            ctk.CTkEntry(ww_row, textvariable=self._vc_wake_var,
                         width=220, height=28,
                         font=ctk.CTkFont(size=11),
                         fg_color=COLORS["surface2"],
                         border_color=COLORS["border"],
                         corner_radius=6, text_color=COLORS["text"]
                         ).pack(side="left", padx=8)

            # TTS row
            tts_row = ctk.CTkFrame(f_voice, fg_color="transparent")
            tts_row.pack(fill="x", padx=16, pady=(0, 4))
            self._vc_tts_var = ctk.BooleanVar(value=vc_cfg.get("tts_enabled", True))
            ctk.CTkSwitch(tts_row, text=" 🔊 Feedback de voz (TTS)",
                          variable=self._vc_tts_var,
                          font=ctk.CTkFont(size=12),
                          text_color=COLORS["text_dim"],
                          button_color=COLORS["accent"],
                          progress_color=COLORS["accent"],
                          onvalue=True, offvalue=False,
                          command=self._save_voice_config).pack(side="left")

            # TTS speed
            ctk.CTkLabel(tts_row, text="  Velocidade:",
                         font=ctk.CTkFont(size=11),
                         text_color=COLORS["text_dim"]).pack(side="left")
            self._vc_rate_var = tk.StringVar(
                value=str(vc_cfg.get("tts_rate", 170)))
            ctk.CTkEntry(tts_row, textvariable=self._vc_rate_var,
                         width=46, height=26,
                         font=ctk.CTkFont(size=11),
                         fg_color=COLORS["surface2"],
                         border_color=COLORS["border"],
                         corner_radius=5, text_color=COLORS["text"]
                         ).pack(side="left", padx=4)

            # Announce warnings
            self._vc_warn_var = ctk.BooleanVar(
                value=vc_cfg.get("announce_warnings", True))
            ctk.CTkCheckBox(f_voice, text="  Anunciar avisos de tempo por voz",
                            variable=self._vc_warn_var,
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS["text_dim"],
                            fg_color=COLORS["accent"],
                            checkbox_width=16, checkbox_height=16,
                            checkmark_color="white",
                            border_color=COLORS["border"],
                            hover_color=COLORS["accent"],
                            command=self._save_voice_config
                           ).pack(anchor="w", padx=16, pady=(0, 4))

            # Last command label
            self._vc_last_lbl = ctk.CTkLabel(
                f_voice, text="Último comando: —",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_dim2"])
            self._vc_last_lbl.pack(anchor="w", padx=16, pady=(0, 4))

            # Buttons row
            vc_btns = ctk.CTkFrame(f_voice, fg_color="transparent")
            vc_btns.pack(fill="x", padx=16, pady=(0, 12))
            ctk.CTkButton(vc_btns, text="🎙 Testar microfone",
                          width=150, height=30, font=ctk.CTkFont(size=11),
                          fg_color=COLORS["surface2"],
                          hover_color=COLORS["surface3"],
                          corner_radius=7, text_color=COLORS["text_dim"],
                          command=self._test_microphone_window
                         ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(vc_btns, text="🔊 Testar voz",
                          width=110, height=30, font=ctk.CTkFont(size=11),
                          fg_color=COLORS["surface2"],
                          hover_color=COLORS["surface3"],
                          corner_radius=7, text_color=COLORS["text_dim"],
                          command=lambda: self.voice and self.voice.speak(
                              "Teste de voz funcionando.")
                         ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(vc_btns, text="📋 Comandos",
                          width=110, height=30, font=ctk.CTkFont(size=11),
                          fg_color=COLORS["surface2"],
                          hover_color=COLORS["surface3"],
                          corner_radius=7, text_color=COLORS["text_dim"],
                          command=self._show_voice_commands_popup
                         ).pack(side="left")
            ctk.CTkButton(vc_btns, text="💾 Salvar",
                          width=90, height=30, font=ctk.CTkFont(size=11),
                          fg_color=COLORS["accent"],
                          hover_color=COLORS["accent_hover"],
                          corner_radius=7, text_color="white",
                          command=self._save_voice_config
                         ).pack(side="right")

        # ── Alertas por Email ─────────────────────────────
        f_email = self._card(scroll, "📧 Alertas por Email")
        em_cfg  = self.config.get("email_alerts") or {}

        em_top = ctk.CTkFrame(f_email, fg_color="transparent")
        em_top.pack(fill="x", padx=16, pady=(12, 4))
        self.email_enabled_var = ctk.BooleanVar(value=em_cfg.get("enabled", False))
        em_sw = ctk.CTkSwitch(
            em_top, text=" 📧  Alertas por Email",
            variable=self.email_enabled_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
            button_color=COLORS["accent2"], progress_color=COLORS["accent2"],
            onvalue=True, offvalue=False,
            command=self._toggle_email_alerts)
        em_sw.pack(side="left")
        self._email_status_lbl = ctk.CTkLabel(
            em_top, text="",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"])
        self._email_status_lbl.pack(side="right")

        # Provider selector
        prov_row = ctk.CTkFrame(f_email, fg_color="transparent")
        prov_row.pack(fill="x", padx=16, pady=(4, 4))
        ctk.CTkLabel(prov_row, text="Provedor:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        providers = ["gmail", "outlook", "yahoo", "custom"]
        self._em_provider_var = ctk.StringVar(
            value=em_cfg.get("provider", "gmail"))
        prov_menu = ctk.CTkOptionMenu(
            prov_row, variable=self._em_provider_var,
            values=providers, width=110,
            fg_color=COLORS["surface2"],
            button_color=COLORS["surface3"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=11),
            command=self._on_email_provider_change)
        prov_menu.pack(side="left", padx=8)

        # SMTP fields
        smtp_frame = ctk.CTkFrame(f_email, fg_color=COLORS["surface2"],
                                  corner_radius=8)
        smtp_frame.pack(fill="x", padx=16, pady=(0, 6))

        for cfg_key, lbl_text, width, show in [
            ("smtp_server", "Servidor SMTP:", 200, ""),
            ("smtp_port",   "Porta:",         80,  ""),
            ("email_from",  "De (email):",    200, ""),
        ]:
            row = ctk.CTkFrame(smtp_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(6, 2))
            ctk.CTkLabel(row, text=lbl_text, width=100,
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_dim"],
                         anchor="w").pack(side="left")
            var = tk.StringVar(value=str(em_cfg.get(cfg_key, "")))
            setattr(self, f"_em_{cfg_key}_var", var)
            ctk.CTkEntry(row, textvariable=var, width=width, height=26,
                         font=ctk.CTkFont(size=11),
                         fg_color=COLORS["surface3"],
                         border_color=COLORS["border"],
                         corner_radius=5, text_color=COLORS["text"],
                         show=show).pack(side="left", padx=4)

        # Password row
        pwd_row = ctk.CTkFrame(smtp_frame, fg_color="transparent")
        pwd_row.pack(fill="x", padx=10, pady=(6, 8))
        ctk.CTkLabel(pwd_row, text="Senha / Token:", width=100,
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"],
                     anchor="w").pack(side="left")
        self._em_pwd_var = tk.StringVar()
        ctk.CTkEntry(pwd_row, textvariable=self._em_pwd_var,
                     show="*", width=200, height=26,
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface3"],
                     border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]
                     ).pack(side="left", padx=4)
        ctk.CTkLabel(pwd_row, text="(criptografado)",
                     font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_dim2"]).pack(side="left", padx=4)

        # TLS/SSL
        sec_row = ctk.CTkFrame(f_email, fg_color="transparent")
        sec_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(sec_row, text="Segurança:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._em_sec_var = ctk.StringVar(
            value="tls" if em_cfg.get("use_tls", True) else
                  "ssl" if em_cfg.get("use_ssl", False) else "none")
        for val, lbl in [("tls", "TLS/STARTTLS"), ("ssl", "SSL"), ("none", "Nenhum")]:
            ctk.CTkRadioButton(sec_row, text=lbl,
                               variable=self._em_sec_var, value=val,
                               font=ctk.CTkFont(size=11),
                               text_color=COLORS["text_dim"],
                               fg_color=COLORS["accent2"],
                               hover_color=COLORS["accent2"]
                              ).pack(side="left", padx=(10, 0))

        # Recipients
        rec_row = ctk.CTkFrame(f_email, fg_color="transparent")
        rec_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(rec_row, text="Destinatários:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._em_rec_var = tk.StringVar(
            value=", ".join(em_cfg.get("recipients", [])))
        ctk.CTkEntry(rec_row, textvariable=self._em_rec_var,
                     width=260, height=26,
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface2"],
                     border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]
                     ).pack(side="left", padx=8)

        # Events checkboxes
        ev_frame = ctk.CTkFrame(f_email, fg_color=COLORS["surface2"],
                                corner_radius=8)
        ev_frame.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(ev_frame, text="Enviar email quando:",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(
                         anchor="w", padx=10, pady=(8, 2))
        ev_defs = em_cfg.get("events", {})
        self._em_event_vars = {}
        for ev_key, ev_lbl in [
            ("timer_started",  "Timer iniciado"),
            ("timer_finished", "Timer concluído"),
            ("timer_cancelled","Timer cancelado"),
            ("condition_met",  "Condição atingida"),
            ("smart_action",   "Smart Mode agiu"),
            ("error",          "Erro detectado"),
        ]:
            var = ctk.BooleanVar(value=ev_defs.get(ev_key, ev_key in
                ("timer_finished", "condition_met", "smart_action")))
            self._em_event_vars[ev_key] = var
            ctk.CTkCheckBox(ev_frame, text=f"  {ev_lbl}",
                            variable=var,
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS["text_dim"],
                            fg_color=COLORS["accent2"],
                            checkbox_width=16, checkbox_height=16,
                            checkmark_color="white",
                            border_color=COLORS["border"],
                            hover_color=COLORS["accent2"]
                           ).pack(anchor="w", padx=10, pady=2)
        ctk.CTkFrame(ev_frame, fg_color="transparent", height=4).pack()

        # Rate limit + quiet hours
        rl_row = ctk.CTkFrame(f_email, fg_color="transparent")
        rl_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(rl_row, text="Máx. por hora:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._em_maxph_var = tk.StringVar(
            value=str(em_cfg.get("max_per_hour", 10)))
        ctk.CTkEntry(rl_row, textvariable=self._em_maxph_var,
                     width=46, height=26,
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface2"],
                     border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]
                     ).pack(side="left", padx=6)
        ctk.CTkLabel(rl_row, text="  Silêncio:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._em_qstart_var = tk.StringVar(
            value=em_cfg.get("quiet_hours_start", ""))
        ctk.CTkEntry(rl_row, textvariable=self._em_qstart_var,
                     width=56, height=26, placeholder_text="23:00",
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface2"],
                     border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]
                     ).pack(side="left", padx=4)
        ctk.CTkLabel(rl_row, text="–",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._em_qend_var = tk.StringVar(
            value=em_cfg.get("quiet_hours_end", ""))
        ctk.CTkEntry(rl_row, textvariable=self._em_qend_var,
                     width=56, height=26, placeholder_text="07:00",
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface2"],
                     border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]
                     ).pack(side="left", padx=4)

        # Email action buttons
        em_btns = ctk.CTkFrame(f_email, fg_color="transparent")
        em_btns.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkButton(em_btns, text="💾 Salvar",
                      width=90, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      corner_radius=7, text_color="white",
                      command=self._save_email_config
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(em_btns, text="📡 Testar conexão",
                      width=140, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=self._test_email_connection
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(em_btns, text="✉ Enviar teste",
                      width=120, height=30, font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      corner_radius=7, text_color=COLORS["text_dim"],
                      command=self._test_email_send
                     ).pack(side="left")

        if not HAS_EMAIL:
            ctk.CTkLabel(f_email,
                text="⚠  pip install cryptography  para senhas criptografadas",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["warning"]).pack(anchor="w", padx=16, pady=(0, 4))

        # ── Modo Economia de Energia ──────────────────────
        f_energy  = self._card(scroll, "💡 Modo Economia de Energia")
        en_cfg    = self.config.get("energy_saver") or {}
        _is_win   = (HAS_ENERGY and self.energy and
                     getattr(self.energy, "is_available", False))

        en_top = ctk.CTkFrame(f_energy, fg_color="transparent")
        en_top.pack(fill="x", padx=16, pady=(12, 4))
        self.energy_enabled_var = ctk.BooleanVar(value=en_cfg.get("enabled", False))
        en_sw = ctk.CTkSwitch(
            en_top, text=" 💡  Modo Economia de Energia",
            variable=self.energy_enabled_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
            button_color=COLORS["accent2"], progress_color=COLORS["accent2"],
            onvalue=True, offvalue=False,
            command=self._toggle_energy_saver)
        en_sw.pack(side="left")
        self._energy_plan_lbl = ctk.CTkLabel(
            en_top, text="",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"])
        self._energy_plan_lbl.pack(side="right")
        if not _is_win:
            en_sw.configure(state="disabled")
            ctk.CTkLabel(f_energy,
                text="ℹ  Disponível apenas no Windows (powercfg).",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_dim2"]).pack(
                    anchor="w", padx=16, pady=(0, 8))
        else:
            # Get available power plans
            try:
                from features.energy_saver import get_available_plans
                avail_plans = get_available_plans()
            except Exception:
                avail_plans = []
            plan_names = [p["name"] for p in avail_plans] or [
                "Economia", "Balanceado", "Alto Desempenho"]
            plan_guids = {p["name"]: p["guid"] for p in avail_plans}

            # Build a key→name lookup for resolving stored config values
            plan_key_to_name = {p["key"]: p["name"] for p in avail_plans}

            eco_row = ctk.CTkFrame(f_energy, fg_color="transparent")
            eco_row.pack(fill="x", padx=16, pady=(0, 4))
            ctk.CTkLabel(eco_row, text="Plano economia:",
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_dim"]).pack(side="left")
            _eco_stored = en_cfg.get("economy_plan", "power_saver")
            _eco_default = (plan_key_to_name.get(_eco_stored)
                            or _eco_stored
                            or (plan_names[0] if plan_names else ""))
            self._en_eco_var = ctk.StringVar(value=_eco_default)
            ctk.CTkOptionMenu(eco_row, variable=self._en_eco_var,
                              values=plan_names, width=160,
                              fg_color=COLORS["surface2"],
                              button_color=COLORS["surface3"],
                              text_color=COLORS["text"],
                              font=ctk.CTkFont(size=11),
                              command=lambda _: self._save_energy_config()
                             ).pack(side="left", padx=8)

            # High-perf plan
            hp_row = ctk.CTkFrame(f_energy, fg_color="transparent")
            hp_row.pack(fill="x", padx=16, pady=(0, 4))
            ctk.CTkLabel(hp_row, text="Plano alto desempenho:",
                         font=ctk.CTkFont(size=12),
                         text_color=COLORS["text_dim"]).pack(side="left")
            _hp_stored = en_cfg.get("high_performance_plan", "high_performance")
            _hp_default = (plan_key_to_name.get(_hp_stored)
                           or _hp_stored
                           or (plan_names[-1] if plan_names else ""))
            self._en_hp_var = ctk.StringVar(value=_hp_default)
            ctk.CTkOptionMenu(hp_row, variable=self._en_hp_var,
                              values=plan_names, width=160,
                              fg_color=COLORS["surface2"],
                              button_color=COLORS["surface3"],
                              text_color=COLORS["text"],
                              font=ctk.CTkFont(size=11),
                              command=lambda _: self._save_energy_config()
                             ).pack(side="left", padx=8)

            # Thresholds
            th_frame = ctk.CTkFrame(f_energy, fg_color=COLORS["surface2"],
                                    corner_radius=8)
            th_frame.pack(fill="x", padx=16, pady=(0, 6))
            for cfg_key, lbl_text, default in [
                ("economy_threshold_minutes", "Ativar economia se timer ≥ (min):", 10),
                ("idle_threshold_minutes",    "Detecção de inatividade (min):",      5),
                ("prepare_minutes",           "Restaurar desempenho antes (min):",   2),
            ]:
                row = ctk.CTkFrame(th_frame, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=(6, 2))
                ctk.CTkLabel(row, text=lbl_text,
                             font=ctk.CTkFont(size=12),
                             text_color=COLORS["text_dim"]).pack(side="left")
                var = tk.StringVar(value=str(en_cfg.get(cfg_key, default)))
                setattr(self, f"_en_{cfg_key}_var", var)
                ctk.CTkEntry(row, textvariable=var,
                             width=56, height=26,
                             font=ctk.CTkFont(size=11),
                             fg_color=COLORS["surface3"],
                             border_color=COLORS["border"],
                             corner_radius=5, text_color=COLORS["text"]
                             ).pack(side="left", padx=8)
            ctk.CTkFrame(th_frame, fg_color="transparent", height=4).pack()

            # Restore on activity
            self._en_restore_var = ctk.BooleanVar(
                value=en_cfg.get("restore_on_activity", True))
            ctk.CTkCheckBox(f_energy,
                            text="  Restaurar desempenho ao detectar atividade",
                            variable=self._en_restore_var,
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS["text_dim"],
                            fg_color=COLORS["accent2"],
                            checkbox_width=16, checkbox_height=16,
                            checkmark_color="white",
                            border_color=COLORS["border"],
                            hover_color=COLORS["accent2"],
                            command=self._save_energy_config
                           ).pack(anchor="w", padx=16, pady=(0, 4))

            # Stats estimate
            if self.energy:
                stats_e = self.energy.get_stats_estimate()
                ctk.CTkLabel(f_energy,
                    text=(f"Estimativa: ~{stats_e.get('saving_pct', 0)}% economia  •  "
                          f"~{stats_e.get('kwh_month', 0)} kWh/mês"),
                    font=ctk.CTkFont(size=11),
                    text_color=COLORS["text_dim2"]).pack(
                        anchor="w", padx=16, pady=(0, 4))

                # Current plan label
                self._energy_plan_lbl.configure(
                    text=self.energy.get_current_plan_label())

            # Action buttons
            en_btns = ctk.CTkFrame(f_energy, fg_color="transparent")
            en_btns.pack(fill="x", padx=16, pady=(4, 12))
            ctk.CTkButton(en_btns, text="💾 Salvar",
                          width=90, height=30, font=ctk.CTkFont(size=11),
                          fg_color=COLORS["accent"],
                          hover_color=COLORS["accent_hover"],
                          corner_radius=7, text_color="white",
                          command=self._save_energy_config
                         ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(en_btns, text="🔄 Testar alternância",
                          width=160, height=30, font=ctk.CTkFont(size=11),
                          fg_color=COLORS["surface2"],
                          hover_color=COLORS["surface3"],
                          corner_radius=7, text_color=COLORS["text_dim"],
                          command=self._test_energy_cycle
                         ).pack(side="left")

    @staticmethod
    def _gamer_proc_text(procs: list) -> str:
        n = len(procs)
        if n == 0: return "Nenhum processo monitorado"
        if n == 1: return f"1 processo: {procs[0]}"
        return f"{n} processos: {', '.join(procs[:2])}{'...' if n > 2 else ''}"

    def _save_gamer_idle(self):
        try:
            v = int(self._gamer_idle_var.get())
            self.config.set("gamer_idle_threshold", v)
        except ValueError:
            pass

    # ── Handlers — Voice Commands ─────────────────────────

    def _toggle_voice_commands(self):
        enabled = self.voice_enabled_var.get()
        vc_cfg  = dict(self.config.get("voice_commands") or {})
        vc_cfg["enabled"] = enabled
        self.config.set("voice_commands", vc_cfg)
        if self.voice:
            if enabled:
                ok = self.voice.start()
                if not ok:
                    self.voice_enabled_var.set(False)
                    vc_cfg["enabled"] = False
                    self.config.set("voice_commands", vc_cfg)
                    messagebox.showerror(
                        "Comandos de Voz",
                        "Não foi possível iniciar o reconhecimento de voz.\n"
                        "Verifique se o microfone está conectado e se as "
                        "dependências estão instaladas:\n"
                        "pip install SpeechRecognition pyttsx3 pyaudio")
            else:
                self.voice.stop()

    def _save_voice_config(self):
        if not hasattr(self, "_vc_mode_var"):
            return
        vc_cfg = dict(self.config.get("voice_commands") or {})
        vc_cfg["mode"]              = self._vc_mode_var.get()
        vc_cfg["wake_words"]        = [
            w.strip() for w in self._vc_wake_var.get().split(",") if w.strip()]
        vc_cfg["tts_enabled"]       = self._vc_tts_var.get()
        vc_cfg["announce_warnings"] = self._vc_warn_var.get()
        try:
            vc_cfg["tts_rate"] = int(self._vc_rate_var.get())
        except ValueError:
            pass
        self.config.set("voice_commands", vc_cfg)
        if self.voice:
            self.voice._cfg = vc_cfg  # live-update without restart
        self._status("✓  Configurações de voz salvas.", COLORS["success"])

    def _test_microphone_window(self):
        if not self.voice:
            messagebox.showinfo("Microfone",
                "Módulo de voz não disponível.\n"
                "pip install SpeechRecognition pyttsx3 pyaudio")
            return
        win = ctk.CTkToplevel(self.root)
        win.title("🎙 Teste de microfone")
        win.geometry("420x240")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkLabel(win, text="Fale algo para testar o microfone...",
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["text"]).pack(pady=(20, 10))

        level_bar = ctk.CTkProgressBar(win, width=360, height=18,
                                       progress_color=COLORS["accent2"])
        level_bar.pack(pady=(0, 10))
        level_bar.set(0)

        result_lbl = ctk.CTkLabel(win, text="Aguardando...",
                                  font=ctk.CTkFont(size=12),
                                  text_color=COLORS["text_dim"],
                                  wraplength=380)
        result_lbl.pack(pady=(0, 10))

        def on_result(text, level):
            level_bar.set(min(1.0, level / 100.0))
            result_lbl.configure(
                text=f"Reconhecido: {text}" if text else "Nada detectado.",
                text_color=COLORS["success"] if text else COLORS["warning"])

        self.voice.test_microphone(on_result)

        ctk.CTkButton(win, text="Fechar", width=100, height=32,
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"],
                      command=win.destroy).pack(pady=(0, 16))

    def _on_voice_status(self, state: str, message: str):
        if not hasattr(self, "_voice_status_lbl"):
            return
        color_map = {
            "listening":    COLORS["success"],
            "processing":   COLORS["accent2"],
            "idle":         COLORS["text_dim"],
            "error":        COLORS["danger"],
            "stopped":      COLORS["text_dim"],
        }
        color = color_map.get(state, COLORS["text_dim"])
        icons = {
            "listening":  "● ouvindo",
            "processing": "◌ processando",
            "idle":       "● inativo",
            "error":      "⚠ erro",
            "stopped":    "● parado",
        }
        self._voice_status_lbl.configure(
            text=icons.get(state, f"● {state}"),
            text_color=color)

    def _on_voice_command(self, command: str, text: str, minutes):
        if hasattr(self, "_vc_last_lbl"):
            self._vc_last_lbl.configure(
                text=f"Último comando: {command} — \"{text}\"",
                text_color=COLORS["text_dim"])

    def _show_voice_commands_popup(self):
        """Abre um popup listando todos os comandos de voz disponíveis."""
        win = ctk.CTkToplevel(self.root)
        win.title("📋 Comandos de Voz")
        win.geometry("520x560")
        win.resizable(False, True)
        win.grab_set()

        # ── Cabeçalho ─────────────────────────────────────────────────
        hdr = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="📋  Comandos de Voz Disponíveis",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=COLORS["text"]).pack(pady=(14, 4))
        vc_cfg = self.config.get("voice_commands") or {}
        wake_words = vc_cfg.get("wake_words", ["ok timer", "hey shutdown"])
        wake_str   = "  /  ".join(f'"{w}"' for w in wake_words)
        ctk.CTkLabel(hdr,
                     text=f"Palavras de ativação: {wake_str}",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(pady=(0, 12))

        # ── Tabela scrollável ──────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(
            win, fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["surface2"],
            scrollbar_button_hover_color=COLORS["surface3"])
        scroll.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        # Dados: (categoria, [(exemplo_pt, exemplo_en, descrição)])
        sections = [
            ("⏱  Timer", [
                ("iniciar 30 minutos",    "start 30 minutes",    "Inicia o timer"),
                ("cancelar",              "cancel / stop",       "Cancela o timer ativo"),
                ("pausar",                "pause",               "Pausa o timer"),
                ("retomar",               "resume / continue",   "Retoma o timer pausado"),
                ("adicionar 5 minutos",   "add 5 minutes",       "Estende o timer"),
                ("quanto tempo falta",    "how much time left",  "Lê o tempo restante"),
            ]),
            ("⚡  Ações rápidas", [
                ("desligar em 20 minutos","shutdown in 20 min",  "Agenda desligamento"),
                ("suspender em 10 minutos","suspend in 10 min",  "Agenda suspensão"),
                ("reiniciar em 5 minutos","reboot in 5 minutes", "Agenda reinicialização"),
            ]),
            ("ℹ️  Status", [
                ("status",                "status",              "Fala o estado atual"),
                ("tempo restante",        "time left",           "Tempo restante em voz"),
            ]),
        ]

        # Cabeçalho da tabela
        def _hdr_row(parent):
            row = ctk.CTkFrame(parent, fg_color=COLORS["surface2"],
                               corner_radius=6)
            row.pack(fill="x", pady=(0, 4))
            for txt, w in [("Português", 180), ("Inglês", 160), ("O que faz", 140)]:
                ctk.CTkLabel(row, text=txt, width=w,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=COLORS["text_dim2"],
                             anchor="w").pack(side="left", padx=8, pady=6)

        for category, cmds in sections:
            # Título da categoria
            ctk.CTkLabel(scroll, text=category,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=COLORS["accent2"]).pack(
                             anchor="w", padx=4, pady=(10, 2))
            _hdr_row(scroll)
            for i, (pt, en, desc) in enumerate(cmds):
                bg = COLORS["surface"] if i % 2 == 0 else COLORS["surface2"]
                row = ctk.CTkFrame(scroll, fg_color=bg, corner_radius=6)
                row.pack(fill="x", pady=1)
                for txt, w in [(f'"{pt}"', 180), (f'"{en}"', 160), (desc, 140)]:
                    ctk.CTkLabel(row, text=txt, width=w,
                                 font=ctk.CTkFont("Courier New", 10)
                                 if txt.startswith('"') else ctk.CTkFont(size=11),
                                 text_color=COLORS["text"]
                                 if txt.startswith('"') else COLORS["text_dim"],
                                 anchor="w").pack(side="left", padx=8, pady=5)

        # Nota sobre modos
        note = ctk.CTkFrame(win, fg_color=COLORS["surface2"], corner_radius=8)
        note.pack(fill="x", padx=12, pady=(4, 4))
        ctk.CTkLabel(note,
                     text=("💡  Modo Eco: diga a palavra de ativação antes do comando.\n"
                           "     Modo Sempre ativo: fale o comando diretamente.\n"
                           "     Push-to-talk: pressione o atalho configurado e fale."),
                     font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_dim2"],
                     justify="left").pack(anchor="w", padx=12, pady=8)

        # Botão fechar
        ctk.CTkButton(win, text="Fechar", width=110, height=32,
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"],
                      corner_radius=8,
                      command=win.destroy).pack(pady=(4, 14))

    # ── Handlers — Email Alerts ───────────────────────────

    def _toggle_email_alerts(self):
        enabled = self.email_enabled_var.get()
        em_cfg  = dict(self.config.get("email_alerts") or {})
        em_cfg["enabled"] = enabled
        self.config.set("email_alerts", em_cfg)

    def _on_email_provider_change(self, provider: str):
        """Auto-fill SMTP settings when provider changes."""
        if not HAS_EMAIL:
            return
        try:
            from features.email_notifier import EMAIL_PROVIDERS
            info = EMAIL_PROVIDERS.get(provider, {})
            if info.get("smtp") and hasattr(self, "_em_smtp_server_var"):
                self._em_smtp_server_var.set(info["smtp"])
                self._em_smtp_port_var.set(str(info.get("port", 587)))
                sec = "ssl" if info.get("ssl") else "tls" if info.get("tls") else "none"
                if hasattr(self, "_em_sec_var"):
                    self._em_sec_var.set(sec)
        except Exception:
            pass

    def _save_email_config(self):
        em_cfg = dict(self.config.get("email_alerts") or {})
        if hasattr(self, "_em_provider_var"):
            em_cfg["provider"]    = self._em_provider_var.get()
        if hasattr(self, "_em_smtp_server_var"):
            em_cfg["smtp_server"] = self._em_smtp_server_var.get()
        if hasattr(self, "_em_smtp_port_var"):
            try:    em_cfg["smtp_port"] = int(self._em_smtp_port_var.get())
            except ValueError: pass
        if hasattr(self, "_em_email_from_var"):
            em_cfg["email_from"]  = self._em_email_from_var.get()
        if hasattr(self, "_em_sec_var"):
            sec = self._em_sec_var.get()
            em_cfg["use_tls"] = (sec == "tls")
            em_cfg["use_ssl"] = (sec == "ssl")
        if hasattr(self, "_em_rec_var"):
            em_cfg["recipients"] = [
                r.strip() for r in self._em_rec_var.get().split(",") if r.strip()]
        if hasattr(self, "_em_event_vars"):
            em_cfg["events"] = {k: v.get() for k, v in self._em_event_vars.items()}
        if hasattr(self, "_em_maxph_var"):
            try:    em_cfg["max_per_hour"] = int(self._em_maxph_var.get())
            except ValueError: pass
        if hasattr(self, "_em_qstart_var"):
            em_cfg["quiet_hours_start"] = self._em_qstart_var.get()
        if hasattr(self, "_em_qend_var"):
            em_cfg["quiet_hours_end"]   = self._em_qend_var.get()
        self.config.set("email_alerts", em_cfg)
        # Save password encrypted
        if self.email_notif and hasattr(self, "_em_pwd_var"):
            pwd = self._em_pwd_var.get()
            if pwd:
                self.email_notif.save_password(pwd)
        self._status("✓  Configurações de email salvas.", COLORS["success"])
        if hasattr(self, "_email_status_lbl"):
            self._email_status_lbl.configure(
                text="✓ salvo", text_color=COLORS["success"])
            self.root.after(3000, lambda: hasattr(self, "_email_status_lbl")
                and self._email_status_lbl.configure(text=""))

    def _test_email_connection(self):
        if not self.email_notif:
            messagebox.showinfo("Email", "Módulo de email não disponível.")
            return
        self._save_email_config()
        if hasattr(self, "_email_status_lbl"):
            self._email_status_lbl.configure(
                text="⏳ testando...", text_color=COLORS["text_dim"])

        def _run():
            ok, msg = self.email_notif.test_connection()
            self.root.after(0, lambda: (
                hasattr(self, "_email_status_lbl") and
                self._email_status_lbl.configure(
                    text="✓ conectado" if ok else f"✗ erro",
                    text_color=COLORS["success"] if ok else COLORS["danger"]),
                messagebox.showinfo(
                    "Teste de Conexão",
                    f"{'✓ Conexão bem-sucedida!' if ok else '✗ Falha na conexão'}\n\n{msg}")
            ))
        import threading as _t
        _t.Thread(target=_run, daemon=True).start()

    def _test_email_send(self):
        if not self.email_notif:
            messagebox.showinfo("Email", "Módulo de email não disponível.")
            return
        self._save_email_config()
        if hasattr(self, "_email_status_lbl"):
            self._email_status_lbl.configure(
                text="⏳ enviando...", text_color=COLORS["text_dim"])

        def _run():
            ok, msg = self.email_notif.send_test()
            self.root.after(0, lambda: (
                hasattr(self, "_email_status_lbl") and
                self._email_status_lbl.configure(
                    text="✓ enviado" if ok else "✗ falha",
                    text_color=COLORS["success"] if ok else COLORS["danger"]),
                messagebox.showinfo(
                    "Email de Teste",
                    f"{'✓ Email enviado com sucesso!' if ok else '✗ Falha ao enviar'}\n\n{msg}")
            ))
        import threading as _t
        _t.Thread(target=_run, daemon=True).start()

    # ── Handlers — Energy Saver ───────────────────────────

    def _toggle_energy_saver(self):
        enabled = self.energy_enabled_var.get()
        en_cfg  = dict(self.config.get("energy_saver") or {})
        en_cfg["enabled"] = enabled
        self.config.set("energy_saver", en_cfg)

    def _save_energy_config(self):
        en_cfg = dict(self.config.get("energy_saver") or {})
        if hasattr(self, "_en_eco_var"):
            en_cfg["economy_plan"]          = self._en_eco_var.get()
        if hasattr(self, "_en_hp_var"):
            en_cfg["high_performance_plan"] = self._en_hp_var.get()
        for key in ("economy_threshold_minutes",
                    "idle_threshold_minutes",
                    "prepare_minutes"):
            attr = f"_en_{key}_var"
            if hasattr(self, attr):
                try:    en_cfg[key] = int(getattr(self, attr).get())
                except ValueError: pass
        if hasattr(self, "_en_restore_var"):
            en_cfg["restore_on_activity"] = self._en_restore_var.get()
        self.config.set("energy_saver", en_cfg)
        self._status("✓  Configurações de energia salvas.", COLORS["success"])

    def _test_energy_cycle(self):
        if not self.energy:
            messagebox.showinfo("Energia", "Módulo de energia não disponível.")
            return
        if hasattr(self, "_energy_plan_lbl"):
            self._energy_plan_lbl.configure(
                text="⏳ testando...", text_color=COLORS["text_dim"])

        def _run():
            ok, msg = self.energy.test_cycle()
            self.root.after(0, lambda: (
                hasattr(self, "_energy_plan_lbl") and
                self._energy_plan_lbl.configure(
                    text=self.energy.get_current_plan_label(),
                    text_color=COLORS["text_dim"]),
                messagebox.showinfo(
                    "Teste de Alternância",
                    f"{'✓ Teste concluído!' if ok else '✗ Teste falhou'}\n\n{msg}")
            ))
        import threading as _t
        _t.Thread(target=_run, daemon=True).start()

    def _on_energy_plan_change(self, plan_key: str, reason: str):
        if hasattr(self, "_energy_plan_lbl") and self.energy:
            label = self.energy.get_current_plan_label()
            self._energy_plan_lbl.configure(
                text=label, text_color=COLORS["text_dim"])
        self._status(f"💡  Plano de energia: {plan_key} — {reason}",
                     COLORS["text_dim"])

    def _on_energy_message(self, text: str):
        self._status(f"💡  {text}", COLORS["text_dim"])

    # ══════════════════════════════════════════════════════
    # HELPERS DE CONSTRUÇÃO
    # ══════════════════════════════════════════════════════

    def _card(self, parent, title: str) -> ctk.CTkFrame:
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.pack(fill="x", padx=16, pady=(0, 10))
        if title:
            ctk.CTkLabel(outer, text=title, font=ctk.CTkFont(size=11),
                         text_color=COLORS["text_dim2"]).pack(anchor="w", pady=(0, 4))
        inner = ctk.CTkFrame(outer, fg_color=COLORS["surface"], corner_radius=10)
        inner.pack(fill="x")
        return inner

    def _switch(self, parent, text: str, var: ctk.BooleanVar,
                cmd=None, bottom: int = 6):
        sw = ctk.CTkSwitch(parent, text=f" {text}", variable=var,
                           font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
                           button_color=COLORS["accent"],
                           progress_color=COLORS["accent"],
                           onvalue=True, offvalue=False)
        if cmd: sw.configure(command=cmd)
        sw.pack(anchor="w", padx=16, pady=(8, bottom))
        return sw

    # ── Modo countdown / schedule ─────────────────────────

    def _set_mode(self, mode: str):
        self.mode_var.set(mode)
        for k, btn in self._mode_btns.items():
            btn.configure(
                fg_color=COLORS["accent"] if k == mode else COLORS["surface2"],
                text_color="white"          if k == mode else COLORS["text"])
        if mode == "countdown":
            self._sc_frame.pack_forget()
            self._cd_frame.pack(fill="x", padx=16, pady=(0, 4))
        else:
            self._cd_frame.pack_forget()
            self._sc_frame.pack(fill="x", padx=16, pady=(0, 4))
            self._update_sched_info()

    def _update_sched_info(self):
        try:
            h = int(self.sched_h.get()); m = int(self.sched_m.get())
            assert 0 <= h <= 23 and 0 <= m <= 59
            now    = datetime.now()
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now: target += timedelta(days=1)
            diff   = int((target - now).total_seconds() / 60)
            self._sched_info.configure(
                text=f"→ em {diff} min  ({target.strftime('%H:%M')})")
        except Exception:
            self._sched_info.configure(text="Horário inválido")

    def _compute_seconds(self) -> Optional[int]:
        if self.mode_var.get() == "countdown":
            m = self._parse_minutes()
            return m * 60 if m else None
        try:
            h = int(self.sched_h.get()); m = int(self.sched_m.get())
            assert 0 <= h <= 23 and 0 <= m <= 59
            now    = datetime.now()
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now: target += timedelta(days=1)
            self.config.set("schedule_hour", h)
            self.config.set("schedule_minute", m)
            return int((target - now).total_seconds())
        except Exception:
            return None

    # ── Apply config ──────────────────────────────────────

    def _apply_config(self):
        self._select_action(self.config.get("last_action"))
        self._set_mode(self.config.get("schedule_mode"))

    def _apply_preset(self, m: int):
        self.time_var.set(str(m)); self._set_mode("countdown")
        self._validate_live()

    def _select_action(self, key: str):
        self.action_var.set(key)
        for k, btn in self._action_buttons.items():
            btn.configure(
                fg_color=COLORS["accent"] if k == key else COLORS["surface2"],
                text_color="white"          if k == key else COLORS["text"])

    def _validate_live(self, e=None):
        val = self.time_var.get().strip()
        ok  = val.isdigit() and 1 <= int(val) <= 1440
        self.time_entry.configure(
            border_color=COLORS["border"] if ok else COLORS["danger"])

    def _parse_minutes(self) -> Optional[int]:
        val = self.time_var.get().strip()
        if not val.isdigit(): return None
        m = int(val)
        return m if 1 <= m <= 1440 else None

    @staticmethod
    def _fmt(s: int) -> str:
        h = s // 3600; m = (s % 3600) // 60; sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    def _status(self, text: str, color: str = COLORS["text_dim"]):
        if self.status_label.winfo_exists():
            self.status_label.configure(text=text, text_color=color)

    def _update_display(self, s: int):
        self.timer_label.configure(text=self._fmt(s))
        self.progress_bar.set(self.engine.progress)
        c = (COLORS["danger"]  if s <= 30  else
             COLORS["warning"] if s <= 300 else COLORS["text"])
        self.timer_label.configure(text_color=c)
        self.progress_bar.configure(
            progress_color=c if s <= 300 else COLORS["accent"])
        self.tray.update(True, s)

    # ── Controle do timer ─────────────────────────────────

    def _start_or_stop(self):
        if self.engine.is_running: self._cancel()
        else:                       self._start()

    def _start(self):
        seconds = self._compute_seconds()
        if seconds is None:
            messagebox.showerror("Entrada inválida",
                "Verifique o tempo ou horário digitado.")
            return

        action  = self.action_var.get()
        minutes = seconds // 60

        self.config.set("last_minutes",     minutes)
        self.config.set("last_action",      action)
        self.config.set("schedule_mode",    self.mode_var.get())
        self.config.set("gamer_mode",       self.gamer_var.get())
        self.config.set("sound_warning",    self.sound_var.get())
        self.config.set("adaptive_enabled", self.adaptive_var.get())
        try: self.config.set("adaptive_extend_min", int(self.adaptive_ext.get()))
        except ValueError: pass

        if not self.engine.start(seconds, action): return

        # ── Feature module hooks ───────────────────────────────────
        if self.energy:
            self.energy.on_timer_start(seconds)
        if self.email_notif:
            self.email_notif.send_event(
                "timer_started",
                action=ACTION_LABELS.get(action, action),
                minutes=minutes,
                time=datetime.now().strftime("%H:%M"))

        # Prevent sleep if enabled
        if self.prevent_sleep_var.get():
            SystemController.prevent_sleep(True)

        self.start_btn.configure(
            text="⏹  Cancelar",
            fg_color=COLORS["danger"], hover_color="#d94040")
        self.pause_btn.configure(state="normal")
        self.extend5_btn.configure(state="normal")
        self.time_entry.configure(state="disabled")
        for btn in self._action_buttons.values():
            btn.configure(state="disabled")

        icon = ACTION_ICONS.get(action, "⏻")
        if self.mode_var.get() == "schedule":
            h = int(self.sched_h.get()); m2 = int(self.sched_m.get())
            self._status(
                f"{icon}  {ACTION_LABELS[action]} às {h:02d}:{m2:02d}",
                COLORS["text"])
        else:
            self._status(
                f"{icon}  {ACTION_LABELS[action]} em {minutes}min",
                COLORS["text"])
        self._update_display(seconds)

        if self.gamer_var.get():
            self._gamer_id = self.root.after(5000, self._gamer_check)

    def _hotkey_start(self):
        if not self.engine.is_running: self._start()

    def _cancel(self):
        self.engine.cancel()
        self.cond_mon.stop()
        SystemController.prevent_sleep(False)
        for aid in [self._gamer_id, self._countdown_id]:
            if aid:
                try: self.root.after_cancel(aid)
                except Exception: pass
        self._gamer_id = self._countdown_id = None

    def _pause_resume(self):
        paused = self.engine.pause_resume()
        self.pause_btn.configure(
            text="▶  Retomar" if paused else "⏸  Pausar")

    def _extend_5min(self):
        """Estende o timer ativo em 5 minutos."""
        if not self.engine.is_running: return
        self.engine.extend(300)
        self._status("⏱  Timer estendido +5min", COLORS["success"])

    def _reset_ui(self):
        self.start_btn.configure(text="▶  Iniciar",
                                 fg_color=COLORS["accent"],
                                 hover_color=COLORS["accent_hover"])
        self.pause_btn.configure(text="⏸  Pausar", state="disabled")
        self.extend5_btn.configure(state="disabled")
        self.time_entry.configure(state="normal")
        for btn in self._action_buttons.values():
            btn.configure(state="normal")
        self._select_action(self.action_var.get())
        self.timer_label.configure(text="--:--", text_color=COLORS["text_dim"])
        self.progress_bar.set(0)
        self.progress_bar.configure(progress_color=COLORS["accent"])
        self.tray.update(False)

    # ── Engine callbacks ──────────────────────────────────

    def _on_tick(self, s: int):
        self._update_display(s)
        if self.energy:
            self.energy.on_timer_tick(s)
        if (self.adaptive_var.get() and s <= 120
                and SystemController.get_idle_seconds() < 30):
            try: ext = int(self.adaptive_ext.get()) * 60
            except ValueError: ext = 600
            self.engine.extend(ext)
            self._status(f"🖱  Atividade detectada → +{ext//60}min",
                         COLORS["warning"])

    def _on_warning(self, s: int):
        mins = s // 60
        txt  = (f"⚠  Atenção: restam {mins}min!" if mins
                else f"⚠  Restam {s}s!")
        self._status(txt, COLORS["warning"])
        if s in (300, 60):
            sound = self.sound_var.get()
            action_label = ACTION_LABELS.get(
                self.engine.state.action, "Ação")
            self.notif.warn(
                "ShutdownTimer ⚠",
                f"{action_label} em {mins or s}{'min' if mins else 's'}",
                sound=sound)
        # Voice TTS announcement
        vc_cfg = self.config.get("voice_commands") or {}
        if self.voice and vc_cfg.get("announce_warnings", True):
            faltam = f"{mins} minuto{'s' if mins != 1 else ''}" if mins else f"{s} segundos"
            self.voice.speak(f"Atenção: faltam {faltam}.")

    def _on_finished(self):
        action  = self.engine.state.action
        label   = ACTION_LABELS.get(action, action)
        minutes = self.engine.state.total_seconds // 60

        self.notif.warn(
            f"⚠  {label} em 15 segundos",
            "Abra o ShutdownTimer para cancelar.",
            sound=self.sound_var.get())

        cancelled = self._show_countdown_dialog(action, label)
        if cancelled:
            self.config.add_history(action, minutes, completed=False)
            self._status("✓  Ação cancelada.", COLORS["success"])
        else:
            self.config.add_history(action, minutes, completed=True)
            self._status("Executando ação...", COLORS["warning"])
            self.root.after(300, SystemController.execute, action)

        # ── Feature module hooks ───────────────────────────────────
        if self.energy:
            self.energy.on_timer_end()
        if self.email_notif:
            ev = "timer_cancelled" if cancelled else "timer_finished"
            self.email_notif.send_event(
                ev,
                action=label,
                minutes=minutes,
                completed_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
                reason="Cancelado pelo usuário" if cancelled else "")
        self._reset_ui()

    def _on_cancelled(self):
        action  = self.engine.state.action
        minutes = self.engine.state.total_seconds // 60
        self.config.add_history(action, minutes, False)
        SystemController.prevent_sleep(False)
        self._status("✓  Contagem cancelada.", COLORS["success"])

        # ── Feature module hooks ───────────────────────────────────
        if self.energy:
            self.energy.on_timer_end()
        if self.email_notif:
            self.email_notif.send_event(
                "timer_cancelled",
                action=ACTION_LABELS.get(action, action),
                minutes=minutes,
                reason="Cancelado pelo usuário")
        self._reset_ui()

    def _on_paused(self, paused: bool):
        self._status("⏸  Timer pausado." if paused else "▶  Timer retomado.",
                     COLORS["text_dim"])

    # ── Shutdown condicional ──────────────────────────────

    def _toggle_conditional(self):
        if self._cond_active:
            self.cond_mon.stop(); self._cond_active = False
            if self.cond_start_btn:
                self.cond_start_btn.configure(
                    text="▶  Ativar monitoramento",
                    fg_color=COLORS["accent2"])
            if hasattr(self, "_cond_status_lbl"):
                self._cond_status_lbl.configure(text="")
            return

        conditions = [
            Condition(kind=kind, param=par.get(), enabled=chk.get())
            for kind, (chk, par) in self._cond_vars.items()
        ]
        if not any(c.enabled for c in conditions):
            messagebox.showwarning("Atenção",
                "Habilite ao menos uma condição.")
            return

        action = self.cond_action_var.get()
        self.cond_mon.start(action, conditions)
        self._cond_active = True
        if self.cond_start_btn:
            self.cond_start_btn.configure(
                text="⏹  Parar monitoramento",
                fg_color=COLORS["danger"])
        if hasattr(self, "_cond_status_lbl"):
            self._cond_status_lbl.configure(
                text="👁  Monitorando condições...",
                text_color=COLORS["accent"])
        self.config.set("cond_action", action)
        self.config.set("conditions",
            [{"kind": c.kind, "param": c.param, "enabled": c.enabled}
             for c in conditions])

    def _on_condition_met(self, action: str, desc: str):
        self._cond_active = False
        if self.cond_start_btn:
            self.cond_start_btn.configure(
                text="▶  Ativar monitoramento",
                fg_color=COLORS["accent2"])
        if hasattr(self, "_cond_status_lbl"):
            self._cond_status_lbl.configure(text="")

        label = ACTION_LABELS.get(action, action)
        self.notif.warn("Condição satisfeita!",
                        f"{desc}\n{label} em 15s.",
                        sound=self.sound_var.get())
        cancelled = self._show_countdown_dialog(
            action, f"{label}  [{desc}]")
        if not cancelled:
            self.config.add_history(action, 0, completed=True)
            if self.email_notif:
                self.email_notif.send_event(
                    "condition_met",
                    condition=desc,
                    action=label,
                    description=desc)
            SystemController.execute(action)
        else:
            if hasattr(self, "_cond_status_lbl"):
                self._cond_status_lbl.configure(
                    text="✓  Ação condicional cancelada.",
                    text_color=COLORS["success"])

    # ── Modo gamer ────────────────────────────────────────

    def _gamer_check(self):
        if not self.engine.is_running: return
        idle      = SystemController.get_idle_seconds()
        threshold = self.config.get("gamer_idle_threshold")
        fs        = SystemController.is_fullscreen_active()
        procs     = self.config.get("gamer_processes") or []
        proc_ok   = any(SystemController.is_process_running(p) for p in procs if p)

        should_pause = (idle < threshold) or fs or proc_ok
        if should_pause and not self.engine.state.paused:
            self.engine.pause_resume()
            reasons = (
                ([f"inativo <{threshold}s"] if idle < threshold else []) +
                (["fullscreen"] if fs else []) +
                (["processo"] if proc_ok else []))
            self._status(f"🎮  Pausado ({', '.join(reasons)})",
                         COLORS["warning"])
        elif not should_pause and self.engine.state.paused:
            self.engine.pause_resume()
            self._status("🎮  Retomado", COLORS["text_dim"])

        self._gamer_id = self.root.after(5000, self._gamer_check)

    def _gamer_settings(self):
        """Abre ProcessSelector para selecionar processos do modo gamer."""
        current = self.config.get("gamer_processes") or []
        def cb(selected):
            self.config.set("gamer_processes", selected)
            if hasattr(self, "_gamer_proc_lbl"):
                self._gamer_proc_lbl.configure(
                    text=self._gamer_proc_text(selected))
        ProcessSelector(self.root, selected_processes=current, callback=cb)

    # ── Dialog 15s ────────────────────────────────────────

    def _show_countdown_dialog(self, action: str, label: str) -> bool:
        icon      = ACTION_ICONS.get(action, "⏻")
        cancelled = {"v": False}

        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Confirmar ação")
        dlg.geometry("380x280")
        dlg.configure(fg_color=COLORS["bg"])
        dlg.resizable(False, False); dlg.grab_set()
        dlg.lift(); dlg.attributes("-topmost", True)
        self.root.update_idletasks()
        dlg.geometry(
            f"380x280+"
            f"{self.root.winfo_x() + (self.root.winfo_width() - 380)//2}+"
            f"{self.root.winfo_y() + (self.root.winfo_height() - 280)//2}")

        ctk.CTkLabel(dlg, text=f"{icon}  {label}",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORS["danger"]).pack(pady=(24, 2))
        ctk.CTkLabel(dlg, text="Pressione CANCELAR para abortar",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack()

        cnt_var = tk.StringVar(value="15")
        cnt_lbl = ctk.CTkLabel(dlg, textvariable=cnt_var,
                               font=ctk.CTkFont("Courier New", 64, "bold"),
                               text_color=COLORS["danger"])
        cnt_lbl.pack(pady=(6, 4))

        prog = ctk.CTkProgressBar(dlg, height=6,
                                  fg_color=COLORS["surface2"],
                                  progress_color=COLORS["danger"],
                                  corner_radius=3)
        prog.pack(fill="x", padx=24, pady=(0, 10)); prog.set(1.0)

        def do_cancel():
            cancelled["v"] = True
            if self._countdown_id:
                try: self.root.after_cancel(self._countdown_id)
                except Exception: pass
                self._countdown_id = None
            dlg.destroy()

        ctk.CTkButton(dlg, text="✕  Cancelar ação",
                      height=40, width=200,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=COLORS["danger"], hover_color="#c94040",
                      text_color="white", corner_radius=10,
                      command=do_cancel).pack()

        total = 15; box = {"v": total}

        def tick():
            box["v"] -= 1; n = box["v"]
            cnt_var.set(str(n)); prog.set(n / total)
            cnt_lbl.configure(
                text_color=COLORS["danger"] if n <= 5 else COLORS["warning"])
            if n <= 0: dlg.destroy()
            else: self._countdown_id = self.root.after(1000, tick)

        self._countdown_id = self.root.after(1000, tick)
        self.root.wait_window(dlg)
        return cancelled["v"]

    # ── Mini widget ───────────────────────────────────────

    def _toggle_mini_widget(self):
        if self.mini.is_visible(): self.mini.hide()
        else:                       self.mini.show()

    def _widget_loop(self):
        if self.mini: self.mini.update()
        self._widget_tick = self.root.after(1000, self._widget_loop)

    # ── Exportar histórico ────────────────────────────────

    def _export_history(self, fmt: str = ""):
        if not fmt:
            ans = messagebox.askquestion("Exportar",
                "Exportar como CSV?\n(Não = JSON)")
            fmt = "csv" if ans == "yes" else "json"
        ext  = ".csv" if fmt == "csv" else ".json"
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=[("CSV","*.csv"),("JSON","*.json")],
            initialfile=f"shutdown_history{ext}")
        if not path: return
        try:
            if fmt == "csv": self.config.export_csv(path)
            else:            self.config.export_json(path)
            messagebox.showinfo("Exportado", f"Salvo em:\n{path}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    # ── Autostart ─────────────────────────────────────────

    def _toggle_autostart(self):
        ok = SystemController.set_autostart(self.autostart_var.get())
        self.config.set("autostart", self.autostart_var.get())
        if not ok:
            messagebox.showwarning("Autostart",
                "Não foi possível alterar.\nVerifique permissões.")

    # ── Tray / janela ─────────────────────────────────────

    def _on_minimize(self, event):
        if event.widget == self.root and HAS_TRAY:
            self.root.withdraw()

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_close(self):
        if self.engine.is_running and HAS_TRAY:
            self.root.withdraw(); return
        if self.engine.is_running:
            if not messagebox.askyesno("Sair",
                    "Timer em andamento. Deseja sair e cancelar?"):
                return
        self._quit_app()

    # ── Smart Mode handlers ───────────────────────────────

    def _toggle_smart_mode(self):
        enabled = self.smart_mode_var.get()
        self.config.set("smart_mode", enabled)
        if enabled:
            self._apply_smart_config()
            self.smart.start()
            self._smart_status_lbl.configure(
                text="● ativo", text_color=COLORS["success"])
            self.notif.send("Smart Mode ativado",
                "O ShutdownTimer está monitorando o sistema automaticamente.")
        else:
            self.smart.stop()
            self._smart_status_lbl.configure(text="", text_color=COLORS["text_dim"])

    def _apply_smart_config(self):
        """Lê as entradas da UI e aplica nos limites do SmartModeEngine."""
        try:
            self.smart.CPU_THRESHOLD = float(self._sm_cpu_var.get())
        except (ValueError, AttributeError):
            pass
        try:
            self.smart.NET_THRESHOLD_KB = float(self._sm_net_var.get())
        except (ValueError, AttributeError):
            pass
        try:
            self.smart.IDLE_SUSPEND_MIN = int(self._sm_suspend_var.get())
        except (ValueError, AttributeError):
            pass
        try:
            self.smart.IDLE_SHUTDOWN_MIN = int(self._sm_shutdown_var.get())
        except (ValueError, AttributeError):
            pass
        try:
            self.smart.UPTIME_REBOOT_DAYS = int(self._sm_uptime_var.get())
        except (ValueError, AttributeError):
            pass

    def _save_smart_config(self):
        """Persiste as configurações do Smart Mode."""
        try:
            self.config.set("smart_cpu_threshold",
                            float(self._sm_cpu_var.get()))
            self.config.set("smart_net_threshold_kb",
                            float(self._sm_net_var.get()))
            self.config.set("smart_idle_suspend_min",
                            int(self._sm_suspend_var.get()))
            self.config.set("smart_idle_shutdown_min",
                            int(self._sm_shutdown_var.get()))
            self.config.set("smart_uptime_reboot_d",
                            int(self._sm_uptime_var.get()))
            self._apply_smart_config()
            self._smart_status_lbl.configure(
                text="✓ salvo", text_color=COLORS["success"])
            self.root.after(2000, lambda: self._smart_status_lbl.configure(
                text="● ativo" if self.smart.is_running else "",
                text_color=COLORS["success"] if self.smart.is_running
                           else COLORS["text_dim"]))
        except ValueError as e:
            messagebox.showerror("Valor inválido",
                f"Verifique os campos do Smart Mode:\n{e}")

    def _on_smart_action(self, action: str, reason: str):
        """Chamado quando Smart Mode decide executar uma ação."""
        if self.engine.is_running:
            return   # Timer manual tem prioridade
        if self.smart.is_blocking:
            return   # Proteção de rede/CPU ativa

        label = ACTION_LABELS.get(action, action)
        self.notif.send(
            f"🧠 Smart Mode — {label}",
            f"Motivo: {reason}\nA ação será executada em 15 segundos.")

        cancelled = self._show_countdown_dialog(
            action, f"Smart Mode: {label}\n{reason}")
        if not cancelled:
            self.config.add_history(action, 0, completed=True)
            if self.email_notif:
                self.email_notif.send_event(
                    "smart_action",
                    action=label,
                    reason=reason,
                    time=datetime.now().strftime("%H:%M"))
            SystemController.execute(action)
        else:
            self._status(f"🧠 Smart Mode: ação '{label}' cancelada pelo usuário.",
                         COLORS["warning"])

    def _on_smart_suggestion(self, kind: str, msg: str):
        """Chamado quando Smart Mode quer sugerir algo (ex: reboot)."""
        self.notif.send("🧠 Smart Mode — Sugestão", msg)
        # Também atualiza status na aba Opções se visível
        if hasattr(self, "_smart_status_lbl"):
            self._smart_status_lbl.configure(
                text="💡 sugestão", text_color=COLORS["warning"])
            self.root.after(5000, lambda: self._smart_status_lbl.configure(
                text="● ativo" if self.smart.is_running else "",
                text_color=COLORS["success"] if self.smart.is_running
                           else COLORS["text_dim"]))

    def _on_smart_status(self, snapshot: dict):
        """Atualiza indicador de status do Smart Mode na UI."""
        if not hasattr(self, "_smart_status_lbl"): return
        if not self.smart.is_running: return

        blocking = snapshot.get("blocking", False)
        cpu      = snapshot.get("cpu", 0)
        net      = snapshot.get("net_kb_s", 0)

        if blocking:
            txt   = f"⛔ bloqueado ({net:.0f} KB/s)"
            color = COLORS["warning"]
        elif cpu >= self.smart.CPU_THRESHOLD:
            txt   = f"⏸ CPU alta ({cpu:.0f}%)"
            color = COLORS["warning"]
        else:
            txt   = "● ativo"
            color = COLORS["success"]

        self._smart_status_lbl.configure(text=txt, text_color=color)

    def _show_smart_habits(self):
        """Janela com os hábitos de uso aprendidos pelo Smart Mode."""
        rows = self.smart.get_habits_summary()

        win = ctk.CTkToplevel(self.root)
        win.title("🧠 Smart Mode — Hábitos aprendidos")
        win.geometry("480x520")
        win.configure(fg_color=COLORS["bg"]); win.grab_set()

        ctk.CTkLabel(win, text="Padrões de uso por hora do dia",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=COLORS["text"]).pack(pady=(18, 4), padx=20, anchor="w")
        ctk.CTkLabel(win,
                     text="Dados acumulados com uso real. Mais amostras = previsões mais precisas.",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(padx=20, anchor="w", pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(win, fg_color=COLORS["bg"],
                                        scrollbar_button_color=COLORS["surface2"])
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Header
        hdr = ctk.CTkFrame(scroll, fg_color=COLORS["surface2"], corner_radius=6, height=28)
        hdr.pack(fill="x", pady=(0, 4)); hdr.pack_propagate(False)
        for txt, w in [("Hora", 55), ("Amostras", 75),
                       ("CPU méd.", 75), ("Inativo", 80), ("Atividade", 100)]:
            ctk.CTkLabel(hdr, text=txt, width=w,
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=COLORS["text_dim2"],
                         anchor="center").pack(side="left", padx=2)

        for r in rows:
            pct    = r["active_pct"]
            color  = (COLORS["success"]  if pct >= 60 else
                      COLORS["warning"]  if pct >= 25 else
                      COLORS["text_dim2"])
            row_f = ctk.CTkFrame(scroll, fg_color=COLORS["surface"], corner_radius=6)
            row_f.pack(fill="x", pady=2)

            h_str = f"{r['hour']:02d}:00"
            for txt, w in [
                    (h_str,                     55),
                    (str(r["samples"]),          75),
                    (f"{r['avg_cpu']}%",         75),
                    (f"{r['avg_idle_m']:.0f}min",80),
                    (f"{pct:.0f}%",              100)]:
                ctk.CTkLabel(row_f, text=txt, width=w,
                             font=ctk.CTkFont(size=11),
                             text_color=color if txt == f"{pct:.0f}%" else COLORS["text_dim"],
                             anchor="center").pack(side="left", padx=4, pady=6)

        # Nota sobre arquivo
        habits_path = str(SmartModeEngine.HABITS_FILE)
        ctk.CTkLabel(win, text=f"Arquivo: {habits_path}",
                     font=ctk.CTkFont(size=9),
                     text_color=COLORS["text_dim2"]).pack(pady=(0, 8))

    # ── Theme ─────────────────────────────────────────────

    def _apply_theme(self, theme_name: str):
        """Apply the selected theme globally."""
        resolved = theme_name
        if theme_name == "system":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                resolved = "light" if val == 1 else "dark"
            except Exception:
                resolved = "dark"

        colors = THEMES.get(resolved, THEMES["dark"])
        COLORS.update(colors)
        ctk_mode = "Light" if resolved == "light" else "Dark"
        ctk.set_appearance_mode(ctk_mode)
        self.config.set("theme", theme_name)
        messagebox.showinfo(
            "Tema aplicado",
            "Reinicie o aplicativo para aplicar o tema completamente.")

    # ── Presentation Mode ─────────────────────────────────

    def _presentation_loop(self):
        """Called every 10s on main thread to check presentation state."""
        pm_cfg = self.config.get("presentation_mode") or {}
        if pm_cfg.get("enabled", False) and self.engine.is_running:
            # Use enhanced decider if available
            if self.pres_enhanced:
                decision = self.pres_enhanced.evaluate_now()
                is_active = decision.activate
                # Update diagnostics panel
                self._update_pres_diag(decision)
            else:
                is_active = self.presentation.is_presentation_active()
            action = pm_cfg.get("action", "pause")
            notify = pm_cfg.get("show_notifications", True)
            if is_active and not self._presentation_active:
                self._presentation_active = True
                if action == "pause" and not self.engine.state.paused:
                    self.engine.pause_resume()
                    if notify:
                        self.notif.send("🎭 Modo Apresentação Ativado",
                                        "Timer pausado automaticamente.")
                elif action == "notify_only" and notify:
                    self.notif.send("🎭 Modo Apresentação",
                                    "Apresentação detectada. Timer continua rodando.")
                self._status("🎭 Apresentação ativa", COLORS["warning"])
                if hasattr(self, "_pres_status_badge"):
                    self._pres_status_badge.configure(
                        text="● ativa", text_color=COLORS["warning"])
            elif not is_active and self._presentation_active:
                self._presentation_active = False
                resume = pm_cfg.get("resume_on_exit", True)
                if action == "pause" and resume and self.engine.state.paused:
                    self.engine.pause_resume()
                    if notify:
                        self.notif.send("🎭 Modo Apresentação Desativado",
                                        "Timer retomado.")
                self._status("🎭 Apresentação encerrada", COLORS["text_dim"])
                if hasattr(self, "_pres_status_badge"):
                    self._pres_status_badge.configure(
                        text="● monitorando", text_color=COLORS["text_dim"])
        elif not self.engine.is_running:
            self._presentation_active = False
        self.root.after(10000, self._presentation_loop)

    def _update_pres_diag(self, decision):
        """Atualiza o painel de diagnóstico de apresentação."""
        if not hasattr(self, "_pres_diag_text"):
            return
        try:
            from features.presentation_enhanced import DecisionResult
            lines = [
                f"Confiança: {decision.confidence:.0%}  "
                f"Decisão: {'ATIVO ✅' if decision.activate else 'inativo ⬜'}",
            ]
            for t in decision.all_triggers:
                st = "✅" if t.active else "⬜"
                lines.append(
                    f"{st} {t.label:28s} p={t.weight:.2f} c={t.reliability:.0%}")
            self._pres_diag_text.configure(state="normal")
            self._pres_diag_text.delete("1.0", "end")
            self._pres_diag_text.insert("end", "\n".join(lines))
            self._pres_diag_text.configure(state="disabled")
        except Exception:
            pass

    def _toggle_presentation_mode(self):
        pm_cfg    = dict(self.config.get("presentation_mode") or {})
        enabled   = self.pres_mode_var.get()
        pm_cfg["enabled"] = enabled
        self.config.set("presentation_mode", pm_cfg)
        if enabled:
            if self.pres_enhanced:
                self.pres_enhanced.start()
            else:
                self.presentation.start()
            if hasattr(self, "_pres_status_badge"):
                self._pres_status_badge.configure(
                    text="● monitorando", text_color=COLORS["success"])
        else:
            if self.pres_enhanced:
                self.pres_enhanced.stop()
            self.presentation.stop()
            self._presentation_active = False
            if hasattr(self, "_pres_status_badge"):
                self._pres_status_badge.configure(
                    text="● inativo", text_color=COLORS["text_dim"])

    def _save_presentation_config(self):
        pm_cfg   = dict(self.config.get("presentation_mode") or {})
        triggers = {
            "powerpoint":       self._pres_pp_var.get(),
            "external_monitor": self._pres_ext_var.get(),
            "videoconf":        self._pres_vc_var.get(),
            "fullscreen_idle":  self._pres_fs_var.get()
                                if hasattr(self, "_pres_fs_var") else False,
            "microphone":       self._pres_mic_var.get()
                                if hasattr(self, "_pres_mic_var") else False,
        }
        pm_cfg["triggers"] = triggers
        # Save weights
        if hasattr(self, "_pres_weight_vars"):
            weights = {tid: round(float(var.get()), 2)
                       for tid, var in self._pres_weight_vars.items()}
            pm_cfg["trigger_weights"] = weights
        # Save threshold
        if hasattr(self, "_pres_threshold_var"):
            pm_cfg["decision_threshold"] = round(
                float(self._pres_threshold_var.get()), 2)
        pm_cfg["action"]            = self._pres_action_var.get()
        pm_cfg["show_notifications"] = self._pres_notify_var.get()
        pm_cfg["resume_on_exit"]    = (self._pres_resume_var.get()
                                       if hasattr(self, "_pres_resume_var")
                                       else True)
        # Custom apps — store as list of {"name": ..., "weight": 0.9}
        raw_apps = self._pres_apps_text.get("1.0", "end").strip()
        pm_cfg["custom_apps"] = [
            {"name": a.strip(), "weight": 0.9}
            for a in raw_apps.splitlines() if a.strip()
        ]
        self.config.set("presentation_mode", pm_cfg)
        self.config.save()
        # Reinit enhanced engine with new config
        if self.pres_enhanced:
            self.pres_enhanced._config = self.config
        if hasattr(self, "_pres_status_lbl"):
            self._pres_status_lbl.configure(
                text="✅ Configurações salvas", text_color=COLORS["success"])

    def _test_presentation_detection(self):
        if self.pres_enhanced:
            decision = self.pres_enhanced.evaluate_now()
            self._update_pres_diag(decision)
            if decision.activate:
                msg   = f"🎭 Modo Apresentação ativo ({decision.confidence:.0%})"
                color = COLORS["warning"]
            else:
                msg   = (f"🟢 Inativo — confiança {decision.confidence:.0%} "
                         f"(limiar {decision.all_triggers[0].weight if decision.all_triggers else '—'})")
                color = COLORS["text_dim"]
        else:
            result = self.presentation.test_detection()
            active = any(result.values())
            parts  = [k for k, v in result.items() if v]
            msg    = f"🎭 Detectado: {', '.join(parts)}" if active \
                     else "🟢 Nenhum gatilho ativo"
            color  = COLORS["success"] if active else COLORS["text_dim"]
        if hasattr(self, "_pres_status_lbl"):
            self._pres_status_lbl.configure(text=msg, text_color=color)

    # ── Calendar Integration handlers ────────────────────

    def _toggle_calendar_integration(self):
        enabled = self._cal_enabled_var.get()
        cal_cfg = dict(self.config.get("calendar_integration") or {})
        cal_cfg["enabled"] = enabled
        self.config.set("calendar_integration", cal_cfg)
        self.config.save()
        if enabled and self.calendar_mgr:
            self.calendar_mgr.reinit_sources()
            self.calendar_mgr.sync_async()

    def _save_calendar_config(self):
        cal_cfg = dict(self.config.get("calendar_integration") or {})
        cal_cfg["enabled"]  = self._cal_enabled_var.get()
        cal_cfg["behavior"] = self._cal_behavior_var.get()
        cal_cfg["notify"]   = self._cal_notify_var.get()

        sources = cal_cfg.get("sources", {})
        # Brasil API
        state_val = self._cal_state_var.get()
        sources["brasil_api"] = {
            "enabled": self._cal_brasil_var.get(),
            "state":   "" if state_val == "(nenhum)" else state_val,
        }
        # Google
        sources["google"] = {
            "enabled":            self._cal_google_var.get(),
            "client_secret_path": self._cal_secret_var.get().strip(),
            "calendar_ids":       ["primary"],
            "any_event":          True,
        }
        # ICS
        ics_path = self._cal_ics_path_var.get().strip()
        sources["ics"] = {
            "enabled": self._cal_ics_var.get(),
            "path":    ics_path if not ics_path.startswith("http") else "",
            "url":     ics_path if ics_path.startswith("http") else "",
        }
        cal_cfg["sources"] = sources
        self.config.set("calendar_integration", cal_cfg)
        self.config.save()
        if self.calendar_mgr:
            self.calendar_mgr._config = self.config
            self.calendar_mgr.reinit_sources()
        if hasattr(self, "_cal_status_lbl"):
            self._cal_status_lbl.configure(
                text="✅ Configurações salvas", text_color=COLORS["success"])

    def _cal_sync(self):
        if not self.calendar_mgr:
            messagebox.showwarning("Calendário",
                "Módulo calendar_integration não disponível.\n"
                "Coloque calendar_integration.py na mesma pasta.")
            return
        if hasattr(self, "_cal_status_lbl"):
            self._cal_status_lbl.configure(
                text="🔄 Sincronizando...", text_color=COLORS["text_dim"])
        self.calendar_mgr.on_sync_done = lambda ok, msg: self.root.after(
            0, self._on_cal_sync_done, ok, msg)
        self.calendar_mgr.sync_async()

    def _on_cal_sync_done(self, ok: bool, msg: str):
        color = COLORS["success"] if ok else COLORS["danger"]
        if hasattr(self, "_cal_status_lbl"):
            self._cal_status_lbl.configure(text=msg, text_color=color)
        self._cal_refresh_upcoming()

    def _cal_clear_cache(self):
        if self.calendar_mgr:
            self.calendar_mgr.clear_cache()
        if hasattr(self, "_cal_status_lbl"):
            self._cal_status_lbl.configure(
                text="� Cache limpo", text_color=COLORS["text_dim"])
        if hasattr(self, "_cal_upcoming_text"):
            self._cal_upcoming_text.configure(state="normal")
            self._cal_upcoming_text.delete("1.0", "end")
            self._cal_upcoming_text.configure(state="disabled")

    def _cal_refresh_upcoming(self):
        if not self.calendar_mgr:
            return
        days = self.calendar_mgr.get_upcoming_special_days(30)
        if hasattr(self, "_cal_upcoming_text"):
            self._cal_upcoming_text.configure(state="normal")
            self._cal_upcoming_text.delete("1.0", "end")
            if days:
                for d in days[:10]:
                    line = (f"{d['display']}  {d['weekday']:10s}"
                            f"  {d['reason']}\n")
                    self._cal_upcoming_text.insert("end", line)
            else:
                self._cal_upcoming_text.insert(
                    "end", "Nenhum dia especial nos próximos 30 dias.")
            self._cal_upcoming_text.configure(state="disabled")

    def _cal_browse_secret(self):
        path = filedialog.askopenfilename(
            title="Selecionar client_secret.json",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")])
        if path and hasattr(self, "_cal_secret_var"):
            self._cal_secret_var.set(path)

    def _cal_browse_ics(self):
        path = filedialog.askopenfilename(
            title="Selecionar arquivo .ics",
            filetypes=[("iCalendar", "*.ics"), ("Todos", "*.*")])
        if path and hasattr(self, "_cal_ics_path_var"):
            self._cal_ics_path_var.set(path)

    def _cal_google_authenticate(self):
        if not HAS_CALENDAR:
            messagebox.showwarning("Calendário",
                "Módulo calendar_integration.py não encontrado.")
            return
        if not HAS_GOOGLE_CAL:
            messagebox.showwarning("Google Calendar",
                "Instale as dependências:\n"
                "pip install google-api-python-client google-auth-oauthlib")
            return
        secret = self._cal_secret_var.get().strip() if \
            hasattr(self, "_cal_secret_var") else ""
        src = GoogleCalendarSource({"client_secret_path": secret,
                                     "calendar_ids": ["primary"]})
        if hasattr(self, "_cal_google_status"):
            self._cal_google_status.configure(
                text="🔄 Autenticando...", text_color=COLORS["text_dim"])
        self.root.update()

        def _auth():
            ok, msg = src.authenticate()
            self.root.after(0, self._on_cal_google_auth, ok, msg, src)
        threading.Thread(target=_auth, daemon=True).start()

    def _on_cal_google_auth(self, ok: bool, msg: str, src):
        color = COLORS["success"] if ok else COLORS["danger"]
        status = "✅ Conectado" if ok else f"❌ {msg}"
        if hasattr(self, "_cal_google_status"):
            self._cal_google_status.configure(
                text=status, text_color=color)
        if ok and self.calendar_mgr:
            self.calendar_mgr.add_google_source(src)
            self._cal_refresh_upcoming()
        elif not ok:
            messagebox.showerror("Google Calendar", msg)

    def _cal_google_disconnect(self):
        if self.calendar_mgr:
            gc = self.calendar_mgr.get_google_source()
            if gc:
                gc.disconnect()
                self.calendar_mgr._sources = [
                    s for s in self.calendar_mgr.sources
                    if not isinstance(s, GoogleCalendarSource)]
        if hasattr(self, "_cal_google_status"):
            self._cal_google_status.configure(
                text="⬜ Desconectado", text_color=COLORS["text_dim2"])

    # ── Export/Import config ──────────────────────────────

    def _export_config_dialog(self, scope: str = "full"):
        ext  = ".json"
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=[("JSON", "*.json"), ("Encrypted JSON", "*.enc.json")],
            initialfile=f"shutdowntimer_backup_{scope}{ext}")
        if not path:
            return
        password = ""
        if hasattr(self, "_export_encrypt_var") and self._export_encrypt_var.get():
            password = self._export_pwd_var.get()
            if not password:
                messagebox.showwarning("Senha", "Digite uma senha para criptografar.")
                return
            confirm = self._export_pwd2_var.get()
            if password != confirm:
                messagebox.showerror("Senha", "As senhas não coincidem.")
                return
        ok = self.config.export_config(path, scope=scope, password=password)
        if ok:
            messagebox.showinfo("Exportado",
                                f"Configurações exportadas para:\n{path}")
        else:
            messagebox.showerror("Erro", "Falha ao exportar configurações.")

    def _import_config_dialog(self, merge: bool = False):
        path = filedialog.askopenfilename(
            filetypes=[("JSON / Encrypted", "*.json *.enc.json"),
                       ("Todos os arquivos", "*.*")])
        if not path:
            return
        password = ""
        if hasattr(self, "_import_pwd_var"):
            password = self._import_pwd_var.get()
        ok, result = self.config.import_config(
            path, password=password, merge=merge)
        if ok:
            messagebox.showinfo(
                "Importado",
                "Configurações importadas com sucesso!\n"
                "Reinicie o app para aplicar todas as mudanças.")
            self._apply_config()
        else:
            messagebox.showerror("Erro ao importar",
                                 f"Não foi possível importar:\n{result}")

    def _restore_backup_dialog(self):
        bd = self.config.get_backup_date()
        if not bd:
            messagebox.showinfo("Backup",
                                "Nenhum backup automático encontrado.")
            return
        if messagebox.askyesno(
                "Restaurar backup",
                f"Restaurar backup de {bd}?\n"
                "As configurações atuais serão substituídas."):
            if self.config.restore_backup():
                messagebox.showinfo(
                    "Restaurado",
                    "Backup restaurado. Reinicie o app para aplicar.")
            else:
                messagebox.showerror("Erro", "Falha ao restaurar backup.")

    def _preview_import_dialog(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON / Encrypted", "*.json *.enc.json"),
                       ("Todos os arquivos", "*.*")])
        if not path:
            return
        password = ""
        if hasattr(self, "_import_pwd_var"):
            password = self._import_pwd_var.get()
        ok, result = self.config.preview_import(path, password=password)
        if not ok:
            messagebox.showerror(
                "Erro",
                f"Não foi possível ler o arquivo:\n{result}")
            return
        win = ctk.CTkToplevel(self.root)
        win.title("🔍 Visualizar Importação")
        win.geometry("520x460")
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        ctk.CTkLabel(win, text="🔍  Conteúdo do arquivo",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=COLORS["text"]).pack(pady=(16, 4), padx=16, anchor="w")

        date_str = result.get("export_date", "")[:16].replace("T", " ")
        scope    = result.get("scope", "full")
        ctk.CTkLabel(
            win,
            text=(f"Criado em: {date_str}  |  Escopo: {scope}  |  "
                  f"v{result.get('version','')}"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim2"]).pack(anchor="w", padx=16)

        txt = ctk.CTkTextbox(
            win, fg_color=COLORS["surface"],
            text_color=COLORS["text_dim"],
            font=ctk.CTkFont("Courier New", 10),
            height=300)
        txt.pack(fill="both", expand=True, padx=16, pady=8)
        txt.insert("end", json.dumps(result, indent=2, ensure_ascii=False)[:4000])
        txt.configure(state="disabled")

        ctk.CTkButton(win, text="Fechar", command=win.destroy,
                      fg_color=COLORS["surface2"],
                      hover_color=COLORS["surface3"],
                      text_color=COLORS["text_dim"]).pack(pady=(0, 12))

    # ── Social share ──────────────────────────────────────

    def _generate_share_card(self):
        layout = getattr(self, "_share_layout_var",
                         tk.StringVar(value="minimal")).get()
        include_ach = getattr(self, "_share_ach_var",
                              tk.BooleanVar(value=True)).get()
        custom_text = ""
        if hasattr(self, "_share_custom_text"):
            custom_text = self._share_custom_text.get("1.0", "end").strip()

        if not HAS_PIL_SHARE:
            messagebox.showwarning(
                "Pillow não instalado",
                "Instale o Pillow para gerar imagens:\npip install Pillow")
            return None

        out = self.share.generate_card(
            layout=layout, custom_text=custom_text,
            include_achievements=include_ach)
        if out:
            self._last_share_path = out
            if hasattr(self, "_share_preview_lbl"):
                self._share_preview_lbl.configure(
                    text=f"✓ Card gerado: {out.name}",
                    text_color=COLORS["success"])
        else:
            messagebox.showerror("Erro", "Não foi possível gerar o card.")
        return out

    def _save_share_card(self):
        out = self._generate_share_card()
        if not out:
            return
        dst = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile="shutdowntimer_stats.png")
        if dst:
            import shutil
            shutil.copy(str(out), dst)
            messagebox.showinfo("Salvo", f"Imagem salva em:\n{dst}")

    def _copy_share_card(self):
        out = self._generate_share_card()
        if not out:
            return
        if self.share.copy_image_to_clipboard(out):
            if hasattr(self, "_share_preview_lbl"):
                self._share_preview_lbl.configure(
                    text="📋 Copiado para a área de transferência!",
                    text_color=COLORS["success"])
        else:
            messagebox.showinfo(
                "Copiar",
                "Copiar imagem só funciona no Windows.\nSalve o arquivo PNG.")

    def _copy_share_text(self):
        stats = self.share.get_stats()
        text  = self.share.get_share_text(stats)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if hasattr(self, "_share_preview_lbl"):
            self._share_preview_lbl.configure(
                text="📋 Texto copiado!", text_color=COLORS["success"])

    def _quit_app(self):
        self.engine.cancel()
        self.cond_mon.stop()
        self.scheduler.stop()
        self.smart.stop()
        self.presentation.stop()
        # Feature 3.3: stop enhanced presentation
        if self.pres_enhanced:
            self.pres_enhanced.stop()
        # Feature 3.1: unload all plugins
        if self.plugin_mgr:
            self.plugin_mgr.unload_all()
        self.hotkeys.clear()
        SystemController.prevent_sleep(False)
        if self.voice:
            self.voice.stop()
        if self.mini: self.mini.hide()
        self.tray.stop()
        if self._widget_tick:
            try: self.root.after_cancel(self._widget_tick)
            except Exception: pass
        self.root.destroy()


# ══════════════════════════════════════════════════════════════
# 13. CLI
# ══════════════════════════════════════════════════════════════

