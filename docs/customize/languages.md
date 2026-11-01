# Add a language

By default pii-airlock looks for names in **English and French**. It checks every configured language on every
text and combines the results, so mixed text is handled.

## Add German as an example

1. Create `.pii-airlock.yaml` in your project:

   ```yaml
   languages: [en, fr, de]
   models:
     de: de_core_news_lg
   ```

2. Download the models and check:

   ```bash
   pii-airlock download-models
   pii-airlock doctor
   ```

   `download-models` picks up the new language from your file. If it reports that your environment has no `pip`
   (common with pipx), it prints the exact `pipx inject` commands to run instead.

More models: [spaCy models list](https://spacy.io/models).

## Many languages with one model (GLiNER)

If you work in many languages, one multilingual model can replace one model per language.

```bash
pipx inject pii-airlock 'pii-airlock[gliner]'
```

```yaml
ner_backend: gliner
```

```bash
pii-airlock download-models
```

| | Standard spaCy models | GLiNER |
|---|---|---|
| Download size | small | about 1.1 GB, plus PyTorch |
| Speed per message | about 6 ms | about 40 ms |
| Names found correctly | good | better, with far fewer false alarms |

Emails, phone numbers, IDs and secrets are found by patterns in both modes.
