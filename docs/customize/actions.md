# Choose what happens

By default every personal item is swapped for a placeholder and restored later. You can pick another behaviour
for each **type** of item (names, emails, bank numbers…).

## The four choices

| Choice | What happens | Use it when |
|---|---|---|
| `tokenize` | Swapped for a placeholder, restored in the answer. **The default.** | Normal work |
| `redact` | Replaced by a label such as `[IBAN_CODE]`. **Not restorable**, and the real value is never stored. | The AI never needs it and you do not want to keep it |
| `allow` | Left alone and not flagged | The type is noise for you, for example locations |
| `block` | Nothing is sent at all | The value must never leave, for example API keys |

## Set one

```bash
pii-airlock action IBAN_CODE redact
pii-airlock action SECRET block
pii-airlock action LOCATION allow
pii-airlock action CREDIT_CARD block --scope user    # all projects
```

## What `block` does in each tool

- **Gateway:** answers with an error (403) and sends nothing.
- **Command line:** `scrub` writes nothing.
- **Hooks:** the tool call is denied, even when you normally get asked. Prompts are blocked too.

Messages say which type and how many, never the value.

## Recommended starting point

If you work with real customer data, this is a sensible policy:

```yaml pii-airlock
entity_actions:
  IBAN_CODE: redact
  CREDIT_CARD: block
  SECRET: block        # API keys and passwords never leave the machine
```

Put it in `.pii-airlock.yaml` or in the block of your project policy.

## Related names stay protected

If you set `EMAIL_ADDRESS: allow`, emails stay readable. But a bare `marie` that matches a "Marie Dubois" found
elsewhere in the text is still hidden.
