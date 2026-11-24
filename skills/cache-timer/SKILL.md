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
- `/cache-timer 80% 2h30m codex` - Evaluate pacing with a specific platform preset (`claude-sub`, `claude-api`, `codex`, `antigravity`).
- `/cache-timer status` - Check current quota and prompt cache status without starting a timer.

If `$ARGUMENTS` is provided, parse usage percentage, reset time, and optional platform preset from `$ARGUMENTS` before asking the user for missing values.

## Why This Matters

Coding agents like Claude Code, OpenAI Codex, and Google Antigravity enforce 5-hour rolling usage windows (plus weekly caps). Running heavy tasks back-to-back until hitting 100% stalls the session for hours. By the time the quota resets, the server-side prompt cache (KV cache) has expired, forcing the next message to re-read the entire conversation history uncached and burn even more quota.

Pacing tasks with short timers keeps the prompt cache warm while stretching remaining quota across the reset window.

## When to Use

- The user invokes `/cache-timer` or `$cache-timer`.
- Session usage reaches 75% to 80% with more than 30 minutes remaining until quota reset.
- The user mentions Claude Code, Codex, or Antigravity hourly or 5-hour limits, quota warnings, or fast token burn.
- A multi-step refactor risks exhausting the current window before completion.

## Steps

### 1. Check Quota Status (Automatic First, Ask as Fallback)

First, check whether the active tool exposes usage telemetry automatically:

- **Claude Code:** Run or inspect `/usage` (shows session window percentage, reset countdown, and prompt cache warm status) or statusline JSON (`prompt_cache`, `current_usage`).
- **Google Antigravity CLI:** Run `/usage` (alias `/quota`) to view five-hour and weekly percentages per model group (Gemini vs. Claude/GPT).
- **OpenAI Codex CLI:** Check `/status` or the usage panel for the active 5-hour window and weekly allowance.

If automatic quota inspection is unavailable and `$ARGUMENTS` did not supply the values, ask the user three short questions:

1. What is your current usage percentage (for example, 78%)?
2. How much time remains until the limit resets (for example, 2h 45m)?
3. Are you on a subscription plan or API/usage credits? (This determines prompt cache TTL.)

### 2. Match Timer to Active Prompt Cache TTL

Read `references/platform-limits-and-cache.md` for full details. Use these safe defaults:

- **Claude Code (Subscription within plan limit):** 60-minute main conversation TTL. Safe timer: 20 to 45 minutes (default 20 minutes).
- **Claude Code (API key, usage credits, cloud provider, or subagents):** 5-minute TTL unless `promptCacheTtl` or `CLAUDE_CODE_PROMPT_CACHE_TTL` is set to `1h`. Safe timer cap: 3 to 4 minutes. Never wait 20 minutes on a 5-minute TTL.
- **OpenAI Codex (GPT-5.6+):** 30-minute default prompt cache TTL. Safe timer: 15 to 20 minutes.
- **Google Antigravity:** Treat default cache window as 15 to 20 minutes. If the Claude/GPT model group is near 80%, check whether the independent Gemini model group still has quota available.

### 3. Confirm Before Entering Pacing Mode

When usage is at or above 75% with significant time left until reset, present a brief status summary (usage %, reset countdown, cache TTL, recommended timer) and ask the user to choose:

1. **Step-by-step paced mode (Recommended):** Break remaining work into small atomic steps and wait on a cache-safe timer between steps.
2. **Checkpoint and pause cleanly:** Run a warm `/compact` or write `HANDOFF.md` now while the cache is warm, then stop until reset.
3. **Continue without pacing:** Finish the current step immediately if it is urgent and small enough to fit inside the remaining quota.

### 4. Calculate and Run the Pacing Timer

Run the bundled script to calculate the exact safe wait interval:

```bash
python3 scripts/pace_timer.py \
  --used-pct 78 \
  --reset-mins 180 \
  --platform claude-sub \
  --planned-steps 6
```

Supported `--platform` presets: `claude-sub`, `claude-api`, `codex`, `antigravity`.

Append `--sleep` to run the countdown timer directly between steps:

```bash
python3 scripts/pace_timer.py \
  --used-pct 78 \
  --reset-mins 180 \
  --platform claude-sub \
  --planned-steps 6 \
  --sleep
```

If the environment enforces short command timeouts and cannot sleep for 15-20 minutes, print the exact `resume_at` wall-clock time returned by the script and instruct the user to send a short resume message before the cache deadline.

### 5. Execute Step-by-Step With Cache-Safe Hygiene

While in paced mode, follow these rules on every turn:

- **One atomic milestone per turn:** Complete one small, verifiable edit or test run, then check quota before continuing.
- **Protect the cached prefix:** Do NOT switch models, toggle fast mode, change reasoning effort on unsupported models, or add/remove MCP servers mid-session.
- **Keep tool outputs compact:** Filter large logs with `head`, `tail`, or `rg` instead of dumping raw output into context.
- **Compact only while warm:** Never run `/compact` right after a long cold break.
- **Use Antigravity model-group escape hatch:** If the Claude/GPT group is nearly exhausted on Antigravity, offer to switch to an available Gemini model group.

## Gotchas

- **Waiting 20 minutes on a 5-minute cache destroys savings:** Verify whether Claude Code is still within subscription limits (1h TTL) or has fallen back to usage credits/API (5m TTL).
- **Never wait if remaining quota is below 5%:** At 95%+ usage with hours left, even keepalive turns can trigger a 100% lockout. Save a checkpoint to disk and pause until reset instead.
- **Subagents use shorter TTLs:** Claude Code subagents default to a 5-minute TTL even on subscriptions. Avoid spawning heavy subagents during quota-paced sessions.
- **Idle compaction:** On Claude Code 1h TTL sessions, leaving a long conversation idle can trigger automatic idle compaction unless `idleCompaction` is set to `false`.
