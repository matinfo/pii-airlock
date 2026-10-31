"""Encryption of mapping files at rest (``mapping_encryption``).

A mapping file holds the real values behind every token. Encrypted with
AES-256-GCM, a copied or backed-up state directory no longer exposes them: the
key lives in ``token.key`` (see token_key.py), which should stay out of backups.
The mapping key is derived from that master key with a distinct label, so the
file key and the token keys never coincide.

File layout: ``MAGIC | 12-byte nonce | ciphertext+tag``. Plain JSON files
(written before this option, or with ``mapping_encryption: false``) still load.
"""

from __future__ import annotations

import hashlib
import hmac
import os

MAGIC = b"PIIMAP\x01\n"
_NONCE_LEN = 12


class MappingDecryptError(ValueError):
    """The file is encrypted and cannot be opened with this key."""


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:  # pragma: no cover - cryptography is a core dependency
        raise RuntimeError(
            "mapping_encryption needs the 'cryptography' package "
            "(pip install cryptography), or set `mapping_encryption: false`."
        ) from None
    return AESGCM(key)


def mapping_key(master: bytes) -> bytes:
    """32-byte AES key derived from the user's master key."""
    return hmac.new(master, b"pii-airlock/mapping-file/v1", hashlib.sha256).digest()


def default_key() -> bytes:
    from .token_key import _master_key, key_path

    return mapping_key(_master_key(key_path()))


def is_sealed(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def seal(plain: bytes, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    # The magic is authenticated too: a truncated or swapped header fails to open.
    return MAGIC + nonce + _aesgcm(key).encrypt(nonce, plain, MAGIC)


def unseal(blob: bytes, key: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag

    body = blob[len(MAGIC):]
    try:
        return _aesgcm(key).decrypt(body[:_NONCE_LEN], body[_NONCE_LEN:], MAGIC)
    except InvalidTag:
        raise MappingDecryptError(
            "cannot decrypt the mapping file: wrong key (was token.key replaced or "
            "deleted?) or the file is corrupt"
        ) from None
