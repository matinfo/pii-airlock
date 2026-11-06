# GitHub Copilot

Copilot has three parts, and only some can be protected.

| Part of Copilot | Protected? | How |
|---|---|---|
| Copilot CLI and cloud agent: tool calls | Yes | Hook |
| Agent mode in VS Code: tool calls | Yes | Hook |
| Copilot Chat in VS Code with **your own model and API key** | Yes | Gateway |
| Default Copilot models, inline suggestions, prompts typed into the CLI | **No** | GitHub offers no way to intercept them |

::: warning Be clear about the gap
Inline suggestions and the default Copilot models send data through GitHub's own servers. pii-airlock cannot
sit in front of that. Do not rely on it there.
:::

## Protect tool calls (hook)

```bash
pii-airlock init
```

Run in a project, `init` installs the Copilot hook for your user (in `~/.copilot/hooks/`) when it
finds Copilot, and guards this project. The hook only acts in projects that have a `.pii-airlock/`
folder. It checks shell commands, file reads and edits, web fetches and MCP calls, and asks you
before anything containing personal data goes ahead.

The cloud agent runs on GitHub's machines and does not see your user hooks. For it, write the hook
into the repository:

```bash
pii-airlock install-hook --target copilot   # .github/hooks/pii-airlock.json
```

## Chat in VS Code

Copilot hooks cannot block what you type in chat. Instead, add your own model that goes through the gateway.

1. Start the gateway: `pii-airlock proxy`
2. In VS Code open **Manage Models** and add a custom endpoint model, using `chatLanguageModels.json`.

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
  }
]
```

For Claude models use `"apiType": "messages"` and the URL `http://127.0.0.1:8745/anthropic/v1/messages`.
Your own API key is forwarded to the provider and never logged.

## Honest status

The Copilot hook follows GitHub's published specification, but has not yet been tested against a live Copilot
session. If a tool call slips through, please
[open an issue](https://github.com/matinfo/pii-airlock/issues/new/choose) with the hook payload.
