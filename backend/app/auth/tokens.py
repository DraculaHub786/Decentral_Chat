import sys
from pathlib import Path
from typing import Optional, Dict, Any
import uuid
import datetime
import jwt
import logging

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from app.globals import g
    from app.core.config import SECRET_KEY, ACCESS_TOKEN_LIFETIME_DAYS, REFRESH_TOKEN_LIFETIME_DAYS
except ImportError:
    from ..globals import g
    from ..core.config import SECRET_KEY, ACCESS_TOKEN_LIFETIME_DAYS, REFRESH_TOKEN_LIFETIME_DAYS

logger = logging.getLogger(__name__)


def generate_token(self_or_user_id, user_id: Optional[str] = None) -> str:
    """Generate JWT access token (long-lived 7-day session for uninterrupted chat experience)"""
    uid = user_id if user_id is not None else self_or_user_id
    payload = {
        'user_id': uid,
        'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=ACCESS_TOKEN_LIFETIME_DAYS),
        'iat': datetime.datetime.now(datetime.UTC)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')


async def _generate_refresh_token(self_or_user_id, user_id: Optional[str] = None, device_fingerprint: str = '') -> str:
    """Generate a 90-day refresh token, stored in Redis for rotation and seamless session extension."""
    uid = user_id if user_id is not None else self_or_user_id
    token_id = str(uuid.uuid4())
    payload = {
        'user_id': uid,
        'token_id': token_id,
        'type': 'refresh',
        'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=REFRESH_TOKEN_LIFETIME_DAYS),
        'iat': datetime.datetime.now(datetime.UTC)
    }
    refresh_token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')

    try:
        token_data = {
            'user_id': uid,
            'device_fingerprint': device_fingerprint,
            'created_at': datetime.datetime.now(datetime.UTC).isoformat()
        }
        await _store_refresh_token(token_id, token_data)
    except Exception as e:
        logger.warning(f"⚠️ Failed to persist refresh token to Redis: {e}")

    return refresh_token


async def _store_refresh_token(self_or_token_id, token_id_or_data, token_data_opt=None):
    """Persist refresh token metadata in Redis (supports both self and direct function calls)."""
    if token_data_opt is not None:
        token_id = token_id_or_data
        token_data = token_data_opt
    else:
        token_id = self_or_token_id
        token_data = token_id_or_data

    try:
        if g.redis_client:
            await g.redis_client.hset(f"refresh_token:{token_id}", mapping=token_data)
            await g.redis_client.expire(f"refresh_token:{token_id}", REFRESH_TOKEN_LIFETIME_DAYS * 24 * 3600)
    except Exception as e:
        logger.warning(f"⚠️ Redis error storing refresh token {token_id}: {e}")


async def get_user_from_token(self_or_request, request=None) -> Optional[str]:
    """Extract user ID from JWT token.
    
    Supports both method call `self.get_user_from_token(request)` and
    standalone function call `get_user_from_token(request)`.
    """
    req = request if request is not None else self_or_request
    try:
        auth_header = req.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None
        
        token = auth_header.replace('Bearer ', '')
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload.get('user_id')
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Exception):
        return None
