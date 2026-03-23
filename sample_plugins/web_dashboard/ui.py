"""
Web Dashboard — UI da aba (plugin tab)
══════════════════════════════════════
Exibe o painel de controle do servidor HTTP diretamente dentro
da aba "🌐 Web Dashboard" da janela principal do ShutdownTimer.

Layout:
  ┌─────────────────────────────────────────┐
  │  Status do servidor  [● Ativo / ○ Parado]│
  │  ─────────────────────────────────────  │
  │  URLs de acesso:                         │
  │  http://192.168.1.100:8080  [Abrir] [📋] │
  │  http://10.0.0.5:8080       [Abrir] [📋] │
  │  ─────────────────────────────────────  │
  │  [▶ Iniciar servidor]  [⏹ Parar]         │
  │  ─────────────────────────────────────  │
  │  Configurações rápidas (porta / PIN)     │
  └─────────────────────────────────────────┘
"""
from __future__ import annotations

import socket
import threading
import tkinter as tk
import webbrowser
from typing import TYPE_CHECKING, Optional

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False

if TYPE_CHECKING:
    from main import WebDashboardPlugin

# ── cores padrão (reaproveitadas do tema dark do ShutdownApp) ──────────────────
_C = {
    "bg":        "#0d0f18",
    "surface":   "#161923",
    "surface2":  "#1e2235",
    "surface3":  "#252a40",
    "accent":    "#4f8ef7",
    "accent2":   "#7c5cf7",
    "danger":    "#f75a5a",
    "warning":   "#f7a94f",
    "success":   "#4ff78e",
    "text":      "#e8eaf6",
    "text_dim":  "#7b82a8",
    "text_dim2": "#4a5070",
    "border":    "#2a2f4a",
}


def _color(key: str) -> str:
    """Tenta pegar cor do COLORS global do ShutdownApp; senão usa fallback."""
    try:
        import __main__
        return getattr(__main__, "COLORS", _C).get(key, _C[key])
    except Exception:
        return _C.get(key, "#888888")


class WebDashboardUI(ctk.CTkFrame):
    """
    Aba "🌐 Web Dashboard" — embutida na janela principal via plugin UI.

    Recebe ``parent`` (frame da aba) e ``api`` (PluginAPI).
    """

    POLL_MS = 2000   # intervalo de atualização do status na UI

    def __init__(self, parent, api=None):
        super().__init__(parent, fg_color=_color("bg"))
        self.api  = api
        self._plugin: Optional[WebDashboardPlugin] = None
        self._poll_id = None

        self._resolve_plugin()
        self._build()
        self._start_poll()

    # ── Resolução da instância do plugin ──────────────────────────────────────

    def _resolve_plugin(self):
        """Obtém a instância WebDashboardPlugin via api ou global."""
        # 1. Via PluginManager runtime (caminho principal)
        if self.api is not None:
            try:
                mgr = self.api._manager
                rt  = mgr.get_runtime("web_dashboard")
                if rt and rt.loaded and rt.module:
                    self._plugin = getattr(rt.module, "_plugin", None)
                    if self._plugin is not None:
                        return
            except Exception:
                pass
        # 2. Fallback: importa o módulo diretamente pelo caminho do arquivo
        try:
            import importlib.util as _ilu
            from pathlib import Path as _P
            _entry = _P(__file__).parent / "main.py"
            _spec  = _ilu.spec_from_file_location("web_dashboard_main",
                                                    str(_entry))
            _mod   = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            self._plugin = getattr(_mod, "_plugin", None)
        except Exception:
            pass

    # ── Construção da UI ──────────────────────────────────────────────────────

    def _build(self):
        self.pack(fill="both", expand=True)

        scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=_color("bg"),
            scrollbar_button_color=_color("surface2"),
            scrollbar_button_hover_color=_color("surface3"),
        )
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # ── Card: Status ───────────────────────────────────────────────────────
        self._card_status = self._card(scroll, "🌐 Servidor HTTP Local")

        status_row = ctk.CTkFrame(self._card_status, fg_color="transparent")
        status_row.pack(fill="x", padx=16, pady=(4, 10))

        self._dot_lbl = ctk.CTkLabel(
            status_row, text="●",
            font=ctk.CTkFont(size=18),
            text_color=_color("text_dim2"),
        )
        self._dot_lbl.pack(side="left")

        self._status_lbl = ctk.CTkLabel(
            status_row,
            text="Carregando…",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_color("text_dim"),
        )
        self._status_lbl.pack(side="left", padx=(6, 0))

        # ── Botões Iniciar / Parar ─────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self._card_status, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        self._start_btn = ctk.CTkButton(
            btn_row,
            text="▶  Iniciar servidor",
            width=160, height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=_color("accent"),
            hover_color=_color("accent2"),
            text_color="#ffffff",
            corner_radius=8,
            command=self._on_start,
        )
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            btn_row,
            text="⏹  Parar",
            width=110, height=34,
            font=ctk.CTkFont(size=12),
            fg_color=_color("danger"),
            hover_color="#c94040",
            text_color="#ffffff",
            corner_radius=8,
            command=self._on_stop,
        )
        self._stop_btn.pack(side="left")

        # ── Card: Links de acesso ──────────────────────────────────────────────
        self._card_links = self._card(scroll, "🔗 Links de acesso (mesma rede Wi-Fi)")
        self._links_frame = ctk.CTkFrame(self._card_links, fg_color="transparent")
        self._links_frame.pack(fill="x", padx=16, pady=(0, 14))

        # placeholder enquanto carrega
        self._no_links_lbl = ctk.CTkLabel(
            self._links_frame,
            text="Servidor inativo — inicie o servidor para ver os links.",
            font=ctk.CTkFont(size=11),
            text_color=_color("text_dim2"),
        )
        self._no_links_lbl.pack(anchor="w", pady=4)

        # ── Card: Configurações rápidas ────────────────────────────────────────
        card_cfg = self._card(scroll, "⚙  Configurações rápidas")

        cfg_grid = ctk.CTkFrame(card_cfg, fg_color="transparent")
        cfg_grid.pack(fill="x", padx=16, pady=(4, 14))
        cfg_grid.columnconfigure(1, weight=1)

        # Interface de rede (host)
        ctk.CTkLabel(
            cfg_grid, text="Interface de rede:",
            font=ctk.CTkFont(size=12),
            text_color=_color("text_dim"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)

        host_frame = ctk.CTkFrame(cfg_grid, fg_color="transparent")
        host_frame.grid(row=0, column=1, columnspan=2, sticky="w", pady=4)

        self._host_var = tk.StringVar(value=self._get_cfg("host", "0.0.0.0"))
        self._host_menu = ctk.CTkOptionMenu(
            host_frame,
            variable=self._host_var,
            values=["0.0.0.0", "127.0.0.1"],
            width=140, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=_color("surface2"),
            button_color=_color("surface3"),
            button_hover_color=_color("accent"),
            text_color=_color("text"),
            dropdown_fg_color=_color("surface2"),
            dropdown_text_color=_color("text"),
            command=self._on_host_changed,
        )
        self._host_menu.pack(side="left")

        self._host_warn_lbl = ctk.CTkLabel(
            host_frame,
            text="⚠ somente este PC" if self._get_cfg("host", "0.0.0.0") == "127.0.0.1"
                 else "✓ acessível na rede Wi-Fi",
            font=ctk.CTkFont(size=10),
            text_color=_color("warning") if self._get_cfg("host", "0.0.0.0") == "127.0.0.1"
                       else _color("success"),
        )
        self._host_warn_lbl.pack(side="left", padx=(8, 0))

        # Porta
        ctk.CTkLabel(
            cfg_grid, text="Porta:",
            font=ctk.CTkFont(size=12),
            text_color=_color("text_dim"),
        ).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)

        self._port_var = tk.StringVar(value=self._get_cfg("port", "8080"))
        self._port_entry = ctk.CTkEntry(
            cfg_grid,
            textvariable=self._port_var,
            width=80, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=_color("surface2"),
            text_color=_color("text"),
            border_color=_color("border"),
        )
        self._port_entry.grid(row=1, column=1, sticky="w", pady=4)

        # PIN
        ctk.CTkLabel(
            cfg_grid, text="PIN:",
            font=ctk.CTkFont(size=12),
            text_color=_color("text_dim"),
        ).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)

        self._pin_var = tk.StringVar(value=self._get_cfg("pin", ""))
        self._pin_entry = ctk.CTkEntry(
            cfg_grid,
            textvariable=self._pin_var,
            show="●",
            width=120, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=_color("surface2"),
            text_color=_color("text"),
            border_color=_color("border"),
            placeholder_text="sem PIN",
        )
        self._pin_entry.grid(row=2, column=1, sticky="w", pady=4)

        ctk.CTkLabel(
            cfg_grid,
            text="(vazio = sem proteção)",
            font=ctk.CTkFont(size=10),
            text_color=_color("text_dim2"),
        ).grid(row=2, column=2, sticky="w", padx=8, pady=4)

        # Extensão rápida
        ctk.CTkLabel(
            cfg_grid, text="+X minutos:",
            font=ctk.CTkFont(size=12),
            text_color=_color("text_dim"),
        ).grid(row=3, column=0, sticky="w", padx=(0, 10), pady=4)

        self._ext_var = tk.StringVar(value=self._get_cfg("extend_minutes", "10"))
        ctk.CTkEntry(
            cfg_grid,
            textvariable=self._ext_var,
            width=80, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=_color("surface2"),
            text_color=_color("text"),
            border_color=_color("border"),
        ).grid(row=3, column=1, sticky="w", pady=4)

        # ── Seções visíveis no dashboard ──────────────────────────────────────
        sep = ctk.CTkFrame(card_cfg, fg_color=_color("border"), height=1)
        sep.pack(fill="x", padx=16, pady=(4, 8))

        ctk.CTkLabel(
            card_cfg,
            text="Seções visíveis no dashboard:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_color("text_dim"),
        ).pack(anchor="w", padx=16, pady=(0, 6))

        toggle_frame = ctk.CTkFrame(card_cfg, fg_color="transparent")
        toggle_frame.pack(fill="x", padx=16, pady=(0, 8))

        def _make_toggle(parent, label: str, cfg_key: str, row: int):
            val = self._get_cfg(cfg_key, "True").lower() not in ("false", "0", "no")
            var = tk.BooleanVar(value=val)
            sw  = ctk.CTkSwitch(
                parent,
                text=label,
                variable=var,
                font=ctk.CTkFont(size=12),
                text_color=_color("text"),
                progress_color=_color("accent"),
                button_color=_color("surface3"),
            )
            sw.grid(row=row, column=0, sticky="w", padx=(0, 20), pady=3)
            return var

        self._sw_start_panel = _make_toggle(toggle_frame, "🚀 Painel iniciar timer", "show_start_panel", 0)
        self._sw_cpu         = _make_toggle(toggle_frame, "💻 CPU & RAM",            "show_cpu",         1)
        self._sw_network     = _make_toggle(toggle_frame, "🌐 Tráfego de rede",      "show_network",     2)
        self._sw_processes   = _make_toggle(toggle_frame, "⚙️  Processos",            "show_processes",   3)

        # Botão salvar
        save_row = ctk.CTkFrame(card_cfg, fg_color="transparent")
        save_row.pack(fill="x", padx=16, pady=(0, 14))

        self._save_btn = ctk.CTkButton(
            save_row,
            text="💾  Salvar e reiniciar servidor",
            width=220, height=32,
            font=ctk.CTkFont(size=12),
            fg_color=_color("surface3"),
            hover_color=_color("accent"),
            text_color=_color("text_dim"),
            corner_radius=8,
            command=self._on_save_config,
        )
        self._save_btn.pack(side="left")

        self._feedback_lbl = ctk.CTkLabel(
            save_row, text="",
            font=ctk.CTkFont(size=11),
            text_color=_color("success"),
        )
        self._feedback_lbl.pack(side="left", padx=10)

    # ── Polling de status ─────────────────────────────────────────────────────

    def _start_poll(self):
        self._poll()

    def _poll(self):
        try:
            if self.winfo_exists():
                self._refresh_status()
                self._poll_id = self.after(self.POLL_MS, self._poll)
        except Exception:
            pass

    def _refresh_status(self):
        running = self._is_running()

        # dot + texto
        if running:
            self._dot_lbl.configure(text_color=_color("success"))
            self._status_lbl.configure(
                text="Ativo",
                text_color=_color("success"),
            )
        else:
            self._dot_lbl.configure(text_color=_color("text_dim2"))
            self._status_lbl.configure(
                text="Parado",
                text_color=_color("text_dim2"),
            )

        # botões
        self._start_btn.configure(state="disabled" if running else "normal")
        self._stop_btn.configure(state="normal" if running else "disabled")

        # links
        self._rebuild_links(running)

    def _rebuild_links(self, running: bool):
        """Reconstrói a lista de URLs com botão Abrir e Copiar."""
        for w in self._links_frame.winfo_children():
            w.destroy()

        if not running:
            ctk.CTkLabel(
                self._links_frame,
                text="Servidor inativo — inicie o servidor para ver os links.",
                font=ctk.CTkFont(size=11),
                text_color=_color("text_dim2"),
            ).pack(anchor="w", pady=4)
            return

        urls = self._get_urls()
        if not urls:
            ctk.CTkLabel(
                self._links_frame,
                text="Nenhum endereço IP detectado.",
                font=ctk.CTkFont(size=11),
                text_color=_color("text_dim2"),
            ).pack(anchor="w", pady=4)
            return

        for url in urls:
            row = ctk.CTkFrame(self._links_frame, fg_color=_color("surface2"),
                               corner_radius=8)
            row.pack(fill="x", pady=4)

            # URL label
            url_lbl = ctk.CTkLabel(
                row,
                text=url,
                font=ctk.CTkFont("Courier New", 12, "bold"),
                text_color=_color("accent"),
                cursor="hand2",
            )
            url_lbl.pack(side="left", padx=(12, 8), pady=8)
            url_lbl.bind("<Button-1>",
                         lambda e, u=url: self._open_url(u))

            # Botão Abrir no navegador
            open_btn = ctk.CTkButton(
                row,
                text="🌐  Abrir",
                width=90, height=28,
                font=ctk.CTkFont(size=11),
                fg_color=_color("accent"),
                hover_color=_color("accent2"),
                text_color="#ffffff",
                corner_radius=6,
                command=lambda u=url: self._open_url(u),
            )
            open_btn.pack(side="right", padx=(4, 12), pady=6)

            # Botão Copiar link
            copy_btn = ctk.CTkButton(
                row,
                text="📋  Copiar",
                width=90, height=28,
                font=ctk.CTkFont(size=11),
                fg_color=_color("surface3"),
                hover_color=_color("accent"),
                text_color=_color("text_dim"),
                corner_radius=6,
                command=lambda u=url, b=None: self._copy_url(u),
            )
            copy_btn.pack(side="right", padx=(0, 4), pady=6)

        # dica QR / celular
        ctk.CTkLabel(
            self._links_frame,
            text="📱  Abra no celular (mesma rede Wi-Fi)",
            font=ctk.CTkFont(size=10),
            text_color=_color("text_dim2"),
        ).pack(anchor="w", pady=(2, 0))

    # ── Ações ─────────────────────────────────────────────────────────────────

    def _open_url(self, url: str):
        """Abre URL no navegador de forma não-bloqueante."""
        threading.Thread(target=webbrowser.open, args=(url,),
                         daemon=True).start()

    def _on_host_changed(self, value: str):
        """Atualiza o label de aviso ao mudar a interface de rede."""
        if value == "127.0.0.1":
            self._host_warn_lbl.configure(
                text="⚠ somente este PC — celular não vai conseguir acessar!",
                text_color=_color("warning"),
            )
        else:
            self._host_warn_lbl.configure(
                text="✓ acessível na rede Wi-Fi",
                text_color=_color("success"),
            )

    def _on_start(self):
        if self._plugin:
            self._plugin.start_server()
        self._refresh_status()

    def _on_stop(self):
        """Para o servidor de forma imediata e atualiza a UI."""
        if self._plugin:
            self._plugin.stop_server()   # fecha socket imediatamente — não bloqueia
        self._refresh_status()

    def _on_save_config(self):
        """Salva porta/host/PIN/extensão via API e reinicia o servidor."""
        if self.api:
            try:
                port = int(self._port_var.get())
                assert 1024 <= port <= 65535
            except (ValueError, AssertionError):
                self._feedback("❌ Porta inválida (1024–65535)", error=True)
                return

            self.api.set_config("port",           port)
            self.api.set_config("host",           self._host_var.get())
            self.api.set_config("pin",            self._pin_var.get().strip())
            try:
                ext = int(self._ext_var.get())
                self.api.set_config("extend_minutes", ext)
            except ValueError:
                pass
            self.api.set_config("show_start_panel", self._sw_start_panel.get())
            self.api.set_config("show_cpu",          self._sw_cpu.get())
            self.api.set_config("show_network",      self._sw_network.get())
            self.api.set_config("show_processes",    self._sw_processes.get())

        # Reinicia o servidor para aplicar as novas configs.
        # stop_server() fecha o socket imediatamente — pode reiniciar logo após.
        if self._plugin:
            self._plugin.stop_server()
            self._plugin._refresh_cfg()
            self.after(200, self._plugin.start_server)
            self.after(300, self._refresh_status)

        self._feedback("✅ Configurações salvas — servidor reiniciando…")

    def _copy_url(self, url: str):
        """Copia URL para a área de transferência."""
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self._feedback(f"📋  {url}  — copiado!")
        except Exception as e:
            self._feedback(f"❌ Erro ao copiar: {e}", error=True)

    def _feedback(self, text: str, error: bool = False):
        """Exibe mensagem temporária no label de feedback."""
        color = _color("danger") if error else _color("success")
        self._feedback_lbl.configure(text=text, text_color=color)
        self.after(3000, lambda: self._feedback_lbl.configure(text=""))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_running(self) -> bool:
        if self._plugin:
            return self._plugin.is_running
        return False

    def _get_urls(self):
        if self._plugin:
            return self._plugin.get_urls()
        # fallback: detecta IPs e usa porta da config
        port = int(self._get_cfg("port", "8080"))
        ips  = _local_ips()
        return [f"http://{ip}:{port}" for ip in ips]

    def _get_cfg(self, key: str, default: str = "") -> str:
        if self.api:
            v = self.api.get_config(key)
            if v is not None:
                return str(v)
        if self._plugin:
            return str(self._plugin.get_cfg().get(key, default))
        return default

    # ── Construtor de card ────────────────────────────────────────────────────

    @staticmethod
    def _card(parent, title: str) -> ctk.CTkFrame:
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            outer,
            text=title,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_color("text_dim"),
        ).pack(anchor="w", pady=(0, 4))
        inner = ctk.CTkFrame(outer, fg_color=_color("surface"), corner_radius=10)
        inner.pack(fill="x")
        return inner

    # ── Limpeza ───────────────────────────────────────────────────────────────

    def destroy(self):
        if self._poll_id:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
        super().destroy()


# ── Utilitário standalone ──────────────────────────────────────────────────────

def _local_ips():
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            if ":" not in addr and addr != "127.0.0.1" and addr not in ips:
                ips.append(addr)
    except Exception:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return ips or ["127.0.0.1"]
