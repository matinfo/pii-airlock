# Clean a file or some text

Use this when you want to hide personal data by hand, for example before pasting into a website chat
that pii-airlock cannot sit in front of.

## The three-step routine

### 1. Hide

```bash
pii-airlock scrub notes.txt -o notes.clean.txt
```

- `notes.clean.txt` is safe to share. It contains placeholders.
- The **key to undo it** (the mapping) is kept, encrypted, in your project's `.pii-airlock/maps/`
  (outside a project: `~/.local/state/pii-airlock/maps/`). Git ignores it.

You can also pipe text in:

```bash
echo "Contact Jean Dupont at jean@acme.fr" | pii-airlock scrub
```

```text
Contact <PERSON_558644> at <EMAIL_ADDRESS_094087>
```

### 2. Use the clean text with your AI

Paste `notes.clean.txt` into the AI. It answers using the placeholders.

### 3. Restore

Save the answer to a file, say `answer.txt`, then:

```bash
pii-airlock restore answer.txt -o answer.final.txt
```

The placeholders are replaced by the real names and emails.

::: danger The mapping contains the real data
It is encrypted with a key that stays on this computer, so it only opens here. If you write it
elsewhere with `--map FILE`, it is plain JSON: never email, upload or commit that file. Delete
mappings when you have finished restoring. If you never need to restore, use `--no-map`.
:::

## Which files work?

| Type | Works | Notes |
|---|---|---|
| Plain text, CSV, JSON | Always | |
| Word `.docx` | Needs the `docx` extra | Changed paragraphs lose inline formatting such as a bold word in the middle. |
| PDF | Needs the `pdf` extra | Text only. You get cleaned text, not a new PDF. |

```bash
pii-airlock scrub report.csv -o report.clean.csv
pii-airlock scrub contract.docx -o contract.clean.docx
pii-airlock scrub scan.pdf > scan.clean.txt
```

Install the extras from [Install, all options](/guide/install#optional-extras).

## See what it would hide first

```bash
pii-airlock detect notes.txt
```

```text
PERSON           0.85  [9:21]    'Jean Dupont'
EMAIL_ADDRESS    0.99  [24:38]   'jean@acme.fr'
```

Nothing is changed. The number is the confidence from 0 to 1.

## Useful options

| Option | What it does |
|---|---|
| `--no-map` | One-way cleanup. You cannot restore afterwards. |
| `--encrypt-map` | Encrypts the map so it only opens on this computer. |
| `--lang fr,en` | Choose the languages to look for. |
| `--threshold 0.7` | Be pickier. Fewer false alarms, more risk of a miss. |
