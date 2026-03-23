"""
Work Hours Only — ShutdownTimer Plugin
Bloqueia ações automáticas fora do horário de trabalho.
"""
from __future__ import annotations
import logging
from datetime import datetime, time

log = logging.getLogger("work_hours")


def on_load():
    log.info("[work_hours] Carregado.")


def on_unload():
    log.info("[work_hours] Descarregado.")


def _parse_params(params: dict) -> tuple:
    """Extrai e valida os parâmetros de horário."""
    start_h = int(params.get("start_hour",   9))
    start_m = int(params.get("start_minute", 0))
    end_h   = int(params.get("end_hour",    18))
    end_m   = int(params.get("end_minute",   0))
    block_we = bool(params.get("block_weekends", True))
    return (time(start_h, start_m), time(end_h, end_m), block_we)


def check_outside_work_hours(params: dict) -> tuple:
    """
    Condição: estamos FORA do horário de trabalho.
    Use esta condição para BLOQUEAR ações automáticas fora do expediente.
    """
    start_time, end_time, block_weekends = _parse_params(params)
    now = datetime.now()
    current_time = now.time().replace(second=0, microsecond=0)
    weekday = now.weekday()  # 0=segunda, 6=domingo

    # Fim de semana
    if block_weekends and weekday >= 5:
        day_name = "Sábado" if weekday == 5 else "Domingo"
        return True, f"{day_name} — fora do expediente"

    # Antes do início
    if current_time < start_time:
        return (True,
                f"{now.strftime('%H:%M')} é antes do expediente "
                f"({start_time.strftime('%H:%M')})")

    # Depois do fim
    if current_time >= end_time:
        return (True,
                f"{now.strftime('%H:%M')} é após o expediente "
                f"({end_time.strftime('%H:%M')})")

    return (False,
            f"Dentro do expediente "
            f"({start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')})")


def check_inside_work_hours(params: dict) -> tuple:
    """
    Condição: estamos DENTRO do horário de trabalho.
    Use esta condição para permitir ações SOMENTE durante o expediente.
    """
    met, reason = check_outside_work_hours(params)
    if met:
        return False, f"Fora do expediente: {reason}"
    return True, reason


def get_schedule_info(params: dict = None) -> dict:
    """Utilitário: retorna o status atual e próximo evento de horário."""
    if params is None:
        params = {}
    start_time, end_time, block_weekends = _parse_params(params)
    now = datetime.now()
    is_out, reason = check_outside_work_hours(params)
    return {
        "now":          now.strftime("%H:%M %A"),
        "work_start":   start_time.strftime("%H:%M"),
        "work_end":     end_time.strftime("%H:%M"),
        "block_weekends": block_weekends,
        "outside_work": is_out,
        "reason":       reason,
    }
