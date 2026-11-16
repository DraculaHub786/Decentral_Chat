"""Short-lived signed URLs for media the browser must load directly.

`<img>`, `<video>` and `<audio>` cannot send an Authorization header, so chat
attachments need a URL the browser can fetch on its own. The previous solution
was `?token=<session JWT>`, which put a 90-day credential into access logs,
proxy logs and browser history — anyone reading it took over the account.

These tokens are narrow: one file, one user, one hour. They cannot be replayed
against any other route, and they expire on their own.
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from app.core.config import SECRET_KEY

# Long enough to render a conversation that was scrolled into, short enough
# that a URL copied out of a log ages out quickly.
MEDIA_TOKEN_TTL_SECONDS = 3600

MEDIA_TOKEN_QUERY_PARAM = "mt"


def normalise_media_name(name: str) -> str:
    """Canonical form of an upload path, used for both signing and checking."""
    return name.replace("\\", "/").strip("/")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    digest = hmac.new(SECRET_KEY.encode("utf-8"), body.encode("ascii"), hashlib.sha256)
    return _b64encode(digest.digest())


def issue_media_token(media_name: str, user_id: str) -> str:
    """Mint a token granting `user_id` read access to one upload path."""
    payload = {
        "p": normalise_media_name(media_name),
        "u": user_id,
        "e": int(time.time()) + MEDIA_TOKEN_TTL_SECONDS,
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def read_media_token(token: str) -> Optional[dict]:
    """Verify a token and return its payload, or None when invalid or expired."""
    if not token or "." not in token:
        return None
    body, _, signature = token.rpartition(".")
    if not body or not signature:
        return None

    # Constant-time compare so a wrong signature reveals nothing about the right one.
    if not hmac.compare_digest(signature, _sign(body)):
        return None

    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("e", 0) < int(time.time()):
        return None
    return payload


def token_allows(token: str, media_name: str, user_id: Optional[str]) -> bool:
    """True when this token authorises this exact path for this caller."""
    payload = read_media_token(token)
    if not payload or not user_id:
        return False
    if payload.get("p") != normalise_media_name(media_name):
        return False
    bound_user = payload.get("u")
    if not bound_user:
        return False
    return hmac.compare_digest(str(bound_user), str(user_id))


def signed_media_url(media_name: str, user_id: str) -> str:
    """Relative URL the browser can load without an Authorization header."""
    name = normalise_media_name(media_name)
    token = issue_media_token(name, user_id)
    return f"/api/uploads/{name}?{MEDIA_TOKEN_QUERY_PARAM}={token}"
