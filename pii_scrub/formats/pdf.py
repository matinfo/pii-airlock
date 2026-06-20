"""PDF — extract text, scrub it, emit plain text.

Optional dependency: pdfminer.six  (pip install 'pii-airlock[pdf]')

MVP scope: PDF is read-only. We extract the text layer and output scrubbed
.txt; we do not re-render a PDF. Documented in the README.
"""

from __future__ import annotations

import io

from .base import Handler, MissingExtra, Scrubber


class PdfHandler(Handler):
    reads_binary = True
    binary_output = False
    out_suffix = ".txt"

    def scrub(self, scrub: Scrubber) -> str:
        try:
            from pdfminer.high_level import extract_text  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on install
            raise MissingExtra("pdf", "pdfminer.six") from exc

        assert isinstance(self.raw, (bytes, bytearray))
        text = extract_text(io.BytesIO(self.raw))
        return scrub(text)
