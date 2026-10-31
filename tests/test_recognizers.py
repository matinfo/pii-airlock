"""Built-in FR/CH identifier and secret recognizers (no spaCy)."""

import pytest

from pii_scrub.recognizers import detect_builtin


def _found(text):
    return {(e, text[s:x]) for e, s, x, _ in detect_builtin(text)}


@pytest.mark.parametrize("text, entity, value", [
    ("NIR : 1 85 05 78 006 084 91.", "FR_NIR", "1 85 05 78 006 084 91"),
    ("nir 185057800608491", "FR_NIR", "185057800608491"),
    ("Corse: 190012B12345642", "FR_NIR", "190012B12345642"),
    ("AVS 756.9217.0769.85", "CH_AHV", "756.9217.0769.85"),
    ("SIRET 732 829 320 00074", "FR_SIRET", "732 829 320 00074"),
    ("SIREN: 732829320", "FR_SIREN", "732829320"),
    ("Tél. 06 12 34 56 78", "PHONE_NUMBER", "06 12 34 56 78"),
    ("call +33 6 12 34 56 78", "PHONE_NUMBER", "+33 6 12 34 56 78"),
    ("Natel 079 123 45 67", "PHONE_NUMBER", "079 123 45 67"),
    ("tel +41 79 123 45 67", "PHONE_NUMBER", "+41 79 123 45 67"),
])
def test_identifiers_detected(text, entity, value):
    assert (entity, value) in _found(text)


@pytest.mark.parametrize("text", [
    "NIR 1 85 05 78 006 084 90",      # wrong key
    "AVS 756.9217.0769.84",           # wrong check digit
    "order 732829321",                # 9 digits, no SIREN keyword
    "SIRET 732 829 320 00075",        # Luhn fails
    "version 1.2.3, port 8080",
])
def test_invalid_or_unrelated_not_detected(text):
    assert not {e for e, _ in _found(text)} & {"FR_NIR", "CH_AHV", "FR_SIREN", "FR_SIRET"}


@pytest.mark.parametrize("text, value", [
    ("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    ("token ghp_" + "a" * 36, "ghp_" + "a" * 36),
    ("OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx", "sk-proj-abcdefghijklmnopqrstuvwx"),
    ("ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrst",
     "sk-ant-api03-abcdefghijklmnopqrst"),
    ("psql postgres://app:s3cr3tpw@db.local/x", "s3cr3tpw"),
    ('password = "hunter2hunter2"', "hunter2hunter2"),
    ("client_secret: Zx9QwErTy123", "Zx9QwErTy123"),
])
def test_secrets_detected(text, value):
    assert ("SECRET", value) in _found(text)


def test_private_key_block():
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"
    assert ("SECRET", key) in _found(f"x\n{key}\ny")


def test_secret_rule_reports_value_not_key_name():
    found = _found("password=correcthorsebattery")
    assert found == {("SECRET", "correcthorsebattery")}


def test_engine_merges_builtin_and_respects_exclusions():
    from types import SimpleNamespace

    from pii_scrub.config import Config
    from pii_scrub.engine import ScrubEngine

    def engine(**cfg):
        eng = ScrubEngine(Config(languages=["en"], **cfg))
        eng.__dict__["_analyzer"] = SimpleNamespace(analyze=lambda **_k: [])
        return eng

    text = "AVS 756.9217.0769.85"
    assert [d.entity_type for d in engine().detect(text)] == ["CH_AHV"]
    assert engine(exclude_entities=["CH_AHV"]).detect(text) == []
    assert engine(builtin_recognizers=False).detect(text) == []


@pytest.mark.parametrize("text,value", [
    ("Rufen Sie mich unter +49 30 901820 an.", "+49 30 901820"),
    ("Chiamami al +39 02 8645 7391 domani.", "+39 02 8645 7391"),
])
def test_international_phone_without_english_context(text, value):
    assert ("PHONE_NUMBER", value) in _found(text)


@pytest.mark.parametrize("text, entity, value", [
    ("Die Steuer-ID lautet 86095742719 laut Bescheid.", "DE_TAX_ID", "86095742719"),
    ("Meine IdNr.: 86 095 742 719.", "DE_TAX_ID", "86 095 742 719"),
    ("Die Steuernummer lautet 21/815/08150 beim Amt.", "DE_TAX_NUMBER", "21/815/08150"),
    ("Partita IVA IT12345678903 della ditta.", "IT_VAT_CODE", "IT12345678903"),
    ("Rufen Sie 030 12345678 an.", "PHONE_NUMBER", "030 12345678"),
    ("Rufen Sie 0170 1234567 an.", "PHONE_NUMBER", "0170 1234567"),
    ("Rufen Sie 089/123456 an.", "PHONE_NUMBER", "089/123456"),
    ("Chiama il 06 12345678 domani.", "PHONE_NUMBER", "06 12345678"),
    ("Chiama il 333 1234567 domani.", "PHONE_NUMBER", "333 1234567"),
    ("Chiama il 02 1234 5678 domani.", "PHONE_NUMBER", "02 1234 5678"),
])
def test_de_it_identifiers_and_national_phones(text, entity, value):
    assert (entity, value) in _found(text)


@pytest.mark.parametrize("text", [
    "Die Steuer-ID 86095742718 hat eine falsche Prüfziffer.",   # bad checksum
    "Bestellnummer 86095742719 wurde versandt.",                # no keyword
    "Partita IVA IT12345678904 della ditta.",                   # bad checksum
    "Am 12.03.2024 um 10:30 kostet es 1234,56 EUR (PLZ 80331).",
    "Order 2024 123456 shipped on 2024-03-12.",
])
def test_de_it_rules_ignore_lookalikes(text):
    assert not {e for e, _ in _found(text)} & {"DE_TAX_ID", "IT_VAT_CODE", "PHONE_NUMBER"}


def test_vat_keyword_without_prefix():
    assert ("IT_VAT_CODE", "12345678903") in _found("P.IVA 12345678903 della ditta.")
