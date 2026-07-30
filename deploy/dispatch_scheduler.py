"""
Multi-client timezone-aware dispatcher.
Task Scheduler runs this every 30 minutes (or at specific times).

Each client's client_profile.json defines:
  schedule.timezone  — IANA timezone name (e.g. "Europe/London", "America/Chicago")
  schedule.active    — true/false to enable/disable
  schedule.slots     — list of {"time": "HH:MM", "pipeline_slot": N (BootHop only)}

The dispatcher converts each slot time to UTC, compares to now, and triggers
the client's pipeline if within the WINDOW_MINUTES window.

Usage:
  python deploy/dispatch_scheduler.py           # normal run
  python deploy/dispatch_scheduler.py --dry-run # show what WOULD run, no execution
  python deploy/dispatch_scheduler.py --status  # show all clients + next fire times
"""

import argparse, json, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo  # type: ignore
    except ImportError:
        print("ERROR: Python 3.9+ required, or install backports.zoneinfo")
        sys.exit(1)

BASE     = Path(__file__).parent.parent           # OTB_Pipeline root
G_INS    = BASE.parent / "g_inspired"             # sibling client folder
PYTHON   = sys.executable
WINDOW   = 30                                      # minutes either side of scheduled time (30 = catches wakeups up to 30 min late)


# ── Client registry ───────────────────────────────────────────────────────────

def _load_profile(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


CLIENTS = [
    # BootHop — laptop is primary. Oracle runs 1 hour later as failsafe.
    # After laptop runs, pipeline.py pushes pipeline_ran_today.json to Oracle
    # so Oracle skips if laptop already handled the slot.
    {
        "name":        "BootHop",
        "profile":     BASE / "client_profile.json",
        "script":      BASE / "pipeline.py",
        "cwd":         BASE,
        "slot_arg":    True,
        "env_base":    None,
    },
    # G-Inspired Automall — laptop primary, Oracle 1h later as failsafe
    {
        "name":        "G-Inspired Automall",
        "profile":     G_INS / "client_profile.json",
        "script":      G_INS / "run.py",
        "cwd":         G_INS,
        "slot_arg":    True,
        "env_base":    str(G_INS),
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_fire(slot_time: str, tz: ZoneInfo) -> datetime:
    """Return next UTC datetime when this slot_time fires in the given timezone."""
    now_local = datetime.now(tz)
    h, m      = [int(x) for x in slot_time.split(":")]
    candidate = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _in_window(now_utc: datetime, slot_time: str, tz: ZoneInfo, days: list | None = None) -> bool:
    """True if the current UTC time is within WINDOW minutes of slot_time in the given tz.
    If days is set (list of weekday ints, 0=Mon), only fires on those days."""
    now_local = now_utc.astimezone(tz)
    if days is not None and now_local.weekday() not in days:
        return False
    h, m      = [int(x) for x in slot_time.split(":")]
    sched     = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    diff_secs = abs((now_local - sched).total_seconds())
    return diff_secs <= WINDOW * 60


def _run_client(client: dict, slot: dict, dry_run: bool):
    cmd = [PYTHON, str(client["script"])]
    if client["slot_arg"] and "pipeline_slot" in slot:
        cmd += ["--slot", str(slot["pipeline_slot"])]

    env_override = {}
    if client["env_base"]:
        import os
        env_override = {**__import__("os").environ, "OTB_CLIENT_BASE": client["env_base"]}

    label = slot.get("label", slot.get("time", "?"))
    print(f"  [FIRE] {client['name']} — {label} slot → {' '.join(cmd)}")

    if not dry_run:
        subprocess.run(
            cmd,
            cwd=str(client["cwd"]),
            env=env_override if env_override else None,
        )


# ── Status display ────────────────────────────────────────────────────────────

def _show_status():
    now_utc = datetime.now(timezone.utc)
    print(f"\nDispatcher Status — UTC {now_utc.strftime('%Y-%m-%d %H:%M')}\n")
    print(f"{'CLIENT':<28} {'TZ':<22} {'SLOT':<12} {'LOCAL TIME':<12} {'NEXT UTC'}")
    print("-" * 95)

    for client in CLIENTS:
        profile  = _load_profile(client["profile"])
        schedule = profile.get("schedule", {})
        active   = schedule.get("active", False)
        tz_name  = schedule.get("timezone", "UTC")
        slots    = schedule.get("slots", [])

        if not active or not client["profile"].exists():
            print(f"  {client['name']:<26} {'(inactive)'}")
            continue

        tz = ZoneInfo(tz_name)
        _day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        for slot in slots:
            nxt      = _next_fire(slot["time"], tz)
            now_l    = datetime.now(tz)
            h, m     = [int(x) for x in slot["time"].split(":")]
            local_ts = now_l.replace(hour=h, minute=m).strftime("%a %H:%M")
            label    = slot.get("label", slot["time"])
            days     = slot.get("days")
            day_str  = "/".join(_day_names[d] for d in days) if days else "daily"
            print(f"  {client['name']:<26} {tz_name:<22} {label:<12} {local_ts:<12} {day_str:<12} {nxt.strftime('%Y-%m-%d %H:%M UTC')}")

    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OTB multi-client dispatcher")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run, no execution")
    parser.add_argument("--status",  action="store_true", help="Show client schedules + next fire times")
    args = parser.parse_args()

    if args.status:
        _show_status()
        return

    now_utc = datetime.now(timezone.utc)
    print(f"[Dispatcher] {now_utc.strftime('%Y-%m-%d %H:%M UTC')} — checking {len(CLIENTS)} clients...")

    fired = 0
    for client in CLIENTS:
        if not client["profile"].exists():
            print(f"  [{client['name']}] profile not found — skipping")
            continue

        profile  = _load_profile(client["profile"])
        schedule = profile.get("schedule", {})

        if not schedule.get("active", False):
            print(f"  [{client['name']}] inactive — skipping")
            continue

        tz_name = schedule.get("timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            print(f"  [{client['name']}] unknown timezone '{tz_name}' — skipping")
            continue

        slots = schedule.get("slots", [])
        for slot in slots:
            allowed_days = slot.get("days")  # None = every day
            if _in_window(now_utc, slot["time"], tz, days=allowed_days):
                _run_client(client, slot, dry_run=args.dry_run)
                fired += 1
                break   # only one slot per client per dispatcher run

    if fired == 0:
        print(f"  No slots due. Next check in 30 min.")
    else:
        print(f"  Done — {fired} client(s) triggered.")


if __name__ == "__main__":
    main()
