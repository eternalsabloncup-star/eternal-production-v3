"""Accurate Online API Token authentication (doc 1.0.3).

Every request requires:
  Authorization: Bearer <API_TOKEN>
  X-Api-Timestamp: dd/MM/yyyy HH:mm:ss
  X-Api-Signature: Base64(HMAC-SHA256(signature_secret, timestamp))

Never log token or signature secret values.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Accurate Indonesia documentation uses local wall-clock timestamps.
_WIB = ZoneInfo("Asia/Jakarta")


def api_timestamp(now: datetime | None = None) -> str:
    """Format required by Accurate Online API Token 1.0.3."""
    dt = now or datetime.now(_WIB)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_WIB)
    else:
        dt = dt.astimezone(_WIB)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def api_signature(signature_secret: str, timestamp: str) -> str:
    """HMAC-SHA256(secret, timestamp) → Base64 (API Token 1.0.3)."""
    digest = hmac.new(
        signature_secret.encode("utf-8"),
        timestamp.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def auth_headers(*, api_token: str, signature_secret: str, now: datetime | None = None) -> dict[str, str]:
    """Fresh signed headers for one outbound Accurate request."""
    ts = api_timestamp(now)
    return {
        "Authorization": f"Bearer {api_token}",
        "X-Api-Timestamp": ts,
        "X-Api-Signature": api_signature(signature_secret, ts),
        "Accept": "application/json",
    }


def normalize_host(host: str) -> str:
    host = (host or "").strip().rstrip("/")
    host = host.removesuffix("/accurate").rstrip("/")
    if not host:
        return ""
    if not host.startswith(("http://", "https://")):
        if "." not in host:
            host = f"https://{host}.accurate.id"
        else:
            host = f"https://{host}"
    return host.rstrip("/")
