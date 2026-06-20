"""Format dispatch by extension."""

from __future__ import annotations

from pathlib import Path

from .base import Handler, MissingExtra, Scrubber
from .csv_json import CsvHandler, JsonHandler
from .docx import DocxHandler
from .pdf import PdfHandler
from .text import TextHandler

__all__ = [
    "Handler",
    "MissingExtra",
    "Scrubber",
    "get_handler_class",
    "FORMATS",
]

# explicit format name -> handler
FORMATS: dict[str, type[Handler]] = {
    "text": TextHandler,
    "csv": CsvHandler,
    "json": JsonHandler,
    "docx": DocxHandler,
    "pdf": PdfHandler,
}

_EXT_MAP: dict[str, type[Handler]] = {
    ".txt": TextHandler,
    ".md": TextHandler,
    ".csv": CsvHandler,
    ".tsv": CsvHandler,
    ".json": JsonHandler,
    ".docx": DocxHandler,
    ".pdf": PdfHandler,
}


def get_handler_class(path: str | Path | None, fmt: str = "auto") -> type[Handler]:
    """Resolve a handler from an explicit format name or the file extension.

    `path=None` (stdin) or unknown extension falls back to plain text.
    """
    if fmt and fmt != "auto":
        try:
            return FORMATS[fmt]
        except KeyError:
            raise ValueError(
                f"Unknown format '{fmt}'. Choose from: {', '.join(FORMATS)}"
            ) from None
    if path is None:
        return TextHandler
    return _EXT_MAP.get(Path(path).suffix.lower(), TextHandler)
