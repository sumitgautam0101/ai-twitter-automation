"""Encryption for credentials at rest (Fernet).

Platform credentials and API keys are stored encrypted; the key comes from the
``OPENSOCIAL_SECRET_KEY`` environment variable (a urlsafe-base64 Fernet key).
``cryptography`` is imported lazily so the package loads without it; encryption
is only needed when actually configuring live posting.
"""

from __future__ import annotations

import json
from pathlib import Path

# Fallback keyfile (next to the DB, git-ignored) so the dashboard can save
# encrypted credentials without the user wiring OPENSOCIAL_SECRET_KEY first.
# The env var, when set, always wins. OPENSOCIAL_KEYFILE relocates the file
# (the API server points it next to the DB).
DEFAULT_KEYFILE = "opensocial.key"


class SecretsError(RuntimeError):
    pass


def keyfile_secret(
    path: str | Path | None = None, *, create: bool = False
) -> str | None:
    """Read the local keyfile; optionally create it on first use."""
    import os

    path = Path(path or os.environ.get("OPENSOCIAL_KEYFILE") or DEFAULT_KEYFILE)
    if path.exists():
        return path.read_text(encoding="ascii").strip() or None
    if not create:
        return None
    key = generate_key()
    path.write_text(key, encoding="ascii")
    return key


def generate_key() -> str:
    """Return a fresh Fernet key (for first-time setup)."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def _fernet(secret_key: str | None):
    if not secret_key:
        raise SecretsError(
            "No encryption key. Set OPENSOCIAL_SECRET_KEY (generate one with "
            "`opensocial keygen`)."
        )
    from cryptography.fernet import Fernet

    try:
        return Fernet(secret_key.encode("ascii"))
    except Exception as exc:  # malformed key
        raise SecretsError(f"Invalid OPENSOCIAL_SECRET_KEY: {exc}") from exc


def encrypt_credentials(creds: dict, secret_key: str | None) -> bytes:
    """Encrypt a credentials dict to bytes for ``platform_accounts``."""
    token = _fernet(secret_key).encrypt(json.dumps(creds).encode("utf-8"))
    return token


def decrypt_credentials(blob: bytes, secret_key: str | None) -> dict:
    """Decrypt the bytes stored in ``platform_accounts.credentials_encrypted``.

    Raises :class:`SecretsError` (never the raw ``cryptography`` ``InvalidToken``)
    when the blob can't be decrypted with this key — typically a key mismatch
    (credentials encrypted under a different ``OPENSOCIAL_SECRET_KEY``/keyfile).
    Callers catch ``SecretsError`` to hold/fall back to dry-run rather than
    crashing; an uncaught ``InvalidToken`` previously killed the whole worker
    tick with an empty error message.
    """
    from cryptography.fernet import InvalidToken

    try:
        raw = _fernet(secret_key).decrypt(blob)
    except InvalidToken as exc:
        raise SecretsError(
            "Could not decrypt stored credentials — the encryption key does not "
            "match the one used to save them (check OPENSOCIAL_SECRET_KEY / "
            "opensocial.key)."
        ) from exc
    return json.loads(raw.decode("utf-8"))
