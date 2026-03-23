"""
╔══════════════════════════════════════════════════════════════╗
║  PluginManager — ShutdownTimer v5.0                          ║
║  Sistema de plugins com sandbox, permissões e comunidade     ║
╠══════════════════════════════════════════════════════════════╣
║  Estrutura de um plugin (pasta ou .zip):                     ║
║    plugin.json    — manifesto                                ║
║    main.py        — ponto de entrada                         ║
║    README.md      — documentação (opcional)                  ║
║    icon.png       — ícone 64×64 (opcional)                   ║
║    ui.py          — UI própria do plugin (opcional)          ║
╚══════════════════════════════════════════════════════════════╝

Manifesto mínimo (plugin.json):
{
    "id":          "meu_plugin",
    "name":        "Meu Plugin",
    "version":     "1.0.0",
    "author":      "Fulano",
    "description": "O que faz",
    "permissions": ["process_list", "network"],
    "entry":       "main.py",
    "conditions":  [],
    "actions":     [],
    "parameters":  [],
    "ui":          {}
}

Permissões suportadas:
    process_list  — listar processos (psutil)
    network       — acesso à internet
    filesystem    — leitura de arquivos locais
    notifications — exibir notificações
    system_action — executar ações de sistema (requer confirmação extra)

Tipos de parâmetro (campo "parameters" no manifesto):
    string        — texto simples
    integer       — número inteiro (min/max opcionais)
    float         — número decimal (min/max opcionais)
    boolean       — verdadeiro/falso
    choice        — seleção única (campo "choices" obrigatório)
    multichoice   — seleção múltipla (campo "choices" obrigatório)
    password      — campo senha (mascarado)
    file          — seletor de arquivo
    folder        — seletor de pasta

UI integrada (campo "ui" no manifesto):
    type          — "tab" (aba na janela principal) ou "window" (janela separada)
    tab_name      — nome da aba (apenas type=tab)
    icon          — emoji/ícone
    entry         — arquivo Python com a classe de UI
    class         — nome da classe de UI
    title         — título da janela (apenas type=window)
    width/height  — tamanho da janela (apenas type=window)
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("PluginManager")

# ── Parâmetro — tipos suportados ──────────────────────────────────────────────
PARAM_TYPES = ("string", "integer", "float", "boolean",
               "choice", "multichoice", "password", "file", "folder")

# ── Diretórios ─────────────────────────────────────────────────────────────────
_BASE_DIR    = Path.home() / ".shutdown_timer"
_PLUGINS_DIR = _BASE_DIR / "plugins"
_STORE_CACHE = _BASE_DIR / "plugin_store_cache.json"

# ── Catálogo simulado da "loja" ────────────────────────────────────────────────
STORE_CATALOG: List[Dict] = [
    {
        "id": "battery_guard",
        "name": "Battery Guard",
        "author": "Community",
        "version": "1.2.0",
        "description": "Desliga quando bateria < X% — ideal para notebooks.",
        "category": "Condição",
        "stars": 4.8,
        "downloads": 1240,
        "permissions": ["process_list"],
        "tags": ["bateria", "notebook", "energia"],
    },
    {
        "id": "temperature_watch",
        "name": "Temperature Watch",
        "author": "ThermalDev",
        "version": "0.9.5",
        "description": "Monitora temperatura da CPU via WMI e pausa timer se ultrapassar limiar.",
        "category": "Condição",
        "stars": 4.5,
        "downloads": 870,
        "permissions": ["process_list"],
        "tags": ["temperatura", "cpu", "proteção"],
    },
    {
        "id": "discord_busy",
        "name": "Discord Busy",
        "author": "GamerStudio",
        "version": "2.0.1",
        "description": "Pausa o timer enquanto você está em chamada de voz no Discord.",
        "category": "Apresentação",
        "stars": 4.9,
        "downloads": 3100,
        "permissions": ["process_list"],
        "tags": ["discord", "chamada", "gaming"],
    },
    {
        "id": "work_hours",
        "name": "Work Hours Only",
        "author": "ProdDev",
        "version": "1.1.0",
        "description": "Bloqueia agendamentos fora do horário de trabalho configurado.",
        "category": "Agendamento",
        "stars": 4.3,
        "downloads": 560,
        "permissions": [],
        "tags": ["trabalho", "horário", "bloqueio"],
    },
    {
        "id": "web_notify",
        "name": "Web Notify",
        "author": "NetDev",
        "version": "1.0.2",
        "description": "Envia notificação HTTP/webhook ao executar ação de desligamento.",
        "category": "Notificação",
        "stars": 4.1,
        "downloads": 400,
        "permissions": ["network", "notifications"],
        "tags": ["webhook", "api", "integração"],
    },
    {
        "id": "calendar_sync_plus",
        "name": "Calendar Sync+",
        "author": "CalDev",
        "version": "1.3.0",
        "description": "Integração avançada com Outlook e Calendário do Windows.",
        "category": "Calendário",
        "stars": 4.6,
        "downloads": 780,
        "permissions": ["filesystem", "network"],
        "tags": ["outlook", "calendário", "office"],
    },
    {
        "id": "web_dashboard",
        "name": "Web Dashboard",
        "author": "Community",
        "version": "1.0.0",
        "description": "Servidor HTTP local com dashboard responsivo para monitorar e controlar o timer remotamente via navegador (celular, tablet, outro PC na mesma rede Wi-Fi). Sem dependências externas.",
        "category": "Utilitário",
        "stars": 4.7,
        "downloads": 920,
        "permissions": ["network", "notifications"],
        "tags": ["web", "dashboard", "remoto", "celular", "http", "wifi"],
    },
]

STORE_CATEGORIES = ["Todos", "Condição", "Apresentação", "Agendamento",
                    "Notificação", "Calendário", "Utilitário"]

PERMISSION_LABELS = {
    "process_list":  ("🔍 Lista de Processos",  "Lê a lista de processos em execução"),
    "network":       ("🌐 Rede",                "Acessa a internet"),
    "filesystem":    ("📂 Sistema de Arquivos", "Lê/escreve arquivos locais"),
    "notifications": ("🔔 Notificações",        "Exibe notificações ao usuário"),
    "system_action": ("⚡ Ações de Sistema",     "Executa desligamento/reinício (alto risco)"),
}


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN API — interface controlada que os plugins recebem
# ══════════════════════════════════════════════════════════════════════════════

class PluginAPI:
    """
    Interface controlada exposta a cada plugin.

    Acesso via ``on_load(api)`` no main.py do plugin:

        def on_load(api):
            api.log("Carregado!")
            threshold = api.get_config("threshold_celsius")
            api.register_condition("is_hot", check_temp)
    """

    def __init__(self, plugin_id: str, manager: "PluginManager"):
        self._plugin_id = plugin_id
        self._manager   = manager
        self._conditions: Dict[str, Callable] = {}
        self._actions:    Dict[str, Callable] = {}
        self._lock = threading.Lock()

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, message: str) -> None:
        """Registra mensagem no log de plugins."""
        self._manager._log(self._plugin_id, message)

    # ── Configuração do plugin ────────────────────────────────────────────────

    def get_config(self, param_id: str = None) -> Any:
        """
        Obtém configuração do plugin.

        ``param_id=None`` → retorna dict completo de configurações.
        """
        return self._manager.get_plugin_config(self._plugin_id, param_id)

    def set_config(self, param_id: str, value: Any) -> None:
        """Persiste um único parâmetro de configuração."""
        current = self._manager.get_plugin_config(self._plugin_id) or {}
        current[param_id] = value
        self._manager.set_plugin_config(self._plugin_id, current)

    # ── Registro de condições e ações ─────────────────────────────────────────

    def register_condition(self, name: str,
                           func: Callable[[Dict], Tuple[bool, str]]) -> None:
        """Registra uma função de condição chamável pelo sistema."""
        with self._lock:
            self._conditions[name] = func
        self._manager._log(self._plugin_id,
                           f"Condição registrada: {name}")

    def register_action(self, name: str,
                        func: Callable[[], None]) -> None:
        """Registra uma ação personalizada."""
        with self._lock:
            self._actions[name] = func
        self._manager._log(self._plugin_id,
                           f"Ação registrada: {name}")

    def get_registered_conditions(self) -> Dict[str, Callable]:
        with self._lock:
            return dict(self._conditions)

    # ── Estatísticas do sistema ───────────────────────────────────────────────

    def get_system_stats(self) -> dict:
        """Retorna snapshot de CPU, RAM, rede e idle."""
        try:
            import psutil  # type: ignore[import]
            cpu    = psutil.cpu_percent(interval=0.1)
            mem    = psutil.virtual_memory()
            net    = psutil.net_io_counters()
            return {
                "cpu_percent":  cpu,
                "mem_percent":  mem.percent,
                "mem_used_mb":  round(mem.used / 1024 / 1024, 1),
                "net_bytes_sent": net.bytes_sent,
                "net_bytes_recv": net.bytes_recv,
            }
        except Exception as e:
            return {"error": str(e)}

    def get_cpu_temperature(self) -> float:
        """
        Retorna a temperatura mais alta da CPU disponível no sistema.
        Tenta psutil primeiro (Linux/macOS/Windows), depois WMI (Windows).
        Retorna -1.0 se nenhum sensor estiver disponível.
        """
        try:
            import psutil  # type: ignore[import]
            temps = psutil.sensors_temperatures()
            if temps:
                for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz",
                            "zenpower", "it8", "nct6775"):
                    if key in temps and temps[key]:
                        return float(max(e.current for e in temps[key]))
                for entries in temps.values():
                    if entries:
                        return float(max(e.current for e in entries))
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                import wmi  # type: ignore[import]
                w = wmi.WMI(namespace=r"root\wmi")
                for item in w.MSAcpi_ThermalZoneTemperature():
                    celsius = (item.CurrentTemperature / 10.0) - 273.15
                    if 0 < celsius < 200:
                        return celsius
            except Exception:
                pass

        return -1.0

    # ── Notificações ─────────────────────────────────────────────────────────

    def show_notification(self, title: str, message: str) -> None:
        """Exibe notificação nativa ao usuário."""
        try:
            from plyer import notification as _n  # type: ignore[import]
            _n.notify(title=title, message=message,
                      app_name="ShutdownTimer", timeout=5)
            return
        except Exception:
            pass
        try:
            import tkinter.messagebox as _mb
            _mb.showinfo(title, message)
        except Exception:
            pass

    # ── Ações de sistema ──────────────────────────────────────────────────────

    def execute_action(self, action: str) -> None:
        """
        Executa ação no temporizador ou no sistema.

        Ações suportadas: ``pause_timer``, ``resume_timer``,
        ``cancel_timer``, ``shutdown``, ``suspend``, ``reboot``, ``lock``.
        """
        app = getattr(self._manager, "_app", None)
        if app is None:
            self._manager._log(self._plugin_id,
                                f"execute_action({action}): app não disponível")
            return
        try:
            after = app.root.after
            if action == "pause_timer":
                after(0, lambda: app._pause_resume()
                      if app.engine.state.running
                      and not app.engine.state.paused else None)
            elif action == "resume_timer":
                after(0, lambda: app._pause_resume()
                      if app.engine.state.paused else None)
            elif action == "cancel_timer":
                after(0, app._cancel)
            elif action in ("shutdown", "suspend", "reboot", "lock"):
                # system_action requer permissão declarada
                perms = self._manager._loaded.get(
                    self._plugin_id, {}).get("permissions", [])
                if "system_action" not in perms:
                    self.log(f"execute_action({action}): permissão "
                             f"'system_action' não declarada — bloqueado")
                    return
                from core.system_controller import SystemController  # type: ignore[import]
                threading.Thread(
                    target=SystemController.execute,
                    args=(action,), daemon=True).start()
            else:
                self.log(f"execute_action: ação desconhecida '{action}'")
        except Exception as e:
            self._manager._log(self._plugin_id,
                                f"execute_action({action}): {e}")

    # ── Estado do timer ───────────────────────────────────────────────────────

    def get_timer_state(self) -> dict:
        """Retorna estado atual do timer."""
        app = getattr(self._manager, "_app", None)
        if app is None:
            return {}
        s = app.engine.state
        return {
            "running":   s.running,
            "paused":    s.paused,
            "remaining": s.remaining,
            "total":     s.total_seconds,
            "action":    s.action,
        }

    # ── UI helpers ────────────────────────────────────────────────────────────

    def add_ui_element(self, parent: Any, element: dict) -> Any:
        """
        Adiciona um elemento de UI simples ao container ``parent``.

        ``element`` — dict com ``type`` e opções:
          ``{"type": "label",  "text": "Olá mundo!"}``
          ``{"type": "button", "text": "Clique", "command": fn}``
          ``{"type": "entry",  "variable": tk_var}``
        """
        try:
            import customtkinter as ctk  # type: ignore[import]
            etype = element.get("type", "label")
            if etype == "label":
                w = ctk.CTkLabel(parent, text=element.get("text", ""))
                w.pack(anchor="w", padx=8, pady=2)
                return w
            elif etype == "button":
                w = ctk.CTkButton(
                    parent, text=element.get("text", ""),
                    command=element.get("command"))
                w.pack(padx=8, pady=4)
                return w
            elif etype == "entry":
                w = ctk.CTkEntry(parent,
                                  textvariable=element.get("variable"))
                w.pack(fill="x", padx=8, pady=2)
                return w
        except Exception as e:
            self.log(f"add_ui_element: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN SANDBOX — execução isolada via subprocess
# ══════════════════════════════════════════════════════════════════════════════

class PluginSandbox:
    """Executa plugin em processo filho isolado com comunicação por JSON."""

    _WRAPPER = """
import sys, json, importlib.util, traceback

manifest = json.loads(sys.argv[1])
plugin_dir = sys.argv[2]
sys.path.insert(0, plugin_dir)

try:
    spec = importlib.util.spec_from_file_location(
        manifest["id"], plugin_dir + "/" + manifest.get("entry","main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = {"ok": True, "result": getattr(mod, "_plugin_result", None)}
except Exception:
    result = {"ok": False, "error": traceback.format_exc()}

print(json.dumps(result))
"""

    def __init__(self, manifest: Dict, plugin_dir: Path):
        self.manifest   = manifest
        self.plugin_dir = plugin_dir
        self._proc: Optional[subprocess.Popen] = None

    def run(self, timeout: float = 10.0) -> Dict:
        """Executa o plugin e retorna o resultado."""
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", self._WRAPPER,
                 json.dumps(self.manifest), str(self.plugin_dir)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            if stdout.strip():
                return json.loads(stdout.strip())
            return {"ok": False, "error": stderr or "Sem saída"}
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"ok": False, "error": "Timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN RUNTIME — carregamento direto (sem sandbox)
# ══════════════════════════════════════════════════════════════════════════════

class PluginRuntime:
    """Carrega plugin diretamente no processo (mais rápido, menos seguro)."""

    def __init__(self, manifest: Dict, plugin_dir: Path):
        self.manifest   = manifest
        self.plugin_dir = plugin_dir
        self._module    = None
        self._loaded    = False
        self._error     = ""

    def load(self) -> Tuple[bool, str]:
        entry = self.plugin_dir / self.manifest.get("entry", "main.py")
        if not entry.exists():
            return False, f"Arquivo não encontrado: {entry}"
        try:
            spec = importlib.util.spec_from_file_location(
                self.manifest["id"], str(entry))
            mod = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(self.plugin_dir))
            spec.loader.exec_module(mod)
            self._module = mod
            self._loaded = True
            return True, ""
        except Exception as e:
            self._error = str(e)
            return False, str(e)

    def call(self, func: str, *args, **kwargs) -> Any:
        if not self._loaded or self._module is None:
            raise RuntimeError("Plugin não carregado")
        fn = getattr(self._module, func, None)
        if fn is None:
            raise AttributeError(f"Função '{func}' não encontrada no plugin")
        return fn(*args, **kwargs)

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def module(self):
        return self._module


# ══════════════════════════════════════════════════════════════════════════════
# PLUGIN MANAGER — orquestrador principal
# ══════════════════════════════════════════════════════════════════════════════

class PluginManager:
    """
    Gerencia ciclo de vida completo dos plugins:
    descoberta, instalação, carregamento, execução e remoção.
    """

    def __init__(self, app):
        """
        app: instância de ShutdownApp (para acesso a config, callbacks, etc.)
        """
        self._app    = app
        self._config = app.config
        self._lock   = threading.Lock()

        # manifesto + runtime carregados
        self._loaded: Dict[str, Dict] = {}          # id -> manifest + runtime
        self._runtimes: Dict[str, PluginRuntime] = {}  # id -> runtime

        # fila de log para a aba de plugins
        self._log_queue: queue.Queue = queue.Queue(maxsize=500)

        # callbacks para UI
        self.on_plugin_loaded:   Optional[Callable[[str], None]] = None
        self.on_plugin_unloaded: Optional[Callable[[str], None]] = None
        self.on_plugin_error:    Optional[Callable[[str, str], None]] = None

        _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        self._auto_load()

    # ── Descoberta ─────────────────────────────────────────────────────────────

    def discover(self) -> List[Dict]:
        """Varre o diretório de plugins e retorna manifestos válidos."""
        manifests: List[Dict] = []
        for path in _PLUGINS_DIR.iterdir():
            manifest = self._read_manifest(path)
            if manifest:
                manifests.append(manifest)
        return manifests

    @staticmethod
    def _read_manifest(path: Path) -> Optional[Dict]:
        """Lê plugin.json de um diretório ou ZIP."""
        try:
            if path.is_dir():
                mf = path / "plugin.json"
                if mf.exists():
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    data["_path"] = str(path)
                    data.setdefault("_enabled", True)
                    return data
            elif path.suffix == ".zip":
                with zipfile.ZipFile(path) as zf:
                    names = zf.namelist()
                    for name in names:
                        if name.endswith("plugin.json"):
                            data = json.loads(zf.read(name))
                            data["_path"] = str(path)
                            data["_zip"]  = True
                            data.setdefault("_enabled", True)
                            return data
        except Exception as e:
            log.warning(f"[PluginMgr] read manifest {path}: {e}")
        return None

    # ── Carga / descarga ───────────────────────────────────────────────────────

    def _auto_load(self):
        """Carrega plugins habilitados na configuração."""
        cfg  = self._config.get("plugins") or {}
        enabled_ids = set(cfg.get("enabled_plugins", []))
        for manifest in self.discover():
            if manifest.get("id") in enabled_ids:
                self.load_plugin(manifest["id"])

    def load_plugin(self, plugin_id: str) -> Tuple[bool, str]:
        """Carrega e ativa um plugin pelo ID."""
        manifest = self._find_manifest(plugin_id)
        if manifest is None:
            return False, f"Plugin '{plugin_id}' não encontrado"

        with self._lock:
            if plugin_id in self._loaded:
                return True, "Já carregado"

        sandbox = (self._config.get("plugins") or {}).get(
            "sandbox_enabled", True)

        if sandbox or manifest.get("_zip"):
            ok, err = self._load_sandboxed(manifest)
        else:
            ok, err = self._load_direct(manifest)

        if ok:
            with self._lock:
                self._loaded[plugin_id] = manifest
            self._log(plugin_id, f"✅ Carregado ({manifest.get('version','')})")
            if self.on_plugin_loaded:
                self.on_plugin_loaded(plugin_id)
        else:
            self._log(plugin_id, f"❌ Erro: {err}")
            if self.on_plugin_error:
                self.on_plugin_error(plugin_id, err)

        return ok, err

    def _load_sandboxed(self, manifest: Dict) -> Tuple[bool, str]:
        """Teste inicial via sandbox (validação rápida)."""
        plugin_dir = self._extract_if_zip(manifest)
        if plugin_dir is None:
            return False, "Falha ao extrair ZIP"
        sb = PluginSandbox(manifest, plugin_dir)
        result = sb.run(timeout=5.0)
        if not result.get("ok"):
            return False, result.get("error", "Erro desconhecido")
        # Se passou na sandbox, carrega direto para uso contínuo
        return self._load_direct_path(manifest, plugin_dir)

    def _load_direct(self, manifest: Dict) -> Tuple[bool, str]:
        plugin_dir = Path(manifest["_path"])
        return self._load_direct_path(manifest, plugin_dir)

    def unload_plugin(self, plugin_id: str) -> bool:
        with self._lock:
            if plugin_id not in self._loaded:
                return False
            rt = self._runtimes.pop(plugin_id, None)
            if rt:
                try:
                    rt.call("on_unload")
                except Exception:
                    pass
            del self._loaded[plugin_id]
        self._log(plugin_id, "🔌 Descarregado")
        if self.on_plugin_unloaded:
            self.on_plugin_unloaded(plugin_id)
        return True

    def unload_all(self):
        ids = list(self._loaded.keys())
        for pid in ids:
            self.unload_plugin(pid)

    # ── Estado ─────────────────────────────────────────────────────────────────

    def is_loaded(self, plugin_id: str) -> bool:
        with self._lock:
            return plugin_id in self._loaded

    def get_loaded(self) -> List[Dict]:
        with self._lock:
            return list(self._loaded.values())

    def get_runtime(self, plugin_id: str) -> Optional[PluginRuntime]:
        with self._lock:
            return self._runtimes.get(plugin_id)

    # ── Integração com condições ────────────────────────────────────────────────

    def get_conditions_from_plugins(self) -> List[Dict]:
        """
        Retorna lista de condições fornecidas por plugins.
        Cada item: {"id", "plugin_id", "label", "description", "params_schema"}
        """
        conditions: List[Dict] = []
        with self._lock:
            for pid, manifest in self._loaded.items():
                for cond in manifest.get("conditions", []):
                    conditions.append({**cond, "plugin_id": pid})
        return conditions

    # ── Instalação ─────────────────────────────────────────────────────────────

    def install_from_path(self, path: str | Path) -> Tuple[bool, str]:
        """Instala plugin de arquivo ZIP ou pasta."""
        src = Path(path)
        if not src.exists():
            return False, "Arquivo/pasta não encontrado"

        if src.is_dir():
            dst = _PLUGINS_DIR / src.name
            if dst.exists():
                return False, "Plugin já instalado (mesmo nome de pasta)"
            try:
                import shutil
                shutil.copytree(str(src), str(dst))
                return True, f"Instalado em {dst}"
            except Exception as e:
                return False, str(e)

        if src.suffix == ".zip":
            dst = _PLUGINS_DIR / src.name
            try:
                import shutil
                shutil.copy2(str(src), str(dst))
                # Valida manifesto
                mf = self._read_manifest(dst)
                if mf is None:
                    dst.unlink()
                    return False, "ZIP inválido (plugin.json não encontrado)"
                return True, f"Instalado: {mf.get('name', src.name)}"
            except Exception as e:
                return False, str(e)

        return False, "Formato não suportado (.zip ou pasta)"

    def remove_plugin(self, plugin_id: str) -> Tuple[bool, str]:
        """Remove plugin do disco."""
        self.unload_plugin(plugin_id)
        for path in _PLUGINS_DIR.iterdir():
            mf = self._read_manifest(path)
            if mf and mf.get("id") == plugin_id:
                try:
                    import shutil
                    if path.is_dir():
                        shutil.rmtree(str(path))
                    else:
                        path.unlink()
                    return True, "Removido"
                except Exception as e:
                    return False, str(e)
        return False, "Plugin não encontrado no disco"

    # ── Configuração persistente ────────────────────────────────────────────────

    def set_enabled(self, plugin_id: str, enabled: bool):
        """Habilita/desabilita plugin e salva em config."""
        plug_cfg = dict(self._config.get("plugins") or {})
        enabled_list = list(plug_cfg.get("enabled_plugins", []))
        if enabled and plugin_id not in enabled_list:
            enabled_list.append(plugin_id)
        elif not enabled:
            enabled_list = [x for x in enabled_list if x != plugin_id]
        plug_cfg["enabled_plugins"] = enabled_list
        self._config.set("plugins", plug_cfg)
        if enabled:
            self.load_plugin(plugin_id)
        else:
            self.unload_plugin(plugin_id)

    # ── Log ────────────────────────────────────────────────────────────────────

    def _log(self, plugin_id: str, msg: str):
        from datetime import datetime
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] [{plugin_id}] {msg}"
        log.info(entry)
        try:
            self._log_queue.put_nowait(entry)
        except queue.Full:
            try:
                self._log_queue.get_nowait()
                self._log_queue.put_nowait(entry)
            except Exception:
                pass

    def get_log_entries(self, max_lines: int = 200) -> List[str]:
        entries = list(self._log_queue.queue)
        return entries[-max_lines:]


    # ── Utilitários ────────────────────────────────────────────────────────────

    def _find_manifest(self, plugin_id: str) -> Optional[Dict]:
        for manifest in self.discover():
            if manifest.get("id") == plugin_id:
                return manifest
        return None

    @staticmethod
    def _extract_if_zip(manifest: Dict) -> Optional[Path]:
        """Extrai ZIP em pasta temporária e retorna o caminho."""
        path = Path(manifest["_path"])
        if not manifest.get("_zip"):
            return path
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="st_plugin_"))
        try:
            with zipfile.ZipFile(path) as zf:
                zf.extractall(str(tmp))
            # Tenta localizar o diretório raiz do plugin dentro do ZIP
            for item in tmp.iterdir():
                if item.is_dir() and (item / "plugin.json").exists():
                    return item
            return tmp
        except Exception as e:
            log.warning(f"[PluginMgr] extract {path}: {e}")
            return None

    @staticmethod
    def get_plugins_dir() -> Path:
        return _PLUGINS_DIR

    # ── Plugin Config (parâmetros configuráveis) ───────────────────────────────

    def get_plugin_config(self, plugin_id: str,
                          param_id: str = None) -> Any:
        """
        Retorna configuração persistida de um plugin.

        Se ``param_id`` for None, retorna o dict completo.
        Se o parâmetro não tiver sido configurado, retorna o valor
        default declarado no manifesto (campo ``parameters``).
        """
        plug_cfg   = dict(self._config.get("plugins") or {})
        all_confs  = plug_cfg.get("plugin_configs", {})
        plugin_conf = all_confs.get(plugin_id, {})

        if param_id is None:
            # Mescla defaults do manifesto com valores salvos
            defaults = self._get_param_defaults(plugin_id)
            return {**defaults, **plugin_conf}

        # Valor salvo → default → None
        if param_id in plugin_conf:
            return plugin_conf[param_id]
        defaults = self._get_param_defaults(plugin_id)
        return defaults.get(param_id)

    def set_plugin_config(self, plugin_id: str, config: dict) -> None:
        """Persiste configuração completa de um plugin no config.json."""
        plug_cfg = dict(self._config.get("plugins") or {})
        all_confs = dict(plug_cfg.get("plugin_configs", {}))
        # Valida e converte valores de acordo com o schema
        validated = self._validate_params(plugin_id, config)
        all_confs[plugin_id] = validated
        plug_cfg["plugin_configs"] = all_confs
        self._config.set("plugins", plug_cfg)
        self._config.save()
        self._log(plugin_id, "Configuração salva.")
        # Notifica plugin em execução (hot reload)
        rt = self.get_runtime(plugin_id)
        if rt:
            try:
                rt.call("on_config_changed", validated)
            except AttributeError:
                pass  # on_config_changed é opcional
            except Exception as e:
                log.warning(f"[PluginMgr] on_config_changed {plugin_id}: {e}")

    def _get_param_defaults(self, plugin_id: str) -> dict:
        """Extrai valores default dos parâmetros do manifesto."""
        manifest = self._find_manifest(plugin_id)
        if manifest is None:
            # Tenta usar manifesto já carregado
            with self._lock:
                manifest = self._loaded.get(plugin_id)
        if manifest is None:
            return {}
        return {
            p["id"]: p.get("default")
            for p in manifest.get("parameters", [])
            if "id" in p
        }

    def _validate_params(self, plugin_id: str, config: dict) -> dict:
        """Valida e converte valores conforme o schema do manifesto."""
        manifest = self._find_manifest(plugin_id)
        if manifest is None:
            with self._lock:
                manifest = self._loaded.get(plugin_id)
        if manifest is None:
            return config

        schema = {p["id"]: p for p in manifest.get("parameters", [])
                  if "id" in p}
        validated = {}
        for key, value in config.items():
            spec = schema.get(key)
            if spec is None:
                validated[key] = value
                continue
            ptype = spec.get("type", "string")
            try:
                if ptype == "integer":
                    v = int(value)
                    if "min" in spec:
                        v = max(int(spec["min"]), v)
                    if "max" in spec:
                        v = min(int(spec["max"]), v)
                    validated[key] = v
                elif ptype == "float":
                    v = float(value)
                    if "min" in spec:
                        v = max(float(spec["min"]), v)
                    if "max" in spec:
                        v = min(float(spec["max"]), v)
                    validated[key] = v
                elif ptype == "boolean":
                    validated[key] = bool(value)
                elif ptype == "choice":
                    choices = spec.get("choices", [])
                    validated[key] = value if (not choices
                                               or value in choices) \
                        else spec.get("default", value)
                elif ptype == "multichoice":
                    choices = spec.get("choices", [])
                    validated[key] = [v for v in (value or [])
                                       if not choices or v in choices]
                else:
                    validated[key] = value
            except (ValueError, TypeError):
                validated[key] = spec.get("default", value)
        return validated

    def reset_plugin_config(self, plugin_id: str) -> None:
        """Restaura parâmetros do plugin para os valores default."""
        defaults = self._get_param_defaults(plugin_id)
        self.set_plugin_config(plugin_id, defaults)

    # ── Plugin UI ──────────────────────────────────────────────────────────────

    def get_plugin_ui(self, plugin_id: str) -> Optional[Dict]:
        """
        Retorna a definição de UI do plugin (campo ``ui`` do manifesto),
        ou None se o plugin não declara UI própria.
        """
        manifest = self._find_manifest(plugin_id)
        if manifest is None:
            with self._lock:
                manifest = self._loaded.get(plugin_id)
        if manifest is None:
            return None
        ui = manifest.get("ui")
        if not ui or not isinstance(ui, dict):
            return None
        return ui

    def build_plugin_ui_window(self, plugin_id: str,
                               parent: Any) -> Optional[Any]:
        """
        Instancia a classe de UI declarada no manifesto (``ui.entry`` /
        ``ui.class``) e retorna o widget raiz.

        Funciona tanto para ``ui.type == "tab"`` quanto ``"window"``.
        Retorna None se o plugin não declara UI ou se ocorrer erro.
        """
        ui_def = self.get_plugin_ui(plugin_id)
        if ui_def is None:
            return None
        # accepts both "tab" and "window" — the caller decides how to embed it

        manifest = self._find_manifest(plugin_id)
        if manifest is None:
            with self._lock:
                manifest = self._loaded.get(plugin_id)
        if manifest is None:
            return None

        plugin_dir = Path(manifest["_path"])
        entry_file = ui_def.get("entry", "ui.py")
        class_name = ui_def.get("class", "PluginUI")
        entry_path = plugin_dir / entry_file
        if not entry_path.exists():
            self._log(plugin_id,
                      f"UI entry não encontrado: {entry_path}")
            return None
        try:
            spec = importlib.util.spec_from_file_location(
                f"{plugin_id}_ui", str(entry_path))
            mod = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(plugin_dir))
            spec.loader.exec_module(mod)
            cls = getattr(mod, class_name)
            api = self.get_plugin_api(plugin_id)
            return cls(parent, api)
        except Exception as e:
            self._log(plugin_id, f"Erro ao construir UI: {e}")
            return None

    # ── Plugin API ─────────────────────────────────────────────────────────────

    def get_plugin_api(self, plugin_id: str) -> "PluginAPI":
        """Retorna (ou cria) a instância de PluginAPI para o plugin."""
        if not hasattr(self, "_apis"):
            self._apis: Dict[str, "PluginAPI"] = {}
        if plugin_id not in self._apis:
            self._apis[plugin_id] = PluginAPI(plugin_id, self)
        return self._apis[plugin_id]

    # ── Carregamento com API ───────────────────────────────────────────────────
    # Sobrescreve _load_direct_path para injetar API no on_load

    def _load_direct_path(self, manifest: Dict,
                           plugin_dir: Path) -> Tuple[bool, str]:
        rt = PluginRuntime(manifest, plugin_dir)
        ok, err = rt.load()
        if ok:
            with self._lock:
                self._runtimes[manifest["id"]] = rt
            api = self.get_plugin_api(manifest["id"])
            # Tenta chamar on_load(api) primeiro, depois on_load()
            try:
                fn = getattr(rt.module, "on_load", None)
                if fn is not None:
                    import inspect
                    if len(inspect.signature(fn).parameters) >= 1:
                        fn(api)
                    else:
                        fn()
            except AttributeError:
                pass  # on_load é opcional
            except Exception as e:
                log.warning(f"[PluginMgr] on_load {manifest['id']}: {e}")
        return ok, err

    # ── Condições de plugins com API ──────────────────────────────────────────

    def evaluate_condition(self, condition_id: str,
                            params: Dict) -> Tuple[bool, str]:
        """
        Avalia condição de plugin.

        Verifica primeiro funções registradas via ``api.register_condition()``,
        depois tenta chamar diretamente a função no módulo do plugin.
        """
        parts = condition_id.split(".", 1)
        if len(parts) < 2:
            return False, "ID de condição inválido"
        plugin_id, cond_fn = parts

        # 1. Condição registrada via API
        if hasattr(self, "_apis"):
            api = self._apis.get(plugin_id)
            if api:
                conds = api.get_registered_conditions()
                if cond_fn in conds:
                    try:
                        result = conds[cond_fn](params)
                        if isinstance(result, tuple):
                            return result
                        return bool(result), ""
                    except Exception as e:
                        return False, str(e)

        # 2. Função direta no módulo
        rt = self.get_runtime(plugin_id)
        if rt is None:
            return False, f"Plugin '{plugin_id}' não está carregado"
        try:
            result = rt.call(cond_fn, params)
            if isinstance(result, tuple):
                return result
            return bool(result), ""
        except Exception as e:
            return False, str(e)

    @staticmethod
    def get_store_catalog(category: str = "Todos",
                          query: str = "") -> List[Dict]:
        """Retorna catálogo filtrado da loja."""
        results = STORE_CATALOG
        if category and category != "Todos":
            results = [p for p in results if p.get("category") == category]
        if query:
            q = query.lower()
            results = [
                p for p in results
                if q in p.get("name", "").lower()
                or q in p.get("description", "").lower()
                or any(q in t for t in p.get("tags", []))
            ]
        return results
