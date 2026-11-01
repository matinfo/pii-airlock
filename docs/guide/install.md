# Install, all options

pii-airlock is a Python program. The tidiest way to install a Python program is **pipx**, which gives it
its own private environment. Pick one method below.

| Method | Good if | Optional extras (Word, PDF, GLiNER) |
|---|---|---|
| **pipx** (recommended) | Any system, most predictable | `pipx inject`, kept across upgrades |
| **Homebrew** | You are on macOS or Linux and prefer `brew` | Possible, but reset on each upgrade |
| **pip** | You manage your own Python environments | `pip install` |
| **Claude Code plugin** | You only use Claude Code | Needs the program installed first |

## Install pipx

::: code-group
```bash [macOS]
brew install pipx
pipx ensurepath
```
```bash [Linux (Debian/Ubuntu)]
sudo apt install pipx
pipx ensurepath
```
```powershell [Windows]
py -m pip install --user pipx
py -m pipx ensurepath
```
:::

Close and reopen your terminal afterwards so the new command is found.

## Method 1: pipx (recommended)

```bash
pipx install "pii-airlock[proxy]"
pii-airlock init
```

`[proxy]` adds the gateway. Without it, only the command-line tools and hooks work.
Added it later by mistake? `pipx inject pii-airlock 'pii-airlock[proxy]'`.

### Optional extras

Plain text, CSV and JSON work out of the box. Add more only if you need them:

```bash
pipx inject pii-airlock 'pii-airlock[docx]'    # Word .docx files
pipx inject pii-airlock 'pii-airlock[pdf]'     # PDF files (text extraction only)
pipx inject pii-airlock 'pii-airlock[all]'    # Word, PDF and gateway
pipx inject pii-airlock 'pii-airlock[gliner]' # one model for many languages (large)
```

## Method 2: Homebrew (macOS and Linux)

```bash
brew install matinfo/tap/pii-airlock
pii-airlock download-models
```

Homebrew installs the command, the hooks and the gateway into a **private virtualenv**: an isolated
folder of Python packages that belongs to pii-airlock alone. You never activate it. The `pii-airlock`
command already points into it.

Find it with:

```bash
brew --prefix pii-airlock
```

The virtualenv is the `libexec` folder inside that path.

To add Word support, PDF support or GLiNER, use that virtualenv's own `pip`:

```bash
"$(brew --prefix pii-airlock)/libexec/bin/python" -m pip install 'pii-airlock[docx]'
```

::: warning Upgrades reset the virtualenv
`brew upgrade pii-airlock` and `brew reinstall pii-airlock` rebuild it. Afterwards, run the extras
command again and `pii-airlock download-models`. If that gets tiresome, use pipx.
:::

## Method 3: pip

Do this inside a virtual environment you created, not in your system Python.

```bash
python3 -m venv ~/pii-airlock-env
source ~/pii-airlock-env/bin/activate      # Windows: ~/pii-airlock-env/Scripts/activate
pip install "pii-airlock[proxy]"
```

You must activate that environment every time before using `pii-airlock`.

## Method 4: Claude Code plugin

Inside Claude Code:

```text
/plugin marketplace add matinfo/pii-airlock
/plugin install pii-airlock@pii-airlock
```

This registers the hooks and adds a `/pii-airlock:setup` helper. It does **not** install the program
itself, so use pipx or Homebrew first. See [Claude Code](/use/claude-code).

## Download the language models

pii-airlock needs language models to recognise names. They are not bundled.

```bash
pii-airlock download-models
```

Run it once, from the same terminal setup you use for `pii-airlock`. English and French are the defaults.
To add other languages, see [Add a language](/customize/languages).

## Install the newest unreleased version

```bash
pipx install git+https://github.com/matinfo/pii-airlock
```

## Update and uninstall

```bash
pipx upgrade pii-airlock        # update
pipx uninstall pii-airlock      # remove
```

Homebrew: `brew upgrade pii-airlock` and `brew uninstall pii-airlock`.
