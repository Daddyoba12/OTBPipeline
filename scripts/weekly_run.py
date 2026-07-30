"""
OTB_Pipeline — Monday Weekly Intelligence Runner
==================================================
Chains trend_scout → weekly_review in sequence.
Run on Monday 05:30 UK before the pipeline's slot 1 fires at 09:00.

  Step 1: trend_scout   → what's working for OTHERS  (data/trend_report.json)
  Step 2: weekly_review → what's working for US       (data/pillar_weights.json)

Both files are then read live by the pipeline every slot:
  - trend_report.json    → injected into hook AI + scene AI prompts
  - pillar_weights.json  → biases pillar selection toward best performers

Run:    python scripts/weekly_run.py
        python scripts/weekly_run.py --days 14   (shorter review window)
"""

import sys, argparse
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def main(days: int = 30):
    start = datetime.now()
    print(f"\n{'#'*60}")
    print(f"  OTB PIPELINE — WEEKLY INTELLIGENCE RUN")
    print(f"  {start:%Y-%m-%d %H:%M}")
    print(f"{'#'*60}")

    # ── Step 1: Trend Scout ────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  STEP 1/2 — Trend Scout: scanning what's winning in the niche")
    print(f"{'─'*60}")
    try:
        from trend_scout import run_scout
        trend_report = run_scout()
        combined = trend_report.get("combined", {})
        rec = combined.get("recommended_this_week", "")
        print(f"\n  ✓ Trend Scout complete")
        if rec:
            print(f"  Recommendation: {rec}")
    except Exception as e:
        print(f"\n  ✗ Trend Scout failed: {e}")
        print("    Continuing to weekly review...")

    # ── Step 2: Weekly Review ──────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  STEP 2/2 — Weekly Review: analysing our own performance ({days} days)")
    print(f"{'─'*60}")
    try:
        from weekly_review import run_review
        aggs = run_review(days=days)
        if aggs:
            total = sum(a.get("total_views", 0) for a in aggs.values())
            platforms = list(aggs.keys())
            print(f"\n  ✓ Weekly Review complete: {total:,} total views across {', '.join(platforms)}")
        else:
            print("\n  ✗ Weekly Review returned no data — check platform credentials")
    except Exception as e:
        print(f"\n  ✗ Weekly Review failed: {e}")

    # ── Done ───────────────────────────────────────────────────────────────────
    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{'#'*60}")
    print(f"  WEEKLY INTELLIGENCE RUN COMPLETE — {elapsed:.0f}s")
    print(f"  Pipeline will now use fresh trends + performance weights")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30, help="Days of history for weekly_review")
    args = p.parse_args()
    main(days=args.days)
