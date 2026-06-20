#!/usr/bin/env python3
"""Claude Code PreToolUse hook: warn/block when tool inputs contain PII.

Usable either via the console script (`pii-scrub hook pre-tool-use`) or
directly (`python -m hooks.pre_tool_use`).
"""

from hooks._common import run_pre_tool_use

if __name__ == "__main__":
    run_pre_tool_use()
