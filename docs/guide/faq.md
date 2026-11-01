# FAQ

## Does my data go to pii-airlock's authors?

No. It runs entirely on your computer. Detection makes no network calls.

## Does it work offline?

Detection does, once the models are downloaded. The AI tool itself still needs the internet.

## Do I need an account or an API key for pii-airlock?

No. You use your own accounts with your AI providers as before. The gateway passes your key through and does not log it.

## Does it slow things down?

Cleaning a message takes a few milliseconds to tens of milliseconds. Hooks add about 60 ms once their helper has started.

## Will the AI still understand my text?

Mostly yes. The same person always gets the same placeholder, so it can follow who did what. If a model handles
`<TOKENS>` badly, try [realistic fakes](/customize/placeholders#style-2-realistic-fakes).

## Can I use it with ChatGPT.com, claude.ai or a phone app?

Not through the gateway. For those, [clean the text by hand](/use/files-and-text) before pasting it.

## Which languages work?

English and French out of the box. [Add others](/customize/languages) with a spaCy model or the multilingual GLiNER model.
Some identifiers are recognised in any language: French, Swiss, German and Italian IDs, phone formats, and secrets such as API keys.

## What counts as personal data here?

Names, emails, phone numbers, bank and card numbers, IP addresses, national IDs, API keys and passwords, and more.
See [What it detects](/reference/detected-types).

## Can it miss something?

Yes. See [Safety and limits](/guide/safety).

## Can I run it for my team on a server?

It is designed for one person's computer and binds to `127.0.0.1` by default. Exposing it more widely is your responsibility.
The file mapping backend and its settings are covered in [Settings](/reference/settings).

## Does it work on Windows?

Yes. macOS, Linux and Windows are tested in CI. The Claude Code **plugin** needs a shell script, so on Windows use `install-hook` instead.

## How do I update or remove it?

`pipx upgrade pii-airlock` and `pipx uninstall pii-airlock`. See [Install, all options](/guide/install#update-and-uninstall).

## How can I contribute?

Adding a language or a provider adapter is a good first contribution.
See [CONTRIBUTING](https://github.com/matinfo/pii-airlock/blob/main/CONTRIBUTING.md).
