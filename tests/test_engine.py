"""Engine tests that avoid loading Presidio/spaCy.

We stub `ScrubEngine.detect` so the span-replacement and de-dup logic can be
tested fast and offline. A live end-to-end check belongs in the verification
suite (requires `pii-airlock download-models`).
"""

import pytest

from pii_scrub.engine import Detection, ScrubEngine, _dedupe_overlaps
from pii_scrub.mapping import Mapping


def _engine_with(detections):
    eng = ScrubEngine()
    eng.detect = lambda text, language=None, known=(): detections  # type: ignore[method-assign]
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


def _engine_finding(value, entity="PERSON"):
    """Analyzer that detects only the first occurrence of `value` (like flaky NER)."""
    from types import SimpleNamespace

    from pii_scrub.config import Config

    def analyze(text, language, entities):
        i = text.find(value)
        return [] if i < 0 else [SimpleNamespace(entity_type=entity, start=i,
                                                 end=i + len(value), score=0.85)]

    eng = ScrubEngine(Config(languages=["en"], builtin_recognizers=False))
    eng.__dict__["_analyzer"] = SimpleNamespace(analyze=analyze)
    return eng


def test_other_mentions_and_name_parts_are_scrubbed():
    eng = _engine_finding("Jean Dupont")
    m = Mapping()
    out = eng.scrub("Jean Dupont called. Later M. Dupont, then JEAN DUPONT, wrote.", m)
    assert "Dupont" not in out and "DUPONT" not in out
    assert out.startswith("<PERSON_1> called.")
    assert "M. " in out  # title kept
    assert m.restore(out) == "Jean Dupont called. Later M. Dupont, then JEAN DUPONT, wrote."


def test_values_from_earlier_texts_are_scrubbed():
    eng = _engine_finding("Jean Dupont")
    m = Mapping()
    eng.scrub("From Jean Dupont", m)
    # This message alone has no model finding: the known value still applies.
    assert eng.scrub("Dupont says hi", m).startswith("<PERSON_")


def test_short_parts_and_particles_not_propagated():
    eng = _engine_finding("Anna de la Cruz")
    out = eng.scrub("Anna de la Cruz: de facto la decision", Mapping())
    assert out.endswith(": de facto la decision")


class _CountingAnalyzer:
    """Finds 'Jean' as PERSON; counts calls; batches through a fake nlp_engine."""

    def __init__(self, batched=True):
        from types import SimpleNamespace

        self.calls: list[str] = []
        self.batches: list[list[str]] = []
        if batched:
            self.nlp_engine = SimpleNamespace(process_batch=self._process_batch)

    def _process_batch(self, texts, language, batch_size):
        self.batches.append(list(texts))
        return ((t, f"artifacts:{t}") for t in texts)

    def analyze(self, text, language, entities, nlp_artifacts=None):
        from types import SimpleNamespace

        if nlp_artifacts is None:
            self.calls.append(text)
        else:
            assert nlp_artifacts == f"artifacts:{text}"
        i = text.find("Jean")
        return [] if i < 0 else [SimpleNamespace(entity_type="PERSON", start=i,
                                                 end=i + 4, score=0.85)]


def _caching_engine(analyzer, languages=("en",), **config):
    from pii_scrub.config import Config

    eng = ScrubEngine(Config(languages=list(languages), builtin_recognizers=False, **config))
    eng.__dict__["_analyzer"] = analyzer
    return eng


def test_repeated_text_is_analyzed_once():
    analyzer = _CountingAnalyzer()
    eng = _caching_engine(analyzer)
    first = eng.detect("Hi Jean")
    assert eng.detect("Hi Jean") == first
    eng.detect("Bye Jean")
    assert analyzer.calls == ["Hi Jean", "Bye Jean"]


def test_cache_keeps_no_text_and_policy_still_applies():
    analyzer = _CountingAnalyzer()
    eng = _caching_engine(analyzer)
    assert eng.detect("Hi Jean")
    assert not any("Jean" in repr(k) for k in eng._cache)
    eng.config = eng.config.merged_with({"allow_list": ["Jean"]})
    eng.__dict__.pop("_rules", None)
    assert eng.detect("Hi Jean") == []  # cached findings, re-filtered
    assert analyzer.calls == ["Hi Jean"]


def test_cache_is_bounded_and_can_be_disabled():
    analyzer = _CountingAnalyzer()
    eng = _caching_engine(analyzer, analysis_cache_size=2)
    for text in ["a Jean", "b Jean", "c Jean", "a Jean"]:
        eng.detect(text)
    assert len(eng._cache) == 2
    assert analyzer.calls == ["a Jean", "b Jean", "c Jean", "a Jean"]  # "a" was evicted

    analyzer = _CountingAnalyzer()
    eng = _caching_engine(analyzer, analysis_cache_size=0)
    eng.detect("Hi Jean")
    eng.detect("Hi Jean")
    assert analyzer.calls == ["Hi Jean", "Hi Jean"] and not eng._cache


def test_prime_batches_uncached_texts_per_language():
    analyzer = _CountingAnalyzer()
    eng = _caching_engine(analyzer, languages=("en", "fr"),
                          models={"en": "x", "fr": "y"})
    eng.detect("seen Jean")
    analyzer.calls.clear()
    eng.prime(["seen Jean", "one Jean", "two", "one Jean", "  "])
    assert analyzer.batches == [["one Jean", "two"], ["one Jean", "two"]]
    for text in ["seen Jean", "one Jean", "two"]:
        eng.detect(text)
    assert analyzer.calls == []  # every detect served from the cache
    assert [d.entity_type for d in eng.detect("one Jean")] == ["PERSON"]


def test_prime_never_exceeds_what_the_cache_holds():
    analyzer = _CountingAnalyzer()
    eng = _caching_engine(analyzer, languages=("en", "fr"), models={"en": "x", "fr": "y"},
                          analysis_cache_size=4)
    eng.prime([f"t{i}" for i in range(10)])
    assert analyzer.batches == [["t0", "t1"], ["t0", "t1"]]


def test_prime_without_batch_support_is_a_no_op():
    analyzer = _CountingAnalyzer(batched=False)
    eng = _caching_engine(analyzer)
    eng.prime(["a Jean", "b Jean"])
    assert not eng._cache and analyzer.calls == []


def test_collect_texts_lists_transformed_strings():
    from pii_scrub.engine import collect_texts
    from pii_scrub.payload import get_adapter, scrub_payload

    body = {"messages": [{"role": "user", "content": "hi"},
                         {"role": "user", "content": [{"type": "text", "text": "yo"}]}]}
    texts = collect_texts(lambda f: scrub_payload(body, get_adapter("anthropic"), f))
    assert {"hi", "yo"} <= set(texts)


def test_scrub_all_scrubs_values_found_later_in_earlier_texts():
    eng = _engine_finding("Jean Dupont")
    messages = ["Dupont asked for the file.", "OK.", "Signed: Jean Dupont"]
    m = Mapping()
    out = eng.scrub_all(lambda f: [f(t) for t in messages], m)
    assert "Dupont" not in " ".join(out)
    assert out[1] == "OK."
    assert [m.restore(t) for t in out] == messages


def test_scrub_all_uses_given_texts_without_a_dry_run():
    eng = _engine_finding("Jean Dupont")
    calls = []

    def run(f):
        calls.append(f)
        return f("Dupont, from Jean Dupont")

    out = eng.scrub_all(run, Mapping(), texts=["Dupont, from Jean Dupont"])
    assert len(calls) == 1 and "Dupont" not in out


def _actions_engine(actions, **config):
    from pii_scrub.config import Config

    cfg = Config(languages=["en"], builtin_recognizers=False,
                 **config).merged_with({"entity_actions": actions})
    eng = _engine_returning([("PERSON", 0, 4, 0.9), ("IBAN_CODE", 5, 9, 0.9)])
    eng.config = cfg
    return eng


def test_redact_is_irreversible_and_never_stored():
    eng = _actions_engine({"iban_code": "redact"})
    m = Mapping()
    out = eng.scrub("Jean 1234 ok", m)
    assert out == "<PERSON_1> [IBAN_CODE] ok"
    assert m.items() == [("PERSON", "Jean")]           # the IBAN is nowhere in the mapping
    assert "1234" not in str(m.to_dict())


def test_allow_overrides_default_and_replaces_exclusion():
    eng = _actions_engine({"PERSON": "allow"})
    assert [d.entity_type for d in eng.detect("Jean 1234 ok")] == ["IBAN_CODE"]
    # exclude_entities keeps working, and an explicit action beats it
    eng = _engine_returning([("URL", 0, 5, 0.9)])
    assert eng.detect("x" * 10) == []
    eng.config = eng.config.merged_with({"entity_actions": {"URL": "tokenize"}})
    assert [d.entity_type for d in eng.detect("x" * 10)] == ["URL"]


def test_block_raises_before_anything_is_minted():
    from pii_scrub.engine import PolicyBlocked

    eng = _actions_engine({"IBAN_CODE": "block"})
    m = Mapping()
    with pytest.raises(PolicyBlocked, match=r"IBAN_CODE×1") as exc:
        eng.scrub_all(lambda f: [f("fine Jean 1234 ok")], m)
    assert "1234" not in str(exc.value) and len(m) == 0
    with pytest.raises(PolicyBlocked):
        eng.scrub("Jean 1234 ok", Mapping())


def test_invalid_action_is_rejected_and_actions_accumulate():
    from pii_scrub.config import Config

    with pytest.raises(ValueError, match="not one of"):
        Config().merged_with({"entity_actions": {"PERSON": "delete"}})
    cfg = Config().merged_with({"entity_actions": {"person": "redact"}}).merged_with(
        {"entity_actions": {"IBAN_CODE": "block"}})
    assert cfg.entity_actions == {"PERSON": "redact", "IBAN_CODE": "block"}


def test_redacted_persons_never_reach_surrogate_fakes():
    eng = _engine_finding("Jean Dupont")
    eng.config = eng.config.merged_with({"entity_actions": {"PERSON": "redact"}})
    m = Mapping(b"k" * 32, surrogates=True)
    out = eng.scrub_all(lambda f: [f("Jean Dupont wrote")], m)
    assert out == ["[PERSON] wrote"] and "Dupont" not in str(m.to_dict())


def test_single_word_false_positive_does_not_blank_the_common_word():
    eng = _engine_finding("Will", entity="PERSON")
    out = eng.scrub("Will you check? I will, and the Will file.", Mapping())
    assert out.startswith("<PERSON_") and "I will," in out    # lower case untouched
    assert out.count("<PERSON_") == 2                          # exact "Will" still follows


def test_propagation_regex_is_compiled_once_for_many_texts():
    from pii_scrub import engine as engine_mod

    engine_mod._propagation_regex.cache_clear()
    eng = _engine_finding("Jean Dupont")
    texts = [f"msg {i}: Dupont wrote to Jean Dupont" for i in range(50)]
    eng.scrub_all(lambda f: [f(t) for t in texts], Mapping())
    assert engine_mod._propagation_regex.cache_info().misses <= 2


def test_phone_inside_an_iban_is_not_reported_separately(monkeypatch):
    text = "IBAN DE89 3704 0044 0532 0130 00"
    engine = ScrubEngine()
    monkeypatch.setattr(engine, "_model_findings", lambda t, lang: (
        ("IBAN_CODE", 5, 32, 1.0), ("PHONE_NUMBER", 20, 32, 0.8)))
    assert [d.entity_type for d in engine.detect(text)] == ["IBAN_CODE"]
