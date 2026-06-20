"""Engine tests that avoid loading Presidio/spaCy.

We stub `ScrubEngine.detect` so the span-replacement and de-dup logic can be
tested fast and offline. A live end-to-end check belongs in the verification
suite (requires `pii-scrub download-models`).
"""

from pii_scrub.engine import Detection, ScrubEngine, _dedupe_overlaps
from pii_scrub.mapping import Mapping


def _engine_with(detections):
    eng = ScrubEngine()
    eng.detect = lambda text, language=None: detections  # type: ignore[method-assign]
    return eng


def test_scrub_replaces_spans_and_is_reversible():
    text = "Email Jean Dupont at jean@acme.fr"
    dets = [
        Detection("PERSON", 6, 17, 0.99),       # "Jean Dupont"
        Detection("EMAIL_ADDRESS", 21, 33, 0.99),  # "jean@acme.fr"
    ]
    eng = _engine_with(dets)
    m = Mapping()
    scrubbed = eng.scrub(text, m)
    assert "Jean Dupont" not in scrubbed
    assert "jean@acme.fr" not in scrubbed
    assert scrubbed == "Email <PERSON_1> at <EMAIL_ADDRESS_1>"
    assert m.restore(scrubbed) == text


def test_scrub_deterministic_repeats():
    text = "Jean and Jean"
    dets = [Detection("PERSON", 0, 4, 0.9), Detection("PERSON", 9, 13, 0.9)]
    eng = _engine_with(dets)
    m = Mapping()
    assert eng.scrub(text, m) == "<PERSON_1> and <PERSON_1>"


def test_dedupe_prefers_higher_score():
    overlapping = [
        Detection("PERSON", 0, 10, 0.6),
        Detection("LOCATION", 3, 8, 0.9),
    ]
    kept = _dedupe_overlaps(overlapping)
    assert len(kept) == 1
    assert kept[0].entity_type == "LOCATION"
