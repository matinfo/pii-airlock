# Other AI apps and SDKs

The **gateway** is a small server on your own computer. You tell your AI tool to talk to it instead of the
provider. It hides personal data on the way out and restores it on the way back.

```text
your app  ──▶  pii-airlock gateway  ──▶  AI provider
          ◀──  (restores originals) ◀──  (sees placeholders only)
```

## 1. Start it

```bash
pii-airlock proxy
```

Keep that terminal open. It listens at `http://127.0.0.1:8745` and only your own computer can reach it.

Seeing `missing httpx / starlette / uvicorn`? You installed without the gateway part.
Run `pipx inject pii-airlock 'pii-airlock[proxy]'`.

## 2. Point your tool at it

Each provider has its own address under the gateway.

| Provider | Address |
|---|---|
| OpenAI and OpenAI-compatible | `http://127.0.0.1:8745/openai` |
| Anthropic (Claude) | `http://127.0.0.1:8745/anthropic` |
| Google Gemini | `http://127.0.0.1:8745/gemini` |

### Set it once per terminal

::: code-group
```bash [macOS / Linux (bash, zsh)]
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai
```
```fish [fish]
set -x OPENAI_BASE_URL http://127.0.0.1:8745/openai
```
```powershell [Windows PowerShell]
$env:OPENAI_BASE_URL = "http://127.0.0.1:8745/openai"
```
```bat [Windows cmd.exe]
set OPENAI_BASE_URL=http://127.0.0.1:8745/openai
```
:::

Start your tool from **that same terminal window**. The setting does not reach programs started elsewhere.
To keep it permanently, add the line to your shell profile.

## Tool by tool

### Codex CLI, OpenAI SDK, LiteLLM, vLLM, Ollama front-ends

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai
```

### Anthropic SDK and tools built on it

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8745/anthropic
```

### Cursor

Open **Settings → Models**, turn on **Override OpenAI Base URL** and enter `http://127.0.0.1:8745/openai`.
Use a model that Cursor can reach through an OpenAI-compatible endpoint.

### Continue (VS Code and JetBrains)

In `~/.continue/config.json`, add `apiBase` to the model:

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

### Google Gemini (Python SDK)

```python
from google import genai
from google.genai.types import HttpOptions

client = genai.Client(
    api_key="...",
    http_options=HttpOptions(base_url="http://127.0.0.1:8745/gemini"),
)
```

## Is it safe to point my app at plain `http`?

Yes here, because the traffic never leaves your computer. Your app talks to `localhost`.
The gateway then makes the real, encrypted `https` call to the provider. There are no certificates to install,
and your API key is passed through without being stored or logged.

## What happens to unknown requests

If the gateway does not know how to clean a request, it **refuses** rather than sending it on.
That covers file uploads, audio and other unfamiliar endpoints. You will see an error such as 403 or 400.
This is the safe default. If you are sure a path never carries personal data, list it under `passthrough_paths`
in [Settings](/reference/settings).

## What is not cleaned

- Text in chat, completion, embedding and token-count requests: **cleaned**, including tool results and tool arguments.
- Images, audio and attached files inside a request: **sent as they are**.

## Check it

Send a message containing a fake name and email. Your tool should show them normally.
The provider's logs should show placeholders. See [Check that it works](/guide/check-it-works).
