"""ScrubEngine: Presidio detection + reversible, deterministic scrubbing.

We build a multilingual Presidio AnalyzerEngine and do the span replacement
*manually* (rather than via presidio-anonymizer) so we keep full control over
token format and reversibility through a Mapping.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property

from .config import Config, load_config
from .mapping import Mapping
from .recognizers import detect_builtin


@dataclass
class Detection:
    entity_type: str
    start: int
    end: int
    score: float

    def text(self, source: str) -> str:
        return source[self.start : self.end]


class ScrubEngine:
    """Detect and scrub PII across the configured languages."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        # spaCy pipelines are not thread-safe; serialize analysis so the engine
        # can be shared across threads (e.g. the proxy's request handlers).
        self._lock = threading.Lock()

    # --- lazy, expensive Presidio objects --------------------------------

    @cached_property
    def _analyzer(self):
        # Imported lazily so that `--help` and config-only paths stay fast.
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        models = [
            {"lang_code": lang, "model_name": self.config.models[lang]}
            for lang in self.config.languages
            if lang in self.config.models
        ]
        if not models:
            raise RuntimeError(
                "No spaCy models configured for languages "
                f"{self.config.languages}. Check `models:` in your config."
            )
        missing = [m["model_name"] for m in models if not _model_available(m["model_name"])]
        if missing:
            # Fail here: Presidio would otherwise try to download the model, and
            # spaCy's downloader prints to stdout and calls sys.exit().
            raise RuntimeError(
                f"spaCy model(s) not installed: {', '.join(missing)}. "
                "Run `pii-airlock download-models`."
            )
        languages = [m["lang_code"] for m in models]
        provider = NlpEngineProvider(
            nlp_configuration={"nlp_engine_name": "spacy", "models": models}
        )
        nlp_engine = provider.create_engine()
        return AnalyzerEngine(
            nlp_engine=nlp_engine,
            registry=_build_registry(languages, nlp_engine),
            supported_languages=languages,
        )

    @property
    def languages(self) -> list[str]:
        """Configured languages that have a spaCy model."""
        return [lang for lang in self.config.languages if lang in self.config.models]

    # --- public API -------------------------------------------------------

    @cached_property
    def _rules(self) -> _Rules:
        return _Rules.from_config(self.config)

    def detect(
        self,
        text: str,
        language: str | None = None,
        known: Iterable[tuple[str, str]] = (),
    ) -> list[Detection]:
        """Return PII detections: model findings filtered by the policy, plus rules.

        Every value found is also matched wherever else it appears, with the
        parts of person names ("Dupont" after "Jean Dupont"): NER often finds a
        name once and misses its other mentions. `known` adds (entity, value)
        pairs found earlier, e.g. in previous messages of the same request.

        Model detections inside an ``allow_list`` term are dropped; ``deny_list``
        terms and ``custom_patterns`` are always reported (score 1.0 by default).
        """
        if not text.strip():
            return []
        rules = self._rules
        found = self._analyze(text, language)
        found += _propagate(text, found, known)
        return rules.filter(text, found) + rules.match(text)

    def _analyze(self, text: str, language: str | None = None) -> list[Detection]:
        """Model (Presidio) detections above the configured score threshold.

        With no `language`, every configured language is analyzed and the
        results are unioned: mixed EN/FR text is common and a single-language
        pass silently misses names in the other language.
        """
        langs = [language] if language else (self.languages or self.config.languages[:1])
        entities = self.config.entities or None
        results = []
        # The lock also guards the first lazy build of _analyzer.
        with self._lock:
            for lang in langs:
                results.extend(
                    self._analyzer.analyze(text=text, language=lang, entities=entities)
                )
        findings = [(r.entity_type, r.start, r.end, r.score) for r in results]
        if self.config.builtin_recognizers:
            findings.extend(detect_builtin(text))
        # Pattern recognizers run once per language: collapse identical spans.
        best: dict[tuple[str, int, int], float] = {}
        for entity_type, start, end, score in findings:
            if self._keep(entity_type, score):
                key = (entity_type, start, end)
                best[key] = max(score, best.get(key, 0.0))
        return [Detection(t, s, e, score) for (t, s, e), score in best.items()]

    def _keep(self, entity_type: str, score: float) -> bool:
        """Apply `exclude_entities` (unless asked for in `entities`) and thresholds."""
        cfg = self.config
        if entity_type in cfg.exclude_entities and entity_type not in cfg.entities:
            return False
        return score >= cfg.score_thresholds.get(entity_type, cfg.score_threshold)

    def scrub(
        self,
        text: str,
        mapping: Mapping,
        language: str | None = None,
    ) -> str:
        """Replace detected PII spans with deterministic tokens from `mapping`.

        Overlapping detections are de-duplicated (highest score wins); spans are
        replaced right-to-left so earlier offsets stay valid.
        """
        return apply_detections(text, self.detect(text, language, mapping.items()), mapping)


@dataclass
class _Rules:
    """Compiled policy: allow-list terms, deny-list terms, custom patterns."""

    allow: list[re.Pattern]
    match_rules: list[tuple[str, re.Pattern, float]]

    @classmethod
    def from_config(cls, config: Config) -> _Rules:
        allow = [_term_re(t) for t in config.allow_list if str(t).strip()]
        rules = [
            (entity, _term_re(term), 1.0)
            for entity, terms in config.deny_list.items()
            for term in terms if str(term).strip()
        ]
        for spec in config.custom_patterns:
            try:
                entity = str(spec["entity"]).upper()
                pattern = re.compile(spec["regex"])
            except (KeyError, TypeError, re.error) as exc:
                raise ValueError(
                    f"Invalid custom_patterns entry {spec!r}: needs `entity` and a valid "
                    f"`regex` ({exc})"
                ) from None
            rules.append((entity, pattern, float(spec.get("score", 1.0))))
        return cls(allow, rules)

    def filter(self, text: str, detections: list[Detection]) -> list[Detection]:
        if not self.allow:
            return detections
        spans = [m.span() for rx in self.allow for m in rx.finditer(text)]
        return [d for d in detections
                if not any(s <= d.start and d.end <= e for s, e in spans)]

    def match(self, text: str) -> list[Detection]:
        return [
            Detection(entity, m.start(), m.end(), score)
            for entity, rx, score in self.match_rules
            for m in rx.finditer(text)
            if m.end() > m.start()
        ]


# Name particles and titles: never propagated on their own.
_NAME_STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "van", "von", "der", "den", "di", "da", "del",
    "dos", "mr", "mrs", "ms", "dr", "mme", "mlle", "m", "herr", "frau", "prof",
}
_MIN_TERM = 3


def _name_parts(value: str) -> list[str]:
    parts = re.split(r"\s+", value.strip())
    if len(parts) < 2:
        return []
    return [
        p for p in parts
        if len(p) >= _MIN_TERM and p[0].isupper()
        and p.rstrip(".").casefold() not in _NAME_STOPWORDS
    ]


def _propagate(
    text: str, detections: list[Detection], known: Iterable[tuple[str, str]]
) -> list[Detection]:
    """Find other mentions of values already detected (and of person-name parts)."""
    terms: dict[str, tuple[str, float]] = {}

    def add(entity: str, value: str, score: float) -> None:
        value = value.strip()
        if len(value) >= _MIN_TERM and value.casefold() not in terms:
            terms[value.casefold()] = (entity, score)
        if entity == "PERSON":
            for part in _name_parts(value):
                terms.setdefault(part.casefold(), (entity, score))

    for d in detections:
        add(d.entity_type, text[d.start : d.end], d.score)
    for entity, value in known:
        add(entity, value, 0.85)
    if not terms:
        return []
    alternation = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    rx = re.compile(r"(?<!\w)(?:" + alternation + r")(?!\w)", re.IGNORECASE)
    taken = [(d.start, d.end) for d in detections]
    out = []
    for m in rx.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue  # already detected
        entity, score = terms[m.group(0).casefold()]
        out.append(Detection(entity, m.start(), m.end(), score))
    return out


def _term_re(term: str) -> re.Pattern:
    """Whole-word, case-insensitive match of a literal term."""
    return re.compile(r"(?<!\w)" + re.escape(str(term).strip()) + r"(?!\w)", re.IGNORECASE)


def apply_detections(text: str, detections: list[Detection], mapping: Mapping) -> str:
    """Replace `detections` in `text` with tokens from `mapping`."""
    mapping.reserve(text)
    spans = sorted(_dedupe_overlaps(detections), key=lambda x: x.start)
    # Mint in reading order (<PERSON_1> is the first person mentioned), then
    # build the output in one pass.
    parts, pos = [], 0
    for d in spans:
        parts += [text[pos : d.start], mapping.token_for(d.entity_type, text[d.start : d.end])]
        pos = d.end
    parts.append(text[pos:])
    return "".join(parts)


def _model_available(model: str) -> bool:
    """Whether a spaCy model name (installed package) or path can be loaded."""
    import importlib.util
    from pathlib import Path

    return importlib.util.find_spec(model) is not None or Path(model).is_dir()


def _build_registry(languages: list[str], nlp_engine):
    """Presidio registry with pattern recognizers for *every* configured language.

    Presidio's bundled recognizer list defaults to English only, so a non-English
    language would otherwise lose email/phone/IBAN/credit-card detection.
    """
    from presidio_analyzer import RecognizerRegistry
    from presidio_analyzer.predefined_recognizers import CreditCardRecognizer

    registry = RecognizerRegistry(supported_languages=languages)
    registry.load_predefined_recognizers(languages=languages, nlp_engine=nlp_engine)
    have_cc = {
        r.supported_language for r in registry.recognizers
        if isinstance(r, CreditCardRecognizer)
    }
    for lang in languages:
        if lang not in have_cc:
            registry.add_recognizer(CreditCardRecognizer(supported_language=lang))
    return registry


def _dedupe_overlaps(detections: list[Detection]) -> list[Detection]:
    """Keep non-overlapping spans, preferring higher score then longer span."""
    chosen: list[Detection] = []
    for d in sorted(detections, key=lambda x: (-x.score, x.start - x.end)):
        if any(not (d.end <= c.start or d.start >= c.end) for c in chosen):
            continue
        chosen.append(d)
    return chosen
