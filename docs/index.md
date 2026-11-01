---
layout: home
hero:
  name: pii-airlock
  text: Use AI without sharing real personal data
  tagline: Names, emails, phone numbers and passwords are swapped for placeholders before your text leaves your computer, then put back in the answer.
  image:
    src: /logo.svg
    alt: pii-airlock
  actions:
    - theme: brand
      text: Get started in 5 minutes
      link: /guide/quick-start
    - theme: alt
      text: What is it?
      link: /guide/what-is-it
features:
  - icon: 🔒
    title: Stays on your computer
    details: Detection runs locally. The AI provider only ever sees placeholders such as <PERSON_482913>.
  - icon: ↩️
    title: Reversible
    details: The answer comes back with your real names and emails in place, so you read it as usual.
  - icon: 🔌
    title: Works with your tools
    details: Claude Code, GitHub Copilot, Cursor, Codex, Aider, Continue and anything that lets you set a base URL.
  - icon: 🛠️
    title: You decide what counts
    details: Tell it which words are never sensitive (your company) or always sensitive (a code name), in one command.
---

## See it in one picture

```text
You write:            Email John Smith (john@acme.com) about the invoice.
The AI receives:      Email <PERSON_482913> (<EMAIL_ADDRESS_093117>) about the invoice.
The AI answers:       Dear <PERSON_482913>, regarding the invoice…
You read:             Dear John Smith, regarding the invoice…
```

::: tip New here?
Read [What is pii-airlock?](/guide/what-is-it), then follow the [Quick start](/guide/quick-start).
You do not need to know Python. You do need to be comfortable pasting a few commands into a terminal.
:::
