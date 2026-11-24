# Platform Limits and Prompt Cache Reference

Checked against official docs on 2026-11-25. Each line says where it comes from; anything marked **unverified** has no official source and should be treated as a guess.

Core rule for every platform: a prompt cache entry lives for its TTL **after the last request that used it** and is refreshed on every hit. A timer does not keep a cache warm by itself; only a request sent before the TTL runs out does. Each such keepalive request still re-reads the whole cached context (cheap, not free).

## 1. Claude Code (Anthropic)

Sources: [Prompt caching in Claude Code](https://code.claude.com/docs/en/prompt-caching), [Settings reference](https://code.claude.com/docs/en/settings-reference), [Costs](https://code.claude.com/docs/en/costs), [Status line](https://code.claude.com/docs/en/statusline), [Tools reference](https://code.claude.com/docs/en/tools-reference), [Env vars](https://code.claude.com/docs/en/env-vars), [Errors](https://code.claude.com/docs/en/errors).

### Cache TTL
| Request | Subscription, within plan usage | Usage credits / overage, API key, cloud provider |
|---|---|---|
| Main conversation | **1 hour** | **5 minutes** |
| Everything else (subagents, forks, compaction) | **5 minutes** (server-controlled helper requests get 1 hour) | **5 minutes** |

- When a subscription goes past its included usage and continues on usage credits, Claude Code **drops the main conversation to the 5-minute TTL**.
- Override (Claude Code v2.1.242+): settings `promptCacheTtl` and `subagentPromptCacheTtl` (`"5m"` or `"1h"`), env vars `CLAUDE_CODE_PROMPT_CACHE_TTL` and `ENABLE_PROMPT_CACHING_1H`. A 1-hour TTL costs more to write on the API (see pricing).

### Seeing usage and cache state
- `/usage` shows a `Prompt cache (main)` line with hit share (v2.1.251+).
- Status line JSON: top-level `prompt_cache` (v2.1.251+) and `context_window.current_usage` (nested, not top-level).
- Limits: the docs confirm session and weekly limits shared across models, and a rolling 5-hour window plus weekly window for Team/Enterprise seats. **Unverified:** exact 5-hour/weekly durations for Pro/Max plans (no official page found).

### What breaks the cache
- Switching models (always recomputes the request).
- Toggling fast mode.
- Changing effort level, **except** on Fable 5.1+, Opus 5.5, Sonnet 5.5 and Haiku 5.5 with an API key or subscription, where the cache is kept.
- Adding/removing an MCP server **only when its tools are loaded upfront**; with tool search deferring tools, it does not invalidate the cache.
- Compacting (rewrites the history). Compact while warm, never right after a cold break.
- Idle compaction: on the 1-hour TTL, a long idle conversation can be compacted automatically. Setting `idleCompaction: false` turns this off (v2.1.290+, default `true`).

### Waiting inside Claude Code
- Foreground Bash commands time out after **2 minutes** by default (`BASH_DEFAULT_TIMEOUT_MS`), ceiling **10 minutes** by default (`BASH_MAX_TIMEOUT_MS`). A timed-out foreground command is moved to the background **unless it starts with `sleep`**. Some Claude Code hosts (for example the desktop app) refuse foreground `sleep` outright. Either way, a 20-minute foreground wait does not work.
- Use a **background** command instead (`run_in_background: true`): the agent is notified when it exits. Background commands default to a **30-minute** timeout (up to 2 hours), so keep a single background wait under ~25 minutes unless the timeout is raised.
- The `Monitor` tool can wait on a condition. Inside `/loop`, the self-paced wakeup takes a delay in seconds (`pace_timer.py --schedule` prints one, clamped to 60-3600).

### Pricing (Anthropic API)
Source: [Prompt caching (API)](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
- Cache write: **1.25x** base input for 5-minute TTL, **2x** for 1-hour TTL.
- Cache read: **0.1x** base input on most models; **0.05x** on Opus 5.5 and Sonnet 5.5; **0.025x** on Fable 5.1/5.2 and Mythos 5.1/5.2.

### Recommended pacing
- 1-hour TTL: default wait **20 minutes**, never above ~45 (and under ~25 for a single background command).
- 5-minute TTL (overage, API, subagents): wait **at most 4 minutes**; for longer gaps checkpoint instead of waiting.

## 2. OpenAI Codex

Sources: [Prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching), [API pricing](https://developers.openai.com/api/docs/pricing), [Codex pricing and limits](https://learn.chatgpt.com/docs/pricing).

### Cache TTL
- **GPT-5.6 and later:** default **30-minute minimum** cache lifetime. Responses API can request a **12-hour** lifetime (`prompt_cache_options.ttl`) at a 2.5x write rate.
- **Earlier models (in-memory cache):** cleared after about **5-10 minutes of inactivity, up to 1 hour**.
- **Extended retention:** `prompt_cache_retention: "24h"` keeps entries up to 24 hours on gpt-5.5, 5.5-pro, 5.4, 5.2, several 5.1 models, gpt-5, gpt-5-codex and gpt-4.1. Organizations without zero data retention default to `24h`; ZDR organizations default to `in_memory`. This is an API option; whether the Codex CLI uses it is **unverified**.

### Pricing
- GPT-5.6+: cache writes **1.25x** uncached input; cached reads **0.1x** on most models (**0.05x** on a few).
- Earlier models: no cache-write charge; cached input billed at **0.1x** on GPT-5.x.

### Limits
- Usage is counted per **five-hour period**; weekly limits may also apply. Run `/status` in Codex, or see chatgpt.com/codex/settings/usage. Pro plans currently have no five-hour cap.

### Recommended pacing
- GPT-5.6+: **15-20 minutes** (inside the 30-minute minimum).
- Older models: **at most 4 minutes**, or checkpoint.

## 3. Google Antigravity

Sources: [Plans](https://antigravity.google/docs/plans.md), [Gemini caching](https://aistudio.google.com/docs/caching).

- **Quotas:** paid Pro quota is "refreshed every five hours until the weekly limit is reached"; Ultra the same with the highest weekly limits; Free and Plus refresh weekly. Quota is described per model.
- **Unverified:** separate "model group" quotas (Gemini vs Claude/GPT) and a `/usage` or `/quota` CLI command. The plans page says to check quota under Settings. Forum reports say Gemini and Claude/GPT models reset on different cycles; treat that as anecdotal.
- **Cache TTL: undocumented.** Gemini implicit caching is on by default for Gemini 2.5 and newer (minimum 4,096 tokens on Gemini 4, 3.8 Flash, 3.6 Flash and 3.1 Pro Preview; 2,048 on 2.5 Flash/Pro), but no TTL is published. Explicit caching is not supported on Gemini 4.
- **Recommended pacing:** assume a short TTL (**4 minutes**) unless you measure otherwise; prefer checkpointing for long gaps. If one model's quota is nearly used up, check whether another model still has quota.
