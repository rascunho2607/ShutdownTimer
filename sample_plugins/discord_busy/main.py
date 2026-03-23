"""
Discord Busy — ShutdownTimer Plugin
Pausa o timer enquanto o Discord detecta chamada de voz ativa.

Estratégia de detecção (da mais confiável para fallback):
  1. Leitura do discord.sock / named pipe (local RPC)
  2. Verificar uso de dispositivo de áudio pelo processo discord.exe
  3. Simples: Discord em execução (fallback conservador)
"""
from __future__ import annotations
import json
import logging
import os
import socket
import sys

log = logging.getLogger("discord_busy")

# IPC socket path varies by OS
_DISCORD_IPC_PATHS = []
if sys.platform == "win32":
    # Windows: named pipe
    _DISCORD_IPC_PATHS = [r"\\.\pipe\discord-ipc-{}".format(i) for i in range(10)]
else:
    # Linux/Mac: unix socket
    _tmp = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    _DISCORD_IPC_PATHS = [os.path.join(_tmp, f"discord-ipc-{i}") for i in range(10)]


def on_load():
    log.info("[discord_busy] Carregado. Monitorando Discord.")


def on_unload():
    log.info("[discord_busy] Descarregado.")


def _discord_is_running() -> bool:
    """Verifica se o processo Discord está em execução."""
    try:
        import psutil
        names = {p.name().lower() for p in psutil.process_iter(["name"])}
        return "discord.exe" in names or "discord" in names
    except Exception:
        return False


def _detect_voice_via_ipc() -> tuple[bool, str]:
    """
    Tenta conectar ao Discord IPC local e verificar se há voice activity.
    Retorna (in_call, detail).
    """
    if sys.platform != "win32":
        # Unix socket
        for path in _DISCORD_IPC_PATHS:
            if not os.path.exists(path):
                continue
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(path)
                # Handshake: opcode 0 = HANDSHAKE
                payload = json.dumps({
                    "v": 1,
                    "client_id": "shutdown_timer_plugin"
                }).encode()
                import struct
                header = struct.pack("<II", 0, len(payload))
                sock.sendall(header + payload)
                data = sock.recv(4096)
                sock.close()
                # Se conseguiu conectar, Discord está rodando com RPC
                return True, "Discord IPC ativo (possível chamada)"
            except Exception:
                pass
        return False, "IPC não disponível"
    else:
        # Windows: named pipe — apenas testa existência
        import os
        for path in _DISCORD_IPC_PATHS:
            if os.path.exists(path):
                return True, "Discord Named Pipe detectado"
        return False, "Named pipe não encontrado"


def _detect_voice_via_audio() -> tuple[bool, str]:
    """
    Heurística: verifica se discord.exe está usando dispositivo de áudio
    verificando conexões de rede UDP ativas (chamadas VoIP usam UDP).
    """
    try:
        import psutil
        for proc in psutil.process_iter(["name", "connections"]):
            if proc.info["name"] and "discord" in proc.info["name"].lower():
                try:
                    conns = proc.connections(kind="udp")
                    if conns:
                        return True, f"Discord com {len(conns)} conexão(ões) UDP ativa(s)"
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
        return False, "Sem conexões UDP no Discord"
    except Exception as e:
        return False, f"Erro: {e}"


def check_discord_call(params: dict) -> tuple:
    """
    Condição: Discord em chamada de voz ativa.
    Retorna (True, motivo) se chamada detectada.
    """
    if not _discord_is_running():
        return False, "Discord não está em execução"

    # Tenta detecção por áudio/UDP (mais confiável sem permissões especiais)
    in_call, detail = _detect_voice_via_audio()
    if in_call:
        return True, f"Discord em chamada — {detail}"

    # Fallback: IPC
    ipc_active, ipc_detail = _detect_voice_via_ipc()
    if ipc_active:
        return True, f"Discord ativo via IPC — {ipc_detail}"

    # Último fallback: se also_check_muted, qualquer execução conta
    if params.get("also_check_muted", False):
        return True, "Discord em execução (modo conservador ativado)"

    return False, f"Discord em execução mas sem chamada detectada ({detail})"
