"""GLiNER backend without the model: windowing, wiring, missing package."""

import sys
import types

import pytest

from pii_scrub import gliner_backend as gb
from pii_scrub.config import Config
from pii_scrub.engine import ScrubEngine


def test_windows_cover_text_with_overlap_at_spaces():
    text = " ".join(f"w{i:04d}" for i in range(600))  # ~3600 chars
    pieces = list(gb.windows(text, size=1000, overlap=200))
    assert pieces[0][0] == 0 and pieces[-1][0] + len(pieces[-1][1]) == len(text)
    for (o1, p1), (o2, _) in zip(pieces, pieces[1:], strict=False):
        assert o2 < o1 + len(p1)                     # overlap
        assert o1 + len(p1) - o2 >= 150              # big enough for a name
        assert text[o2 - 1] == " "                   # starts at a word
    assert all(len(p) <= 1000 for _, p in pieces)
    assert list(gb.windows("short")) == [(0, "short")]


class _FakeGliner:
    calls: list = []

    @classmethod
    def from_pretrained(cls, name):
        return cls()

    def predict_entities(self, text, labels, threshold, flat_ner):
        _FakeGliner.calls.append((text, tuple(labels), threshold))
        i = text.find("Jean Dupont")
        out = [] if i < 0 else [{"start": i, "end": i + 11, "text": "Jean Dupont",
                                 "label": "person", "score": 0.97}]
        j = text.find("jean@acme.fr")  # GLiNER tags emails as "address"
        return out + ([] if j < 0 else [{"start": j, "end": j + 12, "text": "jean@acme.fr",
                                         "label": "address", "score": 0.9}])


@pytest.fixture
def fake_gliner(monkeypatch):
    _FakeGliner.calls = []
    monkeypatch.setitem(sys.modules, "gliner", types.SimpleNamespace(GLiNER=_FakeGliner))


def test_engine_uses_gliner_once_per_text_with_ner_labels_only(fake_gliner):
    eng = ScrubEngine(Config(languages=["en", "fr"], ner_backend="gliner",
                             builtin_recognizers=False))
    text = "Écrire à Jean Dupont, jean@acme.fr, " + "blabla " * 300 + "puis Jean Dupont."
    found = {(d.entity_type, text[d.start:d.end]) for d in eng.detect(text)}
    assert ("PERSON", "Jean Dupont") in found
    assert ("EMAIL_ADDRESS", "jean@acme.fr") in found      # Presidio pattern recognizer
    starts = [d.start for d in eng.detect(text) if d.entity_type == "PERSON"]
    assert len(starts) == 2 and max(starts) > 2000           # second window scanned
    assert {labels for _, labels, _ in _FakeGliner.calls} == {tuple(gb.LABELS)}
    assert len(_FakeGliner.calls) == len(list(gb.windows(text)))  # one language pass


def test_model_threshold_ignores_config(fake_gliner):
    cfg = Config(languages=["en"], ner_backend="gliner").merged_with(
        {"score_thresholds": {"PERSON": 0.35}})
    ScrubEngine(cfg).detect("hello Jean Dupont")
    assert _FakeGliner.calls[0][2] == gb.MODEL_FLOOR  # never the config's: shared analyzer


def test_missing_package_explains_the_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "gliner", None)  # import fails
    eng = ScrubEngine(Config(languages=["en"], ner_backend="gliner"))
    with pytest.raises(RuntimeError, match=r"pii-airlock\[gliner\]"):
        eng.detect("Jean Dupont")


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="ner_backend"):
        ScrubEngine(Config(languages=["en"], ner_backend="bert")).detect("x y")


def test_email_tagged_address_is_left_to_patterns(fake_gliner):
    eng = ScrubEngine(Config(languages=["en"], ner_backend="gliner"))
    assert {d.entity_type for d in eng.detect("write jean@acme.fr")} == {"EMAIL_ADDRESS"}


def test_context_words_still_boost_weak_patterns(fake_gliner):
    eng = ScrubEngine(Config(languages=["en"], ner_backend="gliner",
                             builtin_recognizers=False))
    text = "Michael called from +44 20 7946 0958 about it."
    assert "PHONE_NUMBER" in {d.entity_type for d in eng.detect(text)}


@pytest.mark.parametrize("span, proper", [
    ("Michelin", True), ("Banque Cantonale Vaudoise", True), ("New York", True),
    ("L'entreprise", False), ("la société", False), ("client", False),
    ("port 8080", False), ("d'Airbus", True), ("staging database", False),
])
def test_proper_noun(span, proper):
    assert gb.proper_noun(span) is proper
