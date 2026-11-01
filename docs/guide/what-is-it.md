# What is pii-airlock?

When you paste text into an AI assistant, that text travels to the company running the AI.
If it contains a customer's name, an email address, a phone number or a password, that data
leaves your computer too.

**pii-airlock is a small program that runs on your own computer and sits between you and the AI.**
Think of it as an airlock: personal details cannot pass through it in the clear.

## How it works

1. **You write** your question as usual.
2. **pii-airlock finds** names, emails, phone numbers, bank numbers, secret keys and similar items.
3. **It swaps each one** for a placeholder, for example `<PERSON_482913>`.
4. **The AI sees only placeholders** and answers using them.
5. **pii-airlock swaps the originals back** into the answer before you read it.

The same person always gets the same placeholder, so the AI can still follow who is who.
You can read more in [Placeholders explained](/customize/placeholders).

## What it is good for

- Asking an AI to draft or summarise something that mentions real people.
- Letting a coding assistant work in a project that contains customer data.
- Cleaning a file (text, CSV, JSON, Word, PDF) before you share it.

## What it is not

- **Not a guarantee.** Detection is smart but not perfect. It can miss a name or flag a word that is not personal.
  Read [Safety and limits](/guide/safety) before you rely on it for sensitive work.
- **Not a cloud service.** Nothing is uploaded to pii-airlock's authors. Detection runs on your machine.
- **Not an AI itself.** It does not answer questions. It only protects what you send to the AI you already use.

## Two ways to use it

You pick one depending on the tool you use. [Pick your setup](/use/pick-your-setup) helps you choose.

| | The gateway | Hooks |
|---|---|---|
| In plain words | A local address your AI app talks to instead of the provider | Guards built into Claude Code and Copilot |
| What it does | Swaps and restores automatically | Stops and warns you before personal data is sent |
| Best for | Chat apps, SDKs, Cursor, Codex, Aider | Claude Code and Copilot working on your files |

## Next step

[Quick start (5 minutes)](/guide/quick-start)
