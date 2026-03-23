"""
email_notifier.py — EmailNotifier for ShutdownTimer v5.0
=========================================================
Sends HTML email notifications for timer events.
Credentials are stored encrypted (AES-256 via cryptography).

Required optional packages:
    pip install cryptography   # for credential encryption
All SMTP modules (smtplib, email.*) are part of Python stdlib.
"""

from __future__ import annotations

import hashlib
import logging
import os
import smtplib
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable, Dict, List, Optional

try:
    from cryptography.fernet import Fernet
    import base64 as _b64
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ─────────────────────────────────────────────────────────────────────────────
# Provider presets
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_PROVIDERS: Dict[str, dict] = {
    "gmail": {
        "smtp":  "smtp.gmail.com",
        "port":  587,
        "tls":   True,
        "ssl":   False,
        "note":  "Use senha de app (não a senha normal)",
    },
    "outlook": {
        "smtp":  "smtp-mail.outlook.com",
        "port":  587,
        "tls":   True,
        "ssl":   False,
        "note":  "",
    },
    "yahoo": {
        "smtp":  "smtp.mail.yahoo.com",
        "port":  465,
        "tls":   False,
        "ssl":   True,
        "note":  "",
    },
    "custom": {
        "smtp":  "",
        "port":  587,
        "tls":   True,
        "ssl":   False,
        "note":  "",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Email templates (inline HTML – no external files needed)
# ─────────────────────────────────────────────────────────────────────────────

_BASE_STYLE = """
<style>
  body{font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:0}
  .container{max-width:600px;margin:20px auto;background:#fff;border-radius:10px;overflow:hidden}
  .header{background:#4f8ef7;color:#fff;padding:20px 24px}
  .header h2{margin:0;font-size:20px}
  .content{padding:20px 24px;color:#333;line-height:1.6}
  .stats{background:#f9f9f9;padding:14px;border-radius:6px;margin:12px 0}
  .stats p{margin:4px 0}
  .footer{background:#eee;padding:12px 24px;font-size:12px;color:#666}
  .chip{display:inline-block;background:#e8f0fe;color:#1a73e8;
        border-radius:12px;padding:2px 10px;font-size:13px}
</style>
"""

_TEMPLATES: Dict[str, str] = {
    "timer_started": (
        "<div class='content'>"
        "<p>O timer do ShutdownTimer foi <strong>iniciado</strong>.</p>"
        "<div class='stats'>"
        "<p>⏱  Duração: <strong>{minutes} minutos</strong></p>"
        "<p>⚡  Ação: <strong>{action}</strong></p>"
        "<p>🕐  Início: {time}</p>"
        "</div></div>"
    ),
    "timer_finished": (
        "<div class='content'>"
        "<p>O timer foi <strong>concluído</strong> com sucesso.</p>"
        "<div class='stats'>"
        "<p>✅  Ação executada: <strong>{action}</strong></p>"
        "<p>⏱  Duração: {minutes} minutos</p>"
        "<p>🕐  Concluído em: {completed_at}</p>"
        "</div></div>"
    ),
    "timer_cancelled": (
        "<div class='content'>"
        "<p>O timer foi <strong>cancelado</strong>.</p>"
        "<div class='stats'>"
        "<p>❌  Ação cancelada: <strong>{action}</strong></p>"
        "<p>⏱  Tempo configurado: {minutes} minutos</p>"
        "<p>📝  Motivo: {reason}</p>"
        "</div></div>"
    ),
    "condition_met": (
        "<div class='content'>"
        "<p>Uma <strong>condição monitorada</strong> foi satisfeita.</p>"
        "<div class='stats'>"
        "<p>🎯  Condição: <strong>{condition}</strong></p>"
        "<p>⚡  Ação disparada: <strong>{action}</strong></p>"
        "<p>📝  Descrição: {description}</p>"
        "</div></div>"
    ),
    "smart_action": (
        "<div class='content'>"
        "<p>O <strong>Smart Mode</strong> tomou uma ação automática.</p>"
        "<div class='stats'>"
        "<p>🧠  Motivo: <strong>{reason}</strong></p>"
        "<p>⚡  Ação: <strong>{action}</strong></p>"
        "<p>🕐  Hora: {time}</p>"
        "</div></div>"
    ),
    "error": (
        "<div class='content'>"
        "<p>⚠️  Ocorreu um <strong>erro</strong> no ShutdownTimer.</p>"
        "<div class='stats'>"
        "<p>📝  Detalhe: {error}</p>"
        "<p>🕐  Hora: {time}</p>"
        "</div></div>"
    ),
    "daily_report": (
        "<div class='content'>"
        "<p>Relatório diário de economia de energia.</p>"
        "<div class='stats'>"
        "<p>⚡  Ações hoje: <strong>{actions_today}</strong></p>"
        "<p>⏱  Minutos agendados: <strong>{minutes_today}</strong></p>"
        "<p>💡  Energia estimada poupada: ~{kwh_saved} kWh</p>"
        "<p>🌿  CO₂ evitado: ~{co2_saved} kg</p>"
        "</div></div>"
    ),
    "test": (
        "<div class='content'>"
        "<p>✅ Este é um <strong>email de teste</strong> do ShutdownTimer.</p>"
        "<p>Se você está lendo isto, as configurações SMTP estão corretas.</p>"
        "</div>"
    ),
}

_SUBJECTS: Dict[str, str] = {
    "timer_started":   "⏻ ShutdownTimer — Timer iniciado",
    "timer_finished":  "✅ ShutdownTimer — Timer concluído",
    "timer_cancelled": "❌ ShutdownTimer — Timer cancelado",
    "condition_met":   "🎯 ShutdownTimer — Condição satisfeita",
    "smart_action":    "🧠 ShutdownTimer — Smart Mode atuou",
    "error":           "⚠️ ShutdownTimer — Erro detectado",
    "daily_report":    "📊 ShutdownTimer — Relatório diário",
    "test":            "🔧 ShutdownTimer — Email de teste",
}


# ─────────────────────────────────────────────────────────────────────────────
# Rate-limiting queue
# ─────────────────────────────────────────────────────────────────────────────

class EmailQueue:
    """Thread-safe queue that respects max_per_hour rate limiting."""

    def __init__(self, max_per_hour: int = 5):
        self._max      = max_per_hour
        self._queue:   List[dict]  = []
        self._sent_ts: List[float] = []
        self._lock     = threading.Lock()

    def add(self, email_data: dict, send_fn: Callable[[dict], bool]):
        with self._lock:
            self._queue.append(email_data)
        self._process(send_fn)

    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    def _can_send(self) -> bool:
        now = time.time()
        with self._lock:
            self._sent_ts = [t for t in self._sent_ts if now - t < 3600]
            return len(self._sent_ts) < self._max

    def _process(self, send_fn: Callable[[dict], bool]):
        if not self._can_send():
            return
        with self._lock:
            if not self._queue:
                return
            item = self._queue.pop(0)
        ok = send_fn(item)
        if ok:
            with self._lock:
                self._sent_ts.append(time.time())
        if self._queue:
            threading.Timer(60, self._process, args=(send_fn,)).start()


# ─────────────────────────────────────────────────────────────────────────────
# EmailNotifier
# ─────────────────────────────────────────────────────────────────────────────

class EmailNotifier:
    """
    Sends HTML email notifications for ShutdownTimer events.

    All SMTP operations run in a background thread; never blocks the UI.
    """

    def __init__(self, config):
        self._config  = config
        self._logger  = logging.getLogger("EmailNotifier")
        self._queue   = EmailQueue(
            max_per_hour=self._get_cfg().get("max_per_hour", 5))
        self._last_result: str = ""

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def send_event(self, event: str, **kwargs):
        """
        Enqueue an email for a named event.
        Event keys match _TEMPLATES above.
        Extra kwargs are template variables.
        """
        cfg = self._get_cfg()
        if not cfg.get("enabled", False):
            return
        events = cfg.get("events", {})
        if not events.get(event, True):
            return
        if self._in_quiet_hours():
            self._logger.debug(
                f"Email suppressed (quiet hours): {event}")
            return
        recipients = cfg.get("recipients", [])
        if not recipients:
            return

        kwargs.setdefault("time", datetime.now().strftime("%d/%m/%Y %H:%M"))
        body = self._render(event, kwargs)
        data = {
            "event":      event,
            "subject":    _SUBJECTS.get(event, "ShutdownTimer"),
            "body":       body,
            "recipients": recipients,
        }
        self._queue = EmailQueue(
            max_per_hour=cfg.get("max_per_hour", 5))
        self._queue.add(data, self._send_email)

    def send_test(self) -> tuple:
        """Blocking test send. Returns (success, message)."""
        cfg        = self._get_cfg()
        recipients = cfg.get("recipients", [])
        if not recipients:
            return False, "Nenhum destinatário configurado."
        body = self._render("test", {})
        data = {
            "event":      "test",
            "subject":    _SUBJECTS["test"],
            "body":       body,
            "recipients": recipients,
        }
        ok = self._send_email(data)
        return ok, self._last_result

    def test_connection(self) -> tuple:
        """Only verify SMTP credentials without sending. Returns (ok, msg)."""
        cfg = self._get_cfg()
        try:
            password = self.get_password()
            if not password:
                return False, "Senha não configurada."
            server   = cfg.get("smtp_server", "")
            port     = int(cfg.get("smtp_port", 587))
            use_tls  = cfg.get("use_tls", True)
            use_ssl  = cfg.get("use_ssl", False)
            email_from = cfg.get("email_from", "")

            smtp = self._connect_smtp(server, port, use_tls, use_ssl,
                                      email_from, password)
            smtp.quit()
            self._last_result = "Conexão OK"
            return True, "✅ Conexão SMTP bem-sucedida."
        except Exception as e:
            self._last_result = str(e)
            return False, f"❌ Erro: {e}"

    def save_password(self, password: str):
        """Encrypt and persist password."""
        if not password:
            self._config.data.setdefault("email_alerts", {})["email_password"] = ""
            self._config.save()
            return
        encrypted = self._encrypt(password)
        cfg = dict(self._config.get("email_alerts") or {})
        cfg["email_password"] = encrypted
        self._config.set("email_alerts", cfg)

    def get_password(self) -> str:
        """Decrypt and return stored password, or plain-text fallback."""
        cfg = self._get_cfg()
        raw = cfg.get("email_password", "")
        if not raw:
            return ""
        return self._decrypt(raw)

    # ─────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────

    def _get_cfg(self) -> dict:
        return self._config.get("email_alerts") or {}

    def _render(self, event: str, variables: dict) -> str:
        content = _TEMPLATES.get(event, "<div class='content'><p>{}</p></div>")
        try:
            content = content.format(**variables)
        except KeyError:
            pass
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        footer  = (
            f"<div class='footer'>"
            f"Enviado em {now_str} pelo ShutdownTimer.<br>"
            f"Para desativar, acesse Opções → Alertas por Email."
            f"</div>"
        )
        return (
            f"<!DOCTYPE html><html><head>{_BASE_STYLE}</head>"
            f"<body><div class='container'>"
            f"<div class='header'><h2>⏻ ShutdownTimer</h2></div>"
            f"{content}"
            f"{footer}"
            f"</div></body></html>"
        )

    def _send_email(self, data: dict) -> bool:
        cfg        = self._get_cfg()
        server     = cfg.get("smtp_server", "")
        port       = int(cfg.get("smtp_port", 587))
        use_tls    = cfg.get("use_tls", True)
        use_ssl    = cfg.get("use_ssl", False)
        email_from = cfg.get("email_from", "")
        password   = self.get_password()

        if not server or not email_from or not password:
            self._last_result = "Configurações incompletas"
            return False
        try:
            smtp = self._connect_smtp(server, port, use_tls, use_ssl,
                                      email_from, password)
            for recipient in data["recipients"]:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = data["subject"]
                msg["From"]    = email_from
                msg["To"]      = recipient
                msg.attach(MIMEText(data["body"], "html", "utf-8"))
                smtp.sendmail(email_from, recipient, msg.as_string())
            smtp.quit()
            self._last_result = (
                f"OK — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
            self._logger.info(
                f"Email sent: {data['event']} → {data['recipients']}")
            return True
        except Exception as e:
            self._last_result = str(e)
            self._logger.error(f"Email send error: {e}")
            return False

    @staticmethod
    def _connect_smtp(server: str, port: int, use_tls: bool,
                      use_ssl: bool, email_from: str,
                      password: str) -> smtplib.SMTP:
        if use_ssl:
            smtp = smtplib.SMTP_SSL(server, port, timeout=15)
        else:
            smtp = smtplib.SMTP(server, port, timeout=15)
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(email_from, password)
        return smtp

    def _in_quiet_hours(self) -> bool:
        cfg   = self._get_cfg()
        start = cfg.get("quiet_hours_start", 23)
        end   = cfg.get("quiet_hours_end",   7)
        hour  = datetime.now().hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _encrypt(self, plain: str) -> str:
        if not HAS_CRYPTO:
            return plain
        try:
            key = self._derive_key()
            f   = Fernet(key)
            enc = f.encrypt(plain.encode())
            return _b64.b64encode(enc).decode()
        except Exception:
            return plain

    def _decrypt(self, stored: str) -> str:
        if not HAS_CRYPTO:
            return stored
        try:
            key = self._derive_key()
            f   = Fernet(key)
            raw = _b64.b64decode(stored.encode())
            return f.decrypt(raw).decode()
        except Exception:
            return stored   # treat as plain-text fallback

    @staticmethod
    def _derive_key() -> bytes:
        user_id = os.getlogin() + os.environ.get("COMPUTERNAME", "")
        digest  = hashlib.sha256(user_id.encode()).digest()
        return _b64.urlsafe_b64encode(digest)
