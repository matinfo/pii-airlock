# Quick start

About five minutes. You will install pii-airlock, start it, and point one AI tool at it.

::: info Before you begin
You need a **terminal**: Terminal on macOS, a shell on Linux, or PowerShell on Windows.
You also need **Python 3.10 or newer** and **pipx**. Not sure? Run the check below.
:::

## 1. Check your tools

```bash
python3 --version     # Windows: python --version
pipx --version
```

- Python shows `3.10` or higher: good.
- `pipx: command not found`: see [Install pipx](/guide/install#install-pipx).
- Python missing or too old: install it from [python.org](https://www.python.org/downloads/).

## 2. Install

```bash
pipx install "pii-airlock[proxy]"
```

pipx puts pii-airlock in its own private space, so it never interferes with your other Python projects.
On macOS you can use Homebrew instead; see [Install, all options](/guide/install).

## 3. Run the guided setup

```bash
pii-airlock init
```

This checks the install and downloads the language models used to spot names.
The first download can take a few minutes. You only do it once.

You should end with:

```text
Setup complete.
```

If you see `Setup incomplete`, the lines above it say what to run. Fix that, then run `pii-airlock init` again.

## 4. Start the gateway

```bash
pii-airlock proxy
```

Leave this terminal window open. The gateway now listens on your computer only, at `http://127.0.0.1:8745`.
Nobody else on your network can reach it.

## 5. Point your AI tool at it

Open a **second** terminal and set the address for the tool you use. For OpenAI-style tools, including Codex:

::: code-group
```bash [macOS / Linux]
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai
```
```powershell [Windows PowerShell]
$env:OPENAI_BASE_URL = "http://127.0.0.1:8745/openai"
```
:::

Then start your tool **from that same terminal**. The setting only applies to programs launched from it.

Using Claude Code, Copilot, Cursor or something else? Go to [Pick your setup](/use/pick-your-setup).

## 6. Try it with fake data

In your AI tool, send: `Write a short thank-you email to Jean Dupont, jean@example.com.`

The answer should show **Jean Dupont** and **jean@example.com** as you typed them. The provider's logs show placeholders instead.
If you do not have access to those logs, [Check that it works](/guide/check-it-works) has a test that needs no provider.

## What now?

- [Tell it what is sensitive](/customize/allow-and-deny) in your own work.
- Read [Safety and limits](/guide/safety).
- Stuck? [Troubleshooting](/guide/troubleshooting).
