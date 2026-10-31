"""Built-in pattern recognizers that Presidio lacks: FR/CH identifiers and secrets.

Plain regex + checksum, no spaCy: they run for every language and cost
microseconds. Each rule may validate its match (checksum) and may report only
a capture group (e.g. the value after ``password=``, not the key name).

Secrets are not PII, but API keys and passwords are the most common sensitive
data in coding-agent traffic, so they get the same treatment.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# (entity_type, start, end, score)
Finding = tuple[str, int, int, float]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _valid_nir(match: str) -> bool:
    """French social security number: 13 chars + 2-digit key = 97 - (n mod 97)."""
    raw = re.sub(r"\s", "", match).upper()
    body, key = raw[:13], raw[13:]
    # Corsica: departments 2A / 2B are replaced by 19 / 18 for the key.
    body = body.replace("2A", "19", 1) if body[5:7] == "2A" else body
    body = body.replace("2B", "18", 1) if body[5:7] == "2B" else body
    return body.isdigit() and int(key) == 97 - int(body) % 97


def _valid_ahv(match: str) -> bool:
    """Swiss AHV/AVS number (756.xxxx.xxxx.xx): EAN-13 check digit."""
    d = _digits(match)
    if len(d) != 13:
        return False
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d[:12]))
    return (10 - total % 10) % 10 == int(d[12])


def _valid_luhn(match: str) -> bool:
    return _luhn(_digits(match))


@dataclass(frozen=True)
class Rule:
    entity: str
    regex: re.Pattern
    score: float = 0.95
    validate: Callable[[str], bool] | None = None
    group: int = 0  # capture group to report (0 = whole match)


def _rx(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, flags)


_SEP = r"[ .\-]?"

RULES: tuple[Rule, ...] = (
    # --- France / Switzerland ------------------------------------------------
    Rule("FR_NIR",
         _rx(r"(?<![\w])[12378] ?\d{2} ?(?:0[1-9]|1[0-2]|[2-9]\d) ?(?:\d{2}|2[AB]) ?"
             r"\d{3} ?\d{3} ?\d{2}(?![\w])", re.I),
         validate=_valid_nir),
    Rule("CH_AHV", _rx(r"(?<![\w.])756" + _SEP + r"\d{4}" + _SEP + r"\d{4}" + _SEP
                       + r"\d{2}(?![\w])"),
         validate=_valid_ahv),
    Rule("FR_SIRET", _rx(r"(?<![\w])\d{3} ?\d{3} ?\d{3} ?\d{5}(?![\w])"),
         score=0.85, validate=_valid_luhn),
    # A bare 9-digit number passes Luhn 1 time in 10: require the keyword.
    Rule("FR_SIREN", _rx(r"\bSIREN\b\W{0,5}(\d{3} ?\d{3} ?\d{3})(?![\w])", re.I),
         score=0.85, validate=_valid_luhn, group=1),
    # International format in any language: Presidio scores a bare number 0.4 and
    # only boosts it on English context words, so "Rufen Sie ... +49 30 ..." leaked.
    Rule("PHONE_NUMBER", _rx(r"(?<![\w+])\+\d{1,3}(?:[ .\-]?\(?\d{1,4}\)?){2,5}(?![\w])"),
         score=0.7, validate=lambda m: 8 <= len(_digits(m)) <= 15),
    # National formats Presidio's phone recognizer (US/UK/DE/... regions) misses.
    Rule("PHONE_NUMBER",
         _rx(r"(?<![\w+])(?:\+33 ?(?:\(0\) ?)?|0033 ?|0)[1-9](?:[ .\-]?\d{2}){4}(?![\w])"),
         score=0.8),
    Rule("PHONE_NUMBER",
         _rx(r"(?<![\w+])(?:\+41 ?(?:\(0\) ?)?|0041 ?|0)[1-9]\d[ .\-]?\d{3}"
             r"[ .\-]?\d{2}[ .\-]?\d{2}(?![\w])"),
         score=0.8),
    # --- secrets -----------------------------------------------------------
    Rule("SECRET", _rx(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?"
                       r"-----END [A-Z ]*PRIVATE KEY-----"), score=1.0),
    Rule("SECRET", _rx(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), score=1.0),
    Rule("SECRET", _rx(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{40,})"), score=1.0),
    Rule("SECRET", _rx(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), score=1.0),
    Rule("SECRET", _rx(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"), score=1.0),
    Rule("SECRET", _rx(r"\bAIza[0-9A-Za-z_\-]{35}\b"), score=1.0),
    Rule("SECRET", _rx(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}"), score=1.0),
    Rule("SECRET", _rx(r"\beyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}"), score=0.95),
    # Password in a URL: scheme://user:PASSWORD@host
    Rule("SECRET", _rx(r"[a-z][a-z0-9+.\-]*://[^/\s:@]+:([^/\s@]{3,})@", re.I),
         score=0.95, group=1),
    # key = value assignments: report the value only.
    Rule("SECRET",
         _rx(r"\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token"
             r"|client[_-]?secret)\b[\"']?\s*[:=]\s*[\"']?([^\s\"'`,;]{8,})", re.I),
         score=0.9, group=1),
)


def _valid_iban(match: str) -> bool:
    """ISO 13616 check: move the first 4 chars to the end, letters to 10..35, mod 97."""
    raw = re.sub(r"\s", "", match).upper()
    if not 15 <= len(raw) <= 34:
        return False
    digits = "".join(str(int(c, 36)) for c in raw[4:] + raw[:4])
    return int(digits) % 97 == 1


def _valid_ipv4(match: str) -> bool:
    return all(int(octet) <= 255 for octet in match.split("."))


# Used instead of spaCy/Presidio by the hooks' `hook_fallback: regex` mode: the
# pattern-based entities Presidio would find. No NER, so no PERSON or LOCATION.
FALLBACK_RULES: tuple[Rule, ...] = (
    Rule("EMAIL_ADDRESS",
         _rx(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"),
         score=1.0),
    Rule("IP_ADDRESS", _rx(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"),
         score=0.6, validate=_valid_ipv4),
    Rule("IBAN_CODE", _rx(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"),
         score=1.0, validate=_valid_iban),
    Rule("CREDIT_CARD", _rx(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])"),
         score=1.0, validate=_valid_luhn),
    Rule("PHONE_NUMBER", _rx(r"(?<![\w+])\+\d{1,3}(?:[ .\-]?\(?\d{1,4}\)?){2,5}(?![\w])"),
         score=0.7, validate=lambda m: 8 <= len(_digits(m)) <= 15),
)


def _run(rules: tuple[Rule, ...], text: str) -> list[Finding]:
    out: list[Finding] = []
    for rule in rules:
        for m in rule.regex.finditer(text):
            value = m.group(rule.group)
            if not value or (rule.validate and not rule.validate(value)):
                continue
            start, end = m.span(rule.group)
            out.append((rule.entity, start, end, rule.score))
    return out


def detect_builtin(text: str) -> list[Finding]:
    """Run every built-in rule over `text`."""
    return _run(RULES, text)


def detect_fallback(text: str) -> list[Finding]:
    """Pattern-only stand-in for the Presidio analyzer (see FALLBACK_RULES)."""
    return _run(FALLBACK_RULES, text)
