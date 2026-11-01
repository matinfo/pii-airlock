# Tell it what is sensitive

pii-airlock does not know your business. It may flag your own company name as a person, or miss an internal
code name. Two short commands fix both.

## Stop a false alarm: `allow`

```bash
pii-airlock allow "Acme SA"
```

From now on "Acme SA" is never treated as personal data in this project.
Good candidates: your company, your products, public figures you write about.

## Always hide something: `deny`

```bash
pii-airlock deny "Project Phoenix" --as CODENAME
```

"Project Phoenix" is now always hidden, as a placeholder labelled `CODENAME`. Good for client names,
internal projects and anything the detector would not recognise by itself.

## This project or everything?

By default a rule applies to **the project you are in**. Add `--scope user` to apply it everywhere.

```bash
pii-airlock allow "Jane Roe" --scope user      # your own name, in all projects
```

## See what is in force

```bash
pii-airlock policy show
```

It prints the rules that apply right now and where each came from.

## Create a policy file for a project

```bash
pii-airlock policy init
```

This creates `.claude/skills/pii-airlock/SKILL.md`. Claude Code reads it as instructions about handling personal
data, and pii-airlock reads the settings block inside it. It is a normal text file you can edit and share with your team.

```yaml pii-airlock
allow_list: [Acme SA]
deny_list:
  CODENAME: [Project Phoenix]
custom_patterns:
  - {entity: CONTRACT_ID, regex: 'CT-\d{6}'}
```

`custom_patterns` hides anything that matches a pattern. The example hides contract numbers like `CT-123456`.

## Where settings live

pii-airlock combines several layers. Later ones win:

1. Built-in defaults
2. Your personal file `~/.config/pii-airlock/config.yaml`
3. A project file `.pii-airlock.yaml`
4. A project policy `.claude/skills/pii-airlock/SKILL.md`
5. Command-line options

Allow lists, deny lists and custom patterns **add up** across layers. Every other setting is replaced by the later layer.

## Trusting a project you downloaded

A project's settings can *loosen* protection, for example by allowing a name. So for a repository you did not
write, pii-airlock only applies the settings that **tighten** protection until you say otherwise.

After reading the project's policy files, accept them:

```bash
pii-airlock trust
```

Do this again after a `git pull` that changes them. `pii-airlock policy show` tells you what is currently being ignored.
Your own rules in `~/.config/pii-airlock/config.yaml` are always trusted.
