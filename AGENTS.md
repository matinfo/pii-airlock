# Integrating pii-airlock with AI coding agents

pii-airlock keeps real PII out of LLM traffic for the agents and clients you
already use. There are two integration styles:

- **Gateway** — point the client's *base URL* at the local proxy. Transparent,
  bidirectional (scrubs the request, restores the response). Best for chat-style
  and OpenAI/Anthropic/Gemini-compatible clients.
- **Hooks** — Claude Code's native guardrail events. Best for agentic, tool-using
  sessions where rewriting the payload would interfere with the tool loop.

Start the gateway once:

```bash
pipx install "pii-airlock[proxy]"
pii-airlock proxy            # http://127.0.0.1:8745  (127.0.0.1 only by default)
```

If you're already installed without extras, add gateway deps with:

```bash
pipx inject pii-airlock 'pii-airlock[proxy]'
```

Install spaCy models once:

```bash
pii-airlock download-models
```

If your pipx environment is pip-less, `download-models` prints exact
`pipx inject pii-airlock "<model-wheel-url>"` commands for each model.

If you see `No module named spacy`, run `pii-airlock download-models` from the
same shell/environment where you launch your agent client.

---

## Setting an environment variable (all platforms)

Most clients read a base-URL environment variable. Set it in the shell that
launches the client:

| Shell / OS | Command |
|---|---|
| bash / zsh (macOS, Linux) | `export OPENAI_BASE_URL=http://127.0.0.1:8745/openai` |
| fish | `set -x OPENAI_BASE_URL http://127.0.0.1:8745/openai` |
| PowerShell (Windows) | `$env:OPENAI_BASE_URL = "http://127.0.0.1:8745/openai"` |
| cmd.exe (Windows) | `set OPENAI_BASE_URL=http://127.0.0.1:8745/openai` |

Swap the variable/route for the provider (`/anthropic`, `/gemini`) as below.

---

## Per-agent setup

### Claude Code  *(recommended: hooks)*

Claude Code is agentic — it moves files and runs commands. Use the **hooks** so
PII is surfaced without disturbing the tool loop:

```bash
pii-airlock install-hook            # both events, project scope
pii-airlock install-hook --scope user
```

| Leak vector | Covered by |
|---|---|
| PII you type in a prompt (blocked by default) | `UserPromptSubmit` |
| PII in a text file Claude reads (content is scanned) | `PreToolUse` |
| PII in a shell command, edit, search, URL or MCP call | `PreToolUse` |

> Hooks stay fast: the first call starts a background daemon that keeps the models
> loaded (`pii-airlock daemon status`), so later calls take ~60 ms instead of seconds.

> Hooks cannot see tool *output* (e.g. what `cat` prints) or binary files. Detection
> failures fail closed (treated as PII) unless `hook_on_error: open`.

> You *can* also route Claude Code's API traffic through the gateway with
> `ANTHROPIC_BASE_URL`: tool results are scrubbed and tool-call arguments restored,
> so it also covers tool output the hooks can't see. Tokens are stable (a keyed hash
> of the value), so the model sees a value under the same token on every turn.

### Codex CLI / OpenAI SDK / OpenAI-compatible tools

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai
```

Covers Chat Completions *and* the Responses API (used by the Codex CLI), including
function-call arguments and outputs. Works with the official OpenAI SDKs, the Codex
CLI, `litellm` (`api_base=...`),
`vllm`/Ollama front-ends, and most "OpenAI-compatible" tools.

### Anthropic SDK

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8745/anthropic
```

### Cursor

Settings → **Models** → enable *Override OpenAI Base URL* and set it to:

```
http://127.0.0.1:8745/openai
```

(Use a model served through an OpenAI-compatible endpoint.)

### Continue.dev (VS Code / JetBrains)

In `~/.continue/config.json`, set `apiBase` on the model:

```json
{
  "models": [
    { "title": "via pii-airlock", "provider": "openai",
      "model": "gpt-4o", "apiBase": "http://127.0.0.1:8745/openai" }
  ]
}
```

### Aider

```bash
export OPENAI_API_BASE=http://127.0.0.1:8745/openai
aider
```

### Google Gemini (google-genai SDK)

```python
from google import genai
from google.genai.types import HttpOptions

client = genai.Client(
    api_key="...",
    http_options=HttpOptions(base_url="http://127.0.0.1:8745/gemini"),
)
```

> Gemini's non-SSE streaming is buffered then restored as one response. Pass
> `alt=sse` if your client supports it for live streaming.

---

### GitHub Copilot

Copilot has three surfaces; only some can be guarded.

| Surface | Covered by | Notes |
|---|---|---|
| Copilot Chat / agent mode in VS Code with **your own model** | gateway | Add a *Custom Endpoint* model (below). Needs your own API key. |
| Copilot CLI and the cloud agent: tool calls | hook | `pii-airlock install-hook --target copilot` |
| Default Copilot models, inline suggestions, prompts in the CLI | **not covered** | GitHub's backend has no base-URL setting; bring-your-own-key does not apply to inline suggestions; Copilot ignores a `userPromptSubmitted` hook's output, so prompts cannot be blocked by a hook. |

**VS Code, custom model through the gateway** (`chatLanguageModels.json`, via *Manage Models*).
Give the full URL; the gateway forwards your key and scrubs the request:

```json
[
  {
    "name": "OpenAI via pii-airlock",
    "vendor": "customendpoint",
    "apiKey": "${input:openaiKey}",
    "apiType": "chat-completions",
    "models": [{
      "id": "gpt-4o", "name": "GPT-4o", "toolCalling": true,
      "url": "http://127.0.0.1:8745/openai/v1/chat/completions",
      "maxInputTokens": 100000, "maxOutputTokens": 16000
    }]
  },
  {
    "name": "Claude via pii-airlock",
    "vendor": "customendpoint",
    "apiKey": "${input:anthropicKey}",
    "apiType": "messages",
    "models": [{
      "id": "claude-sonnet-4-6", "name": "Claude Sonnet", "toolCalling": true,
      "url": "http://127.0.0.1:8745/anthropic/v1/messages",
      "maxInputTokens": 100000, "maxOutputTokens": 16000
    }]
  }
]
```

(`apiType: responses` works too, with `http://127.0.0.1:8745/openai/v1/responses`.)

**Copilot CLI / cloud agent, hook.** `pii-airlock install-hook --target copilot` writes
`.github/hooks/pii-airlock.json` (`--scope user`: `~/.copilot/hooks/`, or `$COPILOT_HOME`).
It registers `preToolUse`; the same checks as for Claude Code apply (`hook_decision`,
`entity_actions: block`, `hook_on_error`). Copilot's tool and argument names differ from
Claude Code's, so every argument of every tool call is scanned. A hook timeout is fail-open in
Copilot, so keep the daemon on (`hook_daemon: auto`, the default) to stay well under it. The
cloud agent treats `ask` as `deny`.

> Written from GitHub's and VS Code's current docs; not yet exercised against a live Copilot
> session. If a tool call slips through, open an issue with the hook payload.

## Adding a provider

Adding a provider is one small adapter — see
[`pii_scrub/payload.py`](pii_scrub/payload.py): implement `scrub_request`
(where user text lives) and `restore_response` (where model text lives), register
it, add tests. PRs welcome (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Verify it's working

```bash
pii-airlock proxy &
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai
# Run your client with a fake email/name in the prompt, then check the provider
# dashboard / logs: you should see a token like <EMAIL_ADDRESS_093117>, not the real value, while
# your client still shows the real value in the answer.
```
