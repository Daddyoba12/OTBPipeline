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

import argparse, json, platform, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
WINDOW   = 30                                      # minutes tolerance on each machine's own side of its window

# ── Primary/backup role ─────────────────────────────────────────────────────
# Oracle (Linux, always-on) is primary — fires at the optimized time. The
# Windows laptop is backup — its window doesn't open until HEAD_START minutes
# after the nominal time, so its window never overlaps the primary's. Without
# this gap, both machines could check "already posted?", both see "no" within
# the same few seconds, and both proceed — a real duplicate-post race, not
# just a redundant check. HEAD_START guarantees Oracle's Supabase claim (if it
# ran) is long since visible before the laptop ever looks.
IS_PRIMARY = platform.system() != "Windows"
HEAD_START = 20  # minutes


# ── Client registry ───────────────────────────────────────────────────────────

def _load_profile(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


CLIENTS = [
    # BootHop — Oracle is primary (fires at the nominal time). The Windows
    # laptop is backup — its window doesn't open until HEAD_START minutes
    # later (see IS_PRIMARY above), and only fires if Oracle didn't already
    # handle the slot. pipeline.py also pushes pipeline_ran_today.json to
    # Oracle after a laptop run, as a second signal in case the window check
    # alone ever misses it.
    {
        "slug":        "boothop",
        "name":        "BootHop",
        "profile":     BASE / "client_profile.json",
        "script":      BASE / "pipeline.py",
        "cwd":         BASE,
        "slot_arg":    True,
        "env_base":    None,
    },
    # G-Inspired Automall — Oracle primary, laptop backup HEAD_START min later
    {
        "slug":        "g_inspired",
        "name":        "G-Inspired Automall",
        "profile":     G_INS / "client_profile.json",
        "script":      G_INS / "run.py",
        "cwd":         G_INS,
        "slot_arg":    True,
        "env_base":    str(G_INS),
    },
    # D818 Catering — commander-integrated pipeline (pipeline_d818.py). Slot times
    # come from client_profiles/d818.json's schedule.slots (12:30 lunch, 20:00 evening).
    {
        "slug":        "d818",
        "name":        "D818 Catering",
        "profile":     BASE / "client_profiles" / "d818.json",
        "script":      BASE / "pipeline_d818.py",
        "cwd":         BASE,
        "slot_arg":    True,
        "env_base":    None,
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
    """
    True if now falls in THIS machine's firing window for slot_time — asymmetric
    and non-overlapping between primary and backup (see IS_PRIMARY/HEAD_START above):

      Primary (Oracle): [nominal - WINDOW, nominal + HEAD_START]
      Backup (laptop):  [nominal + HEAD_START, nominal + HEAD_START + WINDOW]

    The two windows touch exactly at nominal + HEAD_START but never overlap, so
    there's no moment where both machines would consider a slot "due" at once.
    If days is set (list of weekday ints, 0=Mon), only fires on those days.
    """
    now_local = now_utc.astimezone(tz)
    if days is not None and now_local.weekday() not in days:
        return False
    h, m      = [int(x) for x in slot_time.split(":")]
    sched     = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    delta_min = (now_local - sched).total_seconds() / 60

    if IS_PRIMARY:
        return -WINDOW <= delta_min <= HEAD_START
    return HEAD_START <= delta_min <= HEAD_START + WINDOW


def _run_client(client: dict, slot: dict, dry_run: bool):
    cmd = [PYTHON, str(client["script"])]
    if client["slot_arg"] and "pipeline_slot" in slot:
        cmd += ["--slot", str(slot["pipeline_slot"])]

    env_override = {}
    if client["env_base"]:
        import os
        env_override = {**__import__("os").environ, "OTB_CLIENT_BASE": client["env_base"]}

    label = slot.get("label", slot.get("time", "?"))
    print(f"  [FIRE] {client['name']} -- {label} slot -> {' '.join(cmd)}")

    if not dry_run:
        try:
            # Hard ceiling so one wedged child (e.g. a stalled download inside
            # the render step) can't freeze the dispatcher itself — a frozen
            # dispatcher process blocks every future 30-min Task Scheduler tick
            # for every client, not just the one that hung.
            subprocess.run(
                cmd,
                cwd=str(client["cwd"]),
                env=env_override if env_override else None,
                timeout=90 * 60,
            )
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {client['name']} -- {label} slot exceeded 90m — killed, continuing dispatcher")


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
    slugs = [c["slug"] for c in CLIENTS]
    parser = argparse.ArgumentParser(description="OTB multi-client dispatcher")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run, no execution")
    parser.add_argument("--status",  action="store_true", help="Show client schedules + next fire times")
    parser.add_argument("--client",  choices=slugs, default=None,
                         help="Only check/run this one client (slug). Omit to process all clients "
                              "sequentially (legacy single-task mode). Each client has its own lock "
                              "file, so running one client's dispatcher instance can never be blocked "
                              "by another client hanging — this is what lets BootHop/G-Inspired/D818 "
                              "run as three independent scheduled tasks instead of one shared loop.")
    args = parser.parse_args()

    clients = [c for c in CLIENTS if c["slug"] == args.client] if args.client else CLIENTS

    if args.status:
        _show_status()
        return

    now_utc = datetime.now(timezone.utc)
    print(f"[Dispatcher] {now_utc.strftime('%Y-%m-%d %H:%M UTC')} — checking {len(clients)} client(s)"
          f"{f' (filtered: {args.client})' if args.client else ''}...")

    fired = 0
    for client in clients:
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
