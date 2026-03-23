"""
ConfigManager — persistência JSON, histórico, export/import, backup.
"""

from config.app_imports import (
    json, csv, uuid, copy,
    Path, datetime,
    List, Optional,
    HAS_CRYPTO,
    _Fernet, _base64, _hashlib,
)
from core.timer_engine import ScheduledAction


# ══════════════════════════════════════════════════════════════
# 5. CONFIG MANAGER
# ══════════════════════════════════════════════════════════════

class ConfigManager:
    DEFAULT: dict = {
        "last_minutes":           30,
        "last_action":            "shutdown",
        "presets":                [15, 30, 60, 120],
        "sound_warning":          False,
        "prevent_sleep":          False,
        "gamer_mode":             False,
        "gamer_idle_threshold":   30,
        "gamer_processes":        [],
        "adaptive_enabled":       False,
        "adaptive_extend_min":    10,
        "autostart":              False,
        "hotkeys_enabled":        False,
        "hotkey_start":           "ctrl+alt+s",
        "hotkey_cancel":          "ctrl+alt+x",
        "hotkey_widget":          "ctrl+alt+w",
        "mini_widget_pos":        [50, 50],
        "schedule_mode":          "countdown",
        "schedule_hour":          23,
        "schedule_minute":        30,
        "cond_enabled":           True,
        "cond_action":            "shutdown",
        "conditions":             [],
        "scheduled_actions":      [],
        "smart_mode":             False,
        "smart_cpu_threshold":    15.0,
        "smart_net_threshold_kb": 100.0,
        "smart_idle_suspend_min": 30,
        "smart_idle_shutdown_min":120,
        "smart_uptime_reboot_d":  5,
        "stats": {
            "total_completed": 0,
            "by_action": {},
            "total_minutes": 0
        },
        "history": [],
        "theme": "dark",
        "presentation_mode": {
            "enabled": False,
            "triggers": {
                "powerpoint":       True,
                "external_monitor": True,
                "videoconf":        True,
                "fullscreen_idle":  False,
                "microphone":       False,
            },
            "trigger_weights": {
                "powerpoint":       1.00,
                "external_monitor": 0.80,
                "videoconf":        0.85,
                "fullscreen_idle":  0.65,
                "microphone":       0.70,
                "custom_apps":      0.90,
            },
            "decision_threshold":           0.60,
            "fullscreen_idle_threshold_s":  60,
            "activation_delay_s":           10,
            "custom_apps": [],
            "action": "pause",
            "resume_on_exit":    True,
            "show_notifications": True,
        },
        # ── Feature 3.1: Plugins ───────────────────────────────────
        "plugins": {
            "enabled_plugins": [],
            "sandbox_enabled": True,
            "auto_update":     False,
            # Configurações individuais de cada plugin (parâmetros configuráveis)
            # Formato: {"plugin_id": {"param_id": value, ...}}
            "plugin_configs": {},
        },
        # ── Feature 3.2: Calendar Integration ─────────────────────
        "calendar_integration": {
            "enabled":              False,
            "block_on_special_day": True,
            "behavior":             "disable_auto",
            "notify":               True,
            "sources": {
                "brasil_api": {"enabled": False, "state": ""},
                "google":     {"enabled": False, "client_secret_path": "",
                               "calendar_ids": ["primary"], "any_event": True},
                "ics":        {"enabled": False, "path": "", "url": ""},
            },
            "rules": {
                "official_holidays": True,
                "busy_events":       True,
                "any_event":         False,
                "keywords":          [],
            },
        },
        # ── Feature 2.1: Voice Commands ────────────────────────────
        "voice_commands": {
            "enabled":             False,
            "wake_words":          ["ok timer", "hey shutdown", "computador"],
            "mode":                "hands_free",
            "push_to_talk_hotkey": "ctrl+alt+v",
            "tts_enabled":         True,
            "tts_voice":           "female",
            "tts_rate":            180,
            "announce_warnings":   True,
            "microphone_index":    None,
        },
        # ── Feature 2.2: Email Alerts ──────────────────────────────
        "email_alerts": {
            "enabled":           False,
            "provider":          "gmail",
            "smtp_server":       "smtp.gmail.com",
            "smtp_port":         587,
            "use_tls":           True,
            "use_ssl":           False,
            "email_from":        "",
            "email_password":    "",
            "recipients":        [],
            "events": {
                "timer_started":   True,
                "timer_finished":  True,
                "timer_cancelled": True,
                "condition_met":   True,
                "error":           True,
                "smart_action":    True,
                "daily_report":    True,
            },
            "max_per_hour":        5,
            "quiet_hours_start":   23,
            "quiet_hours_end":     7,
        },
        # ── Feature 2.3: Energy Saver ──────────────────────────────
        "energy_saver": {
            "enabled":                        False,
            "economy_plan":                   "power_saver",
            "high_performance_plan":          "high_performance",
            "economy_threshold_minutes":      30,
            "idle_threshold_minutes":         5,
            "prepare_minutes":                15,
            "restore_on_activity":            True,
            "keep_high_performance_gaming":   True,
        },
    }

    def __init__(self):
        self.path = Path.home() / ".shutdown_timer_config.json"
        self.data = self._load()

    def _load(self) -> dict:
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                return self._merge(self.DEFAULT, loaded)
        except Exception:
            pass
        import copy; return copy.deepcopy(self.DEFAULT)

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._merge(result[k], v)
            else:
                result[k] = v
        return result

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[Config] {e}")

    def get(self, key: str):
        return self.data.get(key, self.DEFAULT.get(key))

    def set(self, key: str, value):
        self.data[key] = value; self.save()

    def add_history(self, action: str, minutes: int, completed: bool):
        self.data["history"].insert(0, {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action, "minutes": minutes, "completed": completed,
        })
        self.data["history"] = self.data["history"][:50]
        if completed:
            s = self.data["stats"]
            s["total_completed"] += 1
            s["total_minutes"]   += minutes
            s["by_action"][action] = s["by_action"].get(action, 0) + 1
        self.save()

    def get_scheduled_actions(self) -> List[ScheduledAction]:
        raw = self.data.get("scheduled_actions", [])
        out = []
        for r in raw:
            try:
                out.append(ScheduledAction(
                    id       = r.get("id", str(uuid.uuid4())),
                    enabled  = r.get("enabled", True),
                    action   = r.get("action", "shutdown"),
                    days     = r.get("days", list(range(7))),
                    hour     = int(r.get("hour", 23)),
                    minute   = int(r.get("minute", 0)),
                    last_run = r.get("last_run"),
                    name     = r.get("name", "Ação programada"),
                ))
            except Exception:
                pass
        return out

    def save_scheduled_actions(self, actions: List[ScheduledAction]):
        self.data["scheduled_actions"] = [
            {"id": a.id, "enabled": a.enabled, "action": a.action,
             "days": a.days, "hour": a.hour, "minute": a.minute,
             "last_run": a.last_run, "name": a.name}
            for a in actions]
        self.save()

    def export_csv(self, path: str):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f, fieldnames=["timestamp","action","minutes","completed"])
            w.writeheader(); w.writerows(self.data["history"])

    def export_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data["history"], f, indent=2, ensure_ascii=False)

    # ── Backup / restore full config ──────────────────────

    BACKUP_FILE = Path.home() / ".shutdown_timer_backup.json"

    def export_config(self, path: str, scope: str = "full",
                      password: str = "") -> bool:
        """Export config to JSON. scope: 'full'|'settings'|'schedules'|'conditions'"""
        try:
            payload: dict = {
                "version":     "5.0",
                "export_date": datetime.now().isoformat(timespec="seconds"),
                "app_name":    "ShutdownTimer",
                "scope":       scope,
            }
            if scope in ("full", "settings"):
                exclude = {"history", "stats", "scheduled_actions", "conditions"}
                payload["settings"] = {
                    k: v for k, v in self.data.items() if k not in exclude}
            if scope in ("full", "schedules"):
                payload["scheduled_actions"] = self.data.get(
                    "scheduled_actions", [])
            if scope in ("full", "conditions"):
                payload["conditions"] = self.data.get("conditions", [])

            raw = json.dumps(payload, indent=2, ensure_ascii=False).encode()

            if password and HAS_CRYPTO:
                raw = self._encrypt_data(raw, password)
                path = path if path.endswith(".enc") else path
            with open(path, "wb") as f:
                f.write(raw)
            return True
        except Exception as e:
            print(f"[Config] export_config: {e}")
            return False

    def import_config(self, path: str, password: str = "",
                      merge: bool = False) -> tuple:
        """Import config from file. Returns (success, payload_dict|error_str)."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if password and HAS_CRYPTO:
                raw = self._decrypt_data(raw, password)
            payload = json.loads(raw.decode())

            # Auto-backup before overwriting
            self._auto_backup()

            scope = payload.get("scope", "full")
            if "settings" in payload:
                if merge:
                    self.data.update(payload["settings"])
                else:
                    for k, v in payload["settings"].items():
                        self.data[k] = v
            if "scheduled_actions" in payload:
                if merge:
                    existing_ids = {a.get("id") for a in
                                    self.data.get("scheduled_actions", [])}
                    for sa in payload["scheduled_actions"]:
                        if sa.get("id") not in existing_ids:
                            self.data.setdefault(
                                "scheduled_actions", []).append(sa)
                else:
                    self.data["scheduled_actions"] = payload["scheduled_actions"]
            if "conditions" in payload:
                if not merge:
                    self.data["conditions"] = payload["conditions"]
            self.save()
            return True, payload
        except Exception as e:
            return False, str(e)

    def preview_import(self, path: str, password: str = "") -> tuple:
        """Returns (success, payload_dict|error) without applying changes."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if password and HAS_CRYPTO:
                raw = self._decrypt_data(raw, password)
            return True, json.loads(raw.decode())
        except Exception as e:
            return False, str(e)

    def _auto_backup(self):
        try:
            with open(self.BACKUP_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] auto_backup: {e}")

    def restore_backup(self) -> bool:
        try:
            if not self.BACKUP_FILE.exists():
                return False
            with open(self.BACKUP_FILE, "r", encoding="utf-8") as f:
                self.data = self._merge(self.DEFAULT, json.load(f))
            self.save()
            return True
        except Exception as e:
            print(f"[Config] restore_backup: {e}")
            return False

    def get_backup_date(self) -> str:
        try:
            if self.BACKUP_FILE.exists():
                ts = self.BACKUP_FILE.stat().st_mtime
                return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
        return ""

    @staticmethod
    def _encrypt_data(data: bytes, password: str) -> bytes:
        key = _base64.urlsafe_b64encode(
            _hashlib.sha256(password.encode()).digest())
        return _Fernet(key).encrypt(data)

    @staticmethod
    def _decrypt_data(data: bytes, password: str) -> bytes:
        key = _base64.urlsafe_b64encode(
            _hashlib.sha256(password.encode()).digest())
        return _Fernet(key).decrypt(data)
