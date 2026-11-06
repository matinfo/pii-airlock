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
pii-airlock status
```

It prints the rules that apply right now.

## The project policy file

`pii-airlock init` creates `.pii-airlock/config.yaml`. It is a plain YAML file, committed with the
project, so your team shares it. `allow`, `deny` and `action` edit it; you can also edit it by hand:

```yaml
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
3. The project policy `.pii-airlock/config.yaml`
4. Command-line options

Allow lists, deny lists and custom patterns **add up** across layers. Every other setting is replaced by the later layer.

## Trusting a project you downloaded

A project's settings can *loosen* protection, for example by allowing a name. So for a repository you did not
write, pii-airlock only applies the settings that **tighten** protection until you say otherwise.

After reading `.pii-airlock/config.yaml`, accept it:

```bash
pii-airlock trust
```

Do this again after a `git pull` that changes it. `pii-airlock status` tells you what is currently being ignored.
Your own rules in `~/.config/pii-airlock/config.yaml` are always trusted.
