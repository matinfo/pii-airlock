import os

from pii_scrub.mapping import Mapping


def test_deterministic_tokens():
    m = Mapping()
    t1 = m.token_for("PERSON", "Jean Dupont")
    t2 = m.token_for("PERSON", "Jean Dupont")
    t3 = m.token_for("PERSON", "Marie Curie")
    assert t1 == t2 == "<PERSON_1>"
    assert t3 == "<PERSON_2>"


def test_counters_per_type():
    m = Mapping()
    assert m.token_for("PERSON", "a") == "<PERSON_1>"
    assert m.token_for("EMAIL_ADDRESS", "a@b.fr") == "<EMAIL_ADDRESS_1>"


def test_restore_roundtrip():
    m = Mapping()
    tok = m.token_for("EMAIL_ADDRESS", "jean@acme.fr")
    assert m.restore(f"contact: {tok}") == "contact: jean@acme.fr"


def test_save_load_roundtrip(tmp_path):
    m = Mapping()
    m.token_for("PERSON", "Jean Dupont")
    m.token_for("EMAIL_ADDRESS", "jean@acme.fr")
    p = tmp_path / "x.pii-map.json"
    m.save(p)
    # POSIX permission bits; Windows ignores chmod, so assert only there.
    if os.name == "posix":
        assert oct(p.stat().st_mode)[-3:] == "600"

    loaded = Mapping.load(p)
    assert loaded.restore("<PERSON_1> <EMAIL_ADDRESS_1>") == "Jean Dupont jean@acme.fr"
    # continues minting from where it left off
    assert loaded.token_for("PERSON", "New Person") == "<PERSON_2>"


def test_unknown_token_untouched():
    m = Mapping()
    assert m.restore("<UNKNOWN_9>") == "<UNKNOWN_9>"
