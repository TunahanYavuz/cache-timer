#!/usr/bin/env python3
"""
Cache-aware quota pacing calculator and optional countdown timer
for Claude Code, OpenAI Codex, and Google Antigravity sessions.

Waiting inside an agent:
  Most agent shells kill or block long foreground commands (Claude Code's Bash
  tool blocks foreground `sleep`; foreground commands time out after minutes).
  Do NOT run `--sleep` in the foreground there. Instead:
    * Claude Code: run this script with `--sleep` as a BACKGROUND command
      (Bash tool `run_in_background: true`). The harness wakes the agent when
      the process exits. Or, inside `/loop`, use `--schedule` and pass the
      printed `delaySeconds` to ScheduleWakeup.
    * Plain terminal: `--sleep` in the foreground is fine.
    * Anything else: print the plan and tell the user the `resume_at` time.
"""

import argparse
import datetime
import json
import math
import sys
import time

# ttl_mins = prompt cache lifetime after the LAST request (it is refreshed on every
# cache hit). Waits are sized to stay safely inside it. Verify values against
# references/platform-limits-and-cache.md before changing them.
# host_max_wait_mins = longest single wait the host allows. Claude Code background
# commands time out after 30 minutes by default, so one wait is capped at 25.
# The effective ceiling is min(cache ceiling, host limit).
PLATFORM_PRESETS = {
    "claude-sub": {"ttl_mins": 60, "preferred_wait_mins": 20, "host_max_wait_mins": 25, "label": "Claude Code (subscription within plan usage, 1h TTL)"},
    "claude-api": {"ttl_mins": 5, "preferred_wait_mins": 4, "host_max_wait_mins": 25, "label": "Claude Code (API key / credits / overage / subagents, 5m TTL)"},
    "codex": {"ttl_mins": 30, "preferred_wait_mins": 18, "host_max_wait_mins": None, "label": "OpenAI Codex (GPT-5.6+, 30m minimum cache lifetime)"},
    "codex-legacy": {"ttl_mins": 5, "preferred_wait_mins": 4, "host_max_wait_mins": None, "label": "OpenAI Codex (pre-5.6 models, in-memory cache ~5-10m)"},
    "antigravity": {"ttl_mins": 5, "preferred_wait_mins": 4, "host_max_wait_mins": None, "label": "Google Antigravity (cache TTL undocumented, assume 5m)"},
}

# ScheduleWakeup (Claude Code /loop) clamps delays to [60, 3600] seconds.
SCHEDULE_MIN_SECS = 60
SCHEDULE_MAX_SECS = 3600


def safe_wait_ceiling(ttl_mins: int) -> int:
    """Largest wait that still leaves a margin before the cache expires."""
    if ttl_mins <= 5:
        return max(1, ttl_mins - 1)
    margin = min(15, max(2, ttl_mins // 4))
    return max(1, ttl_mins - margin)


def compute_plan(used_pct: float, reset_mins: int, ttl_mins: int, preferred_wait: int, planned_steps: int, threshold: float, host_max_wait=None):
    remaining_pct = max(0.0, 100.0 - used_pct)
    now = datetime.datetime.now()
    reset_at = now + datetime.timedelta(minutes=reset_mins)
    max_safe_wait = safe_wait_ceiling(ttl_mins)
    if host_max_wait:
        max_safe_wait = max(1, min(max_safe_wait, host_max_wait))

    base = {
        "used_pct": used_pct,
        "remaining_pct": round(remaining_pct, 1),
        "reset_mins": reset_mins,
        "reset_at": reset_at.strftime("%H:%M"),
        "cache_ttl_mins": ttl_mins,
        "max_safe_wait_mins": max_safe_wait,
        "cache_deadline": (now + datetime.timedelta(minutes=max_safe_wait)).strftime("%H:%M"),
    }

    if used_pct < threshold or reset_mins <= 15:
        return {
            **base,
            "mode": "NORMAL",
            "reason": f"Usage ({used_pct:.1f}%) is below threshold ({threshold:.1f}%) or reset is imminent ({reset_mins}m).",
            "recommended_wait_mins": 0,
        }

    if remaining_pct <= 5.0 and reset_mins > max_safe_wait:
        return {
            **base,
            "mode": "CHECKPOINT_AND_PAUSE",
            "reason": (
                f"Only {remaining_pct:.1f}% quota remains with {reset_mins}m until reset. "
                "Keepalive pacing risks the 100% lockout. Save a HANDOFF.md (or compact while the cache is still warm) and pause."
            ),
            "recommended_wait_mins": 0,
        }

    steps = max(1, planned_steps)
    ideal_spread = reset_mins / steps
    wait_mins = min(max_safe_wait, max(1, preferred_wait if ideal_spread >= preferred_wait else int(ideal_spread)))

    resume_at = now + datetime.timedelta(minutes=wait_mins)
    budget_per_step = round(remaining_pct / steps, 2)

    # A timer does NOT keep the cache warm by itself: only a request before the TTL
    # runs out does. Bridging all the way to the reset needs this many requests,
    # each one re-reading the whole cached context (cheap, but not free).
    keepalives_to_reset = max(0, math.ceil(reset_mins / max_safe_wait) - 1)

    warning = None
    if ttl_mins <= 5:
        warning = (
            f"Cache TTL is about {ttl_mins} minutes, so waits are capped at {max_safe_wait} minutes. "
            "Long pauses here mean a cold cache on resume; prefer checkpointing over waiting."
        )

    return {
        **base,
        "mode": "PACED_STEPS",
        "reason": f"Usage ({used_pct:.1f}%) reached threshold ({threshold:.1f}%) with {reset_mins}m until reset.",
        "recommended_wait_mins": wait_mins,
        "resume_at": resume_at.strftime("%H:%M"),
        "planned_steps": steps,
        "estimated_budget_per_step_pct": budget_per_step,
        "keepalives_to_reset": keepalives_to_reset,
        "schedule_delay_seconds": min(SCHEDULE_MAX_SECS, max(SCHEDULE_MIN_SECS, wait_mins * 60)),
        "warning": warning,
    }


def countdown(minutes: int) -> None:
    """Sleep in short chunks so progress is visible and Ctrl+C is responsive."""
    end = time.monotonic() + minutes * 60
    while True:
        left = end - time.monotonic()
        if left <= 0:
            break
        print(f"  {math.ceil(left / 60)} minute(s) left", flush=True)
        time.sleep(min(60, left))


def main():
    parser = argparse.ArgumentParser(description="Compute cache-safe quota pacing intervals and optionally wait.")
    parser.add_argument("--used-pct", type=float, required=True, help="Current quota usage percentage (0-100).")
    parser.add_argument("--reset-mins", type=int, required=True, help="Minutes remaining until quota reset.")
    parser.add_argument("--platform", choices=list(PLATFORM_PRESETS.keys()), default="claude-sub", help="Target platform preset.")
    parser.add_argument("--cache-ttl-mins", type=int, default=None, help="Override prompt cache TTL in minutes.")
    parser.add_argument("--preferred-wait-mins", type=int, default=None, help="Preferred pause duration in minutes.")
    parser.add_argument(
        "--max-wait-mins",
        type=int,
        default=None,
        help="Longest single wait the host allows (default: 25 for claude-* presets, none otherwise).",
    )
    parser.add_argument("--planned-steps", type=int, default=5, help="Number of remaining atomic steps.")
    parser.add_argument("--threshold", type=float, default=75.0, help="Usage %% threshold to activate pacing (default: 75).")
    parser.add_argument(
        "--sleep",
        action="store_true",
        help="Wait for the recommended duration. In Claude Code run this as a BACKGROUND command, never in the foreground.",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Print only the delay in seconds for Claude Code's ScheduleWakeup (clamped to 60-3600).",
    )
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
        host_max_wait=args.max_wait_mins if args.max_wait_mins is not None else preset["host_max_wait_mins"],
    )
    plan["platform"] = preset["label"]

    if args.schedule:
        print(plan.get("schedule_delay_seconds", 0))
        return

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"Platform:  {plan['platform']}")
        print(f"Mode:      {plan['mode']}")
        print(f"Reason:    {plan['reason']}")
        print(f"Reset at:  {plan['reset_at']} ({plan['reset_mins']}m remaining)")
        print(f"Cache TTL: {plan['cache_ttl_mins']}m (effective wait ceiling {plan['max_safe_wait_mins']}m)")
        if plan["mode"] == "PACED_STEPS":
            print(f"Recommended wait: {plan['recommended_wait_mins']}m (resume at {plan['resume_at']})")
            print(f"Budget per step:  ~{plan['estimated_budget_per_step_pct']}% across {plan['planned_steps']} steps")
            print(f"Keepalive requests needed to bridge to reset: {plan['keepalives_to_reset']}")
        if plan.get("warning"):
            print(f"WARNING:   {plan['warning']}")

    if args.sleep and plan["mode"] == "PACED_STEPS" and plan["recommended_wait_mins"] > 0:
        minutes = plan["recommended_wait_mins"]
        print(f"\nStarting cache-safe timer for {minutes} minute(s); resume by {plan['resume_at']}.", flush=True)
        try:
            countdown(minutes)
        except KeyboardInterrupt:
            print("\nTimer interrupted by user.", file=sys.stderr)
            sys.exit(130)
        print("TIMER_DONE: send the next step now, before the cache deadline.", flush=True)


if __name__ == "__main__":
    main()
