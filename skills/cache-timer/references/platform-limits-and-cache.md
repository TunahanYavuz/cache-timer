# Platform Limits and Prompt Cache Reference

Verified baseline reference for pacing long coding agent sessions without triggering cold-cache token spikes.

## 1. Claude Code (Anthropic)

- **Quota inspection:** Run `/usage` inside Claude Code (shows session window usage, reset countdown, and `Prompt cache (main)` hit ratio/warm status on v2.1.251+). Statusline scripts can also read `prompt_cache` and `current_usage` JSON fields.
- **Prompt Cache TTL defaults** ([Claude Code Prompt Caching Docs](https://code.claude.com/docs/en/prompt-caching)):
  - **Main conversation (Claude subscription within plan usage):** **1 hour**
  - **Main conversation (API key, usage credits, cloud providers):** **5 minutes**
  - **Subagents, forks, compaction ("everything else"):** **5 minutes**
  - **Important trap:** When a Claude subscription exceeds plan usage and falls back to usage credits, the main conversation TTL automatically drops from 1 hour to **5 minutes**.
- **Manual TTL override (v2.1.242+):**
  - Setting: `promptCacheTtl` (`"5m"` or `"1h"`) / `subagentPromptCacheTtl`
  - Env vars: `CLAUDE_CODE_PROMPT_CACHE_TTL=1h` or `ENABLE_PROMPT_CACHING_1H=1`
- **Cache-breaking actions to avoid mid-session:** Switching models (`/model`), toggling `/fast`, changing effort level on unsupported models, adding/removing upfront MCP servers, or running `/compact` after a cold break.
- **Recommended pacing wait:** **20 minutes** on 1h TTL (safe ceiling ~45m); **4 minutes max** on 5m TTL.

## 2. OpenAI Codex (CLI / Cloud / IDE)

- **Quota model:** 5-hour rolling usage window plus weekly allowance. Usage scales heavily with reasoning duration and model tier ([OpenAI Community Discussion](https://community.openai.com/t/understanding-the-new-codex-limit-system-after-the-april-9-update/1378768)).
- **Quota inspection:** Use `/status` or the Codex usage panel.
- **Prompt Cache TTL** ([OpenAI Prompt Caching Docs](https://developers.openai.com/api/docs/guides/prompt-caching)):
  - **GPT-5.6 and later:** **30-minute** default cache lifetime (1.25x write rate; cached reads discounted to 0.1x or 0.05x ordinary input, up to 95% off). Responses API also supports a 12-hour lifetime option.
  - **Earlier models:** Implicit caching with shorter inactivity windows.
- **Cache-breaking actions to avoid mid-session:** Changing `model`, tool definitions/ordering, `reasoning.effort` without config updates, or running context compaction unnecessarily.
- **Recommended pacing wait:** **15 to 20 minutes** (safely inside the 30-minute default TTL).

## 3. Google Antigravity (CLI / IDE)

- **Quota model:** Independent **5-hour** and **weekly** quotas tracked per model group (Gemini models vs. Claude/GPT models) ([Antigravity CLI /usage Docs](https://antigravity.google/docs/cli/commands/usage/)).
- **Quota inspection:** Run `/usage` (alias `/quota`) in Antigravity CLI to trigger a fresh quota check and display remaining percentages per model group.
- **Escape hatch:** If the Claude/GPT group approaches 80-100% with hours left until reset, you can switch to an available Gemini model group (which maintains its own separate 5-hour and weekly quota) instead of stalling.
- **Recommended pacing wait:** **15 to 20 minutes** when staying on the same session/model group.
