"""
╔══════════════════════════════════════════════════════════════╗
║              ShutdownTimer  v3.0                             ║
║  Agendador inteligente de desligamento para Windows/Linux    ║
╠══════════════════════════════════════════════════════════════╣
║  Arquitetura (separação total de responsabilidades):         ║
║   • SystemController  — ações de SO (shutdown/suspend/...)   ║
║   • TimerEngine       — contagem regressiva thread-safe      ║
║   • ConditionMonitor  — shutdown condicional (CPU/proc/net)  ║
║   • ConfigManager     — persistência JSON                    ║
║   • TrayManager       — ícone na bandeja do sistema          ║
║   • NotificationManager — notificações nativas do SO         ║
║   • HotkeyManager     — atalhos globais de teclado           ║
║   • ShutdownApp       — janela principal (UI)                ║
║   • MiniWidget        — widget flutuante compacto            ║
║   • CLI               — modo linha de comando                ║
╚══════════════════════════════════════════════════════════════╝

Dependências obrigatórias:
    pip install customtkinter

Dependências opcionais (degradam graciosamente se ausentes):
    pip install pystray pillow   # bandeja do sistema
    pip install plyer            # notificações nativas
    pip install psutil           # shutdown condicional (CPU/processo/rede)
    pip install keyboard         # atalhos globais
"""

import os
import sys
import csv
import json
import time
import signal
import argparse
import platform
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Callable, Optional
from dataclasses import dataclass

import customtkinter as ctk
from tkinter import messagebox, filedialog
import tkinter as tk

# ── Imports opcionais ──────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from plyer import notification as plyer_notify
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False


# ══════════════════════════════════════════════════════════════
# 1. SYSTEM CONTROLLER
# ══════════════════════════════════════════════════════════════

class SystemController:
    """Executa ações de energia/sessão de forma segura e portável."""

    PLATFORM = platform.system()  # 'Windows' | 'Linux' | 'Darwin'

    @classmethod
    def shutdown(cls) -> bool:
        try:
            if cls.PLATFORM == "Windows":
                subprocess.run(["shutdown", "/s", "/t", "1"], check=True)
            else:
                subprocess.run(["shutdown", "-h", "now"], check=True)
            return True
        except Exception as e:
            print(f"[SysCtrl] shutdown: {e}"); return False

    @classmethod
    def suspend(cls) -> bool:
        try:
            if cls.PLATFORM == "Windows":
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True)
            elif cls.PLATFORM == "Linux":
                subprocess.run(["systemctl", "suspend"], check=True)
            elif cls.PLATFORM == "Darwin":
                subprocess.run(["pmset", "sleepnow"], check=True)
            return True
        except Exception as e:
            print(f"[SysCtrl] suspend: {e}"); return False

    @classmethod
    def reboot(cls) -> bool:
        try:
            if cls.PLATFORM == "Windows":
                subprocess.run(["shutdown", "/r", "/t", "1"], check=True)
            else:
                subprocess.run(["reboot"], check=True)
            return True
        except Exception as e:
            print(f"[SysCtrl] reboot: {e}"); return False

    @classmethod
    def lock(cls) -> bool:
        try:
            if cls.PLATFORM == "Windows":
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
            elif cls.PLATFORM == "Linux":
                for cmd in [["loginctl", "lock-session"], ["xdg-screensaver", "lock"],
                            ["gnome-screensaver-command", "--lock"], ["xscreensaver-command", "-lock"]]:
                    try:
                        subprocess.run(cmd, check=True, timeout=3); return True
                    except Exception:
                        continue
                return False
            elif cls.PLATFORM == "Darwin":
                subprocess.run(["osascript", "-e",
                    'tell application "System Events" to keystroke "q" '
                    'using {command down, control down}'], check=True)
            return True
        except Exception as e:
            print(f"[SysCtrl] lock: {e}"); return False

    @classmethod
    def execute(cls, action: str) -> bool:
        return {
            "shutdown": cls.shutdown, "suspend": cls.suspend,
            "reboot":   cls.reboot,   "lock":    cls.lock,
        }.get(action, lambda: False)()

    @classmethod
    def get_idle_seconds(cls) -> float:
        try:
            if cls.PLATFORM == "Windows":
                import ctypes
                class LII(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
                lii = LII(); lii.cbSize = ctypes.sizeof(LII)
                ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
                return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
            elif cls.PLATFORM == "Linux":
                r = subprocess.run(["xprintidle"], capture_output=True, text=True)
                return int(r.stdout.strip()) / 1000.0
        except Exception:
            pass
        return 9999.0

    @classmethod
    def get_cpu_percent(cls) -> float:
        return psutil.cpu_percent(interval=0.2) if HAS_PSUTIL else 50.0

    @classmethod
    def get_net_bytes_recv(cls) -> int:
        return psutil.net_io_counters().bytes_recv if HAS_PSUTIL else 0

    @classmethod
    def is_process_running(cls, name: str) -> bool:
        if not HAS_PSUTIL or not name.strip(): return False
        name_lower = name.lower().strip()
        for p in psutil.process_iter(["name"]):
            try:
                if name_lower in p.info["name"].lower(): return True
            except Exception:
                pass
        return False

    @classmethod
    def is_fullscreen_active(cls) -> bool:
        if cls.PLATFORM != "Windows": return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd: return False
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            sw = user32.GetSystemMetrics(0); sh = user32.GetSystemMetrics(1)
            return (rect.left <= 0 and rect.top <= 0
                    and rect.right >= sw and rect.bottom >= sh)
        except Exception:
            return False

    @classmethod
    def set_autostart(cls, enable: bool) -> bool:
        name = "ShutdownTimer"
        app_path = sys.executable
        try:
            if cls.PLATFORM == "Windows":
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE)
                if enable:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ,
                                      f'"{app_path}" --gui')
                else:
                    try: winreg.DeleteValue(key, name)
                    except FileNotFoundError: pass
                winreg.CloseKey(key)
                return True
            elif cls.PLATFORM == "Linux":
                d = Path.home() / ".config" / "autostart"
                d.mkdir(parents=True, exist_ok=True)
                desktop = d / f"{name}.desktop"
                if enable:
                    desktop.write_text(
                        f"[Desktop Entry]\nType=Application\nName={name}\n"
                        f"Exec={app_path} --gui\nHidden=false\n"
                        f"X-GNOME-Autostart-enabled=true\n")
                else:
                    desktop.unlink(missing_ok=True)
                return True
        except Exception as e:
            print(f"[Autostart] {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 2. TIMER ENGINE
# ══════════════════════════════════════════════════════════════

@dataclass
class TimerState:
    total_seconds: int = 0
    remaining: int     = 0
    running: bool      = False
    cancelled: bool    = False
    paused: bool       = False
    action: str        = "shutdown"


class TimerEngine:
    """
    Motor de contagem regressiva desacoplado da UI.
    Suporta pausa/retomada e extensão dinâmica.
    Toda comunicação com a UI ocorre via callbacks.
    """

    def __init__(self):
        self._stop_event  = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.state = TimerState()

        self.on_tick:      Optional[Callable[[int], None]]  = None
        self.on_finished:  Optional[Callable[[], None]]     = None
        self.on_cancelled: Optional[Callable[[], None]]     = None
        self.on_warning:   Optional[Callable[[int], None]]  = None
        self.on_paused:    Optional[Callable[[bool], None]] = None
        self.warning_thresholds: set = {300, 60, 30, 10}

    def start(self, seconds: int, action: str = "shutdown") -> bool:
        if self.state.running: return False
        self.state = TimerState(total_seconds=seconds, remaining=seconds,
                                running=True, action=action)
        self._stop_event.clear()
        self._pause_event.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        with self._lock:
            if self.state.running:
                self.state.cancelled = True
                self._pause_event.set()
                self._stop_event.set()

    def pause_resume(self) -> bool:
        """Alterna pause. Retorna True se pausou agora."""
        if self._pause_event.is_set():
            self._pause_event.clear(); self.state.paused = True
            if self.on_paused: self.on_paused(True)
            return True
        else:
            self._pause_event.set(); self.state.paused = False
            if self.on_paused: self.on_paused(False)
            return False

    def extend(self, extra_seconds: int):
        with self._lock:
            if self.state.running:
                self.state.remaining     += extra_seconds
                self.state.total_seconds += extra_seconds

    @property
    def progress(self) -> float:
        if self.state.total_seconds == 0: return 0.0
        return 1.0 - (self.state.remaining / self.state.total_seconds)

    @property
    def is_running(self) -> bool:
        return self.state.running

    def _run(self):
        warned: set = set()
        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set(): break
            for t in self.warning_thresholds:
                if self.state.remaining <= t and t not in warned:
                    warned.add(t)
                    if self.on_warning: self.on_warning(self.state.remaining)
            if self.on_tick: self.on_tick(self.state.remaining)
            if self.state.remaining <= 0: break
            self._stop_event.wait(timeout=1.0)
            if not self.state.paused:
                with self._lock: self.state.remaining -= 1

        self.state.running = False
        if self.state.cancelled or self._stop_event.is_set():
            if self.on_cancelled: self.on_cancelled()
        else:
            if self.on_tick: self.on_tick(0)
            if self.on_finished: self.on_finished()


# ══════════════════════════════════════════════════════════════
# 3. CONDITION MONITOR
# ══════════════════════════════════════════════════════════════

@dataclass
class Condition:
    kind: str
    param: str = ""
    enabled: bool = True


class ConditionMonitor:
    """Monitora condições do sistema e dispara ação quando satisfeitas."""

    POLL = 5  # segundos

    def __init__(self):
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.action = "shutdown"
        self.conditions: list = []
        self.on_condition_met: Optional[Callable[[str, str], None]] = None
        self._net_baseline = 0
        self._net_high_seen = False

    def start(self, action: str, conditions: list):
        if self._thread and self._thread.is_alive(): return
        self.action = action
        self.conditions = [c for c in conditions if c.enabled]
        self._stop.clear()
        self._net_baseline = SystemController.get_net_bytes_recv()
        self._net_high_seen = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self): self._stop.set()

    def _run(self):
        while not self._stop.wait(self.POLL):
            for cond in self.conditions:
                ok, desc = self._check(cond)
                if ok:
                    if self.on_condition_met:
                        self.on_condition_met(self.action, desc)
                    self._stop.set(); return

    def _check(self, cond: Condition):
        if cond.kind == "cpu_low":
            threshold = float(cond.param or "10")
            cpu = SystemController.get_cpu_percent()
            if cpu < threshold:
                return True, f"CPU baixa ({cpu:.1f}% < {threshold}%)"
        elif cond.kind == "process_closed":
            name = cond.param.strip()
            if name and not SystemController.is_process_running(name):
                return True, f"Processo '{name}' encerrado"
        elif cond.kind == "download_done":
            now = SystemController.get_net_bytes_recv()
            rate = (now - self._net_baseline) / self.POLL
            self._net_baseline = now
            min_rate = float(cond.param or "50000")
            if not self._net_high_seen and rate > min_rate:
                self._net_high_seen = True
            if self._net_high_seen and rate < min_rate * 0.05:
                return True, f"Download concluído (taxa: {rate:.0f} B/s)"
        elif cond.kind == "idle":
            threshold = float(cond.param or "1800")
            idle = SystemController.get_idle_seconds()
            if idle >= threshold:
                return True, f"Inativo por {idle/60:.0f} min"
        return False, ""


# ══════════════════════════════════════════════════════════════
# 4. CONFIG MANAGER
# ══════════════════════════════════════════════════════════════

class ConfigManager:
    DEFAULT: dict = {
        "last_minutes":         30,
        "last_action":          "shutdown",
        "presets":              [15, 30, 60, 120],
        "sound_warning":        False,
        "gamer_mode":           False,
        "gamer_idle_threshold": 30,
        "gamer_processes":      [],
        "adaptive_enabled":     False,
        "adaptive_extend_min":  10,
        "autostart":            False,
        "hotkeys_enabled":      False,
        "hotkey_start":         "ctrl+alt+s",
        "hotkey_cancel":        "ctrl+alt+x",
        "hotkey_widget":        "ctrl+alt+w",
        "mini_widget_pos":      [50, 50],
        "schedule_mode":        "countdown",
        "schedule_hour":        23,
        "schedule_minute":      30,
        "cond_enabled":         True,
        "cond_action":          "shutdown",
        "conditions":           [],
        "stats": {"total_completed": 0, "by_action": {}, "total_minutes": 0},
        "history": [],
    }

    def __init__(self):
        self.path = Path.home() / ".shutdown_timer_config.json"
        self.data = self._load()

    def _load(self) -> dict:
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                return self._merge(self.DEFAULT, loaded)
        except Exception:
            pass
        import copy; return copy.deepcopy(self.DEFAULT)

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._merge(result[k], v)
            else:
                result[k] = v
        return result

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[Config] {e}")

    def get(self, key: str):
        return self.data.get(key, self.DEFAULT.get(key))

    def set(self, key: str, value):
        self.data[key] = value; self.save()

    def add_history(self, action: str, minutes: int, completed: bool):
        self.data["history"].insert(0, {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action, "minutes": minutes, "completed": completed
        })
        self.data["history"] = self.data["history"][:50]
        if completed:
            s = self.data["stats"]
            s["total_completed"] += 1
            s["total_minutes"]   += minutes
            s["by_action"][action] = s["by_action"].get(action, 0) + 1
        self.save()

    def export_csv(self, path: str):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp","action","minutes","completed"])
            w.writeheader(); w.writerows(self.data["history"])

    def export_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data["history"], f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# 5. NOTIFICATION MANAGER
# ══════════════════════════════════════════════════════════════

class NotificationManager:
    @staticmethod
    def send(title: str, message: str, timeout: int = 8):
        if HAS_PLYER:
            try:
                plyer_notify.notify(title=title, message=message,
                                    app_name="ShutdownTimer", timeout=timeout)
                return
            except Exception as e:
                print(f"[Notify] {e}")

    @staticmethod
    def play_beeps():
        def _do():
            try:
                if SystemController.PLATFORM == "Windows":
                    import winsound
                    for freq, dur in [(880,250),(1100,250),(880,250),(1100,400)]:
                        winsound.Beep(freq, dur); time.sleep(0.1)
                else:
                    for _ in range(5): print("\a", end="", flush=True); time.sleep(0.4)
            except Exception as e: print(f"[Sound] {e}")
        threading.Thread(target=_do, daemon=True).start()


# ══════════════════════════════════════════════════════════════
# 6. TRAY MANAGER
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
        # Símbolo de power simples
        cx, cy, r = self.SZ//2, self.SZ//2, 16
        draw.arc([cx-r, cy-r, cx+r, cy+r], start=40, end=320,
                 fill=fg, width=5)
        draw.line([cx, cy-r, cx, cy-4], fill=fg, width=5)
        return img

    def start(self):
        if not HAS_TRAY or self._icon: return
        menu = pystray.Menu(
            pystray.MenuItem("⏻  ShutdownTimer", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir janela",
                lambda: self._app.root.after(0, self._show_window)),
            pystray.MenuItem("⧉  Widget compacto",
                lambda: self._app.root.after(0, self._app._toggle_mini_widget)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("▶ Shutdown 30min",
                lambda: self._app.root.after(0, self._quick, "shutdown", 30)),
            pystray.MenuItem("▶ Shutdown 1h",
                lambda: self._app.root.after(0, self._quick, "shutdown", 60)),
            pystray.MenuItem("▶ Suspender 30min",
                lambda: self._app.root.after(0, self._quick, "suspend", 30)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⏹ Cancelar timer",
                lambda: self._app.root.after(0, self._app._cancel),
                enabled=lambda item: self._app.engine.is_running),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("✕ Sair",
                lambda: self._app.root.after(0, self._app._quit_app)),
        )
        self._icon = pystray.Icon("ShutdownTimer",
                                  icon=self._make_icon(False),
                                  title="ShutdownTimer", menu=menu)
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


# ══════════════════════════════════════════════════════════════
# 7. HOTKEY MANAGER
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


# ══════════════════════════════════════════════════════════════
# 8. CONSTANTS
# ══════════════════════════════════════════════════════════════

COLORS = {
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
}

ACTION_ICONS  = {"shutdown": "⏻", "suspend": "🌙", "reboot": "↺", "lock": "🔒"}
ACTION_LABELS = {"shutdown": "Desligar", "suspend": "Suspender",
                 "reboot": "Reiniciar",  "lock": "Bloquear"}


# ══════════════════════════════════════════════════════════════
# 9. MINI WIDGET
# ══════════════════════════════════════════════════════════════

class MiniWidget:
    """Janelinha flutuante always-on-top com o timer em modo compacto."""

    def __init__(self, root, engine: TimerEngine, config: ConfigManager,
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
        menu.add_command(label="Abrir",           command=self._on_open)
        menu.add_command(label="Cancelar timer",  command=self._on_cancel)
        menu.add_separator()
        menu.add_command(label="Fechar widget",   command=self.hide)
        self._win.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

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
            h = s.remaining // 3600; m = (s.remaining % 3600) // 60; sec = s.remaining % 60
            txt   = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
            icon  = ACTION_ICONS.get(s.action, "⏻")
            color = "#f75a5a" if s.remaining <= 60 else (
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
        dx, dy = e.x_root - self._dx, e.y_root - self._dy
        x, y = self._win.winfo_x() + dx, self._win.winfo_y() + dy
        self._win.geometry(f"+{x}+{y}"); self._dx, self._dy = e.x_root, e.y_root
    def _de(self, e):
        if self._win:
            self._config.set("mini_widget_pos",
                             [self._win.winfo_x(), self._win.winfo_y()])


# ══════════════════════════════════════════════════════════════
# 10. MAIN APP
# ══════════════════════════════════════════════════════════════

class ShutdownApp:
    """Interface principal. Toda comunicação com threads via root.after()."""

    def __init__(self, root: ctk.CTk):
        self.root      = root
        self.config    = ConfigManager()
        self.engine    = TimerEngine()
        self.cond_mon  = ConditionMonitor()
        self.notif     = NotificationManager()
        self.tray      = TrayManager(self)
        self.hotkeys   = HotkeyManager()
        self.mini: Optional[MiniWidget] = None

        self._gamer_id:     Optional[str] = None
        self._countdown_id: Optional[str] = None
        self._widget_tick:  Optional[str] = None
        self._cond_active = False

        self._setup_callbacks()
        self._build_window()
        self._build_ui()
        self._apply_config()

        self.tray.start()
        self.hotkeys.setup(self.config, self)
        self.mini = MiniWidget(self.root, self.engine, self.config,
                               on_cancel=self._cancel, on_open=self._show_window)
        self._widget_loop()

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

    # ── Janela ────────────────────────────────────────────

    def _build_window(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        W, H = 480, 770
        self.root.title("ShutdownTimer")
        self.root.geometry(f"{W}x{H}")
        self.root.resizable(False, False)
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
        # Header
        hdr = ctk.CTkFrame(self.root, fg_color=COLORS["surface"],
                           corner_radius=0, height=56)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="⏻  ShutdownTimer",
                     font=ctk.CTkFont("Segoe UI", 18, "bold"),
                     text_color=COLORS["text"]).pack(side="left", padx=20)

        hdr_r = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_r.pack(side="right", padx=12)
        ctk.CTkButton(hdr_r, text="⧉", width=32, height=28,
                      font=ctk.CTkFont(size=14),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=6, text_color=COLORS["text_dim"],
                      command=self._toggle_mini_widget).pack(side="right", padx=2)
        ctk.CTkLabel(hdr, text=f"🖥 {SystemController.PLATFORM}",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(side="right", padx=4)

        # Corpo scrollável
        self._body = ctk.CTkScrollableFrame(
            self.root, fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["surface2"],
            scrollbar_button_hover_color=COLORS["surface3"])
        self._body.pack(fill="both", expand=True)

        self._build_mode_selector()
        self._build_presets()
        self._build_time_input()
        self._build_action_selector()
        self._build_timer_display()
        self._build_options()
        self._build_conditional()
        self._build_controls()
        self._build_bottom_bar()

    # ── Seções ────────────────────────────────────────────

    def _build_mode_selector(self):
        f = self._card("Modo")
        self.mode_var = ctk.StringVar(value=self.config.get("schedule_mode"))
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 14))
        self._mode_btns: dict = {}
        for key, lbl in [("countdown", "⏱  Contagem regressiva"),
                         ("schedule",  "🕐  Horário específico")]:
            btn = ctk.CTkButton(
                row, text=lbl, width=184, height=34,
                font=ctk.CTkFont(size=13), corner_radius=8,
                fg_color=COLORS["surface2"], hover_color=COLORS["accent"],
                text_color=COLORS["text"], command=lambda k=key: self._set_mode(k))
            btn.pack(side="left", padx=(0, 6))
            self._mode_btns[key] = btn

    def _build_presets(self):
        f = self._card("Presets rápidos")
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

    def _build_time_input(self):
        f = self._card("")
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

    def _build_action_selector(self):
        f = self._card("Ação")
        self.action_var = ctk.StringVar(value=self.config.get("last_action"))
        grid = ctk.CTkFrame(f, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(14, 14))
        self._action_buttons: dict = {}
        for idx, (key, label) in enumerate(ACTION_LABELS.items()):
            btn = ctk.CTkButton(
                grid, text=f"{ACTION_ICONS[key]}  {label}",
                width=186, height=36, font=ctk.CTkFont(size=13), corner_radius=8,
                fg_color=COLORS["surface2"], hover_color=COLORS["accent"],
                text_color=COLORS["text"], command=lambda k=key: self._select_action(k))
            r, c = divmod(idx, 2)
            btn.grid(row=r, column=c,
                     padx=(0, 8) if c == 0 else 0,
                     pady=(0, 8) if r == 0 else 0)
            self._action_buttons[key] = btn

    def _build_timer_display(self):
        f = self._card("")
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
        self.status_label.pack(pady=(2, 14))

        
        self.start_btn = ctk.CTkButton(
            f, text="▶  Iniciar", height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color="white", corner_radius=10,
            command=self._start_or_stop)
        self.start_btn.pack(fill="x", padx=16, pady=(2, 2))

        self.pause_btn = ctk.CTkButton(
            f, text="⏸  Pausar", height=36, font=ctk.CTkFont(size=13),
            fg_color=COLORS["surface"], hover_color=COLORS["surface2"],
            text_color=COLORS["text_dim"], corner_radius=8, state="disabled",
            command=self._pause_resume)
        self.pause_btn.pack(expand=True, fill="x", padx=16, pady=(2, 14))

    def _build_options(self):
        f = self._card("Opções")

        # Aviso sonoro
        self.sound_var = ctk.BooleanVar(value=self.config.get("sound_warning"))
        self._switch(f, "🔔  Aviso sonoro (beeps antes da ação)", self.sound_var)

        # Modo gamer
        self.gamer_var = ctk.BooleanVar(value=self.config.get("gamer_mode"))
        gr = ctk.CTkFrame(f, fg_color="transparent")
        gr.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkSwitch(gr, text="🎮  Modo Gamer (pausa se jogo ativo)",
                      variable=self.gamer_var, font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_dim"],
                      button_color=COLORS["accent"],
                      progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False).pack(side="left")
        ctk.CTkButton(gr, text="⚙", width=28, height=22,
                      font=ctk.CTkFont(size=11),
                      fg_color=COLORS["surface2"], hover_color=COLORS["surface3"],
                      corner_radius=5, text_color=COLORS["text_dim"],
                      command=self._gamer_settings).pack(side="right")

        # Extensão adaptativa
        self.adaptive_var = ctk.BooleanVar(value=self.config.get("adaptive_enabled"))
        ar = ctk.CTkFrame(f, fg_color="transparent")
        ar.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkSwitch(ar, text="🖱  Timer adaptativo (atividade → +X min)",
                      variable=self.adaptive_var, font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_dim"],
                      button_color=COLORS["accent"],
                      progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False).pack(side="left")
        self.adaptive_ext = tk.StringVar(value=str(self.config.get("adaptive_extend_min")))
        ctk.CTkEntry(ar, textvariable=self.adaptive_ext, width=42, height=22,
                     font=ctk.CTkFont(size=11),
                     fg_color=COLORS["surface2"], border_color=COLORS["border"],
                     corner_radius=5, text_color=COLORS["text"]).pack(side="right")
        ctk.CTkLabel(ar, text="min", font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(side="right", padx=2)

        # Autostart
        self.autostart_var = ctk.BooleanVar(value=self.config.get("autostart"))
        self._switch(f, "🚀  Iniciar com o sistema", self.autostart_var,
                     cmd=self._toggle_autostart)

        # Atalhos globais
        self.hotkeys_var = ctk.BooleanVar(value=self.config.get("hotkeys_enabled"))
        hkr = ctk.CTkFrame(f, fg_color="transparent")
        hkr.pack(fill="x", padx=16, pady=(0, 14))
        hk_lbl = (f"⌨  Atalhos: {self.config.get('hotkey_start')} / "
                  f"{self.config.get('hotkey_cancel')}")
        ctk.CTkSwitch(hkr, text=hk_lbl, variable=self.hotkeys_var,
                      font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
                      button_color=COLORS["accent"], progress_color=COLORS["accent"],
                      onvalue=True, offvalue=False,
                      command=lambda: (
                          self.config.set("hotkeys_enabled", self.hotkeys_var.get()),
                          self.hotkeys.setup(self.config, self)
                      )).pack(side="left")
        if not HAS_KEYBOARD:
            ctk.CTkLabel(hkr, text="(pip install keyboard)",
                         font=ctk.CTkFont(size=10),
                         text_color=COLORS["text_dim2"]).pack(side="right")

    def _build_conditional(self):
        f = self._card("Shutdown Condicional")
        # self.cond_enabled_var = ctk.BooleanVar(value=self.config.get("cond_enabled"))
        # self._switch(f, "Executar ação quando condição satisfeita",
        #              self.cond_enabled_var)

        if not HAS_PSUTIL:
            ctk.CTkLabel(f, text="⚠  Instale psutil para usar este recurso",
                         font=ctk.CTkFont(size=11),
                         text_color=COLORS["warning"]).pack(anchor="w", padx=16, pady=(0,8))
            self.cond_start_btn = None
            return

        # Ação condicional
        cr = ctk.CTkFrame(f, fg_color="transparent")
        cr.pack(fill="x", padx=16, pady=(8, 8))
        ctk.CTkLabel(cr, text="Ação:", font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 8))
        self.cond_action_var = ctk.StringVar(value=self.config.get("cond_action"))
        label_to_key = {v: k for k, v in ACTION_LABELS.items()}
        ctk.CTkOptionMenu(
            cr, values=list(ACTION_LABELS.values()),
            variable=tk.StringVar(value=ACTION_LABELS.get(self.config.get("cond_action"), "Desligar")),
            width=130, height=28, font=ctk.CTkFont(size=12),
            fg_color=COLORS["surface2"], button_color=COLORS["surface3"],
            command=lambda v: self.cond_action_var.set(label_to_key.get(v, "shutdown"))
        ).pack(side="left")

        # Condições
        saved = {c.get("kind", ""): c for c in self.config.get("conditions")}
        self._cond_vars: dict = {}
        items = [
            ("cpu_low",        "CPU < ", "10", "% (30s contínuos)"),
            ("process_closed", "Processo fechado: ", "", "(ex: blender.exe)"),
            ("download_done",  "Download concluído", "", ""),
            ("idle",           "Inativo por ", "30", "min"),
        ]
        for kind, prefix, default_val, suffix in items:
            sv = saved.get(kind, {})
            row = ctk.CTkFrame(f, fg_color=COLORS["surface2"], corner_radius=8)
            row.pack(fill="x", padx=16, pady=(0, 5))
            chk = ctk.BooleanVar(value=sv.get("enabled", False))
            par = tk.StringVar(value=sv.get("param", default_val))
            ctk.CTkCheckBox(row, text=prefix, variable=chk,
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS["text_dim"],
                            checkbox_width=16, checkbox_height=16,
                            checkmark_color="white",
                            hover_color=COLORS["accent"],
                            border_color=COLORS["border"],
                            fg_color=COLORS["accent"]
                            ).pack(side="left", padx=(10, 4), pady=8)
            if default_val or kind == "process_closed":
                ctk.CTkEntry(row, textvariable=par, width=52, height=24,
                             font=ctk.CTkFont(size=12),
                             fg_color=COLORS["surface3"], border_color=COLORS["border"],
                             corner_radius=5, text_color=COLORS["text"]
                             ).pack(side="left", padx=(0, 4))
            if suffix:
                ctk.CTkLabel(row, text=suffix, font=ctk.CTkFont(size=11),
                             text_color=COLORS["text_dim2"]).pack(side="left")
            self._cond_vars[kind] = (chk, par)

        self.cond_start_btn = ctk.CTkButton(
            f, text="▶  Ativar monitoramento condicional",
            height=36, font=ctk.CTkFont(size=13),
            fg_color=COLORS["accent2"], hover_color="#6a4ce0",
            text_color="white", corner_radius=8,
            command=self._toggle_conditional)
        self.cond_start_btn.pack(fill="x", padx=16, pady=(4, 14))

    def _build_controls(self):
        f = ctk.CTkFrame(self._body, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=(8, 4))

        row2 = ctk.CTkFrame(f, fg_color="transparent"); row2.pack(fill="x")
        
        ctk.CTkButton(
            row2, text="⧉  Widget", height=36, font=ctk.CTkFont(size=13),
            fg_color=COLORS["surface"], hover_color=COLORS["surface2"],
            text_color=COLORS["text_dim"], corner_radius=8,
            command=self._toggle_mini_widget
        ).pack(side="left", expand=True, fill="x")

    def _build_bottom_bar(self):
        bar = ctk.CTkFrame(self._body, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(4, 20))
        for lbl, cmd in [("📋 Histórico", self._show_history),
                         ("📊 Stats",     self._show_stats),
                         ("💾 Exportar",  self._export_history)]:
            ctk.CTkButton(bar, text=lbl, height=30, font=ctk.CTkFont(size=12),
                          fg_color=COLORS["surface"], hover_color=COLORS["surface2"],
                          text_color=COLORS["text_dim"], corner_radius=7, command=cmd
                          ).pack(side="left", padx=(0, 6))

    # ── Helpers de construção ─────────────────────────────

    def _card(self, title: str) -> ctk.CTkFrame:
        outer = ctk.CTkFrame(self._body, fg_color="transparent")
        outer.pack(fill="x", padx=20, pady=(0, 10))
        if title:
            ctk.CTkLabel(outer, text=title, font=ctk.CTkFont(size=11),
                         text_color=COLORS["text_dim2"]).pack(anchor="w", pady=(0, 4))
        inner = ctk.CTkFrame(outer, fg_color=COLORS["surface"], corner_radius=10)
        inner.pack(fill="x")
        return inner

    def _switch(self, parent, text: str, var: ctk.BooleanVar,
                cmd=None, bottom=6):
        sw = ctk.CTkSwitch(parent, text=f" {text}", variable=var,
                           font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
                           button_color=COLORS["accent"],
                           progress_color=COLORS["accent"],
                           onvalue=True, offvalue=False)
        if cmd: sw.configure(command=cmd)
        sw.pack(anchor="w", padx=16, pady=(8, bottom))
        return sw

    # ── Modo countdown/schedule ───────────────────────────

    def _set_mode(self, mode: str):
        self.mode_var.set(mode)
        for k, btn in self._mode_btns.items():
            if k == mode:
                btn.configure(fg_color=COLORS["accent"], text_color="white")
            else:
                btn.configure(fg_color=COLORS["surface2"], text_color=COLORS["text"])
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
            self._sched_info.configure(text=f"→ em {diff} min  ({target.strftime('%H:%M')})")
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

    # ── Helpers gerais ────────────────────────────────────

    def _apply_config(self):
        self._select_action(self.config.get("last_action"))
        self._set_mode(self.config.get("schedule_mode"))

    def _apply_preset(self, m: int):
        self.time_var.set(str(m)); self._set_mode("countdown")
        self._validate_live()

    def _select_action(self, key: str):
        self.action_var.set(key)
        for k, btn in self._action_buttons.items():
            btn.configure(fg_color=COLORS["accent"] if k == key else COLORS["surface2"],
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
        c = COLORS["danger"] if s <= 30 else (
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

        self.config.set("last_minutes",      minutes)
        self.config.set("last_action",       action)
        self.config.set("schedule_mode",     self.mode_var.get())
        self.config.set("gamer_mode",        self.gamer_var.get())
        self.config.set("sound_warning",     self.sound_var.get())
        self.config.set("adaptive_enabled",  self.adaptive_var.get())
        try: self.config.set("adaptive_extend_min", int(self.adaptive_ext.get()))
        except ValueError: pass

        if not self.engine.start(seconds, action): return

        self.start_btn.configure(text="⏹  Cancelar",
                                 fg_color=COLORS["danger"], hover_color="#d94040")
        self.pause_btn.configure(state="normal")
        self.time_entry.configure(state="disabled")
        for btn in self._action_buttons.values():
            btn.configure(state="disabled")

        icon = ACTION_ICONS.get(action, "⏻")
        if self.mode_var.get() == "schedule":
            h = int(self.sched_h.get()); m2 = int(self.sched_m.get())
            self._status(f"{icon}  {ACTION_LABELS[action]} às {h:02d}:{m2:02d}",
                         COLORS["text"])
        else:
            self._status(f"{icon}  {ACTION_LABELS[action]} em {minutes}min",
                         COLORS["text"])
        self._update_display(seconds)

        if self.gamer_var.get():
            self._gamer_id = self.root.after(5000, self._gamer_check)

    def _hotkey_start(self):
        if not self.engine.is_running: self._start()

    def _cancel(self):
        self.engine.cancel()
        self.cond_mon.stop()
        for aid in [self._gamer_id, self._countdown_id]:
            if aid:
                try: self.root.after_cancel(aid)
                except Exception: pass
        self._gamer_id = self._countdown_id = None

    def _pause_resume(self):
        paused = self.engine.pause_resume()
        self.pause_btn.configure(text="▶  Retomar" if paused else "⏸  Pausar")

    def _reset_ui(self):
        self.start_btn.configure(text="▶  Iniciar",
                                 fg_color=COLORS["accent"],
                                 hover_color=COLORS["accent_hover"])
        self.pause_btn.configure(text="⏸  Pausar", state="disabled")
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
        # Timer adaptativo: atividade nos últimos 2min → estende
        if (self.adaptive_var.get() and s <= 120
                and SystemController.get_idle_seconds() < 30):
            try: ext = int(self.adaptive_ext.get()) * 60
            except ValueError: ext = 600
            self.engine.extend(ext)
            self._status(f"🖱  Atividade detectada → +{ext//60}min", COLORS["warning"])

    def _on_warning(self, s: int):
        mins = s // 60
        txt = f"⚠  Atenção: restam {mins}min!" if mins else f"⚠  Restam {s}s!"
        self._status(txt, COLORS["warning"])
        if s in (300, 60):
            self.notif.send("ShutdownTimer ⚠",
                f"{ACTION_LABELS.get(self.engine.state.action, 'Ação')} em "
                f"{mins or s}{'min' if mins else 's'}")

    def _on_finished(self):
        action  = self.engine.state.action
        label   = ACTION_LABELS.get(action, action)
        minutes = self.engine.state.total_seconds // 60

        if self.sound_var.get():
            self.notif.play_beeps()

        self.notif.send(f"⚠  {label} em 15 segundos",
                        "Abra o ShutdownTimer para cancelar.")

        cancelled = self._show_countdown_dialog(action, label)
        if cancelled:
            self.config.add_history(action, minutes, completed=False)
            self._status("✓  Ação cancelada.", COLORS["success"])
        else:
            self.config.add_history(action, minutes, completed=True)
            self._status("Executando ação...", COLORS["warning"])
            self.root.after(300, SystemController.execute, action)
        self._reset_ui()

    def _on_cancelled(self):
        self.config.add_history(self.engine.state.action,
                                self.engine.state.total_seconds // 60, False)
        self._status("✓  Contagem cancelada.", COLORS["success"])
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
                    text="▶  Ativar monitoramento condicional",
                    fg_color=COLORS["accent2"])
            self._status("Monitoramento condicional encerrado.", COLORS["text_dim"])
            return

        conditions = [
            Condition(kind=kind, param=par.get(), enabled=chk.get())
            for kind, (chk, par) in self._cond_vars.items()
        ]
        if not any(c.enabled for c in conditions):
            messagebox.showwarning("Atenção", "Habilite ao menos uma condição.")
            return

        action = self.cond_action_var.get()
        self.cond_mon.start(action, conditions)
        self._cond_active = True
        if self.cond_start_btn:
            self.cond_start_btn.configure(
                text="⏹  Parar monitoramento",
                fg_color=COLORS["danger"])
        self._status("👁  Monitorando condições...", COLORS["accent"])
        self.config.set("cond_action", action)
        self.config.set("conditions",
            [{"kind": c.kind, "param": c.param, "enabled": c.enabled}
             for c in conditions])

    def _on_condition_met(self, action: str, desc: str):
        self._cond_active = False
        if self.cond_start_btn:
            self.cond_start_btn.configure(
                text="▶  Ativar monitoramento condicional",
                fg_color=COLORS["accent2"])
        label = ACTION_LABELS.get(action, action)
        self.notif.send("Condição satisfeita!",
                        f"{desc}\n{label} em 15s.")
        cancelled = self._show_countdown_dialog(
            action, f"{label}  [{desc}]")
        if not cancelled:
            self.config.add_history(action, 0, completed=True)
            SystemController.execute(action)
        else:
            self._status("✓  Ação condicional cancelada.", COLORS["success"])

    # ── Modo gamer ────────────────────────────────────────

    def _gamer_check(self):
        if not self.engine.is_running: return
        idle     = SystemController.get_idle_seconds()
        threshold= self.config.get("gamer_idle_threshold")
        fs       = SystemController.is_fullscreen_active()
        procs    = self.config.get("gamer_processes") or []
        proc_ok  = any(SystemController.is_process_running(p) for p in procs if p)

        should_pause = (idle < threshold) or fs or proc_ok
        if should_pause and not self.engine.state.paused:
            self.engine.pause_resume()
            reasons = ([f"inativo <{threshold}s"] if idle < threshold else []) + \
                      (["fullscreen"] if fs else []) + \
                      (["processo"] if proc_ok else [])
            self._status(f"🎮  Pausado ({', '.join(reasons)})",
                         COLORS["warning"])
        elif not should_pause and self.engine.state.paused:
            self.engine.pause_resume()
            self._status("🎮  Retomado", COLORS["text_dim"])

        self._gamer_id = self.root.after(5000, self._gamer_check)

    def _gamer_settings(self):
        win = ctk.CTkToplevel(self.root)
        win.title("Modo Gamer — configurações")
        win.geometry("360x300")
        win.configure(fg_color=COLORS["bg"]); win.grab_set()

        ctk.CTkLabel(win, text="Processos que pausam o timer",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(pady=(20, 2), padx=20, anchor="w")
        ctk.CTkLabel(win, text="Um por linha  —  ex: valorant.exe, blender.exe",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(padx=20, anchor="w")

        txt = ctk.CTkTextbox(win, height=100, font=ctk.CTkFont(size=12),
                             fg_color=COLORS["surface2"],
                             text_color=COLORS["text"], corner_radius=8)
        txt.pack(fill="x", padx=20, pady=8)
        txt.insert("1.0", "\n".join(self.config.get("gamer_processes") or []))

        ctk.CTkLabel(win, text="Segundos de inatividade para pausar:",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_dim"]).pack(padx=20, anchor="w")
        idle_var = tk.StringVar(value=str(self.config.get("gamer_idle_threshold")))
        ctk.CTkEntry(win, textvariable=idle_var, width=80, height=30,
                     fg_color=COLORS["surface2"], corner_radius=6,
                     text_color=COLORS["text"]).pack(padx=20, anchor="w", pady=4)

        def save():
            lines = [l.strip() for l in
                     txt.get("1.0", "end").splitlines() if l.strip()]
            self.config.set("gamer_processes", lines)
            try: self.config.set("gamer_idle_threshold", int(idle_var.get()))
            except ValueError: pass
            win.destroy()

        ctk.CTkButton(win, text="💾 Salvar", command=save, height=36,
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      corner_radius=8).pack(pady=12)

    # ── Dialog 15s ────────────────────────────────────────

    def _show_countdown_dialog(self, action: str, label: str) -> bool:
        icon = ACTION_ICONS.get(action, "⏻")
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
            f"{self.root.winfo_y() + (self.root.winfo_height() - 280)//2}"
        )

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
                                  progress_color=COLORS["danger"], corner_radius=3)
        prog.pack(fill="x", padx=24, pady=(0, 10)); prog.set(1.0)

        def do_cancel():
            cancelled["v"] = True
            if self._countdown_id:
                try: self.root.after_cancel(self._countdown_id)
                except Exception: pass
                self._countdown_id = None
            dlg.destroy()

        ctk.CTkButton(dlg, text="✕  Cancelar ação", height=40, width=200,
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

    # ── Histórico / Stats / Exportar ─────────────────────

    def _show_history(self):
        history = self.config.get("history")
        if not history:
            messagebox.showinfo("Histórico", "Nenhuma ação registrada ainda.")
            return
        win = ctk.CTkToplevel(self.root)
        win.title("Histórico"); win.geometry("420x460")
        win.configure(fg_color=COLORS["bg"]); win.grab_set()
        ctk.CTkLabel(win, text="Histórico",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORS["text"]).pack(pady=(16, 8))
        scroll = ctk.CTkScrollableFrame(win, fg_color=COLORS["surface"],
                                        corner_radius=10)
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        for e in history:
            ts     = e.get("timestamp", "")[:16].replace("T", " ")
            action = ACTION_LABELS.get(e.get("action", ""), e.get("action", ""))
            done   = "✓" if e.get("completed") else "✗"
            color  = COLORS["success"] if e.get("completed") else COLORS["danger"]
            row = ctk.CTkFrame(scroll, fg_color=COLORS["surface2"], corner_radius=8)
            row.pack(fill="x", pady=3, padx=4)
            ctk.CTkLabel(row,
                text=f"{done}  {action} ({e.get('minutes','?')}min) — {ts}",
                font=ctk.CTkFont(size=12), text_color=color
            ).pack(anchor="w", padx=12, pady=8)

    def _show_stats(self):
        s     = self.config.get("stats") or {}
        total = s.get("total_completed", 0)
        mins  = s.get("total_minutes", 0)
        by_a  = s.get("by_action", {})

        win = ctk.CTkToplevel(self.root)
        win.title("Estatísticas"); win.geometry("360x380")
        win.configure(fg_color=COLORS["bg"]); win.grab_set()
        ctk.CTkLabel(win, text="📊  Estatísticas",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORS["text"]).pack(pady=(20, 12))
        f = ctk.CTkFrame(win, fg_color=COLORS["surface"], corner_radius=10)
        f.pack(fill="x", padx=20)
        rows = [("Total de ações concluídas", str(total)),
                ("Minutos totais agendados",   str(mins))] + [
               (f"{ACTION_ICONS.get(k,'')} {ACTION_LABELS.get(k,k)}", str(v))
               for k, v in by_a.items()]
        for lbl, val in rows:
            r = ctk.CTkFrame(f, fg_color="transparent"); r.pack(fill="x", padx=12, pady=5)
            ctk.CTkLabel(r, text=lbl, font=ctk.CTkFont(size=13),
                         text_color=COLORS["text_dim"]).pack(side="left")
            ctk.CTkLabel(r, text=val, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=COLORS["accent"]).pack(side="right")
        ctk.CTkLabel(win, text=f"⚡  ~{mins/60:.1f}h de energia economizada",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim2"]).pack(pady=(16, 0))

    def _export_history(self):
        fmt  = messagebox.askquestion("Exportar", "Exportar como CSV?\n(Não = JSON)")
        ext  = ".csv" if fmt == "yes" else ".json"
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=[("CSV","*.csv"),("JSON","*.json")],
            initialfile=f"shutdown_history{ext}")
        if not path: return
        try:
            if fmt == "yes": self.config.export_csv(path)
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
        self.root.deiconify(); self.root.lift(); self.root.focus_force()

    def _on_close(self):
        if self.engine.is_running and HAS_TRAY:
            self.root.withdraw(); return   # Minimiza para tray
        if self.engine.is_running:
            if not messagebox.askyesno("Sair",
                    "Timer em andamento. Deseja sair e cancelar?"):
                return
        self._quit_app()

    def _quit_app(self):
        self.engine.cancel(); self.cond_mon.stop(); self.hotkeys.clear()
        if self.mini: self.mini.hide()
        self.tray.stop()
        if self._widget_tick:
            try: self.root.after_cancel(self._widget_tick)
            except Exception: pass
        self.root.destroy()


# ══════════════════════════════════════════════════════════════
# 11. CLI
# ══════════════════════════════════════════════════════════════

def run_cli() -> bool:
    """
    Modo linha de comando. Retorna True se executou CLI, False se deve abrir GUI.

    Exemplos:
        python shutdown_timer.py --shutdown 30
        python shutdown_timer.py --suspend  60
        python shutdown_timer.py --lock     15
        python shutdown_timer.py --cancel
        python shutdown_timer.py --status
        python shutdown_timer.py --gui
    """
    p = argparse.ArgumentParser(prog="shutdown_timer",
                                description="ShutdownTimer — modo CLI")
    p.add_argument("--shutdown", type=int, metavar="MIN")
    p.add_argument("--suspend",  type=int, metavar="MIN")
    p.add_argument("--reboot",   type=int, metavar="MIN")
    p.add_argument("--lock",     type=int, metavar="MIN")
    p.add_argument("--cancel",   action="store_true")
    p.add_argument("--status",   action="store_true")
    p.add_argument("--gui",      action="store_true")
    args = p.parse_args()

    state_file = Path.home() / ".shutdown_timer_state.json"

    if args.cancel:
        if state_file.exists():
            st = json.loads(state_file.read_text())
            pid = st.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    state_file.unlink(missing_ok=True)
                    print("✓ Timer cancelado.")
                except ProcessLookupError:
                    print("Nenhum timer ativo."); state_file.unlink(missing_ok=True)
        else:
            print("Nenhum timer ativo.")
        return True

    if args.status:
        if state_file.exists():
            st = json.loads(state_file.read_text())
            print(f"Timer ativo: {st.get('action')} — "
                  f"{st.get('remaining_min')} min restantes")
        else:
            print("Nenhum timer ativo.")
        return True

    if args.gui: return False

    action, minutes = None, None
    for act in ("shutdown", "suspend", "reboot", "lock"):
        val = getattr(args, act, None)
        if val is not None:
            action, minutes = act, val; break

    if action is None: return False

    print(f"[ShutdownTimer] {ACTION_LABELS[action]} em {minutes} min")
    remaining = minutes * 60

    def _sig(*_):
        state_file.unlink(missing_ok=True)
        print("\n✓ Cancelado."); sys.exit(0)

    signal.signal(signal.SIGTERM, _sig)
    try:
        while remaining > 0:
            h = remaining // 3600; m = (remaining % 3600) // 60; s = remaining % 60
            print(f"\r  ⏻ {h:02d}:{m:02d}:{s:02d}  ", end="", flush=True)
            state_file.write_text(json.dumps(
                {"pid": os.getpid(), "action": action,
                 "remaining_min": remaining // 60}))
            time.sleep(1); remaining -= 1
        print(f"\nExecutando: {action}...")
        state_file.unlink(missing_ok=True)
        SystemController.execute(action)
    except KeyboardInterrupt:
        state_file.unlink(missing_ok=True)
        print("\n✓ Cancelado."); sys.exit(0)
    return True


# ══════════════════════════════════════════════════════════════
# 12. ENTRY POINT
# ══════════════════════════════════════════════════════════════

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def main():
    if len(sys.argv) > 1 and "--gui" not in sys.argv:
        if run_cli(): return

    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("shutdown.timer.app")

    root = ctk.CTk()
    root.iconbitmap(resource_path("icos/shutdown.ico"))
    ShutdownApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
