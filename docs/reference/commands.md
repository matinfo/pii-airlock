# Commands

A cheat sheet. Run any command with `--help` for the full list of options.

## Setup and checks

| Command | What it does |
|---|---|
| `pii-airlock init` | Guided first-time setup |
| `pii-airlock download-models` | Download the language models (`--lang fr,en` to choose) |
| `pii-airlock doctor` | Health check |
| `pii-airlock --version` | Show the version |

## Clean text and files

| Command | What it does |
|---|---|
| `pii-airlock scrub [file]` | Replace personal data with placeholders. Reads standard input if no file is given. |
| `pii-airlock restore [file] --map M` | Put the originals back using a map file |
| `pii-airlock detect [file]` | List what would be found, change nothing |

`scrub` options:

| Option | Meaning |
|---|---|
| `-o, --out FILE` | Write to a file instead of the screen |
| `--map FILE` | Where to save the map used to restore |
| `--no-map` | One-way cleanup |
| `--encrypt-map` | Encrypt the map for this computer |
| `--lang fr,en` | Languages to look for |
| `--threshold 0.7` | Minimum confidence, 0 to 1 |
| `--format` | Force `text`, `csv`, `json`, `docx` or `pdf` |

## Gateway

| Command | What it does |
|---|---|
| `pii-airlock proxy` | Start the gateway on `127.0.0.1:8745` |
| `pii-airlock proxy --port 8800` | Use another port |
| `pii-airlock proxy --host 0.0.0.0` | Listen on all network interfaces. Only do this if you understand the exposure. |
| `--openai-url`, `--anthropic-url`, `--gemini-url` | Send to a different upstream address |

## Hooks (Claude Code and Copilot)

| Command | What it does |
|---|---|
| `pii-airlock install-hook` | Install both hooks for this project |
| `--scope user` | Install for all projects |
| `--event tool` or `--event prompt` | Install only one of the two |
| `--target copilot` | Install for GitHub Copilot instead of Claude Code |
| `pii-airlock daemon status \| start \| stop` | Control the helper that keeps models loaded |

## Your rules

| Command | What it does |
|---|---|
| `pii-airlock allow "TERM"` | Never treat this as personal data |
| `pii-airlock deny "TERM" --as LABEL` | Always treat this as sensitive |
| `pii-airlock action TYPE tokenize\|redact\|allow\|block` | Choose what happens to a type |
| `pii-airlock policy init` | Create the project policy file |
| `pii-airlock policy show` | Show the rules in force and their source |
| `pii-airlock trust` | Accept this project's settings after reviewing them |

`allow`, `deny` and `action` take `--scope project` (default) or `--scope user`.
