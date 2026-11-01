# Placeholders explained

A placeholder replaces a real value in the text the AI receives. You choose the style.

## Style 1: stable tokens (default)

```text
Jean Dupont  →  <PERSON_558644>
jean@acme.fr →  <EMAIL_ADDRESS_094087>
```

- The **same value always gets the same token**, in every message, file and session. The AI can follow who is who,
  and caching keeps working.
- Tokens are computed with a secret key kept on your computer (`~/.local/state/pii-airlock/token.key`).
  Without it a token tells nobody anything about the value behind it.
- **Tokens change over time.** By default a person gets a new token each day, so a provider cannot follow one person
  across all your conversations.

```yaml
token_rotation: day     # day (default), week, or never
```

Use `never` if you clean one big dataset over several runs and need identical tokens throughout.

To change all tokens immediately, delete `token.key`.

## Style 2: realistic fakes

```yaml
token_style: surrogate
```

```text
Jean Dupont         →  Jasper Iverson
jean.dupont@acme.fr →  jasper.iverson@example.com
```

The text reads naturally, which some models handle better than `<TOKENS>`. Phone numbers, cards and IBANs keep a
valid shape. Other types, such as secrets and places, still use tokens.

Trade-off: if the AI invents a name that happens to equal a fake, that name is also swapped back.

## Style 3: numbered

```yaml
token_style: sequential
```

```text
<PERSON_1>, <PERSON_2> …
```

Numbered in reading order, separately for each request or file. This was the default in early versions.

## Where do I put these settings?

In `~/.config/pii-airlock/config.yaml` for yourself, or `.pii-airlock.yaml` in a project. See
[Settings](/reference/settings).
