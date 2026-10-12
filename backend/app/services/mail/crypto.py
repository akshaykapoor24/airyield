"""Envelope encryption for mailbox credentials.

A refresh token for someone's mailbox is the most sensitive thing FareQube stores, so it is
never written in the clear and never with one key for everything:

    credential  ──AES-256-GCM(data key, aad)──▶  credentials_enc      (nonce ‖ ciphertext)
    data key    ──AES-256-GCM(master,  aad)──▶  credentials_dek_enc  (nonce ‖ wrapped key)

Each row gets its own random data key. The master key (MAIL_ENCRYPTION_KEY) only ever wraps
data keys, so moving it into Cloud KMS later means re-wrapping 32-byte keys, not
re-encrypting every token. `KEY_REF` is stored with the row for exactly that switch.

THE AAD BINDS A CIPHERTEXT TO ITS ROW. It is "<tenant_id>:<connection_id>", so a ciphertext
copied onto another row — another workspace's mailbox, say — fails to decrypt instead of
quietly handing over the wrong person's token.

Pure functions, no database: unit-tested in tests/test_mail_crypto.py.
"""
from __future__ import annotations

import base64
import binascii
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_REF = "local:v1"
_NONCE = 12


class CryptoNotConfigured(RuntimeError):
    """MAIL_ENCRYPTION_KEY is missing or malformed. Message is written for an operator."""


class CredentialsUnreadable(RuntimeError):
    """The stored ciphertext does not open with this key and row — tampered, moved or re-keyed."""


def _master_key(raw: str | None = None) -> bytes:
    if raw is None:
        from app.config import settings
        raw = settings.MAIL_ENCRYPTION_KEY
    if not raw:
        raise CryptoNotConfigured(
            "MAIL_ENCRYPTION_KEY is not set, so mailbox credentials cannot be stored safely. "
            "Set it to base64 of 32 random bytes in .env."
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CryptoNotConfigured("MAIL_ENCRYPTION_KEY is not valid base64.") from exc
    if len(key) != 32:
        raise CryptoNotConfigured(f"MAIL_ENCRYPTION_KEY must decode to 32 bytes, not {len(key)}.")
    return key


def row_aad(tenant_id: int, connection_id: int) -> bytes:
    return f"{tenant_id}:{connection_id}".encode()


def is_configured() -> bool:
    try:
        _master_key()
        return True
    except CryptoNotConfigured:
        return False


def encrypt(payload: dict, aad: bytes, *, master_key: str | None = None) -> tuple[bytes, bytes, str]:
    """(credentials_enc, credentials_dek_enc, key_ref) for a JSON-serialisable payload."""
    master = _master_key(master_key)
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_NONCE)
    body = AESGCM(dek).encrypt(nonce, json.dumps(payload, separators=(",", ":")).encode(), aad)
    wrap_nonce = os.urandom(_NONCE)
    wrapped = AESGCM(master).encrypt(wrap_nonce, dek, b"dek|" + aad)
    return nonce + body, wrap_nonce + wrapped, KEY_REF


def decrypt(credentials_enc: bytes, credentials_dek_enc: bytes, aad: bytes,
            *, master_key: str | None = None) -> dict:
    master = _master_key(master_key)
    try:
        dek = AESGCM(master).decrypt(credentials_dek_enc[:_NONCE], credentials_dek_enc[_NONCE:], b"dek|" + aad)
        body = AESGCM(dek).decrypt(credentials_enc[:_NONCE], credentials_enc[_NONCE:], aad)
    except (InvalidTag, ValueError) as exc:
        raise CredentialsUnreadable("Stored mailbox credentials could not be decrypted.") from exc
    return json.loads(body)
