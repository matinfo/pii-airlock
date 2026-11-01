# Check that it works

Three quick tests, from simplest to most complete. None of them needs an AI account.

## 1. The built-in health check

```bash
pii-airlock doctor
```

It prints one line per check. Every line should start with `[ok]`.

| Line | Meaning if it says `fail` |
|---|---|
| gateway dependencies | The gateway add-on is missing. Run `pipx inject pii-airlock 'pii-airlock[proxy]'`. |
| models | Name-spotting models are not installed. Run `pii-airlock download-models`. |
| mapping roundtrip | An internal self-test failed. Reinstall and report a bug if it persists. |
| hook daemon | Information only. It shows whether the speed-up helper for hooks is running. |

## 2. Hide and restore a sentence

Use obviously fake data.

```bash
echo "Contact John Smith at john@example.com" \
  | pii-airlock scrub --map /tmp/test.pii-map.json -o /tmp/scrubbed.txt
cat /tmp/scrubbed.txt
```

You should see placeholders instead of the name and email:

```text
Contact <PERSON_482913> at <EMAIL_ADDRESS_093117>
```

Your numbers will differ. Now put the originals back:

```bash
pii-airlock restore /tmp/scrubbed.txt --map /tmp/test.pii-map.json
```

```text
Contact John Smith at john@example.com
```

::: tip Windows
Use a folder you own instead of `/tmp`, for example `$env:TEMP\test.pii-map.json`.
:::

## 3. Only look, change nothing

```bash
pii-airlock detect notes.txt
```

It lists what it found, with a confidence score, without altering the file. Handy to see what would be hidden.

## 4. Test the gateway

Start `pii-airlock proxy`, then point your AI client at it as described in
[Other AI apps and SDKs](/use/gateway). Send a message that includes a fake name and email. Your client should
still show them. Your provider's dashboard or logs should show placeholders such as `<EMAIL_ADDRESS_093117>`.

::: warning Delete test mapping files
The mapping file holds the **real** values. Remove it when you finish: `rm /tmp/test.pii-map.json`.
:::
