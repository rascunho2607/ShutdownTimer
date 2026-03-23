"""
SystemController — ações de SO + prevenção de hibernação.
"""

from config.app_imports import (
    os, sys, signal, platform, subprocess, threading, time,
    Path, Dict, Optional,
    HAS_PSUTIL, psutil,
)


# ══════════════════════════════════════════════════════════════
# 1. SYSTEM CONTROLLER
# ══════════════════════════════════════════════════════════════

class SystemController:
    """Executa ações de energia/sessão. Inclui prevenção de hibernação."""

    PLATFORM = platform.system()

    # -- Prevenção de hibernação (Windows) --
    _ES_CONTINUOUS      = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001
    _sleep_inhibit_cookie: Optional[int] = None   # Linux systemd

    @classmethod
    def prevent_sleep(cls, enable: bool) -> bool:
        """Ativa/desativa prevenção de hibernação enquanto o timer roda."""
        try:
            if cls.PLATFORM == "Windows":
                import ctypes
                if enable:
                    ctypes.windll.kernel32.SetThreadExecutionState(
                        cls._ES_CONTINUOUS | cls._ES_SYSTEM_REQUIRED)
                else:
                    ctypes.windll.kernel32.SetThreadExecutionState(
                        cls._ES_CONTINUOUS)
                return True
            elif cls.PLATFORM == "Linux":
                if enable:
                    result = subprocess.Popen(
                        ["systemd-inhibit", "--what=sleep:idle",
                         "--who=ShutdownTimer", "--why=Timer ativo",
                         "--mode=block", "sleep", "infinity"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    cls._sleep_inhibit_cookie = result.pid
                else:
                    if cls._sleep_inhibit_cookie:
                        try:
                            os.kill(cls._sleep_inhibit_cookie, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        cls._sleep_inhibit_cookie = None
                return True
        except Exception as e:
            print(f"[SysCtrl] prevent_sleep({enable}): {e}")
        return False

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
                subprocess.run(
                    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                    check=True)
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
                subprocess.run(
                    ["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
            elif cls.PLATFORM == "Linux":
                for cmd in [["loginctl", "lock-session"],
                            ["xdg-screensaver", "lock"],
                            ["gnome-screensaver-command", "--lock"],
                            ["xscreensaver-command", "-lock"]]:
                    try:
                        subprocess.run(cmd, check=True, timeout=3)
                        return True
                    except Exception:
                        continue
                return False
            elif cls.PLATFORM == "Darwin":
                subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to keystroke "q" '
                     'using {command down, control down}'], check=True)
            return True
        except Exception as e:
            print(f"[SysCtrl] lock: {e}"); return False

    @classmethod
    def execute(cls, action: str) -> bool:
        cls.prevent_sleep(False)   # restaura sempre antes de executar
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
                    _fields_ = [("cbSize", ctypes.c_uint),
                                 ("dwTime", ctypes.c_uint)]
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
            import ctypes, ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd: return False
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            sw = user32.GetSystemMetrics(0); sh = user32.GetSystemMetrics(1)
            return (rect.left <= 0 and rect.top <= 0
                    and rect.right >= sw and rect.bottom >= sh)
        except Exception:
            return False

    @classmethod
    def set_autostart(cls, enable: bool) -> bool:
        name = "ShutdownTimer"; app_path = sys.executable
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
                winreg.CloseKey(key); return True
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

    @classmethod
    def get_process_list(cls) -> list:
        """Retorna lista de processos com metadados. Requer psutil."""
        if not HAS_PSUTIL: return []
        procs = []
        for p in psutil.process_iter(
                ["pid", "name", "cpu_percent", "memory_info", "status"]):
            try:
                mi = p.info["memory_info"]
                procs.append({
                    "pid":    p.info["pid"],
                    "name":   p.info["name"] or "",
                    "cpu":    round(p.info["cpu_percent"] or 0, 1),
                    "mem_mb": round((mi.rss if mi else 0) / 1024 / 1024, 1),
                    "status": p.info["status"] or "",
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x["name"].lower())
        return procs

    @classmethod
    def get_window_titles(cls) -> Dict[str, str]:
        """Retorna dict {proc_name: window_title} para processos com janela visível."""
        titles: Dict[str, str] = {}
        if cls.PLATFORM == "Windows":
            try:
                import ctypes, ctypes.wintypes
                EnumWindows = ctypes.windll.user32.EnumWindows
                GetWindowText = ctypes.windll.user32.GetWindowTextW
                IsWindowVisible = ctypes.windll.user32.IsWindowVisible
                GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

                WNDENUMPROC = ctypes.WINFUNCTYPE(
                    ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))

                def enum_cb(hwnd, _):
                    if IsWindowVisible(hwnd):
                        buf = ctypes.create_unicode_buffer(512)
                        GetWindowText(hwnd, buf, 512)
                        if buf.value:
                            pid = ctypes.c_ulong()
                            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            try:
                                name = psutil.Process(pid.value).name()
                                titles[name] = buf.value
                            except Exception:
                                pass
                    return True

                EnumWindows(WNDENUMPROC(enum_cb), 0)
            except Exception:
                pass
        return titles
