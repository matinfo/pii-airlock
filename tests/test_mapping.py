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


def test_restore_tolerates_escaped_tokens():
    m = Mapping()
    tok = m.token_for("PERSON", "Alice")
    assert tok == "<PERSON_1>"
    text = "a &lt;PERSON_1&gt; b \\<PERSON_1\\> c \\u003cPERSON_1\\u003e d <PERSON_1>"
    assert m.restore(text) == "a Alice b Alice c Alice d Alice"
    # unknown tokens stay as they were, in their original form
    assert m.restore("&lt;PERSON_9&gt;") == "&lt;PERSON_9&gt;"


def test_literal_tokens_in_source_are_never_minted():
    m = Mapping()
    m.reserve("template says <PERSON_1> and &lt;PERSON_2&gt;")
    assert m.token_for("PERSON", "Alice") == "<PERSON_3>"
    assert m.restore("<PERSON_1>") == "<PERSON_1>"


def test_same_value_gets_one_token_across_entity_types():
    m = Mapping()
    assert m.token_for("PERSON", "Paris") == m.token_for("LOCATION", "Paris")
    assert len(m) == 1


def test_save_load_keeps_value_index(tmp_path):
    m = Mapping()
    m.token_for("PERSON", "Alice")
    m.save(tmp_path / "m.json")
    loaded = Mapping.load(tmp_path / "m.json")
    assert loaded.token_for("LOCATION", "Alice") == "<PERSON_1>"
    assert loaded.token_for("PERSON", "Bob") == "<PERSON_2>"
