# What it detects

pii-airlock combines [Microsoft Presidio](https://microsoft.github.io/presidio/), a language model for names, and its own
checked recognizers. Use these type names with [`pii-airlock action`](/customize/actions).

## Common types

| Type | Examples |
|---|---|
| `PERSON` | Names |
| `EMAIL_ADDRESS` | `jean@acme.fr` |
| `PHONE_NUMBER` | `+33 6 12 34 56 78`, `079 123 45 67` |
| `CREDIT_CARD` | Card numbers |
| `IBAN_CODE` | Bank account numbers |
| `IP_ADDRESS` | `192.168.1.10` |
| `LOCATION` | Cities, addresses |
| `SECRET` | API keys, tokens, private keys, `password=…` values |

## Extra recognizers that work in any language

These check the number's built-in check digit, so a random number does not trigger them.

| Type | What it is |
|---|---|
| `FR_NIR` | French social security number |
| `CH_AHV` | Swiss AHV/AVS number |
| `FR_SIRET`, `FR_SIREN` | French business IDs |
| `DE_TAX_ID` | German tax ID (needs a nearby keyword such as `Steuer-ID`) |
| `DE_TAX_NUMBER` | German `Steuernummer` (needs a keyword) |
| `IT_VAT_CODE` | Italian VAT number |
| `SECRET` | Keys for AWS, GitHub, Slack, OpenAI, Anthropic, Google and Stripe, plus JWTs |

## Ignored by default

These fire on almost every date and web link, so they are off unless you ask:

`DATE_TIME`, `URL`, `NRP`, `US_DRIVER_LICENSE`, `US_BANK_NUMBER`, `US_PASSPORT`, `IN_VEHICLE_REGISTRATION`

An email or name inside a link is still caught by its own recognizer.

To turn one on, set `exclude_entities` to a list without it, or an `action` for that type.
To turn off all the extra recognizers: `builtin_recognizers: false`.
