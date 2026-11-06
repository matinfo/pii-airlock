# Safety and limits

Read this page once. It explains what you can rely on and what you cannot.

## What pii-airlock does well

- **Exact restoring.** Anything it hid comes back byte for byte.
- **Consistency.** Once a value is found anywhere in a conversation, every other mention is hidden too, even ones the
  detector would have missed alone, and even earlier ones.
- **Local detection.** Spotting personal data never uses the network. Only the gateway forwards traffic, and only after cleaning.
- **Safe defaults.** If detection fails, hooks treat the input as sensitive. The gateway refuses requests it does not understand.

## What it cannot promise

::: warning Detection is best effort
The detector is statistical. It will sometimes miss a name or an unusual phone format, and sometimes flag a word
that is not personal. **It reduces exposure; it does not guarantee that nothing personal is sent.**
For truly sensitive material, review the cleaned text yourself.
:::

Specific gaps:

- **Images, audio and attachments** inside a request are forwarded as they are.
- **Output of tools** such as the result of `cat file` is not seen by hooks. The gateway does cover it.
- **Copilot's default models and inline suggestions** cannot be protected at all.
- **Websites and mobile apps** cannot be pointed at the gateway.
- **Claude's `thinking` blocks** are signed, so they are neither cleaned nor restored.
- **Word files:** formatting inside changed paragraphs is lost. **PDFs:** you get text out, not a PDF.

## The map file holds the real data

When you clean a file with `scrub`, the mapping stores the original values.

- By default it goes to the project's `.pii-airlock/maps/`, **encrypted** with a key that stays in
  `~/.local/state/pii-airlock/`, and the folder's own `.gitignore` keeps it out of Git.
- `--map FILE` writes plain JSON where you say (add `--encrypt-map` to encrypt it). Never commit,
  email or upload such a file.
- Delete mappings when you are done. Use `--no-map` if you will never need to restore.

The gateway keeps its mapping **in memory only** and forgets it after each response.

On Windows, files cannot be set to owner-only the way they are on macOS and Linux. They inherit your account's
default permissions, which are normally private in your home folder.

## Ways to improve accuracy

1. Use the larger models (the default `_lg`) or [GLiNER](/customize/languages#many-languages-with-one-model-gliner).
2. [Deny](/customize/allow-and-deny) your internal names, so they are always caught.
3. Set the [action](/customize/actions) for critical types to `block`.
4. Lower the threshold (for example `score_threshold: 0.4`) to catch more, accepting more false alarms.

## Reporting a vulnerability

See the [security policy](https://github.com/matinfo/pii-airlock/blob/main/SECURITY.md).
