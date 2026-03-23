"""
Web Dashboard — ShutdownTimer Plugin v2.0.0
════════════════════════════════════════════
Servidor HTTP local para monitorar e controlar o ShutdownTimer
remotamente via qualquer navegador na mesma rede Wi-Fi.

URL de acesso:  http://<IP-do-PC>:<porta>   (padrão: 8080)

Funcionalidades v2:
  • Iniciar timer com tempo customizado + escolha de ação pelo browser
  • Monitor de CPU em tempo real com gráfico sparkline
  • Monitor de tráfego de rede (upload/download em KB/s)
  • Lista de processos com maior uso de CPU/RAM
  • Seções habilitáveis/desabilitáveis nas configurações
  • Dashboard responsivo (mobile-friendly)
  • Botões: Cancelar, Pausar/Retomar, +X min, Executar agora
  • Histórico de hoje
  • API JSON: /api/status  |  /api/control  |  /api/sysinfo
  • PIN opcional para segurança
  • Sem dependências externas — stdlib + psutil (opcional)
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import socket
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

log = logging.getLogger("web_dashboard")

_plugin: "WebDashboardPlugin | None" = None


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_seconds(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    h, rem = divmod(int(seconds), 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _get_local_ips() -> List[str]:
    ips: List[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            if ":" not in addr and addr != "127.0.0.1":
                if addr not in ips:
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


def _pin_hash(pin: str) -> str:
    return hashlib.sha256(pin.strip().encode()).hexdigest()


def _fmt_bytes(n: float) -> str:
    if n < 1024:       return f"{n:.0f} B/s"
    if n < 1048576:    return f"{n/1024:.1f} KB/s"
    return f"{n/1048576:.2f} MB/s"


# ══════════════════════════════════════════════════════════════════════════════
# SYSINFO COLLECTOR — CPU / Rede / Processos via psutil
# ══════════════════════════════════════════════════════════════════════════════

class SysInfoCollector:
    """Coleta métricas do sistema periodicamente em background."""

    HISTORY = 30

    def __init__(self):
        self._lock      = threading.Lock()
        self._cpu_hist  : List[float] = []
        self._net_prev  : Optional[Tuple[int,int]] = None
        self._net_rate  : Tuple[float,float] = (0.0, 0.0)
        self._procs     : List[dict] = []
        self._cpu_now   : float = 0.0
        self._mem_pct   : float = 0.0
        self._stop      = threading.Event()
        self._thread    : Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="sysinfo_collector")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        try:
            import psutil
        except ImportError:
            return
        while not self._stop.wait(2.0):
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory()
                net = psutil.net_io_counters()
                now_recv, now_sent = net.bytes_recv, net.bytes_sent
                if self._net_prev:
                    pr, ps = self._net_prev
                    rate_r = max(0.0, (now_recv - pr) / 2.0)
                    rate_s = max(0.0, (now_sent - ps) / 2.0)
                else:
                    rate_r = rate_s = 0.0
                self._net_prev = (now_recv, now_sent)
                procs = []
                for p in psutil.process_iter(
                        ["pid", "name", "cpu_percent", "memory_percent"]):
                    try:
                        procs.append({
                            "pid":  p.info["pid"],
                            "name": (p.info["name"] or "?")[:30],
                            "cpu":  round(p.info["cpu_percent"] or 0, 1),
                            "mem":  round(p.info["memory_percent"] or 0, 1),
                        })
                    except Exception:
                        pass
                procs.sort(key=lambda x: x["cpu"], reverse=True)
                with self._lock:
                    self._cpu_now  = cpu
                    self._mem_pct  = mem.percent
                    self._net_rate = (rate_r, rate_s)
                    self._procs    = procs[:15]
                    self._cpu_hist.append(round(cpu, 1))
                    if len(self._cpu_hist) > self.HISTORY:
                        self._cpu_hist.pop(0)
            except Exception:
                pass

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu_now":   self._cpu_now,
                "mem_pct":   self._mem_pct,
                "net_recv":  self._net_rate[0],
                "net_sent":  self._net_rate[1],
                "cpu_hist":  list(self._cpu_hist),
                "processes": list(self._procs),
                "has_psutil": True,
            }

    @staticmethod
    def available() -> bool:
        try:
            import psutil
            return True
        except ImportError:
            return False


# ══════════════════════════════════════════════════════════════════════════════
# HTML / CSS / JS DO DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def _sparkline(vals: list, w: int = 120, h: int = 36, color: str = "#4f8ef7") -> str:
    """Gera SVG de uma sparkline a partir de uma lista de valores 0-100."""
    if not vals:
        return f'<svg width="{w}" height="{h}"></svg>'
    mn, mx = min(vals), max(vals)
    rng = mx - mn or 1
    step = w / max(len(vals) - 1, 1)
    pts = " ".join(
        f"{round(i * step, 1)},{round(h - ((v - mn) / rng) * (h - 4) - 2, 1)}"
        for i, v in enumerate(vals)
    )
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="overflow:visible">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def _build_html(state: dict, cfg: dict, sysinfo: dict | None = None) -> str:
    """Gera o HTML completo do dashboard a partir do estado atual."""
    theme       = cfg.get("theme", "dark")
    extend_min  = cfg.get("extend_minutes", 10)
    refresh_s   = cfg.get("refresh_interval", 5)
    allow_ctrl  = cfg.get("allow_control", True)
    show_hist   = cfg.get("show_history", True)
    has_pin     = bool(cfg.get("pin", "").strip())

    show_start_panel = cfg.get("show_start_panel", True)
    show_cpu         = cfg.get("show_cpu",         True)
    show_network     = cfg.get("show_network",     True)
    show_processes   = cfg.get("show_processes",   True)

    if sysinfo is None:
        sysinfo = {}

    # ── cores por tema ─────────────────────────────────────────────────────────
    if theme == "dark":
        C = {
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
            "border":    "#2a2f4a",
        }
    else:
        C = {
            "bg":        "#f8fafc",
            "surface":   "#ffffff",
            "surface2":  "#f1f5f9",
            "surface3":  "#e2e8f0",
            "accent":    "#2563eb",
            "accent2":   "#7c3aed",
            "danger":    "#dc2626",
            "warning":   "#f59e0b",
            "success":   "#10b981",
            "text":      "#0f172a",
            "text_dim":  "#475569",
            "border":    "#cbd5e1",
        }

    # ── dados do estado ────────────────────────────────────────────────────────
    running   = state.get("running", False)
    paused    = state.get("paused",  False)
    remaining = int(state.get("remaining", 0))
    total     = int(state.get("total", 0))
    action    = state.get("action", "shutdown")
    mode      = state.get("mode",   "countdown")
    history   = state.get("history", [])
    pc_name   = state.get("pc_name", platform.node())
    server_time = datetime.now().strftime("%H:%M:%S")

    action_icons = {
        "shutdown": "⏻", "suspend": "🌙",
        "reboot":   "↺",  "lock":   "🔒",
    }
    action_labels = {
        "shutdown": "Desligar",  "suspend": "Suspender",
        "reboot":   "Reiniciar", "lock":    "Bloquear",
    }
    icon  = action_icons.get(action, "⏻")
    label = action_labels.get(action, action.capitalize())

    # progresso circular
    if total > 0 and running:
        pct = max(0, min(100, (remaining / total) * 100))
    else:
        pct = 0
    stroke_dash = round(pct * 3.77, 2)   # circunferência ~377 para r=60

    # status badge
    if not running:
        status_text  = "Inativo"
        status_color = C["text_dim"]
        status_dot   = C["text_dim"]
        timer_display = "--:--"
    elif paused:
        status_text  = "Pausado"
        status_color = C["warning"]
        status_dot   = C["warning"]
        timer_display = _fmt_seconds(remaining)
    else:
        status_text  = "Em execução"
        status_color = C["success"]
        status_dot   = C["success"]
        timer_display = _fmt_seconds(remaining)

    # botões de controle do timer existente
    ctrl_html = ""
    if allow_ctrl:
        pause_label  = "▐▐  Pausar" if (running and not paused) else "▶  Retomar"
        pause_action = "pause"      if (running and not paused) else "resume"
        ctrl_html = f"""
        <div class="controls">
          <button class="btn btn-success"
                  onclick="sendControl('extend', {{minutes: {extend_min}}})"
                  {'disabled' if not running else ''}>
            ➕ +{extend_min} min
          </button>
          <button class="btn btn-warning"
                  onclick="sendControl('{pause_action}')"
                  {'disabled' if not running else ''}>
            {pause_label}
          </button>
          <button class="btn btn-danger"
                  onclick="confirmCancel()"
                  {'disabled' if not running else ''}>
            ✕ Cancelar
          </button>
          <button class="btn btn-action"
                  onclick="confirmShutdownNow()"
                  title="Executa a ação imediatamente">
            {icon} Agora
          </button>
        </div>"""

    # painel iniciar timer
    start_panel_html = ""
    if show_start_panel and allow_ctrl:
        start_panel_html = f"""
    <div class="card" id="startPanel">
      <div class="card-title">🚀 Iniciar timer</div>
      <div class="start-row">
        <div class="time-field">
          <label>Horas</label>
          <input id="stH" type="number" min="0" max="23" value="0" class="time-inp">
        </div>
        <div class="time-sep">:</div>
        <div class="time-field">
          <label>Min</label>
          <input id="stM" type="number" min="0" max="59" value="5" class="time-inp">
        </div>
        <div class="time-sep">:</div>
        <div class="time-field">
          <label>Seg</label>
          <input id="stS" type="number" min="0" max="59" value="0" class="time-inp">
        </div>
      </div>
      <div class="action-pills" id="actionPills">
        <button class="pill pill-active" data-action="shutdown" onclick="selectAction(this)">⏻ Desligar</button>
        <button class="pill" data-action="suspend"  onclick="selectAction(this)">🌙 Suspender</button>
        <button class="pill" data-action="reboot"   onclick="selectAction(this)">↺ Reiniciar</button>
        <button class="pill" data-action="lock"     onclick="selectAction(this)">🔒 Bloquear</button>
      </div>
      <button class="btn btn-accent" style="margin-top:10px" onclick="startTimer()">
        ▶ Iniciar timer
      </button>
    </div>"""

    # card CPU / RAM
    cpu_card_html = ""
    if show_cpu and sysinfo.get("has_psutil"):
        cpu_now  = sysinfo.get("cpu_now",  0)
        mem_pct  = sysinfo.get("mem_pct",  0)
        cpu_hist = sysinfo.get("cpu_hist", [])
        spark    = _sparkline(cpu_hist, 220, 40, C["accent"])
        cpu_card_html = f"""
    <div class="card">
      <div class="card-title">💻 CPU &amp; RAM</div>
      <div class="sys-row">
        <div class="sys-meter">
          <div class="sys-label">CPU</div>
          <div class="meter-bar"><div class="meter-fill" style="width:{cpu_now:.0f}%;background:{C['accent']}"></div></div>
          <div class="sys-val">{cpu_now:.1f}%</div>
        </div>
        <div class="sys-meter">
          <div class="sys-label">RAM</div>
          <div class="meter-bar"><div class="meter-fill" style="width:{mem_pct:.0f}%;background:{C['accent2']}"></div></div>
          <div class="sys-val">{mem_pct:.1f}%</div>
        </div>
      </div>
      <div style="margin-top:10px;opacity:.8">{spark}</div>
    </div>"""

    # card rede
    net_card_html = ""
    if show_network and sysinfo.get("has_psutil"):
        recv = sysinfo.get("net_recv", 0)
        sent = sysinfo.get("net_sent", 0)
        net_card_html = f"""
    <div class="card">
      <div class="card-title">🌐 Tráfego de rede</div>
      <div class="info-grid">
        <div class="info-cell">
          <div class="info-label">⬇ Download</div>
          <div class="info-value" id="netRecv">{_fmt_bytes(recv)}/s</div>
        </div>
        <div class="info-cell">
          <div class="info-label">⬆ Upload</div>
          <div class="info-value" id="netSent">{_fmt_bytes(sent)}/s</div>
        </div>
      </div>
    </div>"""

    # card processos
    procs_card_html = ""
    if show_processes and sysinfo.get("has_psutil"):
        procs = sysinfo.get("processes", [])
        rows_p = ""
        for p in procs[:10]:
            rows_p += (
                f'<tr><td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
                f'{p["name"]}</td>'
                f'<td>{p["cpu"]:.1f}%</td>'
                f'<td>{p["mem"]:.1f}%</td></tr>'
            )
        procs_card_html = f"""
    <div class="card">
      <div class="card-title">⚙️ Processos (top CPU)</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Processo</th><th>CPU</th><th>RAM</th></tr></thead>
          <tbody>{rows_p}</tbody>
        </table>
      </div>
    </div>"""

    # histórico
    hist_html = ""
    if show_hist and history:
        rows = ""
        for h in reversed(history[-20:]):
            ts   = h.get("ts", "")
            act  = h.get("action", "?")
            mins = h.get("minutes", 0)
            done = h.get("completed", False)
            badge = (f'<span class="badge badge-{"success" if done else "danger"}">'
                     f'{"✓" if done else "✗"}</span>')
            rows += (f'<tr><td>{ts}</td>'
                     f'<td>{action_icons.get(act,"⏻")} {action_labels.get(act,act)}</td>'
                     f'<td>{mins} min</td><td>{badge}</td></tr>')
        hist_html = f"""
    <div class="card">
      <div class="card-title">📋 Histórico de hoje</div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Hora</th><th>Ação</th><th>Duração</th><th>Status</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""

    # modal PIN
    pin_modal = ""
    if has_pin:
        pin_modal = """
    <div id="pinModal" class="modal-overlay" style="display:none">
      <div class="modal-box">
        <div class="modal-title">🔒 Autenticação necessária</div>
        <input id="pinInput" type="password" maxlength="8"
               placeholder="Digite o PIN"
               style="width:100%;padding:10px;font-size:1.2rem;text-align:center;
                      border-radius:8px;border:1px solid var(--border);
                      background:var(--surface2);color:var(--text);margin:12px 0"
               onkeydown="if(event.key==='Enter')submitPin()">
        <button class="btn btn-accent" onclick="submitPin()">Confirmar</button>
        <p id="pinError" style="color:var(--danger);margin-top:8px;display:none">PIN incorreto</p>
      </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <title>ShutdownTimer — {pc_name}</title>
  <style>
    :root {{
      --bg:       {C['bg']};
      --surface:  {C['surface']};
      --surface2: {C['surface2']};
      --surface3: {C['surface3']};
      --accent:   {C['accent']};
      --accent2:  {C['accent2']};
      --danger:   {C['danger']};
      --warning:  {C['warning']};
      --success:  {C['success']};
      --text:     {C['text']};
      --text-dim: {C['text_dim']};
      --border:   {C['border']};
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 0 0 32px;
    }}
    .header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 12px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .header-title {{
      font-size: 1.1rem; font-weight: 700;
      display: flex; align-items: center; gap: 8px;
    }}
    .header-meta {{ font-size: 0.78rem; color: var(--text-dim); }}
    .container {{ max-width: 620px; margin: 0 auto; padding: 16px; }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
      margin-bottom: 14px;
    }}
    .card-title {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: .07em;
      color: var(--text-dim);
      margin-bottom: 14px;
      font-weight: 600;
    }}
    .status-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 20px; }}
    .dot {{
      width: 10px; height: 10px; border-radius: 50%;
      background: {status_dot}; box-shadow: 0 0 6px {status_dot}; flex-shrink: 0;
    }}
    .status-text {{ font-size: 0.9rem; font-weight: 600; color: {status_color}; }}
    .timer-center {{ display: flex; flex-direction: column; align-items: center; gap: 6px; }}
    .ring-wrap {{ position: relative; width: 160px; height: 160px; }}
    .ring-wrap svg {{ transform: rotate(-90deg); }}
    .ring-bg  {{ fill: none; stroke: var(--surface3); stroke-width: 8; }}
    .ring-fill {{
      fill: none; stroke: {C['accent']}; stroke-width: 8;
      stroke-linecap: round;
      stroke-dasharray: {stroke_dash} 377;
      transition: stroke-dasharray 1s linear;
    }}
    .ring-text {{
      position: absolute; inset: 0;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center; gap: 2px;
    }}
    .timer-display {{
      font-size: 2rem; font-weight: 800;
      font-variant-numeric: tabular-nums;
      letter-spacing: -1px; color: var(--text); line-height: 1;
    }}
    .timer-action {{ font-size: 0.95rem; color: var(--text-dim); }}
    .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }}
    .info-cell {{ background: var(--surface2); border-radius: 10px; padding: 12px; }}
    .info-label {{
      font-size: 0.72rem; color: var(--text-dim);
      text-transform: uppercase; letter-spacing: .05em; margin-bottom: 4px;
    }}
    .info-value {{ font-size: 1rem; font-weight: 700; }}
    .controls {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .btn {{
      padding: 12px 8px; border: none; border-radius: 10px;
      font-size: 0.9rem; font-weight: 700; cursor: pointer;
      transition: opacity .15s, transform .1s; color: #fff;
    }}
    .btn:active {{ transform: scale(0.96); }}
    .btn:disabled {{ opacity: .35; cursor: not-allowed; transform: none; }}
    .btn-success {{ background: var(--success); color: #0d0f18; }}
    .btn-warning {{ background: var(--warning); color: #0d0f18; }}
    .btn-danger  {{ background: var(--danger); }}
    .btn-accent  {{ background: var(--accent); width: 100%; padding: 13px; }}
    .btn-action  {{ background: var(--accent2); }}
    /* ── Start panel ── */
    .start-row {{
      display: flex; align-items: flex-end; gap: 6px; margin-bottom: 14px;
    }}
    .time-field {{ display: flex; flex-direction: column; align-items: center; flex: 1; }}
    .time-field label {{ font-size: 0.7rem; color: var(--text-dim); margin-bottom: 4px; }}
    .time-inp {{
      width: 100%; padding: 10px 4px; text-align: center;
      font-size: 1.3rem; font-weight: 700;
      background: var(--surface2); color: var(--text);
      border: 1px solid var(--border); border-radius: 10px;
    }}
    .time-sep {{ font-size: 1.5rem; font-weight: 700; padding-bottom: 6px; color: var(--text-dim); }}
    .action-pills {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 4px; }}
    .pill {{
      padding: 7px 14px; border-radius: 20px; border: 1px solid var(--border);
      background: var(--surface2); color: var(--text-dim);
      font-size: 0.85rem; font-weight: 600; cursor: pointer;
      transition: background .15s, color .15s;
    }}
    .pill-active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    /* ── Sys meters ── */
    .sys-row {{ display: flex; flex-direction: column; gap: 10px; }}
    .sys-meter {{ display: flex; align-items: center; gap: 10px; }}
    .sys-label {{ font-size: 0.78rem; color: var(--text-dim); width: 32px; flex-shrink: 0; }}
    .sys-val   {{ font-size: 0.85rem; font-weight: 700; width: 44px; text-align: right; flex-shrink: 0; }}
    .meter-bar {{
      flex: 1; height: 10px; background: var(--surface3);
      border-radius: 6px; overflow: hidden;
    }}
    .meter-fill {{ height: 100%; border-radius: 6px; transition: width .6s ease; }}
    #toast {{
      position: fixed; bottom: 24px; left: 50%;
      transform: translateX(-50%) translateY(80px);
      background: var(--surface3); border: 1px solid var(--border);
      border-radius: 10px; padding: 12px 22px;
      font-size: 0.9rem; font-weight: 600;
      transition: transform .3s; z-index: 999; white-space: nowrap;
    }}
    #toast.show {{ transform: translateX(-50%) translateY(0); }}
    .modal-overlay {{
      position: fixed; inset: 0; background: rgba(0,0,0,.7);
      display: flex; align-items: center; justify-content: center; z-index: 200;
    }}
    .modal-box {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 16px; padding: 28px 24px;
      max-width: 340px; width: 90%; text-align: center;
    }}
    .modal-title {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 10px; }}
    .modal-msg   {{ font-size: 0.9rem; color: var(--text-dim); margin-bottom: 20px; }}
    .modal-btns  {{ display: flex; gap: 10px; }}
    .modal-btns .btn {{ flex: 1; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    th {{ padding: 8px 10px; text-align: left; color: var(--text-dim);
         font-weight: 600; border-bottom: 1px solid var(--border); }}
    td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); }}
    tr:last-child td {{ border-bottom: none; }}
    .badge {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 22px; height: 22px; border-radius: 50%;
      font-size: 0.75rem; font-weight: 700;
    }}
    .badge-success {{ background: var(--success); color: #0d0f18; }}
    .badge-danger  {{ background: var(--danger);  color: #fff; }}
    .refresh-bar {{
      height: 3px; background: var(--accent); width: 100%;
      animation: shrink {refresh_s}s linear infinite;
    }}
    @keyframes shrink {{ from {{ width:100% }} to {{ width:0% }} }}
    @media (max-width: 400px) {{
      .controls {{ grid-template-columns: 1fr 1fr; }}
      .timer-display {{ font-size: 1.6rem; }}
      .start-row {{ flex-wrap: wrap; }}
    }}
  </style>
</head>
<body>
  <div class="refresh-bar" id="rbar"></div>
  <div class="header">
    <div class="header-title"><span>⏱</span><span>ShutdownTimer</span></div>
    <div class="header-meta">🖥 {pc_name} &nbsp;·&nbsp; {server_time}</div>
  </div>
  <div class="container">

    <!-- Timer card -->
    <div class="card">
      <div class="card-title">⏱ Timer</div>
      <div class="status-row">
        <div class="dot"></div>
        <div class="status-text">{status_text}</div>
      </div>
      <div class="timer-center">
        <div class="ring-wrap">
          <svg width="160" height="160" viewBox="0 0 160 160">
            <circle class="ring-bg"   cx="80" cy="80" r="60"/>
            <circle class="ring-fill" cx="80" cy="80" r="60"
                    id="ring" style="stroke-dasharray:{stroke_dash} 377"/>
          </svg>
          <div class="ring-text">
            <div class="timer-display" id="timerDisplay">{timer_display}</div>
            <div class="timer-action">{icon} {label}</div>
          </div>
        </div>
      </div>
      <div class="info-grid">
        <div class="info-cell">
          <div class="info-label">Modo</div>
          <div class="info-value" id="modeVal">{mode.replace("countdown","Contagem")
                                                   .replace("smart","Inteligente")
                                                   .replace("conditional","Condicional")}</div>
        </div>
        <div class="info-cell">
          <div class="info-label">Total programado</div>
          <div class="info-value" id="totalVal">{_fmt_seconds(total) if total else '--'}</div>
        </div>
      </div>
    </div>

    <!-- Controles do timer ativo -->
    {'<div class="card"><div class="card-title">🎮 Controle remoto</div>' + ctrl_html + '</div>'
     if allow_ctrl else ''}

    <!-- Iniciar novo timer -->
    {start_panel_html}

    <!-- CPU & RAM -->
    {cpu_card_html}

    <!-- Rede -->
    {net_card_html}

    <!-- Processos -->
    {procs_card_html}

    <!-- Histórico -->
    {hist_html}

  </div>

  <div id="toast">✅ Feito!</div>

  <div id="confirmModal" class="modal-overlay" style="display:none">
    <div class="modal-box">
      <div class="modal-title" id="confirmTitle">Confirmar</div>
      <div class="modal-msg"   id="confirmMsg">Tem certeza?</div>
      <div class="modal-btns">
        <button class="btn btn-danger" onclick="confirmAction()">Sim</button>
        <button class="btn" style="background:var(--surface3)" onclick="closeConfirm()">Cancelar</button>
      </div>
    </div>
  </div>

  {pin_modal}

  <script>
    let _pin         = '';
    let _pendingCmd  = null;
    let _pendingArgs = null;
    let _confirmCb   = null;
    let _selAction   = 'shutdown';
    const HAS_PIN  = {'true' if has_pin else 'false'};
    const REFRESH_S = {refresh_s};

    // ── Live update timer ──────────────────────────────────────────
    function liveUpdate() {{
      fetch('/api/status')
        .then(r => r.json())
        .then(d => {{
          const td = document.getElementById('timerDisplay');
          const ri = document.getElementById('ring');
          if (!td) return;
          td.textContent = d.timer_display || '--:--';
          const pct = d.progress_pct || 0;
          ri.style.strokeDasharray = (pct * 3.77).toFixed(2) + ' 377';
        }})
        .catch(() => {{}});
    }}

    // ── Live update sysinfo ────────────────────────────────────────
    function sysUpdate() {{
      fetch('/api/sysinfo')
        .then(r => r.json())
        .then(d => {{
          const nr = document.getElementById('netRecv');
          const ns = document.getElementById('netSent');
          if (nr) nr.textContent = d.net_recv_fmt + '/s';
          if (ns) ns.textContent = d.net_sent_fmt + '/s';
        }})
        .catch(() => {{}});
    }}

    setInterval(liveUpdate, REFRESH_S * 1000);
    setInterval(sysUpdate,  3000);
    setTimeout(() => location.reload(), 30000);

    // ── Toast ──────────────────────────────────────────────────────
    function showToast(msg, ms=2500) {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), ms);
    }}

    // ── Controle timer ativo ───────────────────────────────────────
    function sendControl(cmd, args={{}}) {{
      if (HAS_PIN && !_pin) {{
        _pendingCmd  = cmd;
        _pendingArgs = args;
        document.getElementById('pinModal').style.display = 'flex';
        setTimeout(() => document.getElementById('pinInput').focus(), 100);
        return;
      }}
      const body = Object.assign({{cmd}}, args, _pin ? {{pin: _pin}} : {{}});
      fetch('/api/control', {{
        method:  'POST',
        headers: {{'Content-Type': 'application/json'}},
        body:    JSON.stringify(body),
      }})
      .then(r => r.json())
      .then(d => {{
        if (d.ok) {{
          showToast('✅ ' + (d.message || 'Comando enviado'));
          setTimeout(() => location.reload(), 1000);
        }} else {{
          showToast('❌ ' + (d.error || 'Erro'));
          if (d.error === 'PIN inválido') {{ _pin = ''; }}
        }}
      }})
      .catch(() => showToast('❌ Sem resposta do servidor'));
    }}

    // ── Iniciar timer ──────────────────────────────────────────────
    function selectAction(el) {{
      document.querySelectorAll('.pill').forEach(p => p.classList.remove('pill-active'));
      el.classList.add('pill-active');
      _selAction = el.dataset.action;
    }}
    function startTimer() {{
      const h = parseInt(document.getElementById('stH').value) || 0;
      const m = parseInt(document.getElementById('stM').value) || 0;
      const s = parseInt(document.getElementById('stS').value) || 0;
      const total = h * 3600 + m * 60 + s;
      if (total <= 0) {{ showToast('⚠️ Defina um tempo maior que zero'); return; }}
      sendControl('start_timer', {{seconds: total, action: _selAction}});
    }}

    // ── PIN ────────────────────────────────────────────────────────
    function submitPin() {{
      const val = document.getElementById('pinInput').value.trim();
      if (!val) return;
      _pin = val;
      document.getElementById('pinModal').style.display = 'none';
      document.getElementById('pinInput').value = '';
      document.getElementById('pinError').style.display = 'none';
      if (_pendingCmd) {{
        sendControl(_pendingCmd, _pendingArgs || {{}});
        _pendingCmd = _pendingArgs = null;
      }}
    }}

    // ── Confirmações ───────────────────────────────────────────────
    function confirmCancel() {{
      _confirmCb = () => sendControl('cancel');
      document.getElementById('confirmTitle').textContent = '✕ Cancelar timer';
      document.getElementById('confirmMsg').textContent   =
        'O timer será cancelado. Nenhuma ação será executada.';
      document.getElementById('confirmModal').style.display = 'flex';
    }}
    function confirmShutdownNow() {{
      _confirmCb = () => sendControl('execute_now');
      document.getElementById('confirmTitle').textContent = '⚠️ Executar agora';
      document.getElementById('confirmMsg').textContent   =
        'A ação será executada IMEDIATAMENTE. Salve seu trabalho!';
      document.getElementById('confirmModal').style.display = 'flex';
    }}
    function confirmAction() {{
      closeConfirm();
      if (_confirmCb) {{ _confirmCb(); _confirmCb = null; }}
    }}
    function closeConfirm() {{
      document.getElementById('confirmModal').style.display = 'none';
    }}
  </script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class _DashboardHandler(BaseHTTPRequestHandler):
    """Handler HTTP para o dashboard."""

    # referência ao plugin injetada pelo servidor
    plugin: "WebDashboardPlugin | None" = None

    # ── silencia logs padrão do BaseHTTPRequestHandler ────────────────────────
    def log_message(self, fmt, *args):
        pass

    def log_error(self, fmt, *args):
        log.debug(f"[web_dashboard] HTTP error: {fmt % args}")

    # ── rota GET ──────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._serve_dashboard()
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/sysinfo":
            self._serve_sysinfo()
        elif path == "/favicon.ico":
            self._respond(200, b"\x00", "image/x-icon")
        else:
            self._respond(404, b"Not found", "text/plain")

    # ── rota POST ─────────────────────────────────────────────────────────────
    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/api/control":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                data = json.loads(body)
            except Exception:
                self._json({"ok": False, "error": "JSON inválido"})
                return
            self._handle_control(data)
        else:
            self._respond(404, b"Not found", "text/plain")

    # ── handlers ──────────────────────────────────────────────────────────────
    def _serve_dashboard(self):
        p = self.plugin
        if p is None:
            self._respond(503, b"Plugin not ready", "text/plain")
            return
        sysinfo = p.get_sysinfo()
        html = _build_html(p.get_state(), p.get_cfg(), sysinfo).encode("utf-8")
        self._respond(200, html, "text/html; charset=utf-8")

    def _serve_status(self):
        p = self.plugin
        if p is None:
            self._json({"error": "not ready"})
            return
        state = p.get_state()
        remaining = int(state.get("remaining", 0))
        total     = int(state.get("total", 0))
        pct = round((remaining / total) * 100, 1) if total > 0 else 0
        self._json({
            "timer_display": _fmt_seconds(remaining) if state.get("running") else "--:--",
            "remaining":     remaining,
            "total":         total,
            "progress_pct":  pct,
            "running":       state.get("running", False),
            "paused":        state.get("paused",  False),
            "action":        state.get("action",  "shutdown"),
            "mode":          state.get("mode",    "countdown"),
        })

    def _serve_sysinfo(self):
        p = self.plugin
        if p is None:
            self._json({"error": "not ready"})
            return
        si = p.get_sysinfo()
        si["net_recv_fmt"] = _fmt_bytes(si.get("net_recv", 0))
        si["net_sent_fmt"] = _fmt_bytes(si.get("net_sent", 0))
        self._json(si)

    def _handle_control(self, data: dict):
        p = self.plugin
        if p is None:
            self._json({"ok": False, "error": "Plugin não disponível"})
            return

        # verificação de PIN
        cfg     = p.get_cfg()
        pin_cfg = cfg.get("pin", "").strip()
        if pin_cfg:
            pin_sent = str(data.get("pin", "")).strip()
            if _pin_hash(pin_sent) != _pin_hash(pin_cfg):
                self._json({"ok": False, "error": "PIN inválido"})
                return

        if not cfg.get("allow_control", True):
            self._json({"ok": False, "error": "Controle remoto desativado"})
            return

        cmd = data.get("cmd", "")
        ok, msg = p.execute_command(cmd, data)
        self._json({"ok": ok, "message": msg} if ok
                   else {"ok": False, "error": msg})

    # ── helpers ───────────────────────────────────────────────────────────────
    def _respond(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._respond(200, body, "application/json; charset=utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class _ReuseHTTPServer(HTTPServer):
    """HTTPServer com allow_reuse_address sempre ativo.

    O flag deve ser definido como atributo de classe *antes* de
    server_bind() ser chamado pelo __init__ do HTTPServer.
    """
    allow_reuse_address = True


class WebDashboardPlugin:
    """Plugin Web Dashboard — servidor HTTP + dashboard responsivo."""

    def __init__(self, api=None):
        self.api:     Any           = api
        self._server: Optional[_ReuseHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._cfg:    dict          = {}
        self._sysinfo = SysInfoCollector()
        self._refresh_cfg()

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def on_load(self):
        self._refresh_cfg()
        self._sysinfo.start()
        if self._cfg.get("start_on_load", True):
            self.start_server()
        else:
            self._log("Servidor não iniciado (start_on_load=False). "
                      "Use o botão de controle para iniciar.")

    def on_unload(self):
        self.stop_server()
        self._sysinfo.stop()
        self._firewall_close()
        self._log("Web Dashboard descarregado.")

    def on_config_changed(self, new_cfg: dict):
        was_running = self._running
        self.stop_server()
        self._cfg = new_cfg
        if was_running:
            self.start_server()

    # ── Firewall Windows ──────────────────────────────────────────────────────

    _FW_RULE = "ShutdownTimer Web Dashboard"

    def _firewall_open(self, port: int) -> None:
        """Abre a porta no Firewall do Windows (silenciosamente, em background)."""
        if platform.system() != "Windows":
            return
        def _run():
            try:
                import subprocess
                # Remove regra antiga (se existir para outra porta) e cria nova
                subprocess.run(
                    ["netsh", "advfirewall", "firewall", "delete", "rule",
                     f"name={self._FW_RULE}"],
                    capture_output=True, timeout=10
                )
                subprocess.run(
                    ["netsh", "advfirewall", "firewall", "add", "rule",
                     f"name={self._FW_RULE}",
                     "dir=in", "action=allow", "protocol=TCP",
                     f"localport={port}",
                     "description=ShutdownTimer Web Dashboard — porta HTTP local"],
                    capture_output=True, timeout=10
                )
                self._log(f"🔓 Firewall: porta {port} liberada (TCP inbound)")
            except Exception as e:
                self._log(f"⚠️ Firewall: não foi possível abrir porta {port}: {e}")
        threading.Thread(target=_run, daemon=True, name="fw_open").start()

    def _firewall_close(self) -> None:
        """Remove a regra de firewall criada pelo plugin."""
        if platform.system() != "Windows":
            return
        def _run():
            try:
                import subprocess
                subprocess.run(
                    ["netsh", "advfirewall", "firewall", "delete", "rule",
                     f"name={self._FW_RULE}"],
                    capture_output=True, timeout=10
                )
                self._log("🔒 Firewall: regra removida")
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True, name="fw_close").start()

    # ── Servidor ──────────────────────────────────────────────────────────────

    def start_server(self) -> bool:
        if self._running:
            return True

        host = self._cfg.get("host", "0.0.0.0")
        port = int(self._cfg.get("port", 8080))

        # cria handler com referência ao plugin
        handler = type(
            "_BoundHandler",
            (_DashboardHandler,),
            {"plugin": self},
        )

        try:
            srv = _ReuseHTTPServer((host, port), handler)
            srv.timeout = 0.5          # select() timeout dentro de handle_request
        except OSError as e:
            self._log(f"❌ Não foi possível iniciar o servidor na porta {port}: {e}")
            return False

        self._stop_event.clear()
        self._server  = srv
        self._running = True

        self._thread = threading.Thread(
            target=self._serve_loop,
            name="web_dashboard_http",
            daemon=True,
        )
        self._thread.start()

        # Abre porta no Firewall do Windows para acesso pela rede local
        self._firewall_open(port)

        ips = _get_local_ips()
        urls = [f"http://{ip}:{port}" for ip in ips]
        url_list = "  |  ".join(urls)
        self._log(f"✅ Servidor iniciado em: {url_list}")

        if self.api:
            self.api.show_notification(
                "Web Dashboard ativo",
                f"Dashboard disponível em:\n{urls[0]}",
            )

        return True

    def stop_server(self):
        """Para o servidor HTTP de forma imediata e não-bloqueante.

        Usa server_close() para fechar o socket do servidor — isso faz o
        handle_request() em andamento sair imediatamente com OSError,
        sem precisar aguardar a conclusão via shutdown().
        """
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        srv, self._server = self._server, None
        if srv:
            try:
                srv.server_close()   # fecha o socket → handle_request() retorna
            except Exception:
                pass
        self._log("🔌 Servidor parado.")

    def _serve_loop(self):
        """Loop de requisições — sai imediatamente quando o socket é fechado."""
        while not self._stop_event.is_set():
            srv = self._server
            if srv is None:
                break
            try:
                srv.handle_request()
            except OSError:
                # socket fechado por stop_server() — saída limpa
                break
            except Exception:
                if not self._stop_event.is_set():
                    pass  # erro transitório — continua

    # ── Estado ────────────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Coleta estado atual do timer via PluginAPI (ou fallback vazio)."""
        state: dict = {
            "running":  False,
            "paused":   False,
            "remaining": 0,
            "total":    0,
            "action":   "shutdown",
            "mode":     "countdown",
            "history":  [],
            "pc_name":  platform.node(),
        }
        if self.api:
            try:
                ts = self.api.get_timer_state()
                state.update({
                    "running":   ts.get("running",   False),
                    "paused":    ts.get("paused",    False),
                    "remaining": ts.get("remaining", 0),
                    "total":     ts.get("total",     0),
                    "action":    ts.get("action",    "shutdown"),
                })
            except Exception as e:
                self._log(f"get_timer_state: {e}")

            # histórico via app
            try:
                app = getattr(self.api._manager, "_app", None)
                if app and hasattr(app, "config"):
                    raw_hist = app.config.get("history") or []
                    today    = datetime.now().strftime("%Y-%m-%d")
                    today_hist = [
                        h for h in raw_hist
                        if str(h.get("date", "")).startswith(today)
                    ]
                    state["history"] = today_hist
            except Exception:
                pass

            # modo atual (smart / conditional / countdown)
            try:
                app = getattr(self.api._manager, "_app", None)
                if app:
                    if getattr(app, "_smart_active", False):
                        state["mode"] = "smart"
                    elif getattr(app, "_cond_active", False):
                        state["mode"] = "conditional"
            except Exception:
                pass

        return state

    def get_cfg(self) -> dict:
        return self._cfg

    def _refresh_cfg(self):
        if self.api:
            self._cfg = self.api.get_config() or {}
        if not self._cfg:
            self._cfg = {
                "port":             8080,
                "host":             "0.0.0.0",
                "pin":              "",
                "allow_control":    True,
                "extend_minutes":   10,
                "refresh_interval": 5,
                "show_history":     True,
                "theme":            "dark",
                "start_on_load":    True,
                "show_start_panel": True,
                "show_cpu":         True,
                "show_network":     True,
                "show_processes":   True,
            }

    def get_sysinfo(self) -> dict:
        """Retorna snapshot do SysInfoCollector."""
        return self._sysinfo.snapshot()

    # ── Comandos de controle ──────────────────────────────────────────────────

    def execute_command(self, cmd: str, data: dict) -> Tuple[bool, str]:
        """Processa comando vindo do dashboard. Retorna (ok, mensagem)."""
        if not self.api:
            return False, "API não disponível"

        if cmd == "cancel":
            try:
                self.api.execute_action("cancel_timer")
                self._log("🖥 Controle remoto: timer cancelado")
                return True, "Timer cancelado"
            except Exception as e:
                return False, str(e)

        elif cmd == "pause":
            try:
                self.api.execute_action("pause_timer")
                self._log("🖥 Controle remoto: timer pausado")
                return True, "Timer pausado"
            except Exception as e:
                return False, str(e)

        elif cmd == "resume":
            try:
                self.api.execute_action("resume_timer")
                self._log("🖥 Controle remoto: timer retomado")
                return True, "Timer retomado"
            except Exception as e:
                return False, str(e)

        elif cmd == "extend":
            try:
                minutes = int(data.get("minutes", self._cfg.get("extend_minutes", 10)))
                seconds = minutes * 60
                app = getattr(self.api._manager, "_app", None)
                if app and hasattr(app, "engine"):
                    app.engine.extend(seconds)
                    self._log(f"🖥 Controle remoto: +{minutes} min")
                    return True, f"+{minutes} min adicionados"
                return False, "Timer não disponível"
            except Exception as e:
                return False, str(e)

        elif cmd == "execute_now":
            try:
                app = getattr(self.api._manager, "_app", None)
                if app and hasattr(app, "engine"):
                    action = app.engine.state.action if hasattr(app.engine, "state") else "shutdown"
                    self.api.execute_action(action)
                    self._log(f"🖥 Controle remoto: executar agora ({action})")
                    return True, f"Ação '{action}' executada"
                return False, "Timer não disponível"
            except Exception as e:
                return False, str(e)

        elif cmd == "start_timer":
            try:
                seconds = int(data.get("seconds", 0))
                action  = str(data.get("action", "shutdown"))
                if seconds <= 0:
                    return False, "Tempo deve ser maior que zero"
                app = getattr(self.api._manager, "_app", None)
                if app and hasattr(app, "engine"):
                    app.root.after(0, lambda s=seconds, a=action: app.engine.start(s, a))
                    self._log(f"🖥 Controle remoto: iniciar timer {seconds}s → {action}")
                    return True, f"Timer iniciado: {_fmt_seconds(seconds)} → {action}"
                return False, "Timer não disponível"
            except Exception as e:
                return False, str(e)

        else:
            return False, f"Comando desconhecido: {cmd}"

    # ── Log ───────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        if self.api:
            self.api.log(msg)
        else:
            log.info(f"[web_dashboard] {msg}")

    # ── Info pública ──────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    def get_urls(self) -> List[str]:
        port = int(self._cfg.get("port", 8080))
        return [f"http://{ip}:{port}" for ip in _get_local_ips()]


# ══════════════════════════════════════════════════════════════════════════════
# PONTO DE ENTRADA — protocolo PluginManager
# ══════════════════════════════════════════════════════════════════════════════

def on_load(api=None):
    global _plugin
    _plugin = WebDashboardPlugin(api)
    _plugin.on_load()
    return _plugin


def on_unload():
    global _plugin
    if _plugin:
        _plugin.on_unload()
        _plugin = None


def on_config_changed(new_config: dict):
    if _plugin:
        _plugin.on_config_changed(new_config)


# ── API de conveniência para acesso externo ────────────────────────────────────

def get_status() -> dict:
    """Retorna estado atual do plugin (para diagnóstico)."""
    if _plugin is None:
        return {"running": False, "urls": [], "error": "Plugin não carregado"}
    return {
        "running": _plugin.is_running,
        "urls":    _plugin.get_urls(),
        "config":  _plugin.get_cfg(),
    }
