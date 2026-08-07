"""
OTB Commander Watchdog — runs every 15 min via Task Scheduler.
Restarts the commander if it has stopped.
"""
import json, os, subprocess, sys
from pathlib import Path

BASE     = Path(__file__).parent.parent
DATA     = BASE / "data"
PID_FILE = DATA / "commander.pid"
PYTHON   = sys.executable


def _commander_alive() -> bool:
    try:
        if not PID_FILE.exists():
            return False
        pid = int(PID_FILE.read_text().strip())
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def _restart():
    print("[Watchdog] Commander not running — restarting…")
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    subprocess.Popen(
        [PYTHON, str(BASE / "scripts" / "telegram_commander.py")],
        cwd=str(BASE),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    print("[Watchdog] Commander started.")


if __name__ == "__main__":
    if _commander_alive():
        print("[Watchdog] Commander is running — OK.")
    else:
        _restart()
