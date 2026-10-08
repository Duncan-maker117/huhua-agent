"""Authenticated, versioned application encryption with explicit local fallback.

Keys are injected by the environment, never saved beside the database. Ciphertext
is bound to its owner, record and field so swapping rows cannot reveal data.
"""

import base64
import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoConfigurationError(RuntimeError):
    pass


class DataDecryptionError(RuntimeError):
    pass


PREFIX = "huhua:v1:"
MARKER = "__huhua_encrypted__"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)


@dataclass(frozen=True)
class DataCrypto:
    keys: dict[str, bytes]
    active_key: str
    allow_plaintext: bool = False

    def __post_init__(self):
        if any(not isinstance(k, str) or not k or len(v) != 32 for k, v in self.keys.items()):
            raise CryptoConfigurationError("Each data encryption key must have an ID and 32 bytes")
        if self.keys and self.active_key not in self.keys:
            raise CryptoConfigurationError("Active data encryption key is unavailable")
        if not self.keys and not self.allow_plaintext:
            raise CryptoConfigurationError("Data encryption keys are required")

    @property
    def enabled(self) -> bool:
        return bool(self.keys)

    @staticmethod
    def is_encrypted(value) -> bool:
        return (isinstance(value, dict) and value.get(MARKER) == 1) or (
            isinstance(value, str) and value.startswith(PREFIX)
        )

    @staticmethod
    def _aad(owner: str, record: str, field: str) -> bytes:
        if not owner or not record or not field:
            raise ValueError("Encryption requires owner, record and field")
        return json.dumps(["huhua", 1, owner, record, field], separators=(",", ":")).encode()

    def encrypt_bytes(self, value: bytes, *, owner: str, record: str, field: str) -> dict:
        if not self.enabled:
            raise CryptoConfigurationError("Byte encryption requires configured keys")
        aad = self._aad(owner, record, field)
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.keys[self.active_key]).encrypt(nonce, value, aad)
        return {MARKER: 1, "kid": self.active_key, "nonce": _encode(nonce), "ciphertext": _encode(ciphertext)}

    def decrypt_bytes(self, value: dict, *, owner: str, record: str, field: str) -> bytes:
        try:
            if value.get(MARKER) != 1:
                raise ValueError("Unsupported ciphertext")
            key = self.keys[value["kid"]]
            nonce = _decode(value["nonce"])
            if len(nonce) != 12:
                raise ValueError("Invalid nonce")
            return AESGCM(key).decrypt(nonce, _decode(value["ciphertext"]), self._aad(owner, record, field))
        except (KeyError, TypeError, ValueError, AttributeError, InvalidTag) as exc:
            raise DataDecryptionError("Encrypted data cannot be authenticated or its key is unavailable") from exc

    def encrypt_json(self, value, *, owner: str, record: str, field: str):
        if not self.enabled:
            return value
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self.encrypt_bytes(encoded, owner=owner, record=record, field=field)

    def decrypt_json(self, value, *, owner: str, record: str, field: str):
        if self.is_encrypted(value):
            try:
                return json.loads(self.decrypt_bytes(value, owner=owner, record=record, field=field))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DataDecryptionError("Invalid encrypted JSON") from exc
        if self.allow_plaintext:
            return value
        raise DataDecryptionError("Plaintext record requires an explicit offline migration")

    def encrypt_text(self, value: str, *, owner: str, record: str, field: str) -> str:
        if not self.enabled:
            return value
        envelope = self.encrypt_bytes(value.encode("utf-8"), owner=owner, record=record, field=field)
        return PREFIX + _encode(json.dumps(envelope, separators=(",", ":")).encode())

    def decrypt_text(self, value: str, *, owner: str, record: str, field: str) -> str:
        if isinstance(value, str) and value.startswith(PREFIX):
            try:
                envelope = json.loads(_decode(value[len(PREFIX):]))
                return self.decrypt_bytes(envelope, owner=owner, record=record, field=field).decode("utf-8")
            except (ValueError, TypeError, UnicodeError) as exc:
                raise DataDecryptionError("Invalid encrypted text") from exc
        if self.allow_plaintext:
            return value
        raise DataDecryptionError("Plaintext record requires an explicit offline migration")


def crypto_from_settings(settings) -> DataCrypto:
    environment = getattr(settings, "APP_ENV", "local").lower()
    allow_plaintext = bool(getattr(settings, "ALLOW_INSECURE_LOCAL_STORAGE", False)) and environment == "local"
    try:
        raw = getattr(settings, "DATA_ENCRYPTION_KEYS", "{}")
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("Keyring must be an object")
        keys = {key_id: _decode(encoded) for key_id, encoded in parsed.items()}
    except (TypeError, ValueError, AttributeError) as exc:
        raise CryptoConfigurationError("Invalid data encryption keyring") from exc
    return DataCrypto(keys, getattr(settings, "DATA_ENCRYPTION_ACTIVE_KEY", ""), allow_plaintext)


def get_crypto() -> DataCrypto:
    from app.config import get_settings

    return crypto_from_settings(get_settings())
