"""
main.py — ponto de entrada do ShutdownTimer v5.0
"""

import os
import sys
import json
import time
import signal
import argparse
from pathlib import Path

import customtkinter as ctk

from core.system_controller import SystemController
from ui.ui_helpers import ACTION_LABELS
from ui.shutdown_app import ShutdownApp


def run_cli() -> bool:
    p = argparse.ArgumentParser(prog="shutdown_timer",
                                description="ShutdownTimer v4 — CLI")
    p.add_argument("--shutdown", type=int, metavar="MIN")
    p.add_argument("--suspend",  type=int, metavar="MIN")
    p.add_argument("--reboot",   type=int, metavar="MIN")
    p.add_argument("--lock",     type=int, metavar="MIN")
    p.add_argument("--cancel",   action="store_true")
    p.add_argument("--status",   action="store_true")
    p.add_argument("--gui",      action="store_true")
    args = p.parse_args()

    state_file = Path.home() / ".shutdown_timer_state.json"

    if args.cancel:
        if state_file.exists():
            st = json.loads(state_file.read_text())
            pid = st.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    state_file.unlink(missing_ok=True)
                    print("✓ Timer cancelado.")
                except ProcessLookupError:
                    print("Nenhum timer ativo.")
                    state_file.unlink(missing_ok=True)
        else:
            print("Nenhum timer ativo.")
        return True

    if args.status:
        if state_file.exists():
            st = json.loads(state_file.read_text())
            print(f"Timer ativo: {st.get('action')} — "
                  f"{st.get('remaining_min')} min restantes")
        else:
            print("Nenhum timer ativo.")
        return True

    if args.gui: return False

    action, minutes = None, None
    for act in ("shutdown", "suspend", "reboot", "lock"):
        val = getattr(args, act, None)
        if val is not None:
            action, minutes = act, val; break

    if action is None: return False

    print(f"[ShutdownTimer] {ACTION_LABELS[action]} em {minutes} min")
    remaining = minutes * 60

    def _sig(*_):
        state_file.unlink(missing_ok=True)
        print("\n✓ Cancelado."); sys.exit(0)

    signal.signal(signal.SIGTERM, _sig)
    try:
        while remaining > 0:
            h = remaining // 3600; m = (remaining % 3600) // 60; s = remaining % 60
            print(f"\r  ⏻ {h:02d}:{m:02d}:{s:02d}  ", end="", flush=True)
            state_file.write_text(json.dumps(
                {"pid": os.getpid(), "action": action,
                 "remaining_min": remaining // 60}))
            time.sleep(1); remaining -= 1
        print(f"\nExecutando: {action}...")
        state_file.unlink(missing_ok=True)
        SystemController.execute(action)
    except KeyboardInterrupt:
        state_file.unlink(missing_ok=True)
        print("\n✓ Cancelado."); sys.exit(0)
    return True


# ══════════════════════════════════════════════════════════════
# 14. ENTRY POINT
# ══════════════════════════════════════════════════════════════

def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def main():
    if len(sys.argv) > 1 and "--gui" not in sys.argv:
        if run_cli(): return

    if SystemController.PLATFORM == "Windows":
        import ctypes as _ct
        _ct.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "shutdown.timer.app")

    root = ctk.CTk()
    ico  = resource_path("icos/shutdown.ico")
    if os.path.exists(ico):
        try: root.iconbitmap(ico)
        except Exception: pass
    ShutdownApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
