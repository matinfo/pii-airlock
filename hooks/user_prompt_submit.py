#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: warn/block when the prompt contains PII.

Usable either via the console script (`pii-scrub hook user-prompt-submit`) or
directly (`python -m hooks.user_prompt_submit`).
"""

from hooks._common import run_user_prompt_submit

if __name__ == "__main__":
    run_user_prompt_submit()
