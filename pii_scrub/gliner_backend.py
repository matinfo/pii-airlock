"""GLiNER NER backend (``ner_backend: gliner``).

One multilingual model (default ``urchade/gliner_multi_pii-v1``) finds people,
organizations and places in any language, instead of one spaCy model per
language. spaCy then only tokenizes (a blank pipeline: no model to download);
Presidio's pattern recognizers and the built-in ones still find emails,
phones, IDs and secrets.

Our own recognizer rather than Presidio's GLiNERRecognizer, which asks the
model for every Presidio entity (slower, duplicates the pattern recognizers)
and passes long texts whole: GLiNER truncates input to a few hundred words, so
a name on page two would go unseen. We scan long texts in overlapping windows.

Install with ``pip install 'pii-airlock[gliner]'`` (pulls PyTorch); the model
is downloaded on first use, or by ``pii-airlock download-models``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# GLiNER label -> Presidio entity. NER entities only: patterns cover the rest.
LABELS: dict[str, str] = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "location": "LOCATION",
    "address": "LOCATION",
}

# Lowest score asked of the model (Presidio's own default); thresholds below it
# have no effect.
MODEL_FLOOR = 0.3

# Characters per window, well under the model's ~384-token limit, and overlap
# so an entity cut by one window boundary is whole in the next.
WINDOW = 1000
OVERLAP = 200


def windows(text: str, size: int = WINDOW, overlap: int = OVERLAP) -> Iterator[tuple[int, str]]:
    """(offset, piece) covering `text`; pieces end and start at whitespace."""
    start = 0
    while True:
        end = len(text) if len(text) - start <= size else start + size
        if end < len(text):
            cut = text.rfind(" ", start + overlap + 1, end)
            end = cut if cut > 0 else end
        yield start, text[start:end]
        if end >= len(text):
            return
        nxt = text.find(" ", max(end - overlap, start + 1), end)
        start = nxt + 1 if nxt >= 0 else end


_LEMMA = "pii_airlock_lowercase_lemma"
_ELISION = re.compile(r"^(?:[ldjmnst]|qu)['’]", re.IGNORECASE)


def proper_noun(span: str) -> bool:
    """Whether a span has a capitalized word (French elisions aside: L'entreprise).

    GLiNER tags common nouns as organizations or places with high scores
    ("la société" 0.55, "L'entreprise" 0.95, "port 8080" 0.83) that overlap
    real ones ("Michelin" 0.74): capitalization separates them, scores do not.
    Not applied to people, whose names users often type in lower case.
    """
    return any(w[:1].isupper() for w in (_ELISION.sub("", w) for w in span.split()))


def _blank_pipeline(lang: str):
    """spaCy tokenizer with lowercase words as lemmas.

    Presidio boosts weak pattern matches (a phone number scores 0.4) when a
    context word ("call", "tel") is near, comparing against lemmas; a blank
    pipeline has none, so without this "called +44 20 ..." would be dropped.
    """
    import spacy
    from spacy.language import Language

    if not Language.has_factory(_LEMMA):
        def lowercase_lemma(doc):
            for token in doc:
                token.lemma_ = token.lower_
            return doc

        Language.component(_LEMMA, func=lowercase_lemma)
    nlp = spacy.blank(lang)
    nlp.add_pipe(_LEMMA)
    return nlp


def require() -> None:
    try:
        import gliner  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "ner_backend: gliner needs the GLiNER package: "
            "pip install 'pii-airlock[gliner]' (or pipx inject pii-airlock gliner)"
        ) from None


def load_model(name: str):
    require()
    from gliner import GLiNER

    return GLiNER.from_pretrained(name)


def build_analyzer(config):
    """A Presidio AnalyzerEngine whose only NER is GLiNER."""
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
    from presidio_analyzer.local_recognizer import LocalRecognizer
    from presidio_analyzer.nlp_engine import SpacyNlpEngine

    lang = config.languages[0]
    model = load_model(config.gliner_model)
    # Fixed floor, never the config's thresholds: the daemon shares this analyzer
    # across projects, and the cache holds unfiltered findings. Policy filters later.
    entities = set(LABELS.values())
    threshold = MODEL_FLOOR

    class GlinerRecognizer(LocalRecognizer):
        def load(self) -> None:
            pass

        def analyze(self, text, entities, nlp_artifacts=None):
            results = []
            for offset, piece in windows(text):
                for p in model.predict_entities(piece, list(LABELS), threshold=threshold,
                                                flat_ner=True):
                    entity = LABELS.get(p["label"])
                    if entity is None or (entities and entity not in entities):
                        continue
                    if "@" in p["text"] or "://" in p["text"]:
                        continue  # an email or URL tagged "address": patterns own those
                    if entity != "PERSON" and not proper_noun(p["text"]):
                        continue
                    results.append(RecognizerResult(
                        entity, p["start"] + offset, p["end"] + offset, float(p["score"])
                    ))
            return results

    nlp_engine = SpacyNlpEngine(models=[{"lang_code": lang, "model_name": "blank"}])
    nlp_engine.nlp = {lang: _blank_pipeline(lang)}  # tokenizer only, nothing to download
    registry = RecognizerRegistry(supported_languages=[lang])
    registry.load_predefined_recognizers(languages=[lang], nlp_engine=nlp_engine)
    registry.remove_recognizer("SpacyRecognizer")  # the blank pipeline has no NER
    registry.add_recognizer(GlinerRecognizer(
        supported_entities=sorted(entities), name="GLiNER", supported_language=lang
    ))
    return AnalyzerEngine(nlp_engine=nlp_engine, registry=registry, supported_languages=[lang])
