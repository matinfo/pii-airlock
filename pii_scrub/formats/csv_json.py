"""CSV and JSON — scrub per cell / per string value, preserve structure.

Uses the standard library only (no pandas needed) so these formats work in the
core install.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from typing import Any

from .base import Handler, Scrubber, Tokenizer

# Column headers that mark every cell of the column as PII (normalized:
# lowercase, no accents, separators -> space). A lone "Martin" in a cell has
# no context for NER; the header is the context.
_EXACT_HEADERS: dict[str, str] = {
    **dict.fromkeys(
        ["name", "full name", "fullname", "first name", "firstname", "last name", "lastname",
         "surname", "given name", "family name", "nom", "prenom", "nom complet",
         "nom de famille", "vorname", "nachname", "person"], "PERSON"),
    **dict.fromkeys(["dob", "birthdate", "birthday", "naissance", "geburtsdatum"],
                    "DATE_OF_BIRTH"),
    **dict.fromkeys(["ssn", "nir", "avs", "ahv", "passport", "passeport"], "NATIONAL_ID"),
}
# Header words that mark the column wherever they appear ("work email").
_HEADER_WORDS: dict[str, str] = {
    **dict.fromkeys(["email", "mail", "courriel"], "EMAIL_ADDRESS"),
    **dict.fromkeys(["phone", "telephone", "tel", "mobile", "portable", "natel", "telefon",
                     "handy", "fax"], "PHONE_NUMBER"),
    **dict.fromkeys(["address", "adresse", "street", "rue", "strasse"], "ADDRESS"),
    "iban": "IBAN_CODE",
}
_HEADER_PHRASES: dict[str, str] = {
    "date of birth": "DATE_OF_BIRTH",
    "birth date": "DATE_OF_BIRTH",
    "date de naissance": "DATE_OF_BIRTH",
    "social security": "NATIONAL_ID",
    "securite sociale": "NATIONAL_ID",
    "e mail": "EMAIL_ADDRESS",
}


def _normalize_header(cell: str) -> str:
    text = unicodedata.normalize("NFKD", cell).encode("ascii", "ignore").decode().casefold()
    return " ".join(re.split(r"[\s_\-.]+", text)).strip()


def column_entity(header: str) -> str | None:
    """Entity type for a column whose header says it holds PII, else None."""
    h = _normalize_header(header)
    if h in _EXACT_HEADERS:
        return _EXACT_HEADERS[h]
    for phrase, entity in _HEADER_PHRASES.items():
        if f" {phrase} " in f" {h} ":
            return entity
    for word in h.split():
        if word in _HEADER_WORDS:
            return _HEADER_WORDS[word]
    return None


class CsvHandler(Handler):
    reads_binary = False
    binary_output = False
    out_suffix = ".csv"

    def scrub(self, scrub: Scrubber, tokenize: Tokenizer | None = None) -> str:
        assert isinstance(self.raw, str)
        rows = list(csv.reader(io.StringIO(self.raw)))
        out = io.StringIO()
        writer = csv.writer(out)
        columns: dict[int, str] = {}
        if rows and tokenize is not None:
            columns = {i: e for i, cell in enumerate(rows[0]) if (e := column_entity(cell))}
        if columns:  # first row is a header: keep it as is
            writer.writerow(rows[0])
            rows = rows[1:]
        # PII columns first, so their values are known when other cells are
        # scrubbed (a name in a "notes" column is caught too).
        tokens = [
            {i: tokenize(columns[i], cell.strip()) for i, cell in enumerate(row)
             if i in columns and cell.strip()}
            for row in rows
        ] if columns else [{} for _ in rows]
        for row, row_tokens in zip(rows, tokens, strict=True):
            writer.writerow([row_tokens.get(i) or scrub(cell) for i, cell in enumerate(row)])
        return out.getvalue()


class JsonHandler(Handler):
    reads_binary = False
    binary_output = False
    out_suffix = ".json"

    def scrub(self, scrub: Scrubber, tokenize: Tokenizer | None = None) -> str:
        assert isinstance(self.raw, str)
        data = json.loads(self.raw)
        return json.dumps(_walk(data, scrub), ensure_ascii=False, indent=2)


def _walk(obj: Any, scrub: Scrubber) -> Any:
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, list):
        return [_walk(x, scrub) for x in obj]
    if isinstance(obj, dict):
        # Keys too: emails / names used as keys are common in exports.
        return {scrub(k): _walk(v, scrub) for k, v in obj.items()}
    return obj
