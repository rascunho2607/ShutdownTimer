"""
Web Notify — ShutdownTimer Plugin
Envia notificação HTTP/webhook quando o ShutdownTimer executa uma ação.

Suporta qualquer URL: Discord, Slack, Telegram, IFTTT, serviços próprios, etc.
"""
from __future__ import annotations
import json
import logging
import threading
from datetime import datetime

log = logging.getLogger("web_notify")

# Configuração padrão (sobrescrita via params)
_DEFAULT_CONFIG = {
    "url":     "",
    "method":  "POST",
    "payload": '{"event": "{event}", "action": "{action}", "timestamp": "{timestamp}"}',
    "headers": "{}",
    "timeout": 5,
}

# Fila para envios async (evita bloquear a UI)
_send_queue: list = []
_last_result: dict = {"ok": None, "status": None, "error": None}


def on_load():
    log.info("[web_notify] Carregado. Pronto para enviar webhooks.")


def on_unload():
    log.info("[web_notify] Descarregado.")


def _build_payload(template: str, event: str, action: str) -> str:
    """Substitui placeholders no payload."""
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return (template
            .replace("{event}",     event)
            .replace("{action}",    action)
            .replace("{timestamp}", ts)
            .replace("{date}",      datetime.now().strftime("%d/%m/%Y"))
            .replace("{time}",      datetime.now().strftime("%H:%M:%S")))


def send_webhook(params: dict) -> bool:
    """
    Ação: envia POST/GET para a URL configurada.
    Retorna True se envio bem-sucedido.
    """
    url     = params.get("url", _DEFAULT_CONFIG["url"]).strip()
    method  = params.get("method", "POST").upper()
    timeout = int(params.get("timeout", 5))
    event   = params.get("event", "timer_event")
    action  = params.get("action", "unknown")

    payload_tmpl = params.get("payload", _DEFAULT_CONFIG["payload"])
    headers_raw  = params.get("headers", "{}")

    if not url:
        log.warning("[web_notify] URL não configurada — nenhum webhook enviado.")
        _last_result.update({"ok": False, "error": "URL não configurada"})
        return False

    # Parse headers
    try:
        headers = json.loads(headers_raw) if headers_raw.strip() else {}
    except json.JSONDecodeError:
        headers = {}
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("User-Agent",   "ShutdownTimer-WebNotify/1.0")

    # Build payload
    try:
        body_str = _build_payload(payload_tmpl, event, action)
        body_obj = json.loads(body_str)  # valida JSON
    except (json.JSONDecodeError, Exception) as e:
        log.warning(f"[web_notify] Payload inválido: {e} — usando fallback")
        body_obj = {"event": event, "action": action,
                    "timestamp": datetime.now().isoformat()}

    def _do_send():
        try:
            import urllib.request
            import urllib.error
            data = json.dumps(body_obj).encode("utf-8")
            req  = urllib.request.Request(
                url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                _last_result.update({"ok": True, "status": status, "error": None})
                log.info(f"[web_notify] Webhook enviado → {url} ({status})")
        except Exception as e:
            _last_result.update({"ok": False, "status": None, "error": str(e)})
            log.warning(f"[web_notify] Falha no webhook: {e}")

    # Envia em thread separada para não bloquear
    threading.Thread(target=_do_send, daemon=True).start()
    return True  # retorna imediatamente (async)


def notify_shutdown(params: dict) -> bool:
    """Atalho: notifica desligamento."""
    p = dict(params)
    p.setdefault("event", "shutdown")
    p.setdefault("action", "shutdown")
    return send_webhook(p)


def notify_cancel(params: dict) -> bool:
    """Atalho: notifica cancelamento."""
    p = dict(params)
    p.setdefault("event", "cancelled")
    p.setdefault("action", "cancelled")
    return send_webhook(p)


def get_last_result() -> dict:
    """Retorna o resultado do último envio."""
    return dict(_last_result)


def test_webhook(params: dict) -> tuple:
    """Testa a conectividade com a URL configurada."""
    p = dict(params)
    p["event"]  = "test"
    p["action"] = "test"
    ok = send_webhook(p)
    return ok, "Webhook enviado (assíncrono — verifique o destino)" if ok \
               else "URL não configurada"
