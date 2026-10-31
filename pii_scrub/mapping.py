"""Reversible token <-> real-value mapping.

A Mapping mints placeholder tokens for detected PII and remembers the original
value so it can be restored after an LLM round-trip. Tokens are sequential
(``<PERSON_1>``, in reading order) or, with a key, stable (``<PERSON_482913>``,
a keyed hash of the value; see token_key.py). With ``surrogates=True``, values
get realistic fakes instead where possible (``Gaspard Castellan``; see
surrogates.py), and parts of a fake name restore to the matching real part.

SECURITY: the saved mapping file contains the *real* PII. It is written with
0600 permissions and should never be committed (see .gitignore). Treat it like
a secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Callable, Iterable
from itertools import count
from pathlib import Path

from . import surrogates as fakes

# Matches any token this module mints, e.g. <PERSON_1>, <EMAIL_ADDRESS_12>.
TOKEN_RE = re.compile(r"<([A-Z][A-Z0-9_]*)_(\d+)>")

# Tokens as models actually echo them back: raw, HTML-escaped (&lt;PERSON_1&gt;),
# Markdown-escaped (\<PERSON_1\>) or JSON-unicode-escaped (<PERSON_1>).
ANY_TOKEN_RE = re.compile(
    r"(?:<|&lt;|\\<|\\u003[cC])([A-Z][A-Z0-9_]*_\d+)(?:>|&gt;|\\>|\\u003[eE])"
)

# Name particles and titles: kept as they are inside a fake name.
_PARTICLES = {
    "de", "du", "des", "la", "le", "les", "van", "von", "der", "den", "di", "da", "del",
    "dos", "mr", "mrs", "ms", "dr", "mme", "mlle", "m", "herr", "frau", "prof",
}


# Words, emails, IPs: what a fake could collide with in the input.
_WORD_RE = re.compile(r"[\w.@+\-]+")


def _name_words(value: str) -> list[str]:
    return [w for w in value.split() if w.rstrip(".").casefold() not in _PARTICLES]


class Mapping:
    """Bidirectional, deterministic store of value <-> token pairs."""

    def __init__(self, key: bytes | None = None, *, surrogates: bool = False) -> None:
        # None: sequential tokens; else the HMAC key for stable ones.
        self._key = key
        # value -> token. Keyed by value alone: the same string tagged PERSON in
        # one place and LOCATION in another must get one token, or the model
        # loses the link between the two mentions.
        self._value_to_token: dict[str, str] = {}
        # token (or fake) -> value
        self._token_to_value: dict[str, str] = {}
        # token (or fake) -> entity type
        self._entities: dict[str, str] = {}
        # entity_type -> highest index used
        self._counters: dict[str, int] = {}
        # token strings already present in source text; never minted
        self._reserved: set[str] = set()
        # --- surrogates ---
        self._surrogates = surrogates
        self._fake_key = key or secrets.token_bytes(32)
        # fake string -> real string, for every restorable fake (values, name parts)
        self._fakes: dict[str, str] = {}
        # real name part (casefolded) -> its fake (Title case)
        self._part_fakes: dict[str, str] = {}
        # real name parts (casefolded) known to be given names
        self._given: set[str] = set()
        # words of the input, casefolded: a fake must not already appear in it
        self._words: set[str] = set()
        self._restore_rx: re.Pattern | None = None

    def reserve(self, text: str) -> None:
        """Never mint tokens (or fakes) that already appear literally in `text`.

        Otherwise a literal ``<PERSON_1>`` in the input (an earlier scrub, a
        template) would be "restored" to someone's real name.
        """
        self._reserved.update(f"<{m.group(1)}>" for m in ANY_TOKEN_RE.finditer(text))
        if self._surrogates:
            self._words.update(w.strip(".-") for w in _WORD_RE.findall(text.casefold()))

    def learn(self, values: Iterable[tuple[str, str]], texts: Iterable[str] = ()) -> None:
        """Prepare fakes for (entity, value) pairs found ahead of scrubbing.

        Only used with surrogates: the parts of full names get their fakes
        first, so "dupont" or "jean.dupont@..." met before "Jean Dupont" (in
        reading order) still get the fake names of Jean Dupont.
        """
        if not self._surrogates:
            return
        for text in texts:
            self.reserve(text)
        for entity, value in values:
            words = _name_words(value)
            if entity == "PERSON" and len(words) > 1:
                self._given.add(words[0].casefold())
        for entity, value in values:
            if entity == "PERSON" and len(_name_words(value)) > 1:
                self._person_fake(value)

    def token_for(self, entity_type: str, value: str) -> str:
        """Return the existing token for this value, or mint the next one."""
        existing = self._value_to_token.get(value)
        if existing is not None:
            return existing
        token = None
        if self._surrogates and entity_type in fakes.SUPPORTED:
            token = self._fake_for(entity_type, value)
        if token is not None:
            self._fakes[token] = value
            self._restore_rx = None
        elif self._key is not None:
            token = self._stable_token(entity_type, value)
        else:
            idx = self._counters.get(entity_type, 0)
            while True:
                idx += 1
                token = f"<{entity_type}_{idx}>"
                if token not in self._reserved:
                    break
            self._counters[entity_type] = idx
        self._value_to_token[value] = token
        self._token_to_value[token] = value
        self._entities[token] = entity_type
        return token

    def _stable_token(self, entity_type: str, value: str) -> str:
        """``<ENTITY_nnnnnn>`` from HMAC(key, value); rehashed on a collision."""
        data = value.encode("utf-8", "surrogatepass")
        for attempt in count():
            digest = hmac.new(self._key, b"%d\x00" % attempt + data, hashlib.sha256).digest()
            token = f"<{entity_type}_{int.from_bytes(digest[:8], 'big') % 10**6:06d}>"
            if token not in self._reserved and token not in self._token_to_value:
                return token
        raise AssertionError("unreachable")

    # --- surrogates --------------------------------------------------------

    def _free(self, fake: str, value: str) -> bool:
        """`fake` stands for no other value and appears nowhere in the input."""
        if fake.casefold() == value.casefold():
            return False
        if self._fakes.get(fake, value) != value or fake in self._token_to_value:
            return False
        folded = fake.casefold()
        return folded not in self._words and not any(w in self._words for w in folded.split())

    def _part_fake(self, part: str, given: bool) -> str | None:
        folded = part.casefold()
        known = self._part_fakes.get(folded)
        if known is not None:
            return known
        taken = set(self._part_fakes.values())
        for attempt in range(fakes.MAX_ATTEMPTS):
            fake = fakes.name_part(self._fake_key, part, given, attempt)
            if fake not in taken and self._free(fake, part):
                self._part_fakes[folded] = fake
                self._fakes.setdefault(fake, part)
                self._restore_rx = None
                return fake
        return None

    def _person_fake(self, value: str) -> str | None:
        words = _name_words(value)
        out = []
        for word in value.split():
            if word not in words:  # particle or title: kept
                out.append(word)
                continue
            core = word.strip(".-'")
            given = word.casefold() in self._given or (word == words[0] and len(words) > 1)
            fake = self._part_fake(core, given) if core else None
            if fake is None:
                return None
            out.append(word.replace(core, fakes.match_case(fake, core)))
        return " ".join(out)

    def _fake_for(self, entity: str, value: str) -> str | None:
        key = self._fake_key
        for attempt in range(fakes.MAX_ATTEMPTS):
            if entity == "PERSON":
                fake = self._person_fake(value) if attempt == 0 else None
            elif entity == "EMAIL_ADDRESS":
                local = value.split("@", 1)[0]
                parts = [p for p in re.split(r"[._\-+]+", local) if p]
                known = [self._part_fakes.get(p.casefold()) for p in parts]
                names = [k.lower() for k in known] if parts and all(known) else []
                fake = fakes.email(key, value, names, attempt)
            elif entity == "PHONE_NUMBER":
                fake = fakes.phone(key, value, attempt)
            elif entity == "IP_ADDRESS":
                fake = fakes.ip_address(key, value, attempt)
            elif entity == "CREDIT_CARD":
                fake = fakes.credit_card(key, value, attempt)
            else:  # IBAN_CODE
                fake = fakes.iban(key, value, attempt)
            if fake is None:
                return None
            if self._free(fake, value):
                return fake
        return None

    # --- restore -----------------------------------------------------------

    def _pattern(self) -> re.Pattern:
        if self._restore_rx is None:
            alternation = "|".join(
                re.escape(f) for f in sorted(self._fakes, key=len, reverse=True)
            )
            fake_rx = rf"|(?<!\w)(?:{alternation})(?!\w)" if alternation else ""
            self._restore_rx = re.compile(f"(?:{ANY_TOKEN_RE.pattern}){fake_rx}")
        return self._restore_rx

    def restore(self, text: str, escape: Callable[[str], str] | None = None) -> str:
        """Replace every known token (and fake) in `text` with its original value.

        Tolerates the escaped forms models produce (see ``ANY_TOKEN_RE``). One
        pass, so a restored value is never itself taken for a fake. `escape`
        is applied to inserted values (e.g. JSON-escaping inside tool arguments).
        """
        def sub(m: re.Match) -> str:
            if m.group(1):
                value = self._token_to_value.get(f"<{m.group(1)}>")
            else:
                value = self._fakes.get(m.group(0))
            if value is None:
                return m.group(0)
            return escape(value) if escape else value

        return self._pattern().sub(sub, text)

    def hold_back(self, text: str) -> int:
        """Length of the tail of `text` that may be the start of a fake.

        For streaming: that tail must wait for the next chunk before restoring
        ("Gasp" + "ard Castellan"), and so must a complete fake that may still
        grow into another word ("Castellan" + "o").
        """
        if not self._fakes:
            return 0
        longest = max(map(len, self._fakes))
        for k in range(min(len(text), longest), 0, -1):
            if k < len(text) and (text[-k - 1].isalnum() or text[-k - 1] == "_"):
                continue
            tail = text[-k:]
            if any(f.startswith(tail) for f in self._fakes):
                return k
        return 0

    def items(self) -> list[tuple[str, str]]:
        """(entity_type, value) for every value minted so far."""
        out = []
        for token, value in self._token_to_value.items():
            entity = self._entities.get(token)
            if entity is None:
                m = ANY_TOKEN_RE.fullmatch(token)
                if not m:
                    continue
                entity = m.group(1).rsplit("_", 1)[0]
            out.append((entity, value))
        return out

    def __len__(self) -> int:
        return len(self._token_to_value)

    # --- persistence -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": 2,
            "tokens": self._token_to_value,
            "entities": self._entities,
            "fakes": self._fakes,
            "counters": self._counters,
        }

    def save(self, path: str | Path) -> None:
        """Write the mapping as JSON, owner-only.

        Created with mode 0600 from the start (no world-readable window) on
        POSIX. On Windows the mode argument is ignored by the OS, so the file
        inherits the user's default ACLs — typically already user-private in a
        home directory. See the README security note.
        """
        path = Path(path)
        data = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        # O_CREAT's mode only applies when creating; tighten a pre-existing file too.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # best effort (e.g. filesystems without POSIX perms)

    @classmethod
    def load(cls, path: str | Path) -> Mapping:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        m = cls()
        m._token_to_value = dict(data.get("tokens", {}))
        m._entities = dict(data.get("entities", {}))
        m._fakes = dict(data.get("fakes", {}))
        m._counters = dict(data.get("counters", {}))
        for token, value in m._token_to_value.items():
            m._value_to_token.setdefault(value, token)
        return m
