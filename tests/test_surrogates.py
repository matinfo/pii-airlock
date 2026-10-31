"""Surrogate mode: realistic fakes that restore to the real values."""

import json
import re

from pii_scrub import surrogates as fakes
from pii_scrub.mapping import Mapping
from pii_scrub.payload import StreamRestorer, json_escaped
from pii_scrub.recognizers import detect_builtin, detect_fallback

KEY = b"k" * 32


def _m(**kw):
    return Mapping(KEY, surrogates=True, **kw)


def test_person_gets_a_fake_name_and_restores():
    m = _m()
    fake = m.token_for("PERSON", "Jean Dupont")
    first, last = fake.split()
    assert first in fakes.GIVEN_NAMES and last in fakes.FAMILY_NAMES
    assert m.restore(f"Dear {fake},") == "Dear Jean Dupont,"


def test_name_parts_share_the_full_names_fakes():
    m = _m()
    m.learn([("PERSON", "Jean Dupont")])
    surname = m.token_for("PERSON", "dupont")      # met first, in lower case
    full = m.token_for("PERSON", "Jean Dupont")
    assert surname == full.split()[1].lower()
    # The model writing a part alone still restores it.
    assert m.restore(f"Thanks, M. {full.split()[1]}.") == "Thanks, M. Dupont."
    assert m.restore(full.split()[0]) == "Jean"


def test_email_follows_the_name_fakes():
    m = _m()
    m.learn([("PERSON", "Jean Dupont")])
    email = m.token_for("EMAIL_ADDRESS", "jean.dupont@acme.fr")
    full = m.token_for("PERSON", "Jean Dupont")
    assert email == full.lower().replace(" ", ".") + "@example.com"
    assert m.restore(f"mail {email}.") == "mail jean.dupont@acme.fr."
    assert m.token_for("EMAIL_ADDRESS", "support@acme.io").endswith("@example.com")


def test_fakes_are_stable_across_mappings():
    assert _m().token_for("PERSON", "Jean Dupont") == _m().token_for("PERSON", "Jean Dupont")
    assert (Mapping(b"x" * 32, surrogates=True).token_for("PERSON", "Jean Dupont")
            != _m().token_for("PERSON", "Jean Dupont"))


def test_fake_never_already_in_the_input_nor_shared():
    m = _m()
    natural = m.token_for("PERSON", "Jean Dupont").split()[1]
    m2 = _m()
    m2.reserve(f"Our CEO is Anna {natural}.")
    assert natural not in m2.token_for("PERSON", "Jean Dupont")
    a, b = m2.token_for("PERSON", "Ann Lee"), m2.token_for("PERSON", "Bob Ray")
    assert len({a, b, m2.token_for("PERSON", "Jean Dupont")}) == 3


def test_shapes_and_checksums_are_kept():
    m = _m()
    phone = m.token_for("PHONE_NUMBER", "+33 6 12 34 56 78")
    assert re.fullmatch(r"\+33 \d \d\d \d\d \d\d \d\d", phone) and phone != "+33 6 12 34 56 78"
    card = m.token_for("CREDIT_CARD", "4111 1111 1111 1111")
    assert [e for e, *_ in detect_fallback(card)] == ["CREDIT_CARD"] and card.startswith("4")
    iban = m.token_for("IBAN_CODE", "FR76 3000 6000 0112 3456 7890 189")
    assert iban.startswith("FR") and [e for e, *_ in detect_fallback(iban)] == ["IBAN_CODE"]
    ip = m.token_for("IP_ADDRESS", "10.1.2.3")
    assert re.fullmatch(r"(192\.0\.2|198\.51\.100|203\.0\.113)\.\d+", ip)
    assert m.token_for("IP_ADDRESS", "2001:db8::1").startswith("<IP_ADDRESS_")  # token
    for value in (phone, card, iban, ip):
        assert m.restore(value) != value


def test_unsupported_entities_get_tokens():
    m = _m()
    assert re.fullmatch(r"<FR_NIR_\d{6}>", m.token_for("FR_NIR", "185057800608491"))
    assert not detect_builtin(m.token_for("SECRET", "ghp_" + "a" * 36))


def test_restore_is_one_pass():
    m = _m()
    fake_a = m.token_for("PERSON", "Ann Lee")
    # The restored value of one fake is never taken for another fake.
    m._fakes["Ann Lee"] = "WRONG"
    assert m.restore(fake_a) == "Ann Lee"


def test_stream_holds_back_split_fakes():
    m = _m()
    fake = m.token_for("PERSON", "Jean Dupont")
    r = StreamRestorer(m.restore)
    out = "".join(r.feed(c) for c in ["Hi ", fake[:4], fake[4:], " and ", "bye"]) + r.flush()
    assert out == "Hi Jean Dupont and bye"
    r = StreamRestorer(m.restore)
    assert r.feed(f"Hi {fake}") == "Hi "  # complete fake may still grow
    # It grew: the family name is not a fake any more; the given name alone is.
    assert r.feed("o.") + r.flush() == f"Jean {fake.split()[1]}o."


def test_json_arguments_get_escaped_real_values():
    m = _m()
    fake = m.token_for("PERSON", 'Jo "Q" Smith')
    args = json.dumps({"to": fake})
    assert json.loads(json_escaped(m.restore)(args)) == {"to": 'Jo "Q" Smith'}


def test_saved_mapping_restores_fakes(tmp_path):
    m = _m()
    fake = m.token_for("PERSON", "Jean Dupont")
    m.save(tmp_path / "m.json")
    loaded = Mapping.load(tmp_path / "m.json")
    assert loaded.restore(f"{fake} / {fake.split()[1]}") == "Jean Dupont / Dupont"
    assert loaded.items() == [("PERSON", "Jean Dupont")]
