#!/bin/sh
# Entry point for the plugin's hooks: hands the event to the pii-airlock CLI.
#
# The plugin cannot install the CLI, and a hook whose command is missing exits 127,
# which Claude Code treats as a non-blocking error: the prompt or tool call would go
# through unguarded. So a missing CLI blocks (exit 2) instead, and SessionStart says why.
# PII_AIRLOCK_PLUGIN_FAIL_OPEN=1 lets everything through while the CLI is missing.
event="$1"

if ! command -v pii-airlock >/dev/null 2>&1; then
  msg='pii-airlock is not installed. Install it with `brew install matinfo/tap/pii-airlock` or `pipx install "pii-airlock[proxy]"`, then run `pii-airlock download-models`.'
  if [ "$event" = "session-start" ]; then
    echo "$msg PII protection is OFF until then: prompts and tool calls are blocked."
    exit 0
  fi
  [ "${PII_AIRLOCK_PLUGIN_FAIL_OPEN:-}" = "1" ] && exit 0
  echo "pii-airlock plugin: $msg Blocked because PII protection is not active (set PII_AIRLOCK_PLUGIN_FAIL_OPEN=1 to allow anyway)." >&2
  exit 2
fi

# Nothing to scan at session start: the check above is the whole job.
[ "$event" = "session-start" ] && exit 0

exec pii-airlock hook "$event"
