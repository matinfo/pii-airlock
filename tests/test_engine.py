"""Engine tests that avoid loading Presidio/spaCy.

We stub `ScrubEngine.detect` so the span-replacement and de-dup logic can be
tested fast and offline. A live end-to-end check belongs in the verification
suite (requires `pii-airlock download-models`).
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


def test_detect_serializes_concurrent_calls():
    """The engine lock must prevent concurrent entry into the (unsafe) analyzer."""
    import threading
    import time

    class FakeAnalyzer:
        def __init__(self):
            self.inside = 0
            self.max_concurrent = 0

        def analyze(self, text, language, entities):
            self.inside += 1
            self.max_concurrent = max(self.max_concurrent, self.inside)
            time.sleep(0.005)  # widen the race window
            self.inside -= 1
            return []

    eng = ScrubEngine()
    fake = FakeAnalyzer()
    eng.__dict__["_analyzer"] = fake  # prime cached_property, bypass real build

    threads = [threading.Thread(target=lambda: eng.detect("x", "en")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fake.max_concurrent == 1  # never two threads inside analyze at once


def _engine_returning(results, **config):
    """Engine whose analyzer returns fixed Presidio-like results."""
    from types import SimpleNamespace

    from pii_scrub.config import Config

    eng = ScrubEngine(Config(languages=["en"], **config))
    eng.__dict__["_analyzer"] = SimpleNamespace(
        analyze=lambda text, language, entities: [
            SimpleNamespace(entity_type=t, start=s, end=e, score=sc) for t, s, e, sc in results
        ]
    )
    return eng


def test_noisy_entities_excluded_by_default():
    eng = _engine_returning([("URL", 0, 5, 0.9), ("DATE_TIME", 6, 8, 0.9),
                             ("EMAIL_ADDRESS", 9, 12, 0.9)])
    assert [d.entity_type for d in eng.detect("x" * 20)] == ["EMAIL_ADDRESS"]


def test_explicit_entities_override_exclusion():
    eng = _engine_returning([("URL", 0, 5, 0.9)], entities=["URL"])
    assert [d.entity_type for d in eng.detect("x" * 20)] == ["URL"]
    eng = _engine_returning([("URL", 0, 5, 0.9)], exclude_entities=[])
    assert [d.entity_type for d in eng.detect("x" * 20)] == ["URL"]


def test_per_entity_score_thresholds():
    from pii_scrub.config import Config

    cfg = Config(languages=["en"]).merged_with({"score_thresholds": {"person": 0.8}})
    eng = _engine_returning([("PERSON", 0, 4, 0.7), ("PHONE_NUMBER", 5, 9, 0.6)])
    eng.config = cfg
    assert [d.entity_type for d in eng.detect("x" * 20)] == ["PHONE_NUMBER"]
