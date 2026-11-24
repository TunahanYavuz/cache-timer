# cache-timer

A reusable [Agent Skill](https://agentskills.io/specification) for **Claude Code**, **OpenAI Codex**, and **Google Antigravity** that manages 5-hour rolling usage limits and prevents expensive cold-cache token spikes with cache-aware pacing timers.

## Install

Install directly using the [Skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add TunahanYavuz/cache-timer
```

Add `-g` to install globally across all projects:

```bash
npx skills add TunahanYavuz/cache-timer -g
```

### Manual Installation

Copy `skills/cache-timer/` into your agent's skills directory:

- **Claude Code:** `~/.claude/skills/cache-timer/` (or `.claude/skills/cache-timer/` per project)
- **OpenAI Codex:** `~/.codex/skills/cache-timer/`
- **Google Antigravity / other agents:** Place `skills/cache-timer/` in your configured skills directory.

## Usage

Invoke directly with the `/` slash command (Claude Code / Antigravity) or `$` command (Codex), or let the agent trigger it automatically when usage approaches 75-80%:

```text
/cache-timer
/cache-timer 78% 3h
/cache-timer 80% 2h30m codex
/cache-timer status
```

In Codex:

```text
$cache-timer 80% 2h30m codex
```

## How It Works

1. **Auto-checks quota** when the tool exposes it (`/usage` in Claude Code or Antigravity CLI, `/status` in Codex), or asks for current usage %, reset countdown, and plan type.
2. **Matches wait timers to the real Prompt Cache TTL** so pauses never expire the KV cache:
   - **Claude Code (Subscription):** 1-hour main cache TTL -> safe 20-minute default pause.
   - **Claude Code (API / Credits / Subagents):** 5-minute TTL -> caps wait at 4 minutes and warns before cache expiry.
   - **OpenAI Codex (GPT-5.6+):** 30-minute default TTL -> safe 15-18 minute pause.
   - **Google Antigravity:** Tracks Gemini vs. Claude/GPT quotas independently and suggests switching model groups when one nears exhaustion.
3. **Executes step-by-step with cache-safe hygiene** (no mid-session model switches, fast-mode toggles, or cold `/compact` calls).

## Repository Structure

```text
cache-timer/
├── LICENSE
├── README.md
└── skills/
    └── cache-timer/
        ├── SKILL.md
        ├── references/
        │   └── platform-limits-and-cache.md
        └── scripts/
            └── pace_timer.py
```

## License

MIT
