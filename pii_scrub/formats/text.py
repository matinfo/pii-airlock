"""Plain text / prompts / .txt — scrub the whole buffer."""

from __future__ import annotations

from .base import Handler, Scrubber


class TextHandler(Handler):
    reads_binary = False
    binary_output = False
    out_suffix = ".txt"

    def scrub(self, scrub: Scrubber) -> str:
        assert isinstance(self.raw, str)
        return scrub(self.raw)
