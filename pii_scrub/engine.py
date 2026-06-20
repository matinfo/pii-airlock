"""ScrubEngine: Presidio detection + reversible, deterministic scrubbing.

We build a multilingual Presidio AnalyzerEngine and do the span replacement
*manually* (rather than via presidio-anonymizer) so we keep full control over
token format and reversibility through a Mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .config import Config, load_config
from .mapping import Mapping


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
        provider = NlpEngineProvider(
            nlp_configuration={"nlp_engine_name": "spacy", "models": models}
        )
        nlp_engine = provider.create_engine()
        return AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=[m["lang_code"] for m in models],
        )

    # --- public API -------------------------------------------------------

    def detect(self, text: str, language: str | None = None) -> list[Detection]:
        """Return PII detections above the configured score threshold."""
        if not text.strip():
            return []
        lang = language or self.config.languages[0]
        entities = self.config.entities or None
        results = self._analyzer.analyze(text=text, language=lang, entities=entities)
        return [
            Detection(r.entity_type, r.start, r.end, r.score)
            for r in results
            if r.score >= self.config.score_threshold
        ]

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
        detections = self.detect(text, language)
        detections = _dedupe_overlaps(detections)
        out = text
        for d in sorted(detections, key=lambda x: x.start, reverse=True):
            token = mapping.token_for(d.entity_type, text[d.start : d.end])
            out = out[: d.start] + token + out[d.end :]
        return out


def _dedupe_overlaps(detections: list[Detection]) -> list[Detection]:
    """Keep non-overlapping spans, preferring higher score then longer span."""
    chosen: list[Detection] = []
    for d in sorted(detections, key=lambda x: (-x.score, x.start - x.end)):
        if any(not (d.end <= c.start or d.start >= c.end) for c in chosen):
            continue
        chosen.append(d)
    return chosen
