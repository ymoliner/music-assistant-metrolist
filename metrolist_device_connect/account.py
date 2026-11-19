"""Account identity inputs used by Metrolist Device Connect."""

from __future__ import annotations

import base64
import hashlib
import hmac

ACCOUNT_PROOF_LABEL = b"metrolist-device-connect-v2/account-proof"
ACCOUNT_SCOPE_LABEL = b"metrolist-device-connect-v2/account-scope"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _cookie_value(cookie: str) -> str:
    values: dict[str, str] = {}
    for part in cookie.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            values[name] = value
    for name in ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID"):
        if values.get(name):
            return values[name]
    raise ValueError("Cookie must contain SAPISID or a supported Secure PAPISID cookie")


def _clean_data_sync_id(value: str) -> str:
    value = value.strip()
    if "||" in value:
        prefix, suffix = value.split("||", 1)
        value = prefix if prefix.strip() else suffix.strip()
    value = value.strip()
    if not value:
        raise ValueError("A valid Metrolist dataSyncId is required")
    return value


def derive_account_identity(cookie: str, data_sync_id: str) -> tuple[str, str]:
    """Return Metrolist's (fingerprint, account proof secret) without retaining inputs."""
    credential = _cookie_value(cookie.strip()).encode()
    scope = _clean_data_sync_id(data_sync_id)
    proof_secret = _b64(
        hmac.digest(credential, ACCOUNT_PROOF_LABEL + b"/" + scope.encode(), "sha256")
    )
    fingerprint = _b64(
        hashlib.sha256(ACCOUNT_SCOPE_LABEL + b"/" + scope.encode()).digest()
    )
    return fingerprint, proof_secret
