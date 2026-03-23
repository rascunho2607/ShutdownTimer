"""
╔══════════════════════════════════════════════════════════════╗
║  CalendarIntegration — ShutdownTimer v5.0                    ║
║  Múltiplas fontes de calendário com cache inteligente        ║
╠══════════════════════════════════════════════════════════════╣
║  Fontes suportadas:                                          ║
║   • BrasilAPI  — feriados nacionais e estaduais              ║
║   • Google Calendar — OAuth2 (requer client_secret.json)     ║
║   • Arquivo .ICS local / URL remota                          ║
╚══════════════════════════════════════════════════════════════╝

Dependências opcionais:
    pip install requests icalendar
    pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
"""

from __future__ import annotations

import json
import threading
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger("CalendarIntegration")

# ── Imports opcionais ──────────────────────────────────────────────────────────
try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import icalendar as _icalendar
    HAS_ICALENDAR = True
except ImportError:
    HAS_ICALENDAR = False

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as _GRequest
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build as _gcal_build
    HAS_GOOGLE_CAL = True
except ImportError:
    HAS_GOOGLE_CAL = False

# ── Constantes ────────────────────────────────────────────────────────────────
_BASE_DIR   = Path.home() / ".shutdown_timer"
_TOKEN_FILE = _BASE_DIR / "google_calendar_token.json"
_CACHE_FILE = _BASE_DIR / "calendar_cache.json"
_SCOPES     = ["https://www.googleapis.com/auth/calendar.readonly"]

BRASIL_STATES: Dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}


# ══════════════════════════════════════════════════════════════════════════════
# BASE SOURCE
# ══════════════════════════════════════════════════════════════════════════════

class CalendarSource:
    """Classe base para todas as fontes de calendário."""

    def __init__(self, config: dict):
        self.config = config
        self._lock  = threading.Lock()

    def get_events(self, start: date, end: date) -> List[Dict]:
        """Retorna lista de eventos no período [start, end]."""
        raise NotImplementedError

    def is_special_day(self, day: date) -> Tuple[bool, str]:
        """Retorna (True, motivo) se o dia for especial."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__


# ══════════════════════════════════════════════════════════════════════════════
# BRASIL API — Feriados nacionais e estaduais
# ══════════════════════════════════════════════════════════════════════════════

class BrasilAPISource(CalendarSource):
    """Feriados nacionais e estaduais via BrasilAPI (gratuita, sem autenticação)."""

    _BASE = "https://brasilapi.com.br/api/feriados/v1/{year}"
    _TIMEOUT = 8  # segundos

    def __init__(self, config: dict):
        super().__init__(config)
        self._cache: Dict[int, List[Dict]] = {}   # year -> list of events
        self._state: Optional[str] = config.get("state")  # sigla: "SP", "RJ" ...

    # ── Pública ────────────────────────────────────────────────────────────────

    def get_events(self, start: date, end: date) -> List[Dict]:
        events: List[Dict] = []
        for year in range(start.year, end.year + 1):
            events.extend(self._fetch_year(year))
        # filtrar no intervalo
        result = []
        for ev in events:
            try:
                d = date.fromisoformat(ev["date"])
                if start <= d <= end:
                    result.append(ev)
            except Exception:
                pass
        return result

    def is_special_day(self, day: date) -> Tuple[bool, str]:
        if not HAS_REQUESTS:
            return False, ""
        events = self._fetch_year(day.year)
        day_str = day.strftime("%Y-%m-%d")
        for ev in events:
            if ev.get("date") == day_str:
                return True, f"Feriado: {ev.get('name', '')}"
        return False, ""

    # ── Privado ────────────────────────────────────────────────────────────────

    def _fetch_year(self, year: int) -> List[Dict]:
        if year in self._cache:
            return self._cache[year]
        if not HAS_REQUESTS:
            return []
        try:
            url = self._BASE.format(year=year)
            resp = _requests.get(url, timeout=self._TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                self._cache[year] = data
                return data
        except Exception as e:
            log.warning(f"[BrasilAPI] {year}: {e}")
        return []

    @property
    def name(self) -> str:
        return "Feriados Nacionais (Brasil)"


# ══════════════════════════════════════════════════════════════════════════════
# ICS FILE / URL SOURCE
# ══════════════════════════════════════════════════════════════════════════════

class ICSSource(CalendarSource):
    """Fonte: arquivo .ics local ou URL remota."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._path: str = config.get("path", "")
        self._url: str  = config.get("url", "")
        self._events: Optional[List[Dict]] = None
        self._loaded_ts: float = 0.0
        self._TTL = 3600  # 1 hora

    def _load(self) -> List[Dict]:
        if not HAS_ICALENDAR:
            return []
        import time
        now = time.time()
        if self._events is not None and (now - self._loaded_ts) < self._TTL:
            return self._events

        raw: Optional[bytes] = None
        try:
            if self._url and HAS_REQUESTS:
                resp = _requests.get(self._url, timeout=10)
                if resp.status_code == 200:
                    raw = resp.content
            elif self._path and Path(self._path).exists():
                raw = Path(self._path).read_bytes()
        except Exception as e:
            log.warning(f"[ICS] load: {e}")

        if not raw:
            return []

        events: List[Dict] = []
        try:
            cal = _icalendar.Calendar.from_ical(raw)
            for comp in cal.walk():
                if comp.name != "VEVENT":
                    continue
                try:
                    dt_start = comp.get("dtstart")
                    if dt_start is None:
                        continue
                    dt = dt_start.dt
                    if isinstance(dt, datetime):
                        d = dt.date()
                    else:
                        d = dt
                    summary = str(comp.get("summary", "Evento"))
                    events.append({"date": d.isoformat(), "name": summary,
                                   "source": "ics"})
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"[ICS] parse: {e}")

        self._events = events
        self._loaded_ts = now
        return events

    def get_events(self, start: date, end: date) -> List[Dict]:
        result = []
        for ev in self._load():
            try:
                d = date.fromisoformat(ev["date"])
                if start <= d <= end:
                    result.append(ev)
            except Exception:
                pass
        return result

    def is_special_day(self, day: date) -> Tuple[bool, str]:
        day_str = day.isoformat()
        for ev in self._load():
            if ev.get("date") == day_str:
                return True, f"Evento: {ev.get('name','')}"
        return False, ""

    @property
    def name(self) -> str:
        return "Calendário ICS"


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE CALENDAR SOURCE
# ══════════════════════════════════════════════════════════════════════════════

class GoogleCalendarSource(CalendarSource):
    """Integração com Google Calendar via OAuth2."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._client_secret: str = config.get("client_secret_path", "")
        self._calendar_ids: List[str] = config.get(
            "calendar_ids", ["primary"])
        self._service = None
        self._authenticated = False

    # ── Autenticação ───────────────────────────────────────────────────────────

    def authenticate(self) -> Tuple[bool, str]:
        """Inicia OAuth2. Retorna (ok, mensagem)."""
        if not HAS_GOOGLE_CAL:
            return False, ("google-api-python-client não instalado.\n"
                           "pip install google-api-python-client "
                           "google-auth-oauthlib")
        _BASE_DIR.mkdir(parents=True, exist_ok=True)
        creds = None
        if _TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(_TOKEN_FILE), _SCOPES)
            except Exception:
                pass

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(_GRequest())
                except Exception:
                    creds = None

            if not creds:
                if not self._client_secret or not Path(
                        self._client_secret).exists():
                    return False, (
                        "Arquivo client_secret.json não encontrado.\n"
                        "Configure o caminho nas opções de calendário.")
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self._client_secret, _SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    return False, f"Falha na autenticação: {e}"

            try:
                _TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                pass

        try:
            self._service = _gcal_build(
                "calendar", "v3", credentials=creds)
            self._authenticated = True
            return True, "Conectado ao Google Calendar."
        except Exception as e:
            return False, f"Erro ao criar serviço: {e}"

    def disconnect(self):
        """Remove token salvo."""
        self._service = None
        self._authenticated = False
        if _TOKEN_FILE.exists():
            try:
                _TOKEN_FILE.unlink()
            except Exception:
                pass

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated and self._service is not None

    # ── Eventos ────────────────────────────────────────────────────────────────

    def get_events(self, start: date, end: date) -> List[Dict]:
        if not self.is_authenticated:
            return []
        events: List[Dict] = []
        t_min = datetime.combine(start, datetime.min.time()).isoformat() + "Z"
        t_max = datetime.combine(end,   datetime.max.time()).isoformat() + "Z"
        for cal_id in self._calendar_ids:
            try:
                result = (self._service.events()
                          .list(calendarId=cal_id,
                                timeMin=t_min, timeMax=t_max,
                                singleEvents=True, orderBy="startTime")
                          .execute())
                for item in result.get("items", []):
                    start_raw = item.get("start", {})
                    d_str = start_raw.get("date") or start_raw.get(
                        "dateTime", "")[:10]
                    events.append({
                        "date":    d_str,
                        "name":    item.get("summary", "Evento"),
                        "source":  "google",
                        "all_day": "date" in start_raw,
                        "status":  item.get("status", "confirmed"),
                        "transparency": item.get("transparency", "opaque"),
                    })
            except Exception as e:
                log.warning(f"[Google Calendar] {cal_id}: {e}")
        return events

    def is_special_day(self, day: date) -> Tuple[bool, str]:
        events = self.get_events(day, day)
        cfg    = self.config
        keywords  = cfg.get("keywords", [])
        busy_only = cfg.get("busy_only", False)
        any_event = cfg.get("any_event", True)

        for ev in events:
            if busy_only and ev.get("transparency") == "transparent":
                continue
            if keywords:
                name_lower = ev.get("name", "").lower()
                if not any(kw.lower() in name_lower for kw in keywords):
                    continue
            if any_event or busy_only or keywords:
                return True, f"Google Calendar: {ev.get('name','')}"
        return False, ""

    @property
    def name(self) -> str:
        return "Google Calendar"


# ══════════════════════════════════════════════════════════════════════════════
# CALENDAR MANAGER — Orquestrador
# ══════════════════════════════════════════════════════════════════════════════

class CalendarManager:
    """
    Gerencia múltiplas fontes de calendário, faz cache local e decide
    se um dia é especial para bloquear ações automáticas.
    """

    _CACHE_TTL_HOURS = 6   # revalidar cache a cada 6 h

    def __init__(self, config):
        self._config = config
        self._lock   = threading.Lock()
        self._sources: List[CalendarSource] = []
        self._cache: Dict[str, Tuple[bool, str]] = {}  # date_iso -> (is_special, reason)
        self._cache_ts: Dict[str, float] = {}
        self._last_sync: Optional[datetime] = None
        self.on_sync_done: Optional[Callable[[bool, str], None]] = None

        _BASE_DIR.mkdir(parents=True, exist_ok=True)
        self._load_disk_cache()
        self._init_sources()

    # ── Inicialização de fontes ────────────────────────────────────────────────

    def _init_sources(self):
        cfg = self._config.get("calendar_integration") or {}
        sources_cfg = cfg.get("sources", {})
        self._sources = []

        # Brasil API
        brasil_cfg = sources_cfg.get("brasil_api", {})
        if brasil_cfg.get("enabled", False):
            self._sources.append(BrasilAPISource(brasil_cfg))

        # ICS local / URL
        ics_cfg = sources_cfg.get("ics", {})
        if ics_cfg.get("enabled", False):
            self._sources.append(ICSSource(ics_cfg))

        # Google Calendar
        google_cfg = sources_cfg.get("google", {})
        if google_cfg.get("enabled", False):
            src = GoogleCalendarSource(google_cfg)
            # Tenta autenticar silenciosamente com token salvo
            if _TOKEN_FILE.exists():
                ok, _ = src.authenticate()
                if ok:
                    self._sources.append(src)

    def reinit_sources(self):
        """Reinicia as fontes (chamado após alterar configurações)."""
        self._sources = []
        self._init_sources()

    # ── Acesso público ────────────────────────────────────────────────────────

    def is_special_day(self, day: Optional[date] = None) -> Tuple[bool, str]:
        """Verifica se a data é especial em alguma fonte."""
        if day is None:
            day = date.today()
        key = day.isoformat()

        import time
        with self._lock:
            if key in self._cache:
                ts = self._cache_ts.get(key, 0)
                if time.time() - ts < self._CACHE_TTL_HOURS * 3600:
                    return self._cache[key]

        result = (False, "")
        for src in self._sources:
            try:
                ok, reason = src.is_special_day(day)
                if ok:
                    result = (ok, reason)
                    break
            except Exception as e:
                log.warning(f"[CalMgr] {src.name}: {e}")

        with self._lock:
            import time
            self._cache[key] = result
            self._cache_ts[key] = time.time()

        self._save_disk_cache()
        return result

    def get_upcoming_special_days(self, days: int = 30) -> List[Dict]:
        """Retorna dias especiais nos próximos N dias."""
        today   = date.today()
        specials: List[Dict] = []
        for i in range(days):
            d = today + timedelta(days=i)
            is_sp, reason = self.is_special_day(d)
            if is_sp:
                specials.append({
                    "date":    d.isoformat(),
                    "display": d.strftime("%d/%m/%Y"),
                    "weekday": ["Segunda", "Terça", "Quarta", "Quinta",
                                "Sexta", "Sábado", "Domingo"][d.weekday()],
                    "reason":  reason,
                })
        return specials

    def sync_async(self):
        """Dispara sincronização em background."""
        threading.Thread(target=self._sync, daemon=True).start()

    def _sync(self):
        """Sincroniza cache para os próximos 60 dias."""
        today = date.today()
        end   = today + timedelta(days=60)
        count = 0
        for src in self._sources:
            try:
                events = src.get_events(today, end)
                import time
                with self._lock:
                    for ev in events:
                        key = ev.get("date", "")
                        if key:
                            self._cache[key] = (True, ev.get("name", "Evento"))
                            self._cache_ts[key] = time.time()
                count += len(events)
            except Exception as e:
                log.warning(f"[CalMgr] sync {src.name}: {e}")

        self._last_sync = datetime.now()
        self._save_disk_cache()
        if self.on_sync_done:
            self.on_sync_done(True, f"Sincronizados {count} eventos")

    def clear_cache(self):
        with self._lock:
            self._cache.clear()
            self._cache_ts.clear()
        self._save_disk_cache()

    @property
    def last_sync_str(self) -> str:
        if self._last_sync:
            return self._last_sync.strftime("hoje %H:%M" if
                self._last_sync.date() == date.today() else "%d/%m/%Y %H:%M")
        return "nunca"

    @property
    def sources(self) -> List[CalendarSource]:
        return list(self._sources)

    def get_google_source(self) -> Optional[GoogleCalendarSource]:
        for s in self._sources:
            if isinstance(s, GoogleCalendarSource):
                return s
        # Ainda não adicionado, mas talvez configurado
        cfg = (self._config.get("calendar_integration") or {})
        src_cfg = cfg.get("sources", {}).get("google", {})
        if src_cfg:
            return GoogleCalendarSource(src_cfg)
        return None

    def add_google_source(self, source: GoogleCalendarSource):
        """Adiciona Google Calendar já autenticado às fontes."""
        # Remover instâncias anteriores
        self._sources = [s for s in self._sources
                         if not isinstance(s, GoogleCalendarSource)]
        self._sources.append(source)

    # ── Cache em disco ────────────────────────────────────────────────────────

    def _load_disk_cache(self):
        try:
            if _CACHE_FILE.exists():
                data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                self._cache    = {k: tuple(v) for k, v in  # type: ignore[misc]
                                  data.get("cache", {}).items()}
                self._cache_ts = data.get("ts", {})
                ls = data.get("last_sync")
                if ls:
                    self._last_sync = datetime.fromisoformat(ls)
        except Exception as e:
            log.warning(f"[CalMgr] load cache: {e}")

    def _save_disk_cache(self):
        try:
            data = {
                "cache": {k: list(v) for k, v in self._cache.items()},
                "ts":    self._cache_ts,
                "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            }
            _CACHE_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.warning(f"[CalMgr] save cache: {e}")
