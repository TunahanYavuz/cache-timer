---
name: cache-timer
description: Manage 5-hour rolling usage limits and preserve prompt cache across Claude Code, OpenAI Codex, and Google Antigravity sessions. Use when an AI coding session approaches its rate limit (75-80% usage), when invoked via /cache-timer, or when pacing multi-step tasks with timers to prevent cold-cache token spikes caused by long quota lockouts.
license: MIT
user-invocable: true
argument-hint: "[usage%] [reset-time] [platform]"
---
# cache-timer

Prevent quota lockouts and expensive cold-cache token reloads during long coding sessions by checking usage limits, pacing work into atomic steps, and waiting on cache-safe timers between steps.

## Slash Command Usage

Invoke directly at any time with `/cache-timer` (Claude Code / Antigravity) or `$cache-timer` (Codex):

- `/cache-timer` - Auto-check usage or prompt for current usage %, reset time, and plan type.
- `/cache-timer 78% 3h` - Evaluate pacing immediately for 78% usage with 3 hours left until reset.
- `/cache-timer 80% 2h30m codex` - Evaluate pacing with a specific platform preset (`claude-sub`, `claude-api`, `codex`, `codex-legacy`, `antigravity`).
- `/cache-timer status` - Check current quota and prompt cache status without starting a timer.

If `$ARGUMENTS` is provided, parse usage percentage, reset time, and optional platform preset from `$ARGUMENTS` before asking the user for missing values.

## Why This Matters

Coding agents enforce rolling usage windows (5-hour sessions plus weekly caps on most plans). Running heavy tasks back-to-back until 100% stalls the session for hours. By the time the quota resets, the prompt cache has expired, so the next message re-reads the entire conversation uncached and burns even more quota.

Pacing work with short, cache-safe pauses stretches the remaining quota across the reset window while keeping the cache warm.

**A timer alone does not keep the cache warm.** A cache entry lives for its TTL after the *last request that used it*. Only a request sent before the TTL runs out refreshes it, and each such keepalive re-reads the whole cached context (cheap, not free). Size every wait so the next request lands inside the TTL.

## When to Use

- The user invokes `/cache-timer` or `$cache-timer`.
- Session usage reaches 75% to 80% with more than 30 minutes remaining until quota reset.
- The user mentions Claude Code, Codex, or Antigravity hourly or 5-hour limits, quota warnings, or fast token burn.
- A multi-step refactor risks exhausting the current window before completion.

## Steps

### 1. Check Quota Status (Automatic First, Ask as Fallback)

First, check whether the active tool exposes usage telemetry:

- **Claude Code:** `/usage` shows session and weekly usage and, on v2.1.251+, a `Prompt cache (main)` line. Status line scripts can read the top-level `prompt_cache` field and `context_window.current_usage`.
- **OpenAI Codex:** `/status` shows remaining limits (also chatgpt.com/codex/settings/usage).
- **Google Antigravity:** quota per model is shown under Settings. A CLI usage command is not officially documented; try `/usage` only if it exists in your version.

If automatic inspection is unavailable and `$ARGUMENTS` did not supply the values, ask the user three short questions:

1. What is your current usage percentage (for example, 78%)?
2. How much time remains until the limit resets (for example, 2h 45m)?
3. Are you on a subscription within its included usage, or on API key / usage credits / overage? (This decides the cache TTL.)

### 2. Match Timer to Active Prompt Cache TTL

Read `references/platform-limits-and-cache.md` for sources and details. Safe defaults:

- **Claude Code, subscription within plan usage (`claude-sub`):** main conversation TTL **1 hour**. Default wait **20 minutes**. The effective ceiling is **25 minutes**: the cache would allow ~45, but a single background wait times out at 30 minutes, and the smaller limit wins.
- **Claude Code, API key / usage credits / overage / cloud provider (`claude-api`):** TTL **5 minutes**. Wait **at most 4 minutes**. A subscription that runs past its included usage drops to this TTL automatically. Override with `promptCacheTtl: "1h"` or `CLAUDE_CODE_PROMPT_CACHE_TTL=1h` (v2.1.242+; 1-hour cache writes cost 2x instead of 1.25x on the API).
- **Claude Code subagents, forks, compaction:** TTL **5 minutes** even on a subscription (`subagentPromptCacheTtl` can raise it).
- **OpenAI Codex, GPT-5.6+ (`codex`):** **30-minute minimum** cache lifetime. Wait **15-20 minutes**.
- **OpenAI Codex, older models (`codex-legacy`):** in-memory cache cleared after **~5-10 minutes** of inactivity. Wait **at most 4 minutes**.
- **Google Antigravity (`antigravity`):** cache TTL is **not documented**. Assume a short TTL (wait **at most 4 minutes**) and prefer checkpointing for longer gaps.

### 3. Confirm Before Entering Pacing Mode

When usage is at or above 75% with significant time left until reset, present a brief status summary (usage %, reset countdown, cache TTL, recommended wait, keepalives needed to reach the reset) and ask the user to choose:

1. **Step-by-step paced mode (Recommended):** Break remaining work into small atomic steps and wait on a cache-safe timer between steps.
2. **Checkpoint and pause cleanly:** Compact or write `HANDOFF.md` now while the cache is warm, then stop until reset.
3. **Continue without pacing:** Finish the current step immediately if it is urgent and small enough to fit inside the remaining quota.

### 4. Calculate the Wait

```bash
python3 scripts/pace_timer.py --used-pct 78 --reset-mins 180 --platform claude-sub --planned-steps 6
```

Presets: `claude-sub`, `claude-api`, `codex`, `codex-legacy`, `antigravity`. Use `--cache-ttl-mins` to override the TTL and `--json` for machine-readable output. The plan includes `resume_at`, `cache_deadline` and `keepalives_to_reset`.

### 5. Wait Without Blocking the Agent

Do **not** run a long foreground `sleep` inside an agent shell:

- Claude Code foreground commands time out after 2 minutes by default (10 minutes max), and a timed-out command that starts with `sleep` is not moved to the background. Some hosts (such as the desktop app) refuse foreground `sleep` outright.
- Codex and Antigravity shells have their own command timeouts.

Use one of these instead:

- **Claude Code, background command (preferred):** run `python3 scripts/pace_timer.py ... --sleep` with `run_in_background: true`. The agent is notified when it exits (it prints `TIMER_DONE`). Background commands time out after 30 minutes by default, which is why the `claude-*` presets cap a single wait at 25 minutes (`--max-wait-mins` changes this if the timeout was raised). Every wake-up is a request that refreshes the cache, so longer gaps are bridged with repeated short waits.
- **Claude Code `/loop`:** run `python3 scripts/pace_timer.py ... --schedule` to get a delay in seconds (clamped to 60-3600) and pass it to the self-paced wakeup.
- **Plain terminal (outside the agent):** `--sleep` in the foreground is fine; it prints a countdown and `TIMER_DONE`.
- **Anything else:** print the `resume_at` time and ask the user to send a short message before the `cache_deadline`.

### 6. Execute Step-by-Step With Cache-Safe Hygiene

While in paced mode, follow these rules on every turn:

- **One atomic milestone per turn:** Complete one small, verifiable edit or test run, then check quota before continuing.
- **Protect the cached prefix:** Do not switch models or toggle fast mode. Changing effort keeps the cache only on Fable 5.1+, Opus 5.5, Sonnet 5.5 and Haiku 5.5 (API key or subscription); otherwise avoid it. Adding or removing an MCP server breaks the cache only when its tools load upfront (not with deferred tool search).
- **Keep tool outputs compact:** Filter large logs with `head`, `tail`, or `rg` instead of dumping raw output into context.
- **Compact only while warm:** Never compact right after a long cold break.
- **Antigravity escape hatch:** If one model's quota is nearly exhausted, check whether another model still has quota before stalling.

## Gotchas

- **Waiting 20 minutes on a 5-minute cache destroys the savings:** check whether Claude Code is still within subscription usage (1h TTL) or has fallen back to credits/overage (5m TTL).
- **Never wait if remaining quota is below 5%:** at 95%+ with hours left, even keepalive turns can trigger the lockout. Save a checkpoint to disk and pause until reset.
- **Subagents use 5-minute TTLs:** in Claude Code, subagents and forks get 5 minutes even on a subscription. For orchestrator-style sessions, give each subagent one narrow task and have it write a handoff file when its context grows, instead of resuming a large subagent after a long gap (a cold resume re-reads its whole history).
- **Bridging to the reset costs requests:** with a 1-hour TTL and a 3-hour gap, 25-minute waits mean about 7 keepalive requests (3 if the host allows 45-minute waits); with a 5-minute TTL you need dozens, so checkpointing is usually cheaper.
- **Idle compaction:** on the 1-hour TTL, Claude Code can compact a long idle conversation automatically (v2.1.290+). Set `idleCompaction: false` to turn it off.
