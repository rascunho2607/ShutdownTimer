"""
Calendar Sync Plus — ShutdownTimer Plugin
Integração com Outlook e Calendário do Windows.

Dependências opcionais:
  pip install pywin32          # Outlook (win32com)
  pip install winsdk           # Windows Calendar (winrt) — Python 3.10+
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("calendar_sync_plus")

# ─── Helpers ────────────────────────────────────────────────────────────────

def _parse_sources(sources_str: str) -> list[str]:
    return [s.strip().lower() for s in sources_str.split(",") if s.strip()]


def _should_ignore(title: str, keywords_str: str) -> bool:
    if not keywords_str.strip():
        return False
    lower = title.lower()
    for kw in keywords_str.split(","):
        if kw.strip().lower() in lower:
            return True
    return False


# ─── Outlook via win32com ───────────────────────────────────────────────────

def _get_outlook_events(start: datetime, end: datetime) -> list[dict]:
    """Retorna eventos do Outlook entre start e end."""
    try:
        import win32com.client  # pywin32
        outlook   = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        calendar  = namespace.GetDefaultFolder(9)  # olFolderCalendar
        items     = calendar.Items
        items.IncludeRecurrences = True
        items.Sort("[Start]")

        fmt = "%m/%d/%Y %H:%M %p"
        restrict = (f"[Start] >= '{start.strftime(fmt)}' "
                    f"AND [End] <= '{end.strftime(fmt)}'")
        results = []
        for appt in items.Restrict(restrict):
            try:
                results.append({
                    "title":  appt.Subject,
                    "start":  datetime.strptime(str(appt.Start)[:16], "%Y-%m-%d %H:%M"),
                    "end":    datetime.strptime(str(appt.End)[:16],   "%Y-%m-%d %H:%M"),
                    "source": "outlook",
                })
            except Exception:
                pass
        return results
    except ImportError:
        log.debug("[calendar_sync_plus] pywin32 não instalado — Outlook ignorado")
        return []
    except Exception as e:
        log.warning(f"[calendar_sync_plus] Erro Outlook: {e}")
        return []


# ─── Windows Calendar via ICS parsing ──────────────────────────────────────

def _get_ics_events(start: datetime, end: datetime) -> list[dict]:
    """
    Tenta ler arquivos .ics da pasta padrão do Calendário do Windows.
    Fallback simples sem dependências externas.
    """
    events = []
    ics_roots = [
        Path.home() / "AppData" / "Local" / "Packages",
    ]
    ics_files: list[Path] = []
    for root in ics_roots:
        if root.exists():
            for pkg in root.glob("microsoft.windowscommunicationsapps*"):
                ics_files.extend(pkg.rglob("*.ics"))

    for ics_path in ics_files[:50]:  # limite de segurança
        try:
            _parse_ics_file(ics_path, start, end, events)
        except Exception:
            pass
    return events


def _parse_ics_file(path: Path, start: datetime, end: datetime,
                    results: list) -> None:
    """Parser mínimo de iCalendar sem dependências."""
    content = path.read_text(encoding="utf-8", errors="ignore")
    in_event = False
    event: dict = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            event = {}
        elif line == "END:VEVENT" and in_event:
            in_event = False
            if "dtstart" in event and "dtend" in event:
                ev_start = _parse_ics_dt(event["dtstart"])
                ev_end   = _parse_ics_dt(event["dtend"])
                if ev_start and ev_end and ev_start < end and ev_end > start:
                    results.append({
                        "title":  event.get("summary", "(sem título)"),
                        "start":  ev_start,
                        "end":    ev_end,
                        "source": "windows",
                    })
        elif in_event:
            if line.startswith("SUMMARY:"):
                event["summary"] = line[8:]
            elif line.startswith("DTSTART"):
                event["dtstart"] = line.split(":", 1)[-1]
            elif line.startswith("DTEND"):
                event["dtend"] = line.split(":", 1)[-1]


def _parse_ics_dt(value: str) -> datetime | None:
    """Converte string iCalendar para datetime (sem tz ou UTC)."""
    value = value.strip().rstrip("Z")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


# ─── Lógica unificada ───────────────────────────────────────────────────────

def _collect_events(sources: list[str], start: datetime, end: datetime,
                    ignore_keywords: str) -> list[dict]:
    events = []
    if "outlook" in sources:
        events.extend(_get_outlook_events(start, end))
    if "windows" in sources:
        events.extend(_get_ics_events(start, end))
    if ignore_keywords.strip():
        events = [e for e in events if not _should_ignore(e["title"], ignore_keywords)]
    return events


# ─── Hooks ─────────────────────────────────────────────────────────────────

def on_load():
    log.info("[calendar_sync_plus] Carregado. Verificando fontes disponíveis…")
    # Testa disponibilidade
    try:
        import win32com.client  # noqa: F401
        log.info("[calendar_sync_plus] ✔ Outlook (pywin32) disponível")
    except ImportError:
        log.info("[calendar_sync_plus] ✗ Outlook indisponível — instale pywin32")

    ics_root = Path.home() / "AppData" / "Local" / "Packages"
    ics_pkgs = list(ics_root.glob("microsoft.windowscommunicationsapps*"))
    if ics_pkgs:
        log.info("[calendar_sync_plus] ✔ Windows Calendar (ICS) disponível")
    else:
        log.info("[calendar_sync_plus] ✗ Windows Calendar não encontrado")


def on_unload():
    log.info("[calendar_sync_plus] Descarregado.")


# ─── Conditions ────────────────────────────────────────────────────────────

def has_active_event(params: dict) -> tuple[bool, str]:
    """
    Condition: retorna True se há um evento ativo agora (±buffers).
    """
    sources         = _parse_sources(params.get("sources", "outlook,windows"))
    buf_before      = int(params.get("buffer_before_min", 5))
    buf_after       = int(params.get("buffer_after_min",  0))
    ignore_keywords = params.get("ignore_keywords", "")

    now   = datetime.now()
    start = now - timedelta(minutes=buf_after)
    end   = now + timedelta(minutes=buf_before)

    events = _collect_events(sources, start, end, ignore_keywords)

    for ev in events:
        ev_start = ev["start"] - timedelta(minutes=buf_before)
        ev_end   = ev["end"]   + timedelta(minutes=buf_after)
        if ev_start <= now <= ev_end:
            label  = ev["title"]
            source = ev["source"]
            msg    = f"Evento ativo [{source}]: \"{label}\" até {ev['end'].strftime('%H:%M')}"
            return True, msg

    return False, "Nenhum evento ativo"


def has_event_in_next_minutes(params: dict) -> tuple[bool, str]:
    """
    Condition: retorna True se há um evento nos próximos N minutos.
    """
    sources         = _parse_sources(params.get("sources", "outlook,windows"))
    lookahead       = int(params.get("lookahead_min",  30))
    ignore_keywords = params.get("ignore_keywords", "")

    now = datetime.now()
    end = now + timedelta(minutes=lookahead)

    events = _collect_events(sources, now, end, ignore_keywords)
    # Filtra apenas eventos que ainda não começaram
    upcoming = [e for e in events if e["start"] >= now]

    if upcoming:
        upcoming.sort(key=lambda e: e["start"])
        next_ev = upcoming[0]
        diff    = int((next_ev["start"] - now).total_seconds() / 60)
        msg     = (f"Evento em {diff} min [{next_ev['source']}]: "
                   f"\"{next_ev['title']}\" às {next_ev['start'].strftime('%H:%M')}")
        return True, msg

    return False, f"Sem eventos nos próximos {lookahead} minutos"


def is_free_until_eod(params: dict) -> tuple[bool, str]:
    """
    Condition: retorna True se não há mais eventos para o resto do dia.
    Útil como condição para desligar automaticamente ao fim do expediente.
    """
    sources    = _parse_sources(params.get("sources", "outlook,windows"))
    eod_hour   = int(params.get("eod_hour",   23))
    eod_minute = int(params.get("eod_minute", 59))

    now = datetime.now()
    eod = now.replace(hour=eod_hour, minute=eod_minute, second=0, microsecond=0)

    if now >= eod:
        return True, "Já passou do fim do dia configurado"

    events = _collect_events(sources, now, eod, "")
    if not events:
        return True, f"Sem mais eventos até {eod_hour:02d}:{eod_minute:02d}"

    events.sort(key=lambda e: e["start"])
    next_ev = events[0]
    msg     = (f"Ainda há eventos hoje [{next_ev['source']}]: "
               f"\"{next_ev['title']}\" às {next_ev['start'].strftime('%H:%M')}")
    return False, msg


# ─── Actions ───────────────────────────────────────────────────────────────

def log_next_event(params: dict) -> bool:
    """Ação de diagnóstico: registra o próximo evento no log."""
    sources    = _parse_sources(params.get("sources", "outlook,windows"))
    lookahead  = int(params.get("lookahead_min", 120))

    now    = datetime.now()
    end    = now + timedelta(minutes=lookahead)
    events = _collect_events(sources, now, end, "")

    if not events:
        log.info(f"[calendar_sync_plus] Nenhum evento nos próximos {lookahead} min.")
        return True

    events.sort(key=lambda e: e["start"])
    for ev in events[:5]:
        diff = int((ev["start"] - now).total_seconds() / 60)
        log.info(f"[calendar_sync_plus] Evento [{ev['source']}] em {diff:3d} min: "
                 f"\"{ev['title']}\" {ev['start'].strftime('%H:%M')}–{ev['end'].strftime('%H:%M')}")
    return True
