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
pipx inject pii-airlock 'pii-airlock[proxy]'
pii-airlock proxy            # http://127.0.0.1:8745  (127.0.0.1 only by default)
```

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
| PII you type in a prompt | `UserPromptSubmit` |
| PII in a file Claude reads | `PreToolUse` |
| PII in a shell command Claude runs | `PreToolUse` |

> You *can* also route Claude Code's API traffic through the gateway with
> `ANTHROPIC_BASE_URL`, but tool-call arguments aren't restored, which can affect
> agentic runs. Prefer hooks for Claude Code; use the gateway for chat clients.

### Codex CLI / OpenAI SDK / OpenAI-compatible tools

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai
```

Works with the official OpenAI SDKs, the Codex CLI, `litellm` (`api_base=...`),
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
# dashboard / logs: you should see <EMAIL_ADDRESS_1>, not the real value, while
# your client still shows the real value in the answer.
```
