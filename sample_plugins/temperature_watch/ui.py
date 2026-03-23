"""
Temperature Watch — UI própria (type=window)

Exemplo de como um plugin pode fornecer uma janela de UI personalizada.
A classe TemperatureUI é instanciada pelo PluginUIWindow do ShutdownTimer.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False


class TemperatureUI(ctk.CTkFrame if _HAS_CTK else tk.Frame):  # type: ignore[misc]
    """
    Frame que exibe leitura de temperatura em tempo real.
    Recebe ``parent`` (widget pai) e ``api`` (PluginAPI).
    """

    _POLL_MS = 2000  # atualiza a cada 2 s

    def __init__(self, parent, api=None):
        super().__init__(parent)
        self.api   = api
        self._job  = None
        self._stop = threading.Event()

        if _HAS_CTK:
            self.configure(fg_color="#0d0f18")

        self._build()
        self._update()

    # ── Build ─────────────────────────────────────────────────

    def _build(self):
        C = {
            "bg":       "#0d0f18",
            "surface":  "#161923",
            "surface2": "#1e2235",
            "accent":   "#4f8ef7",
            "success":  "#4ff78e",
            "warning":  "#f7a94f",
            "danger":   "#f75a5a",
            "text":     "#e8eaf6",
            "text_dim": "#7b82a8",
        }

        if _HAS_CTK:
            # ── Título ────────────────────────────────────────
            ctk.CTkLabel(
                self,
                text="🌡️  Monitor de Temperatura",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color=C["text"]
            ).pack(pady=(16, 4))

            # ── Leitura atual ─────────────────────────────────
            self._temp_lbl = ctk.CTkLabel(
                self,
                text="— °C",
                font=ctk.CTkFont(size=40, weight="bold"),
                text_color=C["accent"]
            )
            self._temp_lbl.pack(pady=(8, 0))

            self._status_lbl = ctk.CTkLabel(
                self,
                text="Aguardando leitura…",
                font=ctk.CTkFont(size=11),
                text_color=C["text_dim"],
                wraplength=380,
                justify="center"
            )
            self._status_lbl.pack(pady=(4, 8))

            # ── Card de ajuda (visível só quando sensor não encontrado) ───
            self._help_card = ctk.CTkFrame(
                self, fg_color="#1a1a2e", corner_radius=10)

            ctk.CTkLabel(
                self._help_card,
                text="⚙️  Leitura de temperatura indisponível",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=C["warning"]
            ).pack(anchor="w", padx=14, pady=(12, 4))

            ctk.CTkLabel(
                self._help_card,
                text=(
                    "Seu processador pode não ser compatível com leitura padrão.\n"
                    "Este plugin já inclui um módulo automático para leitura\n"
                    "da temperatura — nenhuma instalação adicional é necessária."
                ),
                font=ctk.CTkFont(size=11),
                text_color=C["text_dim"],
                justify="left",
                wraplength=380,
            ).pack(anchor="w", padx=14, pady=(0, 12))

            # ── Parâmetros atuais ─────────────────────────────
            cfg_card = ctk.CTkFrame(
                self, fg_color=C["surface2"], corner_radius=8)
            cfg_card.pack(fill="x", padx=16, pady=(4, 4))

            ctk.CTkLabel(
                cfg_card,
                text="Configuração atual",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=C["text_dim"]
            ).pack(anchor="w", padx=12, pady=(8, 2))

            self._cfg_lbl = ctk.CTkLabel(
                cfg_card,
                text=self._format_config(),
                font=ctk.CTkFont("Courier New", 11),
                text_color=C["text"],
                justify="left"
            )
            self._cfg_lbl.pack(anchor="w", padx=12, pady=(0, 10))

            # ── Botão atualizar ───────────────────────────────
            ctk.CTkButton(
                self,
                text="🔄  Atualizar agora",
                width=160, height=32,
                font=ctk.CTkFont(size=12),
                fg_color=C["surface2"],
                hover_color=C["surface"],
                text_color=C["text_dim"],
                command=self._update
            ).pack(pady=(6, 12))

        else:
            # Fallback tkinter puro
            tk.Label(self, text="🌡️ Temperature Watch",
                     font=("Arial", 13, "bold")).pack(pady=8)
            self._temp_lbl = tk.Label(self, text="— °C",
                                       font=("Arial", 32, "bold"),
                                       fg="#4f8ef7")
            self._temp_lbl.pack()
            self._status_lbl = tk.Label(self, text="Aguardando…",
                                         font=("Arial", 10),
                                         wraplength=380, justify="center")
            self._status_lbl.pack()

            # Card de ajuda (tkinter puro)
            self._help_card = tk.Frame(self, bd=1, relief="groove")
            tk.Label(self._help_card,
                     text=(
                         "Seu processador pode não ser compatível com\n"
                         "leitura padrão. Este plugin já inclui um módulo\n"
                         "automático — nenhuma instalação é necessária."
                     ),
                     font=("Arial", 9), justify="left").pack(padx=8, pady=8)

            self._cfg_lbl = tk.Label(self,
                                      text=self._format_config(),
                                      font=("Courier New", 10),
                                      justify="left")
            self._cfg_lbl.pack(padx=10, pady=6)

    # ── Atualização periódica ─────────────────────────────────

    def _update(self):
        temp      = self._read_temp()
        threshold = self._get_param("threshold", 85)

        if temp < 0:
            temp_txt   = "N/D"
            status_txt = "⚠  Sensor de temperatura não detectado neste sistema."
            color      = "#7b82a8"
            show_help  = True
        else:
            show_help = False
            temp_txt  = f"{temp:.1f} °C"
            if temp >= threshold:
                status_txt = f"🔴  SUPERAQUECENDO  (limite: {threshold}°C)"
                color      = "#f75a5a"
            elif temp >= threshold * 0.85:
                status_txt = f"🟡  Atenção  (limite: {threshold}°C)"
                color      = "#f7a94f"
            else:
                status_txt = f"🟢  Normal  (limite: {threshold}°C)"
                color      = "#4ff78e"

        try:
            if _HAS_CTK:
                self._temp_lbl.configure(text=temp_txt, text_color=color)
                self._status_lbl.configure(text=status_txt)
                self._cfg_lbl.configure(text=self._format_config())
                if show_help:
                    self._help_card.pack(fill="x", padx=16, pady=(0, 4),
                                         before=self._cfg_lbl.master)
                else:
                    self._help_card.pack_forget()
            else:
                self._temp_lbl.configure(text=temp_txt, fg=color)
                self._status_lbl.configure(text=status_txt)
                self._cfg_lbl.configure(text=self._format_config())
                if show_help:
                    self._help_card.pack(pady=4)
                else:
                    self._help_card.pack_forget()

            if self._job:
                try:
                    self.after_cancel(self._job)
                except Exception:
                    pass
            self._job = self.after(self._POLL_MS, self._update)
        except Exception:
            pass  # Widget destruído

    # ── Helpers ───────────────────────────────────────────────

    def _read_temp(self) -> float:
        # 1ª prioridade: PluginAPI
        if self.api:
            t = self.api.get_cpu_temperature()
            if t >= 0:
                return t
        # 2ª–4ª: cascata local (C# → LHM/OHM → psutil)
        try:
            from sample_plugins.temperature_watch.main import _get_cpu_temp_direct
            return _get_cpu_temp_direct()
        except Exception:
            pass
        return -1.0

    def _get_param(self, key: str, default=None):
        if self.api:
            v = self.api.get_config(key)
            return v if v is not None else default
        return default

    def _format_config(self) -> str:
        if self.api is None:
            return "(API não disponível)"
        cfg = self.api.get_config() or {}
        labels = {
            "threshold":    "Limite (°C)",
            "poll_interval":"Intervalo (s)",
            "action":       "Ação",
            "auto_resume":  "Auto retomar",
        }
        lines = [
            f"  {lbl:<24} {cfg.get(k, '—')}"
            for k, lbl in labels.items()
        ]
        return "\n".join(lines)

    def destroy(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        super().destroy()
