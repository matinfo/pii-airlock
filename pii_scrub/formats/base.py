"""Format handler protocol.

A handler receives the raw file contents and a `scrub` callable (str -> str)
that anonymizes a single piece of text. It applies that callable to every
textual segment of the format and returns the reassembled output.

Reversibility comes for free: the same Mapping closed over by `scrub` is used
across all segments, and `Mapping.restore` runs on the textual output.
"""

from __future__ import annotations

from collections.abc import Callable

Scrubber = Callable[[str], str]


class MissingExtra(RuntimeError):
    """Raised when a format needs an optional dependency that isn't installed."""

    def __init__(self, extra: str, package: str) -> None:
        super().__init__(
            f"This format requires the optional '{extra}' dependency.\n"
            f"Install it with:  pip install 'pii-scrub[{extra}]'   (provides {package})"
        )


class Handler:
    """Base format handler."""

    #: read the source file as bytes (True) or decoded text (False)
    reads_binary: bool = False
    #: the output is binary (True) or text (False)
    binary_output: bool = False
    #: suffix for a default output file
    out_suffix: str = ".txt"

    def __init__(self, raw: str | bytes) -> None:
        self.raw = raw

    def scrub(self, scrub: Scrubber) -> str | bytes:  # pragma: no cover - abstract
        raise NotImplementedError
