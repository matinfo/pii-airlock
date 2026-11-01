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
pii-airlock install-hook --target copilot
```

This writes `.github/hooks/pii-airlock.json` in your repository. For every repository at once:

```bash
pii-airlock install-hook --target copilot --scope user
```

The hook checks shell commands, file reads and edits, web fetches and MCP calls, and asks you before anything
containing personal data goes ahead.

::: tip Already ran `install-hook` for Claude Code in this project?
Skip this step. Copilot CLI also reads the project's Claude Code settings, so it already runs the same hook.
Installing both would check every call twice. The Claude Code plugin and `--scope user` do not write that file,
so they do not reach Copilot.
:::

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
