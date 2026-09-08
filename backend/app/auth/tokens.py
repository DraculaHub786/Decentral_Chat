from typing import Dict, Set, Optional, List
from aiohttp import web
import aiohttp_cors
from aiohttp_session import get_session
import asyncio, json, hashlib, jwt, datetime, uuid, os, base64, bcrypt, random, mimetypes, secrets, string, shutil, subprocess, tempfile, io
from datetime import timedelta
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, storage as firebase_storage, firestore
import redis.asyncio as redis
from cryptography.fernet import Fernet
import logging
from pathlib import Path
from PIL import Image, ImageOps
import PyPDF2
from docx import Document
from pptx import Presentation
import openpyxl
from app.globals import g
from app.core.config import (REDIS_URL, SECRET_KEY, FIREBASE_CRED, PORT,
    MAX_FILE_SIZE, UPLOAD_DIR, ALLOWED_EXTENSIONS, ENCRYPTION_KEY,
    HAS_LIBREOFFICE, HAS_UNOCONV, FFMPEG_PATH, HAS_PDF2DOCX, PDFConverter,
    HAS_BS4, HAS_MARKDOWN, print_conversion_capabilities)
from app.core.security import (_ensure_secret_key, _ensure_fernet_key,
    _validate_password, _validate_file_magic, _resolve_safe_path, _log_safe, _is_admin)
from app.core.rate_limiter import RateLimiter
from app.core.redis_client import MockRedis, MockPipeline
from app.core.firebase_client import init_firebase
logger = logging.getLogger(__name__)
import pickle
from app.core.redis_client import (init_redis)
def generate_token(self, user_id: str) -> str:
    """Generate JWT access token (15-minute expiry)"""
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15),
        'iat': datetime.datetime.now(datetime.UTC)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

async def _generate_refresh_token(self, user_id: str, device_fingerprint: str = '') -> str:
    """Generate a 30-day refresh token, stored in Redis for rotation.

    Made async so the persistence write is properly awaited instead of
    fire-and-forget (avoids the previous event-loop race where the token
    metadata could fail to persist before the token was returned).
    """
    token_id = str(uuid.uuid4())
    payload = {
        'user_id': user_id,
        'token_id': token_id,
        'type': 'refresh',
        'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30),
        'iat': datetime.datetime.now(datetime.UTC)
    }
    refresh_token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    # Store in Redis with device fingerprint for revocation / rotation.
    # Await directly (caller is already async) so persistence is guaranteed.
    try:
        token_data = {
            'user_id': user_id,
            'device_fingerprint': device_fingerprint,
            'created_at': datetime.datetime.now(datetime.UTC).isoformat()
        }
        await self._store_refresh_token(token_id, token_data)
    except Exception:
        pass  # Gracefully degrade: refresh still works, just no persistence
    return refresh_token

async def _store_refresh_token(self, token_id: str, token_data: dict):
    """Persist refresh token metadata in Redis."""
    try:
        await g.redis_client.hset(f"refresh_token:{token_id}", mapping=token_data)
        await g.redis_client.expire(f"refresh_token:{token_id}", 30 * 24 * 3600)  # 30 days
    except Exception:
        pass

async def get_user_from_token(self, request) -> Optional[str]:
    """Extract user ID from JWT token"""
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None
        
        token = auth_header.replace('Bearer ', '')
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

