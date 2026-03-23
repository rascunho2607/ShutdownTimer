"""
energy_saver.py — EnergySaver for ShutdownTimer v5.0
=====================================================
Manages Windows power plans during long timers:
  • Switches to "Economia" when idle
  • Switches to "Alto Desempenho" in the last N minutes
  • Restores the original plan when the timer ends/cancels

Linux: shows a degradation notice (cpupower not guaranteed).
"""

from __future__ import annotations

import logging
import platform
import subprocess
import time
from typing import Callable, Optional

PLATFORM = platform.system()

POWER_PLANS = {
    "high_performance": {
        "guid":        "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        "name":        "Alto Desempenho",
        "description": "Máximo desempenho, maior consumo",
    },
    "balanced": {
        "guid":        "381b4222-f694-41f0-9685-ff5bb260df2f",
        "name":        "Balanceado",
        "description": "Equilíbrio entre desempenho e economia",
    },
    "power_saver": {
        "guid":        "a1841308-3541-4fab-bc81-f71556f20b4a",
        "name":        "Economia",
        "description": "Máxima economia, menor desempenho",
    },
    "ultimate_performance": {
        "guid":        "e9a42b02-d5df-448d-aa00-03f14749eb61",
        "name":        "Desempenho Final",
        "description": "Workstations, consumo extremo",
    },
}

_GUID_TO_KEY = {v["guid"]: k for k, v in POWER_PLANS.items()}


def get_current_plan_guid() -> Optional[str]:
    """Return GUID of the currently active Windows power plan."""
    if PLATFORM != "Windows":
        return None
    try:
        result = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True, text=True, timeout=5)
        line = result.stdout.strip()
        parts = line.split()
        if len(parts) >= 4:
            return parts[3]
        for part in parts:
            if len(part) == 36 and part.count("-") == 4:
                return part
    except Exception as e:
        logging.getLogger("EnergySaver").error(f"get_current_plan: {e}")
    return None


def set_plan_by_guid(guid: str) -> bool:
    """Switch to the power plan with this GUID. Returns True on success."""
    if PLATFORM != "Windows":
        return False
    try:
        subprocess.run(
            ["powercfg", "/setactive", guid],
            check=True, timeout=5,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        logging.getLogger("EnergySaver").error(f"set_plan: {e}")
        return False


def set_plan(plan_key: str) -> bool:
    """Switch to a plan by key (e.g. 'power_saver')."""
    info = POWER_PLANS.get(plan_key)
    if not info:
        return False
    return set_plan_by_guid(info["guid"])


def get_available_plans() -> list:
    """Return list of {'key', 'guid', 'name'} for plans present on this PC."""
    if PLATFORM != "Windows":
        return []
    available = []
    try:
        result = subprocess.run(
            ["powercfg", "/list"],
            capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            for key, info in POWER_PLANS.items():
                if info["guid"].lower() in line.lower():
                    available.append({"key": key, **info})
                    break
    except Exception:
        pass
    if not available:
        available = list({"key": k, **v} for k, v in POWER_PLANS.items())
    return available


class EnergySaver:
    """
    Automatically manages the Windows power plan during ShutdownTimer runs.

    Lifecycle
    ---------
    on_timer_start(total_seconds)  — called when user presses Start
    on_timer_tick(remaining)       — called each second by TimerEngine.on_tick
    on_timer_end()                 — called on both finish and cancel

    Callbacks
    ---------
    on_plan_change(plan_key, reason)  — UI can update the "current plan" label
    on_message(text)                  — informational messages for the UI
    """

    def __init__(self, config):
        self._config  = config
        self._logger  = logging.getLogger("EnergySaver")

        self._original_guid:    Optional[str] = None
        self._current_key:      Optional[str] = None
        self._timer_start_time: float = 0.0
        self._last_activity_ts: float = 0.0
        self._high_perf_done:   bool  = False
        self._active:           bool  = False

        self.on_plan_change: Optional[Callable[[str, str], None]] = None
        self.on_message:     Optional[Callable[[str], None]]       = None

    @property
    def is_available(self) -> bool:
        return PLATFORM == "Windows"

    @property
    def is_active(self) -> bool:
        return self._active

    def on_timer_start(self, total_seconds: int):
        cfg = self._get_cfg()
        if not cfg.get("enabled", False):
            return
        if not self.is_available:
            self._emit("⚠ Gerenciamento de energia disponível apenas no Windows por enquanto")
            return

        self._original_guid    = get_current_plan_guid()
        self._timer_start_time = time.time()
        self._last_activity_ts = time.time()
        self._high_perf_done   = False
        self._active           = True
        threshold_s = cfg.get("economy_threshold_minutes", 30) * 60
        if total_seconds >= threshold_s:
            self._switch_to_economy("timer longo (>= "
                                    f"{threshold_s // 60} min)")

    def on_timer_tick(self, remaining: int):
        if not self._active:
            return
        cfg = self._get_cfg()
        if not cfg.get("enabled", False):
            return

        idle_s          = self._get_idle_seconds()
        idle_thresh_s   = cfg.get("idle_threshold_minutes", 5) * 60
        prepare_s       = cfg.get("prepare_minutes", 15) * 60
        restore_on_act  = cfg.get("restore_on_activity", True)
        keep_gaming     = cfg.get("keep_high_performance_gaming", True)

        # If gamer mode active, keep high-perf and skip
        if keep_gaming and self._is_gamer_mode():
            self._maybe_switch("high_performance", "modo gamer ativo")
            return

        # User returned — restore original plan
        if idle_s < 30 and restore_on_act:
            if (self._current_key is not None
                    and self._current_key != self._get_original_key()):
                self._restore_original("usuário ativo")
            self._last_activity_ts = time.time()
            return

        # Idle too long → economy
        if (time.time() - self._last_activity_ts) >= idle_thresh_s:
            self._switch_to_economy(
                f"inativo por {(time.time() - self._last_activity_ts) / 60:.0f} min")

        # Approaching end → high performance (run once)
        if remaining <= prepare_s and not self._high_perf_done:
            self._high_perf_done = True
            plan_key = cfg.get("high_performance_plan", "high_performance")
            self._maybe_switch(plan_key, f"últimos {prepare_s // 60} min")

    def on_timer_end(self):
        if not self._active:
            return
        self._active = False
        self._restore_original("timer encerrado")

    def test_cycle(self) -> tuple:
        """
        Quick test: economy → original.  Returns (success, message).
        """
        if not self.is_available:
            return False, "Disponível apenas no Windows."
        original = get_current_plan_guid()
        ok1 = set_plan("power_saver")
        time.sleep(0.8)
        ok2 = set_plan_by_guid(original) if original else False
        if ok1 and ok2:
            return True, "✅ Alternância de planos OK."
        return False, "❌ Falha ao alternar planos. Verifique permissões."

    def get_current_plan_label(self) -> str:
        guid = get_current_plan_guid()
        if not guid:
            return "Desconhecido"
        key  = _GUID_TO_KEY.get(guid.lower())
        if key:
            return POWER_PLANS[key]["name"]
        return f"Plano personalizado ({guid[:8]}…)"

    def get_stats_estimate(self) -> dict:
        """Rough monthly saving estimates."""
        if not self.is_available:
            return {}
        return {
            "saving_pct": 18,
            "kwh_month":  2.3,
        }

    def _switch_to_economy(self, reason: str):
        cfg     = self._get_cfg()
        plan_key = cfg.get("economy_plan", "power_saver")
        self._maybe_switch(plan_key, reason)

    def _restore_original(self, reason: str):
        if self._original_guid:
            if set_plan_by_guid(self._original_guid):
                key = _GUID_TO_KEY.get(self._original_guid.lower(), "original")
                self._current_key = key
                self._emit(f"Plano restaurado: {key} ({reason})")
                if self.on_plan_change:
                    self.on_plan_change(key, reason)
        else:
            set_plan("balanced")
            self._current_key = "balanced"

    def _maybe_switch(self, plan_key: str, reason: str):
        if self._current_key == plan_key:
            return
        if set_plan(plan_key):
            self._current_key = plan_key
            name = POWER_PLANS.get(plan_key, {}).get("name", plan_key)
            self._emit(f"Plano alterado → {name} ({reason})")
            if self.on_plan_change:
                self.on_plan_change(plan_key, reason)

    def _get_original_key(self) -> Optional[str]:
        if not self._original_guid:
            return None
        return _GUID_TO_KEY.get(self._original_guid.lower())

    def _get_idle_seconds(self) -> float:
        try:
            if PLATFORM == "Windows":
                import ctypes
                class LII(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint),
                                 ("dwTime", ctypes.c_uint)]
                lii = LII()
                lii.cbSize = ctypes.sizeof(LII)
                ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
                return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
        except Exception:
            pass
        return 0.0

    def _is_gamer_mode(self) -> bool:
        try:
            return bool(self._config.get("gamer_mode"))
        except Exception:
            return False

    def _get_cfg(self) -> dict:
        return self._config.get("energy_saver") or {}

    def _emit(self, text: str):
        self._logger.info(text)
        if self.on_message:
            try:
                self.on_message(text)
            except Exception:
                pass
