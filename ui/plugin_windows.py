"""
PluginSettingsWindow e PluginUIWindow — janelas de configuração e UI de plugins.
"""

from config.app_imports import (
    tk, ctk,
    messagebox, filedialog,
    Dict, List, Any, Optional,
)
from ui.ui_helpers import COLORS


# ══════════════════════════════════════════════════════════════
# 10B. PLUGIN SETTINGS WINDOW
# ══════════════════════════════════════════════════════════════

class PluginSettingsWindow(ctk.CTkToplevel):
    """
    Janela de configuração dinâmica para um plugin.

    Gera campos de UI automaticamente a partir do esquema de parâmetros
    declarado no campo ``parameters`` do plugin.json.

    Tipos suportados:
        string, integer, float, boolean, choice,
        multichoice, password, file, folder.
    """

    _TYPE_ICONS = {
        "string":      "📝",
        "integer":     "🔢",
        "float":       "📐",
        "boolean":     "☑",
        "choice":      "🔘",
        "multichoice": "☑",
        "password":    "🔑",
        "file":        "📄",
        "folder":      "📂",
    }

    def __init__(self, parent, plugin_mgr,
                 manifest: dict):
        super().__init__(parent)
        self._mgr      = plugin_mgr
        self._manifest = manifest
        self._pid      = manifest.get("id", "")
        self._params   = manifest.get("parameters", [])
        self._vars: Dict[str, Any] = {}

        self.title(f"⚙  Configurações — {manifest.get('name', self._pid)}")
        self.geometry("480x560")
        self.resizable(True, True)
        self.grab_set()

        self._build()
        self._load_current_values()

    # ── Build ─────────────────────────────────────────────────

    def _build(self):
        C = COLORS

        # Header
        hdr = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0,
                           height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr,
            text=f"⚙  {self._manifest.get('name', self._pid)}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C["text"]
        ).pack(side="left", padx=14, pady=8)
        ctk.CTkLabel(
            hdr,
            text=f"v{self._manifest.get('version', '')}",
            font=ctk.CTkFont(size=11),
            text_color=C["text_dim2"]
        ).pack(side="left")

        # Body (scrollable)
        body = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"],
            scrollbar_button_color=C["surface2"],
            scrollbar_button_hover_color=C["surface3"])
        body.pack(fill="both", expand=True, padx=0, pady=0)

        if not self._params:
            ctk.CTkLabel(
                body,
                text="Este plugin não possui parâmetros configuráveis.",
                font=ctk.CTkFont(size=12),
                text_color=C["text_dim"]
            ).pack(pady=40)
        else:
            for param in self._params:
                self._build_param_field(body, param)

        # Footer
        footer = ctk.CTkFrame(self, fg_color=C["surface"],
                               corner_radius=0, height=52)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        ctk.CTkButton(
            footer, text="Restaurar Padrões",
            width=150, height=32,
            font=ctk.CTkFont(size=12),
            fg_color=C["surface2"],
            hover_color=C["surface3"],
            text_color=C["text_dim"],
            command=self._restore_defaults
        ).pack(side="left", padx=12, pady=10)

        ctk.CTkButton(
            footer, text="Cancelar",
            width=90, height=32,
            font=ctk.CTkFont(size=12),
            fg_color=C["surface2"],
            hover_color=C["surface3"],
            text_color=C["text_dim"],
            command=self.destroy
        ).pack(side="right", padx=(0, 8), pady=10)

        ctk.CTkButton(
            footer, text="💾  Salvar",
            width=100, height=32,
            font=ctk.CTkFont(size=12),
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            text_color="white",
            command=self._save
        ).pack(side="right", padx=(0, 4), pady=10)

    def _build_param_field(self, parent, param: dict):
        """Constrói um campo de formulário para um parâmetro."""
        C    = COLORS
        pid  = param.get("id", "")
        ptype = param.get("type", "string")
        label = param.get("label", pid)
        desc  = param.get("description", "")
        icon  = self._TYPE_ICONS.get(ptype, "•")

        # Card do parâmetro
        card = ctk.CTkFrame(parent, fg_color=C["surface"], corner_radius=8)
        card.pack(fill="x", padx=10, pady=4)

        # Label + tipo
        lbl_row = ctk.CTkFrame(card, fg_color="transparent")
        lbl_row.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            lbl_row,
            text=f"{icon}  {label}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C["text"]
        ).pack(side="left")

        if param.get("min") is not None or param.get("max") is not None:
            range_txt = ""
            if param.get("min") is not None and param.get("max") is not None:
                range_txt = f"({param['min']} – {param['max']})"
            elif param.get("min") is not None:
                range_txt = f"(≥ {param['min']})"
            else:
                range_txt = f"(≤ {param['max']})"
            ctk.CTkLabel(
                lbl_row, text=range_txt,
                font=ctk.CTkFont(size=10),
                text_color=C["text_dim2"]
            ).pack(side="left", padx=6)

        # Widget de entrada
        if ptype == "boolean":
            var = ctk.BooleanVar()
            self._vars[pid] = var
            ctk.CTkSwitch(
                card, text="", variable=var,
                button_color=C["accent2"],
                progress_color=C["accent2"],
                width=46
            ).pack(anchor="w", padx=12, pady=(0, 6))

        elif ptype == "choice":
            choices = param.get("choices", [])
            var = ctk.StringVar()
            self._vars[pid] = var
            ctk.CTkOptionMenu(
                card, values=choices if choices else [""],
                variable=var,
                width=300, height=30,
                font=ctk.CTkFont(size=12),
                fg_color=C["surface2"],
                button_color=C["surface3"],
                text_color=C["text"]
            ).pack(anchor="w", padx=12, pady=(0, 6))

        elif ptype == "multichoice":
            choices = param.get("choices", [])
            vars_list: List[ctk.BooleanVar] = []
            self._vars[pid] = vars_list
            mc_frame = ctk.CTkFrame(card, fg_color="transparent")
            mc_frame.pack(fill="x", padx=12, pady=(0, 6))
            for ch in choices:
                v = ctk.BooleanVar()
                vars_list.append((ch, v))
                ctk.CTkCheckBox(
                    mc_frame, text=ch, variable=v,
                    font=ctk.CTkFont(size=11),
                    text_color=C["text"],
                    checkbox_width=18, checkbox_height=18,
                    checkmark_color="white",
                    fg_color=C["accent2"],
                    hover_color=C["accent"]
                ).pack(anchor="w", pady=1)

        elif ptype == "password":
            var = ctk.StringVar()
            self._vars[pid] = var
            ctk.CTkEntry(
                card, textvariable=var, show="●",
                height=30, font=ctk.CTkFont(size=12),
                fg_color=C["surface2"],
                text_color=C["text"],
                border_color=C["border"]
            ).pack(fill="x", padx=12, pady=(0, 6))

        elif ptype == "file":
            var = ctk.StringVar()
            self._vars[pid] = var
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=(0, 6))
            ctk.CTkEntry(
                row, textvariable=var,
                height=30, font=ctk.CTkFont(size=11),
                fg_color=C["surface2"],
                text_color=C["text"],
                border_color=C["border"]
            ).pack(side="left", fill="x", expand=True, padx=(0, 6))
            ctk.CTkButton(
                row, text="📄", width=34, height=30,
                fg_color=C["surface3"],
                hover_color=C["accent"],
                text_color=C["text_dim"],
                command=lambda v=var: self._pick_file(v)
            ).pack(side="left")

        elif ptype == "folder":
            var = ctk.StringVar()
            self._vars[pid] = var
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=(0, 6))
            ctk.CTkEntry(
                row, textvariable=var,
                height=30, font=ctk.CTkFont(size=11),
                fg_color=C["surface2"],
                text_color=C["text"],
                border_color=C["border"]
            ).pack(side="left", fill="x", expand=True, padx=(0, 6))
            ctk.CTkButton(
                row, text="📂", width=34, height=30,
                fg_color=C["surface3"],
                hover_color=C["accent"],
                text_color=C["text_dim"],
                command=lambda v=var: self._pick_folder(v)
            ).pack(side="left")

        else:
            # string, integer, float
            var = ctk.StringVar()
            self._vars[pid] = var
            ctk.CTkEntry(
                card, textvariable=var,
                height=30, font=ctk.CTkFont(size=12),
                fg_color=C["surface2"],
                text_color=C["text"],
                border_color=C["border"]
            ).pack(fill="x", padx=12, pady=(0, 6))

        # Descrição
        if desc:
            ctk.CTkLabel(
                card, text=desc,
                font=ctk.CTkFont(size=10),
                text_color=C["text_dim2"],
                wraplength=400, justify="left"
            ).pack(anchor="w", padx=12, pady=(0, 8))

    # ── Load / Save / Reset ───────────────────────────────────

    def _load_current_values(self):
        """Popula os campos com os valores atualmente salvos."""
        current = self._mgr.get_plugin_config(self._pid) or {}
        for param in self._params:
            pid   = param.get("id", "")
            ptype = param.get("type", "string")
            value = current.get(pid, param.get("default"))
            var   = self._vars.get(pid)
            if var is None:
                continue
            try:
                if ptype == "multichoice":
                    selected = set(value or [])
                    for (ch, bv) in var:
                        bv.set(ch in selected)
                elif ptype == "boolean":
                    var.set(bool(value))
                else:
                    var.set(str(value) if value is not None else "")
            except Exception:
                pass

    def _collect_values(self) -> dict:
        """Lê todos os campos e retorna dict de valores."""
        result = {}
        for param in self._params:
            pid   = param.get("id", "")
            ptype = param.get("type", "string")
            var   = self._vars.get(pid)
            if var is None:
                continue
            try:
                if ptype == "multichoice":
                    result[pid] = [ch for (ch, bv) in var if bv.get()]
                elif ptype == "boolean":
                    result[pid] = var.get()
                elif ptype == "integer":
                    result[pid] = int(var.get())
                elif ptype == "float":
                    result[pid] = float(var.get())
                else:
                    result[pid] = var.get()
            except (ValueError, TypeError):
                result[pid] = param.get("default")
        return result

    def _save(self):
        """Valida, persiste e fecha."""
        values = self._collect_values()
        try:
            self._mgr.set_plugin_config(self._pid, values)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e), parent=self)

    def _restore_defaults(self):
        """Preenche campos com os valores default do manifesto."""
        for param in self._params:
            pid   = param.get("id", "")
            ptype = param.get("type", "string")
            defv  = param.get("default")
            var   = self._vars.get(pid)
            if var is None:
                continue
            try:
                if ptype == "multichoice":
                    selected = set(defv or [])
                    for (ch, bv) in var:
                        bv.set(ch in selected)
                elif ptype == "boolean":
                    var.set(bool(defv))
                else:
                    var.set(str(defv) if defv is not None else "")
            except Exception:
                pass

    @staticmethod
    def _pick_file(var: ctk.StringVar):
        p = filedialog.askopenfilename()
        if p:
            var.set(p)

    @staticmethod
    def _pick_folder(var: ctk.StringVar):
        p = filedialog.askdirectory()
        if p:
            var.set(p)


# ══════════════════════════════════════════════════════════════
# 10C. PLUGIN UI WINDOW — janela UI própria de plugin
# ══════════════════════════════════════════════════════════════

class PluginUIWindow(ctk.CTkToplevel):
    """
    Janela que hospeda a UI própria de um plugin (declarada com ``ui.type=window``).
    Instancia a classe de UI definida no manifesto e a embute nesta janela.
    """

    def __init__(self, parent, plugin_mgr,
                 manifest: dict):
        ui_def = manifest.get("ui", {})
        title  = ui_def.get("title",
                             f"🔌 {manifest.get('name', manifest.get('id','Plugin'))}")
        width  = int(ui_def.get("width",  500))
        height = int(ui_def.get("height", 400))

        super().__init__(parent)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.resizable(True, True)
        self.configure(fg_color=COLORS["bg"])

        # Tenta construir UI do plugin
        pid    = manifest.get("id", "")
        widget = plugin_mgr.build_plugin_ui_window(pid, self)

        if widget is None:
            ctk.CTkLabel(
                self,
                text=f"⚠  Não foi possível carregar a UI do plugin\n"
                     f"({ui_def.get('entry','ui.py')} / "
                     f"{ui_def.get('class','PluginUI')})",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["warning"]
            ).pack(expand=True)
        elif hasattr(widget, "pack"):
            widget.pack(fill="both", expand=True)
