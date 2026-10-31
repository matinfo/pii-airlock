#!/usr/bin/env python3
"""Claude Code PreToolUse hook: warn/block when tool inputs contain PII.

Usable either via the console script (`pii-airlock hook pre-tool-use`) or
directly (`python -m pii_scrub.hooks.pre_tool_use`).
"""

from pii_scrub.hooks._common import run_pre_tool_use

if __name__ == "__main__":
    run_pre_tool_use()
