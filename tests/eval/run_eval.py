"""Detection quality harness: per-entity recall/precision on a labeled EN+FR corpus.

    python -m tests.eval.run_eval                 # report
    python -m tests.eval.run_eval --gate          # exit 1 if below thresholds.json
    python -m tests.eval.run_eval -v              # also list misses and false positives
    python -m tests.eval.run_eval --models en=en_core_web_lg,fr=fr_core_news_lg
    python -m tests.eval.run_eval --backend gliner   # needs pii-airlock[gliner]

The corpus (corpus.jsonl) holds only fake data. Each case lists the PII values
that appear in its text; every occurrence of a value is a gold span.

Metrics, per entity type:
  recall     gold spans overlapped by a detection of the same type
  precision  detections overlapping a gold span of the same type
  leak-free  gold spans fully covered by detections of *any* type (what matters
             for privacy: a PERSON tokenized as LOCATION is still hidden)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path

from pii_scrub.config import Config
from pii_scrub.engine import ScrubEngine

HERE = Path(__file__).parent
CORPUS = HERE / "corpus.jsonl"
THRESHOLDS = HERE / "thresholds.json"
SMALL_MODELS = {"en": "en_core_web_sm", "fr": "fr_core_news_sm"}


@dataclass
class Stats:
    gold: int = 0
    found: int = 0       # gold spans hit by a same-type detection
    covered: int = 0     # gold spans fully covered by any detection
    detected: int = 0
    correct: int = 0     # detections hitting a same-type gold span

    @property
    def recall(self) -> float:
        return self.found / self.gold if self.gold else 1.0

    @property
    def leak_free(self) -> float:
        return self.covered / self.gold if self.gold else 1.0

    @property
    def precision(self) -> float:
        return self.correct / self.detected if self.detected else 1.0


@dataclass
class Report:
    per_entity: dict[str, Stats] = field(default_factory=lambda: defaultdict(Stats))
    total: Stats = field(default_factory=Stats)
    misses: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)


def load_corpus(path: Path = CORPUS) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def gold_spans(case: dict) -> list[tuple[str, int, int]]:
    """Every occurrence of every labeled value, as (entity, start, end)."""
    text, spans = case["text"], set()
    for entity, value in case["pii"]:
        for m in re.finditer(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text):
            spans.add((entity, m.start(), m.end()))
    return sorted(spans, key=lambda s: s[1])


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def available_models(models: dict[str, str]) -> dict[str, str]:
    return {lang: m for lang, m in models.items() if find_spec(m) is not None}


def evaluate(cases: list[dict], models: dict[str, str], backend: str = "spacy") -> Report:
    if backend == "spacy":
        models = available_models(models)
    engine = ScrubEngine(Config(languages=list(models), models=models, ner_backend=backend))
    report = Report()
    for case in cases:
        text = case["text"]
        gold = gold_spans(case)
        dets = [(d.entity_type, d.start, d.end) for d in engine.detect(text)]
        for entity, start, end in gold:
            stats = (report.per_entity[entity], report.total)
            hit = any(t == entity and _overlap((s, e), (start, end)) for t, s, e in dets)
            covered = _covered(start, end, [(s, e) for _, s, e in dets])
            for st in stats:
                st.gold += 1
                st.found += hit
                st.covered += covered
            if not hit:
                kind = "LEAK" if not covered else "mistyped"
                report.misses.append(f"[{case['id']}] {kind} {entity}: {text[start:end]!r}")
        for entity, start, end in dets:
            ok = any(t == entity and _overlap((start, end), (s, e)) for t, s, e in gold)
            for st in (report.per_entity[entity], report.total):
                st.detected += 1
                st.correct += ok
            if not ok:
                report.false_positives.append(
                    f"[{case['id']}] extra {entity}: {text[start:end]!r}"
                )
    return report


def _covered(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    """Whether [start, end) is fully inside the union of `spans`."""
    pos = start
    for s, e in sorted(spans):
        if s <= pos < e:
            pos = e
    return pos >= end


def format_report(report: Report, verbose: bool = False) -> str:
    rows = [f"{'entity':<16}{'gold':>5}{'recall':>9}{'leak-free':>11}{'precision':>11}"]
    for entity, st in sorted(report.per_entity.items()):
        rows.append(
            f"{entity:<16}{st.gold:>5}{st.recall:>9.2f}{st.leak_free:>11.2f}{st.precision:>11.2f}"
        )
    t = report.total
    rows.append(f"{'ALL':<16}{t.gold:>5}{t.recall:>9.2f}{t.leak_free:>11.2f}{t.precision:>11.2f}")
    if verbose:
        rows += ["", "Misses:", *report.misses, "", "Extra detections:", *report.false_positives]
    return "\n".join(rows)


def check_gate(report: Report, thresholds: dict) -> list[str]:
    """Return failure messages for every metric below its threshold."""
    failures = []
    for entity, floors in thresholds.items():
        st = report.total if entity == "ALL" else report.per_entity.get(entity, Stats())
        for metric, floor in floors.items():
            value = getattr(st, metric)
            if value + 1e-9 < floor:
                failures.append(f"{entity} {metric} {value:.2f} < {floor:.2f}")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gate", action="store_true", help="exit 1 if below thresholds.json")
    ap.add_argument("-v", "--verbose", action="store_true", help="list misses and extras")
    ap.add_argument("--models", help="lang=model pairs, e.g. en=en_core_web_lg,fr=fr_core_news_lg")
    ap.add_argument("--backend", choices=["spacy", "gliner"], default="spacy")
    args = ap.parse_args(argv)

    models = dict(SMALL_MODELS)
    if args.models:
        models = dict(pair.split("=", 1) for pair in args.models.split(","))
    missing = sorted(set(models) - set(available_models(models)))
    if missing and args.backend == "spacy":
        print(f"warning: models not installed for {missing}; those cases are scored anyway",
              file=sys.stderr)
    report = evaluate(load_corpus(), models, args.backend)
    print(format_report(report, args.verbose))
    if args.gate:
        failures = check_gate(report, json.loads(THRESHOLDS.read_text("utf-8")))
        if failures:
            print("\nGATE FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
            return 1
        print("\ngate ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
