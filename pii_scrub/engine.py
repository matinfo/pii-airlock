"""ScrubEngine: Presidio detection + reversible, deterministic scrubbing.

We build a multilingual Presidio AnalyzerEngine and do the span replacement
*manually* (rather than via presidio-anonymizer) so we keep full control over
token format and reversibility through a Mapping.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import Counter, OrderedDict
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import TypeVar

from .config import Config, load_config
from .mapping import Mapping
from .recognizers import Finding, detect_builtin, detect_fallback

T = TypeVar("T")


class PolicyBlocked(Exception):
    """Text holds an entity whose `entity_actions` policy is `block`.

    Not a RuntimeError: callers report it as a refusal, not a detection failure.
    """

    def __init__(self, found: Counter) -> None:
        self.found = found
        summary = ", ".join(f"{t}×{n}" for t, n in found.most_common())
        super().__init__(f"blocked by policy (entity_actions): {summary}")


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

    def __init__(self, config: Config | None = None, *, regex_only: bool = False) -> None:
        self.config = config or load_config()
        # No spaCy: pattern recognizers only (fast start, but names are missed).
        self.regex_only = regex_only
        # spaCy pipelines are not thread-safe; serialize analysis so the engine
        # can be shared across threads (e.g. the proxy's request handlers).
        self._lock = threading.Lock()
        # Model findings per (language, entities, text digest), most recent last.
        # Chat clients resend the whole conversation every turn: without this,
        # each request re-runs spaCy over the entire history.
        self._cache: OrderedDict[tuple, tuple[Finding, ...]] = OrderedDict()

    # --- lazy, expensive Presidio objects --------------------------------

    @cached_property
    def _analyzer(self):
        backend = self.config.ner_backend
        if backend == "gliner":
            from .gliner_backend import build_analyzer

            return build_analyzer(self.config)
        if backend != "spacy":
            raise ValueError(f"ner_backend must be spacy or gliner, not {backend!r}")
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

    def load(self) -> None:
        """Load the models now rather than on the first detection."""
        if not self.regex_only:
            with self._lock:
                self._analyzer  # noqa: B018 - builds the cached analyzer

    def with_config(self, config: Config) -> ScrubEngine:
        """An engine applying `config`'s policy with this engine's loaded models.

        `config` must use the same languages and models; the model findings
        cache is shared too (it holds unfiltered findings, policy applies later).
        """
        other = ScrubEngine(config, regex_only=self.regex_only)
        other._lock, other._cache = self._lock, self._cache
        if "_analyzer" in self.__dict__:
            other.__dict__["_analyzer"] = self._analyzer
        return other

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
        cfg = self.config
        return [d for d in rules.filter(text, found) + rules.match(text)
                if cfg.action_for(d.entity_type) != "allow"]

    def _analyze(self, text: str, language: str | None = None) -> list[Detection]:
        """Model (Presidio) detections above the configured score threshold.

        With no `language`, every configured language is analyzed and the
        results are unioned: mixed EN/FR text is common and a single-language
        pass silently misses names in the other language.
        """
        findings: list[Finding] = []
        if self.regex_only:
            findings.extend(detect_fallback(text))
        else:
            for lang in self._langs(language):
                findings.extend(self._model_findings(text, lang))
        if self.config.builtin_recognizers:
            findings.extend(detect_builtin(text))
        # Pattern recognizers run once per language: collapse identical spans.
        best: dict[tuple[str, int, int], float] = {}
        for entity_type, start, end, score in findings:
            if self._keep(entity_type, score):
                key = (entity_type, start, end)
                best[key] = max(score, best.get(key, 0.0))
        return [Detection(t, s, e, score) for (t, s, e), score in best.items()]

    def _langs(self, language: str | None) -> list[str]:
        if self.config.ner_backend == "gliner":
            return self.config.languages[:1]  # one multilingual model: one pass
        return [language] if language else (self.languages or self.config.languages[:1])

    def _cache_key(self, text: str, lang: str) -> tuple:
        # A digest, not the text: the cache keeps no copy of the PII it saw.
        digest = hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=16)
        return (lang, tuple(self.config.entities), digest.digest())

    def _cache_put(self, key: tuple, results) -> tuple[Finding, ...]:
        findings = tuple((r.entity_type, r.start, r.end, r.score) for r in results)
        if self.config.analysis_cache_size > 0:
            self._cache[key] = findings
            while len(self._cache) > self.config.analysis_cache_size:
                self._cache.popitem(last=False)
        return findings

    def _model_findings(self, text: str, lang: str) -> tuple[Finding, ...]:
        """Presidio findings for one language, unfiltered (the policy applies later)."""
        key = self._cache_key(text, lang)
        # The lock also guards the first lazy build of _analyzer.
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            results = self._analyzer.analyze(
                text=text, language=lang, entities=self.config.entities or None
            )
            return self._cache_put(key, results)

    def prime(self, texts: Iterable[str], language: str | None = None) -> None:
        """Analyze `texts` as one spaCy batch per language and cache the findings.

        Call it before scrubbing many strings (a chat payload, CSV cells): spaCy's
        batched pipeline is about twice as fast as one call per string. At most
        what the cache holds is primed, so no primed entry is evicted before use.
        """
        if self.regex_only:
            return
        langs = self._langs(language)
        limit = self.config.analysis_cache_size // max(len(langs), 1)
        unique = list(dict.fromkeys(t for t in texts if t.strip()))[:limit]
        if len(unique) < 2:
            return
        entities = self.config.entities or None
        with self._lock:
            analyzer = self._analyzer
            nlp_engine = getattr(analyzer, "nlp_engine", None)
            if nlp_engine is None:
                return
            for lang in langs:
                todo = []
                for text in unique:
                    key = self._cache_key(text, lang)
                    if key in self._cache:
                        self._cache.move_to_end(key)  # keep it past this batch's inserts
                    else:
                        todo.append((text, key))
                if not todo:
                    continue
                batch = nlp_engine.process_batch(
                    texts=[t for t, _ in todo], language=lang, batch_size=32
                )
                for (text, key), (_, artifacts) in zip(todo, batch, strict=True):
                    self._cache_put(key, analyzer.analyze(
                        text=text, language=lang, entities=entities, nlp_artifacts=artifacts
                    ))

    def _keep(self, entity_type: str, score: float) -> bool:
        """Drop allowed entities (see Config.action_for), apply thresholds."""
        cfg = self.config
        if cfg.action_for(entity_type) == "allow":
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
        detections = self.detect(text, language, mapping.items())
        self._check_blocked(detections)
        return apply_detections(text, detections, mapping, self._redacted())

    def _redacted(self) -> frozenset[str]:
        return frozenset(e for e, a in self.config.entity_actions.items() if a == "redact")

    def _check_blocked(self, detections: Iterable[Detection]) -> None:
        """Raise PolicyBlocked if any detection's entity has the `block` action."""
        blocked = Counter(d.entity_type for d in detections
                          if self.config.action_for(d.entity_type) == "block")
        if blocked:
            raise PolicyBlocked(blocked)

    def scrub_all(
        self,
        run: Callable[[Callable[[str], str]], T],
        mapping: Mapping,
        texts: Iterable[str] | None = None,
    ) -> T:
        """Scrub every string `run` passes to its transform; return what `run` returns.

        All strings are analyzed first (one batch), and every value found in any
        of them is scrubbed in all of them: NER that finds "Jean Dupont" only in
        the last message would otherwise leave "Dupont" in clear in the first.
        `texts` are the strings `run` will pass, if already known; by default
        `run` is dry-run once to list them, so it must have no side effects
        (see collect_texts).
        """
        texts = list(dict.fromkeys(collect_texts(run) if texts is None else texts))
        self.prime(texts)
        found = [(t, d) for t in texts for d in self.detect(t)]
        self._check_blocked(d for _, d in found)  # before anything is minted
        known = list(dict.fromkeys((d.entity_type, d.text(t)) for t, d in found))
        redacted = self._redacted()
        mapping.learn([k for k in known if k[0] not in redacted], texts)
        return run(lambda t: apply_detections(
            t, self.detect(t, known=[*known, *mapping.items()]), mapping, redacted
        ))


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


@lru_cache(maxsize=16)
def _propagation_regex(terms: tuple[tuple[str, bool], ...]) -> re.Pattern:
    """One whole-word regex for (term, case_insensitive) pairs, longest first."""
    def alt(items):
        return "|".join(re.escape(t) for t in sorted(items, key=len, reverse=True))

    folded = [t for t, ci in terms if ci]
    exact = [t for t, ci in terms if not ci]
    parts = ([f"(?i:{alt(folded)})"] if folded else []) + ([alt(exact)] if exact else [])
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)")


def _propagate(
    text: str, detections: list[Detection], known: Iterable[tuple[str, str]]
) -> list[Detection]:
    """Find other mentions of values already detected (and of person-name parts).

    Case: parts of a multi-word person name and the full name match in any case
    ("Dupont", "dupont", "DUPONT" after "Jean Dupont"). A value found alone
    ("Will", "Server") matches its exact spelling only: NER false positives on
    common words would otherwise blank out every "will" and "server" in the
    request, code included.
    """
    terms: dict[tuple[str, bool], tuple[str, float]] = {}

    def add(entity: str, value: str, score: float) -> None:
        value = value.strip()
        if len(value) < _MIN_TERM:
            return
        multiword = entity == "PERSON" and len(value.split()) > 1
        key = (value.casefold() if multiword else value, multiword)
        terms.setdefault(key, (entity, score))
        if multiword:
            for part in _name_parts(value):
                terms.setdefault((part.casefold(), True), (entity, score))

    for d in detections:
        add(d.entity_type, text[d.start : d.end], d.score)
    for entity, value in known:
        add(entity, value, 0.85)
    if not terms:
        return []
    rx = _propagation_regex(tuple(sorted(terms)))
    lookup = {(t.casefold() if ci else t, ci): v for (t, ci), v in terms.items()}
    taken = [(d.start, d.end) for d in detections]
    out = []
    for m in rx.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue  # already detected
        word = m.group(0)
        entity, score = lookup.get((word.casefold(), True)) or lookup[(word, False)]
        out.append(Detection(entity, m.start(), m.end(), score))
    return out


def _term_re(term: str) -> re.Pattern:
    """Whole-word, case-insensitive match of a literal term."""
    return re.compile(r"(?<!\w)" + re.escape(str(term).strip()) + r"(?!\w)", re.IGNORECASE)


def apply_detections(
    text: str,
    detections: list[Detection],
    mapping: Mapping,
    redact: Collection[str] = (),
) -> str:
    """Replace `detections` in `text` with tokens from `mapping`.

    Entities in `redact` become ``[ENTITY]`` instead: irreversible, and the
    value is never stored in the mapping (nor in a saved mapping file).
    """
    mapping.reserve(text)
    spans = sorted(_dedupe_overlaps(detections), key=lambda x: x.start)
    # Mint in reading order (<PERSON_1> is the first person mentioned), then
    # build the output in one pass.
    parts, pos = [], 0
    for d in spans:
        if d.entity_type in redact:
            replacement = f"[{d.entity_type}]"
        else:
            replacement = mapping.token_for(d.entity_type, text[d.start : d.end])
        parts += [text[pos : d.start], replacement]
        pos = d.end
    parts.append(text[pos:])
    return "".join(parts)


def collect_texts(run: Callable[[Callable[[str], str]], object]) -> list[str]:
    """The strings `run` passes to its transform, run once with an identity transform.

    `run` must have no side effects, e.g. a payload adapter building a new body:
    ``collect_texts(lambda f: scrub_payload(body, adapter, f))`` lists what a real
    scrub of `body` will analyze, so it can be primed as one batch.
    """
    texts: list[str] = []

    def grab(text: str) -> str:
        texts.append(text)
        return text

    run(grab)
    return texts


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
