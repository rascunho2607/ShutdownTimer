"""
Temperature Watch — ShutdownTimer Plugin v1.0
Monitora a temperatura da CPU e age conforme configurado pelo usuário.

Compatível com a PluginAPI do ShutdownTimer v5.0.
Funciona sem a API para manter retrocompatibilidade.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading

log = logging.getLogger("temperature_watch")

# ── Instância global do plugin ─────────────────────────────────────────────────
_plugin: "TemperaturePlugin | None" = None


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class TemperaturePlugin:
    """Lógica principal do plugin Temperature Watch."""

    def __init__(self, api=None):
        self.api   = api        # PluginAPI (pode ser None em modo legado)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused_by_us = False

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def on_load(self):
        msg = "Temperature Watch carregado"
        if self.api:
            self.api.log(msg)
            # Registra condição para uso na aba Condicional
            self.api.register_condition("is_overheating", self.is_overheating)
        else:
            log.info(f"[temperature_watch] {msg}")

        self._start_monitoring()

    def on_unload(self):
        self._stop.set()
        msg = "Temperature Watch descarregado"
        if self.api:
            self.api.log(msg)
        else:
            log.info(f"[temperature_watch] {msg}")

    def on_config_changed(self, new_config: dict):
        """Chamado automaticamente quando o usuário salva configurações."""
        msg = f"Configuração atualizada: {new_config}"
        if self.api:
            self.api.log(msg)
        else:
            log.info(f"[temperature_watch] {msg}")

    # ── Monitoramento ─────────────────────────────────────────────────────────

    def _start_monitoring(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True)
        self._thread.start()

    def _monitor_loop(self):
        while not self._stop.is_set():
            self._tick()
            interval = self._get_config("poll_interval", 10)
            self._stop.wait(interval)

    def _tick(self):
        temp      = self._get_temperature()
        threshold = self._get_config("threshold", 85)

        if temp < 0:
            return  # Sensor indisponível

        if temp >= threshold:
            self._on_overheat(temp, threshold)
        elif self._paused_by_us:
            # Temperatura voltou ao normal — retoma se configurado
            auto_resume = self._get_config("auto_resume", True)
            if auto_resume and self.api:
                self.api.log(
                    f"Temperatura normalizada ({temp:.1f}°C < {threshold}°C)"
                    " — retomando timer")
                self.api.execute_action("resume_timer")
                self._paused_by_us = False

    def _on_overheat(self, temp: float, threshold):
        action = self._get_config("action", "pause_timer")
        msg    = f"CPU: {temp:.1f}°C ≥ {threshold}°C"

        if self.api:
            self.api.log(f"⚠ Superaquecimento! {msg}")
            self.api.show_notification("🌡️ Temperature Watch", msg)
            if action == "pause_timer":
                timer = self.api.get_timer_state()
                if timer.get("running") and not timer.get("paused"):
                    self.api.execute_action("pause_timer")
                    self._paused_by_us = True
            elif action == "cancel_timer":
                self.api.execute_action("cancel_timer")
            # "notify" → apenas a notificação acima
        else:
            log.warning(f"[temperature_watch] Superaquecimento: {msg}")

    # ── Condição (registrável via api.register_condition) ─────────────────────

    def is_overheating(self, params: dict):
        """
        Condição: CPU acima do limiar.
        Retorna (True, motivo) quando superaquecendo.
        """
        threshold = float(
            params.get("threshold")
            or self._get_config("threshold", 85)
        )
        temp = self._get_temperature()
        if temp < 0:
            return False, "Sensor de temperatura indisponível"
        if temp >= threshold:
            return True, f"CPU a {temp:.1f}°C ≥ {threshold:.0f}°C"
        return False, f"CPU a {temp:.1f}°C (limiar: {threshold:.0f}°C)"

    # ── Temperatura ───────────────────────────────────────────────────────────

    def _get_temperature(self) -> float:
        # 1ª prioridade: PluginAPI (quando carregado pelo ShutdownTimer)
        if self.api:
            t = self.api.get_cpu_temperature()
            if t >= 0:
                return t
        # 2ª–4ª: cascata local (C# → psutil → -1.0)
        return _get_cpu_temp_direct()

    # ── Config ────────────────────────────────────────────────────────────────

    def _get_config(self, key: str, default=None):
        if self.api:
            v = self.api.get_config(key)
            return v if v is not None else default
        return default

    def _get_all_config(self) -> dict:
        """Retorna o dict completo de config (apenas no modo sem API)."""
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# TEMPERATURA DIRETA (sem API — modo legado)
# ══════════════════════════════════════════════════════════════════════════════

def _get_temp_via_csharp() -> float:
    """
    Lê temperatura da CPU via temp_reader.exe incluído na pasta do plugin.
    O executável usa WMI nativo do Windows sem dependências externas.
    Retorna -1.0 se o executável não existir ou falhar.
    """
    if sys.platform != "win32":
        return -1.0
    try:
        base_dir = os.path.dirname(__file__)
        exe_path = os.path.join(base_dir, "temp_reader.exe")
        if not os.path.isfile(exe_path):
            return -1.0
        result = subprocess.check_output(
            [exe_path],
            text=True,
            timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        ).strip()
        temp = float(result)
        if 0 < temp < 150:
            return temp
    except Exception:
        pass
    return -1.0


def _get_temp_via_lhm_ohm() -> float:
    """
    Lê temperatura da CPU via Libre Hardware Monitor ou Open Hardware Monitor.
    Requer que um deles esteja instalado e rodando em segundo plano.
    Retorna -1.0 se nenhum estiver disponível.
    """
    if sys.platform != "win32":
        return -1.0

    namespaces = [r"root\LibreHardwareMonitor", r"root\OpenHardwareMonitor"]
    for ns in namespaces:
        try:
            import wmi  # type: ignore[import]
            w = wmi.WMI(namespace=ns)
            temps = [
                s.Value for s in w.Sensor()
                if s.SensorType == "Temperature"
                and "CPU" in s.Name
                and s.Value is not None
            ]
            if temps:
                return float(max(temps))
        except Exception:
            continue
    return -1.0


def _get_temp_via_psutil() -> float:
    """
    Lê temperatura via psutil.
    Funciona em Linux/macOS e em alguns sistemas Windows.
    Retorna -1.0 se indisponível.
    """
    try:
        import psutil
        temps = psutil.sensors_temperatures()
        if not temps:
            return -1.0
        for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz",
                    "zenpower", "it8", "nct6775"):
            if key in temps and temps[key]:
                return float(max(e.current for e in temps[key]))
        # Qualquer sensor disponível
        for entries in temps.values():
            if entries:
                return float(max(e.current for e in entries))
    except Exception:
        pass
    return -1.0


def _get_cpu_temp_direct() -> float:
    """
    Obtém temperatura da CPU sem a PluginAPI.
    Cascata: C# (temp_reader.exe) → LHM/OHM (WMI) → psutil → -1.0.
    """
    # 1ª prioridade: executável C# incluído no plugin (Windows)
    t = _get_temp_via_csharp()
    if t >= 0:
        return t

    # 2ª prioridade: Libre/Open Hardware Monitor (Windows)
    t = _get_temp_via_lhm_ohm()
    if t >= 0:
        return t

    # 3ª prioridade: psutil (Linux/macOS/Windows parcial)
    t = _get_temp_via_psutil()
    if t >= 0:
        return t

    return -1.0


def is_lhm_ohm_available() -> bool:
    """Verifica se o Libre ou Open Hardware Monitor está acessível via WMI."""
    return _get_temp_via_lhm_ohm() >= 0


def get_temperature_info() -> dict:
    """
    Utilitário público: retorna sensores disponíveis via psutil.
    Útil para o usuário descobrir qual valor colocar em 'psutil_sensor_key'.
    """
    result: dict = {"available": False, "sensors": {}, "available_keys": []}
    try:
        import psutil
        temps = psutil.sensors_temperatures()
        if temps:
            result["available"] = True
            result["available_keys"] = list(temps.keys())
            result["sensors"] = {
                k: [{"label": e.label, "current": e.current,
                     "high": e.high, "critical": e.critical}
                    for e in v]
                for k, v in temps.items()
            }
    except Exception as e:
        result["error"] = str(e)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PONTOS DE ENTRADA — ShutdownTimer v5.0
# ══════════════════════════════════════════════════════════════════════════════

def on_load(api=None):
    """
    Chamado pelo PluginManager quando o plugin é carregado.
    Aceita PluginAPI (v5.0) ou sem argumento (modo legado).
    """
    global _plugin
    _plugin = TemperaturePlugin(api)
    _plugin.on_load()
    return _plugin


def on_unload():
    """Chamado pelo PluginManager quando o plugin é descarregado."""
    if _plugin:
        _plugin.on_unload()


def on_config_changed(new_config: dict):
    """Chamado automaticamente quando o usuário salva configurações (hot reload)."""
    if _plugin:
        _plugin.on_config_changed(new_config)


def is_overheating(params: dict) -> tuple:
    """Função de condição (retrocompatibilidade com modo direto)."""
    if _plugin:
        return _plugin.is_overheating(params)
    threshold = float(params.get("threshold_c", params.get("threshold", 85)))
    temp = _get_cpu_temp_direct()
    if temp < 0:
        return False, "Sensor indisponível"
    if temp >= threshold:
        return True, f"CPU a {temp:.1f}°C ≥ {threshold:.0f}°C"
    return False, f"CPU a {temp:.1f}°C (limiar: {threshold:.0f}°C)"


# Alias retrocompatível
check_high_temperature = is_overheating
