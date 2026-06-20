"""Format handler tests using a fake scrubber (no Presidio needed)."""

import json

from pii_scrub.formats import get_handler_class
from pii_scrub.formats.csv_json import CsvHandler, JsonHandler
from pii_scrub.formats.text import TextHandler


def fake_scrub(s: str) -> str:
    # Pretend "Jean" is PII.
    return s.replace("Jean", "<PERSON_1>")


def test_dispatch_by_extension():
    assert get_handler_class("a.txt") is TextHandler
    assert get_handler_class("a.csv") is CsvHandler
    assert get_handler_class("a.json") is JsonHandler
    assert get_handler_class(None) is TextHandler
    assert get_handler_class("weird.xyz") is TextHandler


def test_explicit_format_overrides_extension():
    assert get_handler_class("a.txt", fmt="json") is JsonHandler


def test_text_handler():
    assert TextHandler("hi Jean").scrub(fake_scrub) == "hi <PERSON_1>"


def test_csv_handler_preserves_columns():
    raw = "name,city\nJean,Paris\n"
    out = CsvHandler(raw).scrub(fake_scrub)
    assert "<PERSON_1>" in out
    assert "city" in out
    assert out.count("\n") >= 2


def test_json_handler_walks_strings_only():
    raw = json.dumps({"name": "Jean", "age": 30, "tags": ["Jean", "x"]})
    out = json.loads(JsonHandler(raw).scrub(fake_scrub))
    assert out["name"] == "<PERSON_1>"
    assert out["age"] == 30  # numbers untouched
    assert out["tags"] == ["<PERSON_1>", "x"]
