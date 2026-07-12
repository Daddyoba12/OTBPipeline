"""
Post-rerun monitor — launched by do_rerun() in telegram_commander.py.

Usage: python _rerun_monitor.py <slot> <pipeline_pid>

Waits for the pipeline process to finish, then checks the crash log for new
errors. If found, launches claude --dangerously-skip-permissions -p "..." to
diagnose and fix, and sends a Telegram status update.
"""

import json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DATA, BASE

PYTHON   = sys.executable
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

CRASH_LOG = DATA / "pipeline_crash.log"
STEP_FILE = DATA / "pipeline_step.txt"


def _send(text: str):
    try:
        import requests
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception:
        pass


def _new_errors_since(since_ts: float) -> list[str]:
    if not CRASH_LOG.exists():
        return []
    errors = []
    for line in CRASH_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ts_str = line[1:line.index("]")]
            ts = datetime.fromisoformat(ts_str).timestamp()
            if ts >= since_ts and "UNHANDLED" in line or "SyntaxError" in line or "Traceback" in line:
                errors.append(line)
        except Exception:
            pass
    return errors[-10:]


def main():
    if len(sys.argv) < 3:
        print("Usage: _rerun_monitor.py <slot> <pid>")
        sys.exit(1)

    slot = sys.argv[1]
    pid  = int(sys.argv[2])
    start_ts = time.time()

    # Wait for the pipeline process to exit (max 30 min)
    deadline = start_ts + 1800
    while time.time() < deadline:
        try:
            os.kill(pid, 0)  # signal 0 = check if alive
        except OSError:
            break  # process ended
        time.sleep(10)

    elapsed = int(time.time() - start_ts)
    errors = _new_errors_since(start_ts)

    if not errors:
        _send(f"<b>Slot {slot} rerun complete</b> ({elapsed}s) — no new errors.")
        return

    # Errors found — invoke Claude Code to diagnose and fix
    error_summary = "\n".join(errors[:5])
    _send(
        f"<b>Slot {slot} rerun encountered errors:</b>\n<code>{error_summary[:400]}</code>\n\n"
        f"Calling Claude Code to diagnose..."
    )

    prompt = (
        f"The OTB Pipeline rerun for slot {slot} just failed. "
        f"New errors in C:\\Users\\babso\\Desktop\\OTB_Pipeline\\data\\pipeline_crash.log:\n"
        f"{error_summary}\n\n"
        f"Read the relevant source files, diagnose the root cause, apply fixes, "
        f"then report what you changed in one short paragraph."
    )

    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
            cwd=str(BASE),
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
        )
        reply = (result.stdout or result.stderr or "No output from Claude.").strip()
        _send(f"<b>Claude Code diagnosis:</b>\n{reply[:1000]}")
    except FileNotFoundError:
        _send("Claude Code CLI not found in PATH. Install with: npm install -g @anthropic-ai/claude-code")
    except subprocess.TimeoutExpired:
        _send("Claude Code timed out after 5 min.")
    except Exception as e:
        _send(f"Claude Code call failed: {e}")


if __name__ == "__main__":
    main()
