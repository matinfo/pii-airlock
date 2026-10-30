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


def test_json_handler_scrubs_keys():
    raw = json.dumps({"Jean": {"role": "admin"}})
    out = json.loads(JsonHandler(raw).scrub(fake_scrub))
    assert out == {"<PERSON_1>": {"role": "admin"}}


def test_docx_handler_covers_headers_tables_hyperlinks_and_metadata():
    import io

    import pytest

    docx = pytest.importorskip("docx")
    from pii_scrub.formats.docx import DocxHandler

    doc = docx.Document()
    para = doc.add_paragraph("Dear ")
    para.add_run("Je")
    para.add_run("an,")  # entity split across runs
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Jean in table"
    doc.sections[0].header.paragraphs[0].text = "Header Jean"
    doc.sections[0].footer.paragraphs[0].text = "Footer Jean"
    doc.core_properties.author = "Jean Author"
    doc.core_properties.title = "Notes about Jean"
    buf = io.BytesIO()
    doc.save(buf)

    out = docx.Document(io.BytesIO(DocxHandler(buf.getvalue()).scrub(fake_scrub)))
    assert out.paragraphs[0].text == "Dear <PERSON_1>,"
    assert out.tables[0].cell(0, 0).text == "<PERSON_1> in table"
    assert out.sections[0].header.paragraphs[0].text == "Header <PERSON_1>"
    assert out.sections[0].footer.paragraphs[0].text == "Footer <PERSON_1>"
    assert out.core_properties.author == ""
    assert out.core_properties.title == "Notes about <PERSON_1>"


def test_csv_pii_columns_tokenized_by_header():
    from pii_scrub.formats.csv_json import column_entity
    from pii_scrub.mapping import Mapping

    assert column_entity("Prénom") == "PERSON"
    assert column_entity("work_email") == "EMAIL_ADDRESS"
    assert column_entity("Date de naissance") == "DATE_OF_BIRTH"
    assert column_entity("customer_id") is None
    assert column_entity("Status") is None

    m = Mapping()
    raw = "id,Nom,Téléphone,notes\n1,Martin,079 123 45 67,ok\n2,Rossi,,call Martin\n"
    out = CsvHandler(raw).scrub(fake_scrub, m.token_for)
    lines = out.splitlines()
    assert lines[0] == "id,Nom,Téléphone,notes"  # header kept
    assert lines[1] == "1,<PERSON_1>,<PHONE_NUMBER_1>,ok"
    assert lines[2].startswith("2,<PERSON_2>,,")
    assert m.restore(out).replace("\r\n", "\n") == raw


def test_csv_without_tokenizer_scrubs_cells():
    out = CsvHandler("Nom\nJean\n").scrub(fake_scrub)
    assert out.splitlines() == ["Nom", "<PERSON_1>"]
