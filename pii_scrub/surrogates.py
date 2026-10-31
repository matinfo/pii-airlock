"""Realistic fake values (``token_style: surrogate``).

Instead of ``<PERSON_482913>`` the model sees ``Gaspard Castellan``: text reads
naturally, and models handle names, emails and phone numbers they can parse
better than placeholders (grammar, formatting, tool arguments). Each fake is
derived from the value with HMAC (see token_key.py), so it is stable like a
token, and is restored to the real value in the response.

Fakes come from safe pools: fictional names, ``example.com`` addresses
(RFC 2606), documentation IP ranges (RFC 5737). Phones, cards and IBANs keep
their shape and checksums but random digits. Entities without a generator here
fall back to tokens.

Every function takes ``attempt``: the caller retries with the next attempt
when a fake collides with another value or with text already in the input.
"""

from __future__ import annotations

import hashlib
import hmac
import re

# Fictional-sounding but plausible names, ASCII only (safe in any JSON or
# shell context), chosen to avoid common English/French words.
GIVEN_NAMES = (
    "Adele", "Ambroise", "Bastien", "Brice", "Clemence", "Cyril", "Delphine", "Dorian",
    "Elias", "Elodie", "Fabien", "Flavie", "Gaetan", "Gaspard", "Ilona", "Isaure",
    "Jasper", "Joris", "Kendra", "Kilian", "Leandre", "Lorna", "Maelle", "Mirko",
    "Nils", "Nolwenn", "Oriane", "Pascaline", "Quentin", "Romane", "Solene", "Tristan",
    "Ulrich", "Valentin", "Wilfried", "Yannick", "Zelie", "Anouk", "Bertille", "Corentin",
)
FAMILY_NAMES = (
    "Abernathy", "Aubertin", "Belcourt", "Brassard", "Castellan", "Chevrier", "Darrow",
    "Desrosiers", "Eckhart", "Esterhazy", "Fairbanks", "Fontenay", "Gauvain", "Gilbride",
    "Harrowgate", "Hennessy", "Ingram", "Iverson", "Jessop", "Jolicoeur", "Kerrigan",
    "Kowalczyk", "Lachance", "Lindqvist", "Marchetti", "Merriweather", "Nantel", "Nordahl",
    "Ostrander", "Ouellet", "Pellerin", "Quarles", "Rousselot", "Salvaggio", "Thibodeau",
    "Underhill", "Valcourt", "Whitcombe", "Yardley", "Zellweger",
)
SUPPORTED = frozenset({
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IP_ADDRESS", "CREDIT_CARD", "IBAN_CODE",
})
# Past this many attempts the caller falls back to a token.
MAX_ATTEMPTS = 64

_DOC_NETS = ("192.0.2", "198.51.100", "203.0.113")


def _rand(key: bytes, label: str, attempt: int) -> int:
    msg = f"{label}\x00{attempt}".encode("utf-8", "surrogatepass")
    return int.from_bytes(hmac.new(key, msg, hashlib.sha256).digest(), "big")


def _digits(key: bytes, label: str, attempt: int):
    """An endless, deterministic stream of digits for `label`."""
    n, i = 0, 0
    while True:
        if n == 0:
            n, i = _rand(key, f"{label}#{i}", attempt), i + 1
        n, d = divmod(n, 10)
        yield d


def match_case(fake: str, real: str) -> str:
    if real.isupper() and len(real) > 1:
        return fake.upper()
    if real.islower():
        return fake.lower()
    return fake


def name_part(key: bytes, part: str, given: bool, attempt: int) -> str:
    """Fake given or family name for one real name part (case-insensitive)."""
    pool = GIVEN_NAMES if given else FAMILY_NAMES
    pick = _rand(key, f"name:{part.casefold()}", 0) + attempt  # walk the pool on retries
    return pool[pick % len(pool)]


def email(key: bytes, value: str, local_parts: list[str], attempt: int) -> str:
    """``given.family@example.com`` from the fakes of the local part's names."""
    local = ".".join(local_parts) if local_parts else f"user{_rand(key, value, 0) % 10**4}"
    if attempt:
        local += str(attempt + 1)
    return f"{local}@example.com"


def reshape_digits(key: bytes, value: str, attempt: int, keep: int) -> str:
    """Same separators, first `keep` digits kept, other digits random."""
    digits = _digits(key, f"digits:{value}", attempt)
    out, seen = [], 0
    for ch in value:
        if ch.isdigit():
            out.append(ch if seen < keep else str(next(digits)))
            seen += 1
        else:
            out.append(ch)
    return "".join(out)


def phone(key: bytes, value: str, attempt: int) -> str:
    # Keep the country code / trunk prefix and first digit: the number still
    # looks like it comes from the same country and network.
    return reshape_digits(key, value, attempt, keep=3 if value.lstrip().startswith("+") else 2)


def ip_address(key: bytes, value: str, attempt: int) -> str | None:
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value):
        return None  # IPv6: token
    n = _rand(key, f"ip:{value}", 0) + attempt
    return f"{_DOC_NETS[n % 3]}.{n // 3 % 254 + 1}"


def _luhn_digit(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return str((10 - total % 10) % 10)


def credit_card(key: bytes, value: str, attempt: int) -> str:
    fake = reshape_digits(key, value, attempt, keep=1)
    positions = [i for i, ch in enumerate(fake) if ch.isdigit()]
    body = "".join(fake[i] for i in positions[:-1])
    last = positions[-1]
    return fake[:last] + _luhn_digit(body) + fake[last + 1:]


def iban(key: bytes, value: str, attempt: int) -> str:
    raw = re.sub(r"\s", "", value).upper()
    stream = _digits(key, f"iban:{value}", attempt)
    bban = "".join(
        str(next(stream)) if c.isdigit() else "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[next(stream) * 2 % 26]
        for c in raw[4:]
    )
    numeric = "".join(str(int(c, 36)) for c in bban + raw[:2] + "00")
    fake = f"{raw[:2]}{98 - int(numeric) % 97:02d}{bban}"
    # Re-insert the original spacing.
    out, i = [], 0
    for ch in value:
        if ch.isspace():
            out.append(ch)
        else:
            out.append(fake[i])
            i += 1
    return "".join(out)
