"""CSV and JSON — scrub per cell / per string value, preserve structure.

Uses the standard library only (no pandas needed) so these formats work in the
core install.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .base import Handler, Scrubber


class CsvHandler(Handler):
    reads_binary = False
    binary_output = False
    out_suffix = ".csv"

    def scrub(self, scrub: Scrubber) -> str:
        assert isinstance(self.raw, str)
        reader = csv.reader(io.StringIO(self.raw))
        out = io.StringIO()
        writer = csv.writer(out)
        for row in reader:
            writer.writerow([scrub(cell) for cell in row])
        return out.getvalue()


class JsonHandler(Handler):
    reads_binary = False
    binary_output = False
    out_suffix = ".json"

    def scrub(self, scrub: Scrubber) -> str:
        assert isinstance(self.raw, str)
        data = json.loads(self.raw)
        return json.dumps(_walk(data, scrub), ensure_ascii=False, indent=2)


def _walk(obj: Any, scrub: Scrubber) -> Any:
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, list):
        return [_walk(x, scrub) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, scrub) for k, v in obj.items()}
    return obj
