"""
SmartModeEngine — gerenciamento inteligente de energia com aprendizado de hábitos.
"""

from config.app_imports import (
    json, time, threading,
    Path, datetime,
    Callable, Dict, List, Optional,
    HAS_PSUTIL, psutil,
)
from core.system_controller import SystemController


# ══════════════════════════════════════════════════════════════
# 5A. SMART MODE ENGINE
# ══════════════════════════════════════════════════════════════

class SmartModeEngine:
    """
    Gerenciamento inteligente de energia que aprende os hábitos de uso.

    Módulos:
      - Monitor de atividade (CPU, disco, rede, idle, uptime)
      - Proteção de download  (bloqueia ações se rede ativa)
      - Proteção de CPU       (adia ações se CPU ≥ threshold)
      - Sugestão de reboot    (uptime > N dias)
      - Hibernação em horários de baixa atividade
      - Desligamento em longos períodos de inatividade
      - Aprendizado de hábitos (JSON local)
    """

    POLL          = 60        # segundos entre verificações
    HABITS_FILE   = Path.home() / ".shutdown_timer_habits.json"

    # Limites padrão (configuráveis via config)
    CPU_THRESHOLD       = 15.0   # %
    NET_THRESHOLD_KB    = 100.0  # KB/s  — tráfego "ativo"
    IDLE_SHUTDOWN_MIN   = 120    # min de inatividade → desligar
    IDLE_SUSPEND_MIN    = 30     # min de inatividade → suspender
    UPTIME_REBOOT_DAYS  = 5      # dias ligado → sugerir reboot
    NET_WINDOW_SECS     = 60     # janela para medir taxa de rede

    def __init__(self):
        self._stop     = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock     = threading.Lock()

        # Callbacks para a UI
        self.on_action:     Optional[Callable[[str, str], None]] = None  # (action, reason)
        self.on_suggestion: Optional[Callable[[str, str], None]] = None  # (kind, msg)
        self.on_status:     Optional[Callable[[dict], None]]     = None  # snapshot dict

        # Estado interno
        self._net_prev_bytes: int   = 0
        self._net_prev_ts:    float = 0.0
        self._net_rate_kb:    float = 0.0
        self._blocking:       bool  = False   # bloqueia ações enquanto True
        self._last_reboot_suggestion: Optional[str] = None

        # Hábitos carregados
        self.habits: dict = self._load_habits()

    # ── Ciclo principal ───────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._net_prev_bytes = SystemController.get_net_bytes_recv()
        self._net_prev_ts    = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive()
                    and not self._stop.is_set())

    def _run(self):
        while not self._stop.wait(self.POLL):
            try:
                self._tick()
            except Exception as e:
                print(f"[SmartMode] tick error: {e}")

    def _tick(self):
        now      = datetime.now()
        hour     = now.hour
        minute   = now.minute

        # ── Coleta métricas ───────────────────────────────
        cpu      = SystemController.get_cpu_percent()
        idle_s   = SystemController.get_idle_seconds()
        net_rate = self._measure_net_rate()
        uptime_d = self._get_uptime_days()

        # Registra hábitos desta hora
        self._record_habit(hour, cpu, idle_s)

        snapshot = {
            "cpu":      cpu,
            "idle_min": round(idle_s / 60, 1),
            "net_kb_s": round(net_rate, 1),
            "uptime_d": round(uptime_d, 1),
            "blocking": self._blocking,
            "hour":     hour,
        }
        if self.on_status:
            self.on_status(snapshot)

        # ── Proteção de download ──────────────────────────
        if net_rate > self.NET_THRESHOLD_KB:
            self._blocking = True
            return   # Não age enquanto há tráfego significativo
        else:
            self._blocking = False

        # ── Proteção de CPU ───────────────────────────────
        if cpu >= self.CPU_THRESHOLD:
            return   # Adia decisão

        # ── Sugestão de reboot por uptime ─────────────────
        if uptime_d >= self.UPTIME_REBOOT_DAYS:
            today = now.strftime("%Y-%m-%d")
            if self._last_reboot_suggestion != today:
                self._last_reboot_suggestion = today
                msg = (f"O sistema está ligado há {uptime_d:.0f} dias. "
                       "Considere reiniciar para manter a estabilidade.")
                if self.on_suggestion:
                    self.on_suggestion("reboot", msg)

        # ── Hibernação em horário de baixa atividade ──────
        if self._is_low_activity_hour(hour) and idle_s > 600:
            # Só age na janela de inatividade e após 10min sem uso
            if self.on_action:
                self.on_action("suspend",
                               f"Horário de baixa atividade ({hour:02d}h) "
                               f"e inativo há {idle_s/60:.0f}min")
            return

        # ── Desligamento em longos períodos de inatividade ─
        if idle_s >= self.IDLE_SHUTDOWN_MIN * 60:
            # Previsão: usuário provavelmente não voltará em breve
            if self._predict_no_return(hour):
                if self.on_action:
                    self.on_action("shutdown",
                                   f"Inativo há {idle_s/60:.0f}min e sem "
                                   "previsão de retorno")
                return

        # ── Suspensão em inatividade média ────────────────
        if idle_s >= self.IDLE_SUSPEND_MIN * 60:
            if self.on_action:
                self.on_action("suspend",
                               f"Inativo há {idle_s/60:.0f}min")

    # ── Medição de rede ───────────────────────────────────

    def _measure_net_rate(self) -> float:
        """Retorna taxa de rede em KB/s desde a última medição."""
        now_bytes = SystemController.get_net_bytes_recv()
        now_ts    = time.time()
        dt        = now_ts - self._net_prev_ts
        if dt <= 0:
            return self._net_rate_kb
        rate_kb = (now_bytes - self._net_prev_bytes) / dt / 1024
        self._net_prev_bytes = now_bytes
        self._net_prev_ts    = now_ts
        self._net_rate_kb    = max(0.0, rate_kb)
        return self._net_rate_kb

    # ── Uptime ────────────────────────────────────────────

    @staticmethod
    def _get_uptime_days() -> float:
        try:
            if HAS_PSUTIL:
                return (time.time() - psutil.boot_time()) / 86400
            if SystemController.PLATFORM == "Windows":
                import ctypes
                ms = ctypes.windll.kernel32.GetTickCount64()
                return ms / 1000 / 86400
        except Exception:
            pass
        return 0.0

    # ── Aprendizado de hábitos ────────────────────────────

    def _record_habit(self, hour: int, cpu: float, idle_s: float):
        """Registra atividade desta hora no arquivo de hábitos."""
        key = str(hour)
        with self._lock:
            h = self.habits.setdefault(key, {
                "samples":    0,
                "avg_cpu":    0.0,
                "avg_idle_m": 0.0,
                "active_pct": 0.0,
            })
            n = h["samples"]
            h["avg_cpu"]    = (h["avg_cpu"]    * n + cpu)        / (n + 1)
            h["avg_idle_m"] = (h["avg_idle_m"] * n + idle_s/60) / (n + 1)
            active = 1.0 if idle_s < 120 else 0.0
            h["active_pct"] = (h["active_pct"] * n + active)     / (n + 1)
            h["samples"]    = n + 1
        self._save_habits()

    def _is_low_activity_hour(self, hour: int) -> bool:
        """True se esta hora historicamente tem pouca atividade (< 20%)."""
        h = self.habits.get(str(hour))
        if not h or h["samples"] < 5:
            # Sem dados suficientes: considera baixa atividade entre 02-06h
            return 2 <= hour <= 6
        return h["active_pct"] < 0.20

    def _predict_no_return(self, hour: int) -> bool:
        """True se historicamente o usuário raramente usa o PC nesta hora."""
        h = self.habits.get(str(hour))
        if not h or h["samples"] < 5:
            return 1 <= hour <= 7   # madrugada como default
        return h["active_pct"] < 0.10

    def get_habits_summary(self) -> List[dict]:
        """Retorna lista de horas com estatísticas para exibição na UI."""
        rows = []
        for hour in range(24):
            h = self.habits.get(str(hour), {})
            rows.append({
                "hour":       hour,
                "samples":    h.get("samples",    0),
                "avg_cpu":    round(h.get("avg_cpu",    0.0), 1),
                "avg_idle_m": round(h.get("avg_idle_m", 0.0), 1),
                "active_pct": round(h.get("active_pct", 0.0) * 100, 0),
            })
        return rows

    def _load_habits(self) -> dict:
        try:
            if self.HABITS_FILE.exists():
                return json.loads(self.HABITS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_habits(self):
        try:
            with self._lock:
                data = dict(self.habits)
            self.HABITS_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception as e:
            print(f"[SmartMode] save habits: {e}")

    @property
    def is_blocking(self) -> bool:
        return self._blocking

    def get_snapshot(self) -> dict:
        """Leitura instantânea das métricas (sem esperar POLL)."""
        return {
            "cpu":      SystemController.get_cpu_percent(),
            "idle_min": round(SystemController.get_idle_seconds() / 60, 1),
            "net_kb_s": round(self._net_rate_kb, 1),
            "uptime_d": round(self._get_uptime_days(), 1),
            "blocking": self._blocking,
        }
