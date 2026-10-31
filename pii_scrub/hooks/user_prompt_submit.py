#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: warn/block when the prompt contains PII.

Usable either via the console script (`pii-airlock hook user-prompt-submit`) or
directly (`python -m pii_scrub.hooks.user_prompt_submit`).
"""

from pii_scrub.hooks._common import run_user_prompt_submit

if __name__ == "__main__":
    run_user_prompt_submit()
