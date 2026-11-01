# Clean a file or some text

Use this when you want to hide personal data by hand, for example before pasting into a website chat
that pii-airlock cannot sit in front of.

## The three-step routine

### 1. Hide

```bash
pii-airlock scrub notes.txt --map notes.pii-map.json -o notes.clean.txt
```

- `notes.clean.txt` is safe to share. It contains placeholders.
- `notes.pii-map.json` is the **key to undo it**. Keep it private. See the warning below.

You can also pipe text in:

```bash
echo "Contact Jean Dupont at jean@acme.fr" | pii-airlock scrub --map m.pii-map.json
```

```text
Contact <PERSON_558644> at <EMAIL_ADDRESS_094087>
```

### 2. Use the clean text with your AI

Paste `notes.clean.txt` into the AI. It answers using the placeholders.

### 3. Restore

Save the answer to a file, say `answer.txt`, then:

```bash
pii-airlock restore answer.txt --map notes.pii-map.json -o answer.final.txt
```

The placeholders are replaced by the real names and emails.

::: danger The map file contains the real data
Never email it, upload it or commit it to Git. Delete it when you have finished restoring.
If you do not need to restore, use `--no-map`, which makes the cleanup one-way.
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
