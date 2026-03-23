"""
Battery Guard — ShutdownTimer Plugin v1.2
Pausa o timer quando a bateria fica abaixo do limiar configurado.

Compatível com a PluginAPI do ShutdownTimer v5.0.
Funciona sem a API para manter retrocompatibilidade.
"""
from __future__ import annotations
import logging

log = logging.getLogger("battery_guard")

# ── Instância global ───────────────────────────────────────────────────────────
_plugin: "BatteryGuardPlugin | None" = None


class BatteryGuardPlugin:
    """Lógica principal do Battery Guard."""

    def __init__(self, api=None):
        self.api = api

    def on_load(self):
        msg = "Battery Guard carregado. Monitorando bateria."
        if self.api:
            self.api.log(msg)
            self.api.register_condition("check_low_battery",
                                         self.check_low_battery)
        else:
            log.info(f"[battery_guard] {msg}")

    def on_unload(self):
        msg = "Battery Guard descarregado."
        if self.api:
            self.api.log(msg)
        else:
            log.info(f"[battery_guard] {msg}")

    def on_config_changed(self, new_config: dict):
        if self.api:
            self.api.log(f"Configuração atualizada: {new_config}")

    def check_low_battery(self, params: dict):
        """Condição: bateria abaixo do limiar."""
        threshold = int(
            params.get("threshold")
            or (self.api.get_config("threshold") if self.api else None)
            or 20
        )
        ignore_plugged = (
            params.get("ignore_when_plugged",
                        (self.api.get_config("ignore_when_plugged")
                         if self.api else True))
        )
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery is None:
                return False, "Sem bateria detectada"
            percent = battery.percent
            plugged = battery.power_plugged
            if plugged and ignore_plugged:
                return False, f"Carregando ({percent:.0f}%) — sem ação"
            if percent <= threshold:
                return True, f"Bateria em {percent:.0f}% (≤ {threshold}%)"
            return False, f"Bateria em {percent:.0f}% (limiar: {threshold}%)"
        except ImportError:
            return False, "psutil não instalado"
        except Exception as e:
            return False, f"Erro: {e}"

    def _get_config(self, key: str, default=None):
        if self.api:
            v = self.api.get_config(key)
            return v if v is not None else default
        return default


def on_load(api=None):
    global _plugin
    _plugin = BatteryGuardPlugin(api)
    _plugin.on_load()
    return _plugin


def on_unload():
    if _plugin:
        _plugin.on_unload()


def on_config_changed(new_config: dict):
    if _plugin:
        _plugin.on_config_changed(new_config)


def check_low_battery(params: dict) -> tuple:
    """Retrocompatibilidade — chamada direta sem instância."""
    if _plugin:
        return _plugin.check_low_battery(params)
    threshold = int(params.get("threshold", 20))
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            return False, "Sem bateria detectada"
        percent = battery.percent
        if battery.power_plugged:
            return False, f"Carregando ({percent:.0f}%)"
        if percent <= threshold:
            return True, f"Bateria em {percent:.0f}% (≤ {threshold}%)"
        return False, f"Bateria em {percent:.0f}% (limiar: {threshold}%)"
    except ImportError:
        return False, "psutil não instalado"
    except Exception as e:
        return False, f"Erro: {e}"


def get_battery_info() -> dict:
    """Utilitário: informações completas da bateria."""
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            return {"available": False}
        return {
            "available": True,
            "percent":   battery.percent,
            "plugged":   battery.power_plugged,
            "secs_left": battery.secsleft,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}
