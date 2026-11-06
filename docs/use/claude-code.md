# Claude Code

Claude Code reads files and runs commands for you. pii-airlock adds checkpoints called **hooks**
that look at what is about to be sent and stop you when it contains personal data.

## Set it up: `pii-airlock init`

First install the program ([Install, all options](/guide/install)). Then, in your project:

```bash
pii-airlock init
```

This creates a `.pii-airlock/` folder in the project and installs the hooks for your user, once.
The hooks only act in projects that have this folder, so your other projects are left alone.
Run `pii-airlock init` in each project you want guarded. Restart Claude Code after the first
`init` so it loads the hooks.

```bash
pii-airlock status   # is this project guarded, by which hooks
pii-airlock off      # pause it here (pii-airlock on resumes)
```

At the start of each session, Claude is told the project's rules: use placeholders, never work
around a block, never open the mapping files.

## Or: the plugin

Inside Claude Code:

```text
/plugin marketplace add matinfo/pii-airlock
/plugin install pii-airlock@pii-airlock
```

You also get a `/pii-airlock:setup` helper. You still run `pii-airlock init` in each project: it
sees the plugin and does not install the hooks a second time.

::: warning If the program is missing
In a guarded project, the plugin **blocks every prompt and tool call** while the `pii-airlock`
command cannot be found, and says why. Install the program to fix it.
:::

The plugin's launcher is a shell script, so on Windows use `pii-airlock init` without the plugin.

## What you will see

| What you did | What happens |
|---|---|
| Typed a prompt containing personal data | The prompt is **blocked**. You get a scrubbed version to send instead. |
| Claude wants to read a file containing personal data | Claude Code **asks you** to confirm. |
| Claude wants to run a command, edit a file, search or fetch a URL containing personal data | Claude Code **asks you** to confirm. |

Every message tells you what type was found (for example "2 emails") but never repeats the value itself.

### A false alarm?

If pii-airlock flags something that is not personal, such as your company name, tell it once:

```bash
pii-airlock allow "Acme SA"
```

See [Tell it what is sensitive](/customize/allow-and-deny).

## Change how strict it is

Put these in your project's `.pii-airlock/config.yaml` (see
[Tell it what is sensitive](/customize/allow-and-deny).

| Setting | Effect |
|---|---|
| `hook_decision: deny` | Block risky tool calls outright instead of asking. |
| `prompt_decision: warn` | Let prompts through with a warning instead of blocking. |
| `hook_on_error: open` | If detection breaks, carry on instead of treating the input as sensitive. |

## What hooks cannot see

Hooks check what goes **into** a tool. They cannot see what a tool **prints back**. If Claude runs `cat customers.csv`,
the output reaches the AI unchecked. Images and PDFs are not inspected either.

For full coverage, also send Claude Code's traffic through the gateway:

```bash
pii-airlock proxy
```
```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8745/anthropic
claude
```

The gateway hides personal data in tool output too and restores it in the commands Claude writes back.

## Why does the first prompt feel slow?

The name-spotting models take a few seconds to load. pii-airlock starts a small background helper on the first
call that keeps them loaded, so later checks take about 60 milliseconds. It stops after 30 idle minutes.

```bash
pii-airlock daemon status
pii-airlock daemon stop
```
