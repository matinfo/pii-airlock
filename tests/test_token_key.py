"""Stable tokens: keyed-hash minting and key management."""

import os
import stat
from datetime import date

import pytest

from pii_scrub import token_key as tk
from pii_scrub.config import Config
from pii_scrub.mapping import TOKEN_RE, Mapping


def test_same_value_same_token_across_mappings_and_order():
    key = b"k" * 32
    a, b = Mapping(key), Mapping(key)
    a.token_for("PERSON", "Marie Dubois")
    first = a.token_for("PERSON", "Jean Dupont")
    assert b.token_for("PERSON", "Jean Dupont") == first
    assert TOKEN_RE.fullmatch(first)
    assert b.restore(f"hi {first}") == "hi Jean Dupont"


def test_another_key_gives_other_tokens():
    assert (Mapping(b"a" * 32).token_for("PERSON", "Jean")
            != Mapping(b"b" * 32).token_for("PERSON", "Jean"))


def test_collisions_and_reserved_tokens_are_rehashed():
    key = b"k" * 32
    token = Mapping(key).token_for("PERSON", "Jean")
    m = Mapping(key)
    m.reserve(f"literal {token} in the input")
    other = m.token_for("PERSON", "Jean")
    assert other != token and TOKEN_RE.fullmatch(other)
    assert m.restore(token) == token  # the literal is never restored


def test_mapping_round_trip_keeps_stable_tokens(tmp_path):
    m = Mapping(b"k" * 32)
    token = m.token_for("EMAIL_ADDRESS", "jean@acme.fr")
    m.save(tmp_path / "m.json")
    assert Mapping.load(tmp_path / "m.json").restore(token) == "jean@acme.fr"


def test_master_key_is_created_once_and_private():
    key = tk.token_key(Config())
    path = tk.key_path()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    tk._master_key.cache_clear()
    assert tk.token_key(Config()) == key


def test_rotation_periods():
    cfg = Config()
    monday, tuesday = date(2026, 10, 26), date(2026, 10, 27)
    assert tk.token_key(cfg, monday) != tk.token_key(cfg, tuesday)
    week = Config(token_rotation="week")
    assert tk.token_key(week, monday) == tk.token_key(week, tuesday)
    assert tk.token_key(week, monday) != tk.token_key(week, date(2026, 11, 2))
    never = Config(token_rotation="never")
    assert tk.token_key(never, monday) == tk.token_key(never, date(2030, 1, 1))


def test_sequential_and_invalid_settings():
    assert tk.token_key(Config(token_style="sequential")) is None
    with pytest.raises(ValueError, match="token_style"):
        tk.token_key(Config(token_style="random"))
    with pytest.raises(ValueError, match="token_rotation"):
        tk.token_key(Config(token_rotation="hourly"))


def test_corrupt_key_fails_loudly():
    path = tk.key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"short")
    tk._master_key.cache_clear()
    with pytest.raises(ValueError, match="corrupt"):
        tk.token_key(Config())
