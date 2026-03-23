"""
TimerEngine, ConditionMonitor, SchedulerMonitor — motores de contagem, condição e agendamento.
"""

from config.app_imports import (
    threading, time,
    datetime,
    Callable, List, Optional,
    dataclass, field,
)
from core.system_controller import SystemController


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
    """Motor de contagem regressiva desacoplado da UI."""

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

    POLL = 5

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
            now  = SystemController.get_net_bytes_recv()
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
# 4. SCHEDULER MONITOR  (agendamento recorrente)
# ══════════════════════════════════════════════════════════════

@dataclass
class ScheduledAction:
    id:       str
    enabled:  bool
    action:   str
    days:     List[int]          # 0=Segunda … 6=Domingo
    hour:     int
    minute:   int
    last_run: Optional[str]      # ISO timestamp
    name:     str


class SchedulerMonitor:
    """Verifica a cada minuto se alguma ação programada deve ser executada."""

    POLL = 30   # segundos entre verificações

    def __init__(self):
        self._stop   = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.on_fire: Optional[Callable[[ScheduledAction], None]] = None

    def start(self, get_actions: Callable[[], List[ScheduledAction]]):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._get_actions = get_actions
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self): self._stop.set()

    def _run(self):
        while not self._stop.wait(self.POLL):
            now = datetime.now()
            for sa in self._get_actions():
                if not sa.enabled: continue
                if now.weekday() not in sa.days: continue
                if now.hour != sa.hour or now.minute != sa.minute: continue
                # Evita disparar mais de uma vez no mesmo minuto
                ts = now.strftime("%Y-%m-%dT%H:%M")
                if sa.last_run and sa.last_run.startswith(ts): continue
                sa.last_run = now.isoformat(timespec="seconds")
                if self.on_fire:
                    self.on_fire(sa)
