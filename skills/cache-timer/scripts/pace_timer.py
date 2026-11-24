#!/usr/bin/env python3
"""
Cache-aware quota pacing calculator and optional countdown timer
for Claude Code, OpenAI Codex, and Google Antigravity sessions.
"""

import argparse
import datetime
import json
import sys
import time

PLATFORM_PRESETS = {
    "claude-sub": {"ttl_mins": 60, "preferred_wait_mins": 20, "label": "Claude Code (Subscription, 1h TTL)"},
    "claude-api": {"ttl_mins": 5, "preferred_wait_mins": 4, "label": "Claude Code (API/Credits, 5m TTL)"},
    "codex": {"ttl_mins": 30, "preferred_wait_mins": 18, "label": "OpenAI Codex (GPT-5.6+, 30m TTL)"},
    "antigravity": {"ttl_mins": 30, "preferred_wait_mins": 18, "label": "Google Antigravity (30m default)"},
}


def compute_plan(used_pct: float, reset_mins: int, ttl_mins: int, preferred_wait: int, planned_steps: int, threshold: float):
    remaining_pct = max(0.0, 100.0 - used_pct)
    now = datetime.datetime.now()
    reset_at = now + datetime.timedelta(minutes=reset_mins)

    safety_buffer = 1 if ttl_mins <= 5 else min(5, max(2, ttl_mins // 6))
    max_safe_wait = max(1, ttl_mins - safety_buffer)

    if used_pct < threshold or reset_mins <= 15:
        return {
            "mode": "NORMAL",
            "reason": f"Usage ({used_pct:.1f}%) is below threshold ({threshold:.1f}%) or reset is imminent ({reset_mins}m).",
            "used_pct": used_pct,
            "remaining_pct": round(remaining_pct, 1),
            "reset_mins": reset_mins,
            "reset_at": reset_at.strftime("%H:%M"),
            "cache_ttl_mins": ttl_mins,
            "recommended_wait_mins": 0,
            "cache_deadline": (now + datetime.timedelta(minutes=max_safe_wait)).strftime("%H:%M"),
        }

    if remaining_pct <= 5.0 and reset_mins > max_safe_wait:
        return {
            "mode": "CHECKPOINT_AND_PAUSE",
            "reason": (
                f"Only {remaining_pct:.1f}% quota remains with {reset_mins}m until reset. "
                "Keepalive pacing risks hitting the 100% lockout. Run a warm /compact or save HANDOFF.md and pause."
            ),
            "used_pct": used_pct,
            "remaining_pct": round(remaining_pct, 1),
            "reset_mins": reset_mins,
            "reset_at": reset_at.strftime("%H:%M"),
            "cache_ttl_mins": ttl_mins,
            "recommended_wait_mins": 0,
            "cache_deadline": (now + datetime.timedelta(minutes=max_safe_wait)).strftime("%H:%M"),
        }

    steps = max(1, planned_steps)
    ideal_spread = reset_mins / steps
    wait_mins = int(round(min(max_safe_wait, max(1, min(preferred_wait, ideal_spread)))))
    if ideal_spread >= preferred_wait and preferred_wait <= max_safe_wait:
        wait_mins = preferred_wait

    resume_at = now + datetime.timedelta(minutes=wait_mins)
    budget_per_step = round(remaining_pct / steps, 2)

    warning = None
    if ttl_mins <= 5:
        warning = (
            "Active cache TTL is 5 minutes. Waiting 20 minutes would expire the cache. "
            "Wait is capped at 4 minutes; consider setting promptCacheTtl=1h for longer pauses."
        )

    return {
        "mode": "PACED_STEPS",
        "reason": f"Usage ({used_pct:.1f}%) reached threshold ({threshold:.1f}%) with {reset_mins}m until reset.",
        "used_pct": used_pct,
        "remaining_pct": round(remaining_pct, 1),
        "reset_mins": reset_mins,
        "reset_at": reset_at.strftime("%H:%M"),
        "cache_ttl_mins": ttl_mins,
        "max_safe_wait_mins": max_safe_wait,
        "recommended_wait_mins": wait_mins,
        "resume_at": resume_at.strftime("%H:%M"),
        "planned_steps": steps,
        "estimated_budget_per_step_pct": budget_per_step,
        "warning": warning,
    }


def main():
    parser = argparse.ArgumentParser(description="Compute cache-safe quota pacing intervals and optionally wait.")
    parser.add_argument("--used-pct", type=float, required=True, help="Current quota usage percentage (0-100).")
    parser.add_argument("--reset-mins", type=int, required=True, help="Minutes remaining until quota reset.")
    parser.add_argument("--platform", choices=list(PLATFORM_PRESETS.keys()), default="claude-sub", help="Target platform preset.")
    parser.add_argument("--cache-ttl-mins", type=int, default=None, help="Override prompt cache TTL in minutes.")
    parser.add_argument("--preferred-wait-mins", type=int, default=None, help="Preferred pause duration in minutes.")
    parser.add_argument("--planned-steps", type=int, default=5, help="Number of remaining atomic steps.")
    parser.add_argument("--threshold", type=float, default=75.0, help="Usage % threshold to activate pacing (default: 75).")
    parser.add_argument("--sleep", action="store_true", help="Actually sleep for the recommended wait duration.")
    parser.add_argument("--json", action="store_true", help="Output plan as JSON.")
    args = parser.parse_args()

    preset = PLATFORM_PRESETS[args.platform]
    ttl_mins = args.cache_ttl_mins if args.cache_ttl_mins is not None else preset["ttl_mins"]
    preferred_wait = args.preferred_wait_mins if args.preferred_wait_mins is not None else preset["preferred_wait_mins"]

    plan = compute_plan(
        used_pct=args.used_pct,
        reset_mins=args.reset_mins,
        ttl_mins=ttl_mins,
        preferred_wait=preferred_wait,
        planned_steps=args.planned_steps,
        threshold=args.threshold,
    )
    plan["platform"] = preset["label"]

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"Platform: {plan['platform']}")
        print(f"Mode:     {plan['mode']}")
        print(f"Reason:   {plan['reason']}")
        print(f"Reset at: {plan['reset_at']} ({plan['reset_mins']}m remaining)")
        print(f"Cache TTL: {plan['cache_ttl_mins']}m")
        if plan["mode"] == "PACED_STEPS":
            print(f"Recommended wait: {plan['recommended_wait_mins']}m (resume at {plan['resume_at']})")
            print(f"Budget per step:  ~{plan['estimated_budget_per_step_pct']}% across {plan['planned_steps']} steps")
        if plan.get("warning"):
            print(f"WARNING:  {plan['warning']}")

    if args.sleep and plan["mode"] == "PACED_STEPS" and plan["recommended_wait_mins"] > 0:
        wait_secs = args.recommended_wait_mins * 60
        print(f"\nStarting cache-safe timer for {plan['recommended_wait_mins']} minute(s)...", flush=True)
        try:
            time.sleep(wait_secs)
            print("Timer finished. Cache is still warm - ready for the next atomic step.")
        except KeyboardInterrupt:
            print("\nTimer interrupted by user.", file=sys.stderr)
            sys.exit(130)


if __name__ == "__main__":
    main()
