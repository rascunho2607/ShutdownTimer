"""
╔══════════════════════════════════════════════════════════════╗
║  PresentationMode Enhanced — ShutdownTimer v5.0             ║
║  Sistema completo de detecção com 6 gatilhos e pontuação    ║
╠══════════════════════════════════════════════════════════════╣
║  Gatilhos:                                                   ║
║   1. PowerPoint em modo apresentação (confiabilidade 0.95)  ║
║   2. Monitor externo conectado (0.80)                        ║
║   3. Aplicativo de videoconferência ativo (0.85)             ║
║   4. Tela cheia + sem entrada do usuário (0.65)              ║
║   5. Microfone em uso (0.70)                                 ║
║   6. Apps personalizados (configurável, padrão 0.90)         ║
╚══════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger("PresentationModeEnhanced")

IS_WINDOWS = sys.platform == "win32"

try:
    import psutil as _psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_WEIGHTS: Dict[str, float] = {
    "powerpoint":      1.00,
    "external_monitor": 0.80,
    "videoconf":       0.85,
    "fullscreen_idle": 0.65,
    "microphone":      0.70,
    "custom_apps":     0.90,
}

VIDEOCONF_PROCESSES = {
    "zoom.exe":       0.95,
    "teams.exe":      0.95,
    "slack.exe":      0.80,
    "webex.exe":      0.90,
    "skype.exe":      0.85,
    "discord.exe":    0.75,
    "meet.google.com": 0.70,
    "obs64.exe":      0.80,
    "obs32.exe":      0.80,
    "streamlabs obs.exe": 0.80,
}


# ══════════════════════════════════════════════════════════════════════════════
# RESULTADO DE GATILHO
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TriggerResult:
    trigger_id:   str
    label:        str
    active:       bool
    reliability:  float          # 0.0 – 1.0 (quão confiável é este gatilho)
    detail:       str  = ""      # texto explicativo p/ diagnóstico
    weight:       float = 1.0    # peso configurado pelo usuário


@dataclass
class DecisionResult:
    activate:       bool
    confidence:     float
    active_triggers: List[TriggerResult] = field(default_factory=list)
    all_triggers:    List[TriggerResult] = field(default_factory=list)
    reason:         str = ""


# ══════════════════════════════════════════════════════════════════════════════
# TRIGGERS — verificações individuais
# ══════════════════════════════════════════════════════════════════════════════

class PresentationTriggers:
    """
    Coletânea de verificações estáticas, cada uma retorna TriggerResult.
    """

    # ── 1. PowerPoint ──────────────────────────────────────────────────────────

    @staticmethod
    def check_powerpoint() -> TriggerResult:
        """Detecta PowerPoint em modo apresentação (tela cheia ou slideshow)."""
        tid = "powerpoint"
        label = "PowerPoint (Slideshow)"
        base_reliability = 0.95

        if not IS_WINDOWS:
            # No Linux/Mac verificamos pelo nome de processo
            return PresentationTriggers._check_process_simple(
                tid, label, {"soffice", "libreoffice"}, base_reliability)

        # Windows: verificar janela com título de apresentação
        active = False
        detail = ""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # Verificar por nome de processo E título de janela
            titles = []

            def _enum_cb(hwnd, _):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    titles.append(buf.value.lower())
                return True

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
            user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)

            slideshow_kw = ["slide show", "apresentação de slides",
                            "- powerpoint", "slideshow"]
            for t in titles:
                if any(kw in t for kw in slideshow_kw):
                    active = True
                    detail = "Janela de slideshow detectada"
                    break

            if not active and HAS_PSUTIL:
                pp_procs = {"powerpnt.exe", "soffice.exe"}
                running  = {p.name().lower() for p in _psutil.process_iter(["name"])}
                if pp_procs & running:
                    active = True
                    detail = "PowerPoint em execução"

        except Exception as e:
            detail = f"Erro: {e}"

        return TriggerResult(tid, label, active, base_reliability, detail)

    # ── 2. Monitor externo ────────────────────────────────────────────────────

    @staticmethod
    def check_external_monitor() -> TriggerResult:
        tid   = "external_monitor"
        label = "Monitor Externo"
        base  = 0.80
        active, detail = False, ""

        try:
            if IS_WINDOWS:
                SM_CMONITORS = 80
                count = ctypes.windll.user32.GetSystemMetrics(SM_CMONITORS)
                active = count > 1
                detail = f"{count} monitor(es) detectado(s)"
            else:
                # Linux: xrandr
                import subprocess
                result = subprocess.run(
                    ["xrandr", "--query"], capture_output=True, text=True, timeout=3)
                lines    = result.stdout.splitlines()
                connected = [l for l in lines if " connected" in l]
                active   = len(connected) > 1
                detail   = f"{len(connected)} monitor(es) conectado(s)"
        except Exception as e:
            detail = f"Erro: {e}"

        return TriggerResult(tid, label, active, base, detail)

    # ── 3. Videoconferência ───────────────────────────────────────────────────

    @staticmethod
    def check_videoconf() -> TriggerResult:
        tid   = "videoconf"
        label = "Videoconferência"
        base  = 0.85
        active, detail = False, ""

        if not HAS_PSUTIL:
            return TriggerResult(tid, label, False, 0.0,
                                 "psutil não disponível")
        try:
            running = {p.name().lower() for p in
                       _psutil.process_iter(["name"])}
            for proc_name, reliability in VIDEOCONF_PROCESSES.items():
                if proc_name in running:
                    active = True
                    base   = reliability
                    detail = f"{proc_name} em execução"
                    break
        except Exception as e:
            detail = f"Erro: {e}"

        return TriggerResult(tid, label, active, base, detail)

    # ── 4. Tela cheia + sem entrada ────────────────────────────────────────────

    @staticmethod
    def check_fullscreen_idle(idle_threshold_s: int = 60) -> TriggerResult:
        """Detecta app em tela cheia + sistema ocioso."""
        tid   = "fullscreen_idle"
        label = "Tela Cheia + Inatividade"
        base  = 0.65
        active, detail = False, ""

        if not IS_WINDOWS:
            return TriggerResult(tid, label, False, 0.0, "Windows apenas")

        try:
            # Verifica tela cheia
            user32 = ctypes.windll.user32
            hwnd   = user32.GetForegroundWindow()
            if hwnd:
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                sw = user32.GetSystemMetrics(0)
                sh = user32.GetSystemMetrics(1)
                is_fs = (rect.left == 0 and rect.top == 0 and
                         rect.right == sw and rect.bottom == sh)
            else:
                is_fs = False

            # Verifica idle
            idle_ms = PresentationTriggers._get_idle_ms()
            idle_s  = idle_ms // 1000

            if is_fs and idle_s >= idle_threshold_s:
                active = True
                detail = f"Tela cheia + {idle_s}s sem input"
            else:
                detail = (f"Tela cheia: {is_fs}, "
                          f"idle: {idle_s}s (limiar: {idle_threshold_s}s)")
        except Exception as e:
            detail = f"Erro: {e}"

        return TriggerResult(tid, label, active, base, detail)

    # ── 5. Microfone em uso ───────────────────────────────────────────────────

    @staticmethod
    def check_microphone() -> TriggerResult:
        tid   = "microphone"
        label = "Microfone em Uso"
        base  = 0.70
        active, detail = False, ""

        if IS_WINDOWS:
            try:
                # Windows 10+: verifica via registro de privacidade
                import winreg
                key_path = (r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                            r"\CapabilityAccessManager\ConsentStore\microphone\NonPackaged")
                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
                    # Procura por LastUsedTimeStop == 0 (em uso)
                    i = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            sub_key  = winreg.OpenKey(key, sub_name)
                            try:
                                val, _ = winreg.QueryValueEx(
                                    sub_key, "LastUsedTimeStop")
                                if val == 0:
                                    active = True
                                    detail = f"Microfone em uso: {sub_name.split('#')[-1]}"
                                    winreg.CloseKey(sub_key)
                                    break
                            except Exception:
                                pass
                            winreg.CloseKey(sub_key)
                            i += 1
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except Exception:
                    pass

                if not active:
                    # Fallback: verifica processos conhecidos que usam mic
                    mic_procs = {"zoom.exe", "teams.exe", "discord.exe",
                                 "skype.exe", "webex.exe", "obs64.exe"}
                    if HAS_PSUTIL:
                        running = {p.name().lower()
                                   for p in _psutil.process_iter(["name"])}
                        overlap = mic_procs & running
                        if overlap:
                            active = True
                            detail = f"App com mic: {', '.join(overlap)}"

            except Exception as e:
                detail = f"Erro: {e}"
        else:
            # Linux: verifica via pactl
            try:
                import subprocess
                result = subprocess.run(
                    ["pactl", "list", "sources"], capture_output=True,
                    text=True, timeout=3)
                active = "RUNNING" in result.stdout
                detail = "Fonte de áudio ativa" if active else "Sem fonte ativa"
            except Exception as e:
                detail = f"Erro: {e}"

        return TriggerResult(tid, label, active, base, detail)

    # ── 6. Apps personalizados ────────────────────────────────────────────────

    @staticmethod
    def check_custom_apps(apps: List[Dict]) -> TriggerResult:
        """
        apps: lista de {"name": "app.exe", "weight": 0.9}
        """
        tid   = "custom_apps"
        label = "Apps Personalizados"
        base  = 0.90
        active, detail = False, ""

        if not apps:
            return TriggerResult(tid, label, False, base,
                                 "Nenhum app configurado")

        if not HAS_PSUTIL:
            return TriggerResult(tid, label, False, 0.0,
                                 "psutil não disponível")

        try:
            running = {p.name().lower()
                       for p in _psutil.process_iter(["name"])}
            for app in apps:
                name = app.get("name", "").lower()
                if name and name in running:
                    base   = float(app.get("weight", 0.9))
                    active = True
                    detail = f"{name} em execução"
                    break
        except Exception as e:
            detail = f"Erro: {e}"

        return TriggerResult(tid, label, active, base, detail)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_process_simple(trigger_id: str, label: str,
                               proc_names: set,
                               reliability: float) -> TriggerResult:
        if not HAS_PSUTIL:
            return TriggerResult(trigger_id, label, False, 0.0,
                                 "psutil não disponível")
        try:
            running = {p.name().lower()
                       for p in _psutil.process_iter(["name"])}
            found   = proc_names & running
            active  = bool(found)
            detail  = f"Processo(s): {found}" if active else ""
            return TriggerResult(trigger_id, label, active,
                                 reliability, detail)
        except Exception as e:
            return TriggerResult(trigger_id, label, False,
                                 reliability, f"Erro: {e}")

    @staticmethod
    def _get_idle_ms() -> int:
        """Retorna tempo de inatividade em ms (Windows)."""
        if not IS_WINDOWS:
            return 0
        try:
            class LASTINPUT(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint),
                             ("dwTime", ctypes.c_ulong)]
            li = LASTINPUT()
            li.cbSize = ctypes.sizeof(LASTINPUT)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
            return ctypes.windll.kernel32.GetTickCount() - li.dwTime
        except Exception:
            return 0


# ══════════════════════════════════════════════════════════════════════════════
# DECIDER — motor de decisão baseado em pesos
# ══════════════════════════════════════════════════════════════════════════════

class PresentationDecider:
    """
    Avalia todos os gatilhos e decide se o modo apresentação deve ser ativado
    usando sistema de pontuação ponderada.

    Pontuação = Σ(weight_i × reliability_i) para gatilhos ativos
    Normalizada por Σ(weight_i × reliability_i) para todos os gatilhos.
    Ativa quando score normalizado >= threshold.
    """

    def __init__(self, config):
        self._config = config

    def _get_pres_config(self) -> dict:
        return self._config.get("presentation_mode") or {}

    def evaluate(self) -> DecisionResult:
        """Avalia todos os gatilhos e retorna resultado de decisão."""
        pres_cfg  = self._get_pres_config()
        triggers_en  = pres_cfg.get("triggers", {})
        user_weights = pres_cfg.get("trigger_weights", {})
        threshold    = float(pres_cfg.get("decision_threshold", 0.6))
        custom_apps  = pres_cfg.get("custom_apps", [])
        idle_thresh  = int(pres_cfg.get("fullscreen_idle_threshold_s", 60))

        all_results: List[TriggerResult] = []

        # Coleta todos os gatilhos
        if triggers_en.get("powerpoint", True):
            r = PresentationTriggers.check_powerpoint()
            r.weight = user_weights.get("powerpoint", DEFAULT_WEIGHTS["powerpoint"])
            all_results.append(r)

        if triggers_en.get("external_monitor", True):
            r = PresentationTriggers.check_external_monitor()
            r.weight = user_weights.get("external_monitor",
                                        DEFAULT_WEIGHTS["external_monitor"])
            all_results.append(r)

        if triggers_en.get("videoconf", True):
            r = PresentationTriggers.check_videoconf()
            r.weight = user_weights.get("videoconf", DEFAULT_WEIGHTS["videoconf"])
            all_results.append(r)

        if triggers_en.get("fullscreen_idle", False):
            r = PresentationTriggers.check_fullscreen_idle(idle_thresh)
            r.weight = user_weights.get("fullscreen_idle",
                                        DEFAULT_WEIGHTS["fullscreen_idle"])
            all_results.append(r)

        if triggers_en.get("microphone", False):
            r = PresentationTriggers.check_microphone()
            r.weight = user_weights.get("microphone", DEFAULT_WEIGHTS["microphone"])
            all_results.append(r)

        if custom_apps:
            r = PresentationTriggers.check_custom_apps(custom_apps)
            r.weight = user_weights.get("custom_apps",
                                        DEFAULT_WEIGHTS["custom_apps"])
            all_results.append(r)

        # Calcula pontuação
        active_results  = [r for r in all_results if r.active]
        weighted_active = sum(r.weight * r.reliability for r in active_results)
        weighted_total  = sum(r.weight * r.reliability for r in all_results)

        if weighted_total > 0:
            confidence = weighted_active / weighted_total
        else:
            confidence = 0.0

        activate = confidence >= threshold

        if not all_results:
            reason = "Nenhum gatilho habilitado"
        elif activate:
            names = [r.label for r in active_results]
            reason = f"Modo apresentação ativo: {', '.join(names)}"
        else:
            reason = (f"Confiança {confidence:.0%} < "
                      f"limiar {threshold:.0%}")

        return DecisionResult(
            activate        = activate,
            confidence      = confidence,
            active_triggers = active_results,
            all_triggers    = all_results,
            reason          = reason,
        )

    def test_single(self, trigger_id: str,
                    params: Optional[Dict] = None) -> TriggerResult:
        """Testa um único gatilho para diagnóstico."""
        params = params or {}
        if trigger_id == "powerpoint":
            return PresentationTriggers.check_powerpoint()
        if trigger_id == "external_monitor":
            return PresentationTriggers.check_external_monitor()
        if trigger_id == "videoconf":
            return PresentationTriggers.check_videoconf()
        if trigger_id == "fullscreen_idle":
            return PresentationTriggers.check_fullscreen_idle(
                params.get("idle_threshold_s", 60))
        if trigger_id == "microphone":
            return PresentationTriggers.check_microphone()
        if trigger_id == "custom_apps":
            cfg = self._get_pres_config()
            return PresentationTriggers.check_custom_apps(
                params.get("apps", cfg.get("custom_apps", [])))
        return TriggerResult(trigger_id, trigger_id, False, 0.0,
                             "Gatilho desconhecido")


# ══════════════════════════════════════════════════════════════════════════════
# PRESENTATION MODE ENHANCED — substitui a classe básica
# ══════════════════════════════════════════════════════════════════════════════

class PresentationModeEnhanced:
    """
    Versão completa do Modo Apresentação com todos os 6 gatilhos,
    motor de decisão ponderada e diagnósticos em tempo real.

    Interface compatível com a classe PresentationMode original.
    """

    POLL = 10  # segundos entre verificações

    def __init__(self, config):
        self._config  = config
        self._decider = PresentationDecider(config)
        self._thread: Optional[threading.Thread] = None
        self._stop_ev = threading.Event()
        self._active  = False
        self._lock    = threading.Lock()

        # Últimos resultados para UI de diagnóstico
        self._last_result: Optional[DecisionResult] = None

        # Callbacks
        self.on_activated:    Optional[Callable[[DecisionResult], None]] = None
        self.on_deactivated:  Optional[Callable[[], None]] = None
        self.on_result:       Optional[Callable[[DecisionResult], None]] = None

    # ── Ciclo de vida ──────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_ev.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="PresentationModeEnhanced")
        self._thread.start()

    def stop(self):
        self._stop_ev.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._active = False

    @property
    def is_enabled(self) -> bool:
        cfg = self._config.get("presentation_mode") or {}
        return bool(cfg.get("enabled", False))

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def last_result(self) -> Optional[DecisionResult]:
        return self._last_result

    # ── Loop principal ────────────────────────────────────────────────────────

    def _run(self):
        while not self._stop_ev.is_set():
            if self.is_enabled:
                try:
                    result = self._decider.evaluate()
                    self._last_result = result
                    if self.on_result:
                        self.on_result(result)
                    self._handle_state_change(result)
                except Exception as e:
                    log.warning(f"[PresentationModeEnhanced] _run: {e}")
            self._stop_ev.wait(self.POLL)

    def _handle_state_change(self, result: DecisionResult):
        with self._lock:
            was_active = self._active
            now_active = result.activate

        if now_active and not was_active:
            with self._lock:
                self._active = True
            log.info(f"[PresentationMode] ATIVADO — {result.reason}")
            if self.on_activated:
                self.on_activated(result)

        elif not now_active and was_active:
            with self._lock:
                self._active = False
            log.info("[PresentationMode] DESATIVADO")
            if self.on_deactivated:
                self.on_deactivated()

    # ── API pública ────────────────────────────────────────────────────────────

    def evaluate_now(self) -> DecisionResult:
        """Avalia imediatamente (para teste/diagnóstico)."""
        result = self._decider.evaluate()
        self._last_result = result
        return result

    def test_detection(self) -> str:
        """Retorna string de diagnóstico completo (compatibilidade)."""
        result = self.evaluate_now()
        lines = [
            f"Confiança: {result.confidence:.0%}  |  "
            f"Decisão: {'ATIVO ✅' if result.activate else 'INATIVO ⬜'}",
            f"Motivo: {result.reason}",
            "",
            "Gatilhos avaliados:",
        ]
        for r in result.all_triggers:
            status = "✅" if r.active else "⬜"
            lines.append(
                f"  {status} {r.label:30s}  "
                f"conf: {r.reliability:.0%}  peso: {r.weight:.2f}"
            )
            if r.detail:
                lines.append(f"     → {r.detail}")
        return "\n".join(lines)

    def get_status_dict(self) -> Dict:
        """Retorna estado atual como dicionário para a UI."""
        if not self._last_result:
            return {"active": False, "confidence": 0.0, "triggers": []}
        r = self._last_result
        return {
            "active":     r.activate,
            "confidence": r.confidence,
            "reason":     r.reason,
            "triggers": [
                {
                    "id":          t.trigger_id,
                    "label":       t.label,
                    "active":      t.active,
                    "reliability": t.reliability,
                    "weight":      t.weight,
                    "detail":      t.detail,
                }
                for t in r.all_triggers
            ],
        }
