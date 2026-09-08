from app.core.config import BASE_DIR
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
logger = logging.getLogger(__name__)
def _ensure_secret_key(path=None):
    """
    Load SECRET_KEY from env var, or from a file on disk, or generate once and persist.
    Ensures JWT signing key never changes across restarts.
    """
    env_key = os.getenv('SECRET_KEY')
    if env_key:
        return env_key
    if path is None:
        path = os.path.join(BASE_DIR, '.secret_key')
    path = Path(path)
    if path.exists():
        key = path.read_text().strip()
        if key:
            logger.info("✅ Loaded SECRET_KEY from file")
            return key
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    try:
        path.write_text(key)
        logger.info(f"✅ Generated and saved SECRET_KEY to {path}")
    except Exception as e:
        logger.warning(f"⚠️ Could not save SECRET_KEY to {path}: {e}")
    return key


def _ensure_fernet_key(path=None):
    """
    Load ENCRYPTION_KEY from env var, or from a file on disk, or generate once and persist.
    Ensures encrypted data never becomes undecryptable after restart.
    """
    env_key = os.getenv('ENCRYPTION_KEY')
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key
    if path is None:
        path = os.path.join(BASE_DIR, '.fernet_key')
    path = Path(path)
    if path.exists():
        raw = path.read_text().strip()
        if raw:
            logger.info("✅ Loaded ENCRYPTION_KEY from file")
            return raw.encode() if isinstance(raw, str) else raw
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    try:
        path.write_text(key.decode() if isinstance(key, bytes) else key)
        logger.info(f"✅ Generated and saved ENCRYPTION_KEY to {path}")
    except Exception as e:
        logger.warning(f"⚠️ Could not save ENCRYPTION_KEY to {path}: {e}")
    return key if isinstance(key, bytes) else key.encode()


def _resolve_safe_path(base_dir, user_path):
    """
    Verify that a user-supplied file path resolves within the allowed base directory.
    Prevents SSRF / path traversal attacks.
    Raises ValueError if the path escapes.
    """
    base = Path(base_dir).resolve()
    target = Path(user_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: '{user_path}' resolves to '{target}' "
            f"which is outside the allowed base directory '{base}'"
        )
    return target




def _validate_password(password):
    """Validate password strength. Returns (is_valid, message)."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    return True, ""


# ==================== CONFIGURATION ====================

PORT = int(os.getenv('PORT', 8080))
SECRET_KEY = _ensure_secret_key()
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
FIREBASE_CRED = os.getenv('FIREBASE_CRED_PATH', 'firebase-config.json')

# File Upload Configuration
# Use parent directory's uploads folder (project root)
UPLOAD_DIR = Path(__file__).parent.parent / 'uploads'
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_EXTENSIONS = {
    'image': {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'},
    'video': {'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv'},
    'audio': {'mp3', 'wav', 'ogg', 'm4a', 'aac', 'opus', 'flac'},
    'document': {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf'},
    'archive': {'zip', 'rar', '7z', 'tar', 'gz'}
}

# Create upload directories
for category in ['images', 'videos', 'audio', 'documents', 'archives', 'voices', 'avatars', 'thumbnails']:
    (UPLOAD_DIR / category).mkdir(parents=True, exist_ok=True)

# Encryption for messages
ENCRYPTION_KEY = _ensure_fernet_key()
cipher_suite = Fernet(ENCRYPTION_KEY if isinstance(ENCRYPTION_KEY, bytes) else ENCRYPTION_KEY.encode())

# Global state
active_connections: Dict[str, Set[web.WebSocketResponse]] = {}
active_calls: Dict[str, Dict] = {}
active_group_calls: Dict[str, Dict] = {}  # group_call_id -> {participants: {user_id: status}, type: audio/video, group_id: ...}
redis_client: Optional[redis.Redis] = None


# ==================== SERVER CLASS ====================



def _validate_file_magic(file_path, expected_ext):
    """
    Check magic bytes for images; for non-images, reject obvious script content.
    Returns True if file looks safe, False otherwise.
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(512)

        image_signatures = {
            'png': (b'\x89PNG\r\n\x1a\n',),
            'jpg': (b'\xff\xd8\xff',),
            'jpeg': (b'\xff\xd8\xff',),
            'gif': (b'GIF87a', b'GIF89a'),
            'webp': (b'RIFF',),
            'bmp': (b'BM',),
            'ico': (b'\x00\x00\x01\x00',),
        }

        ext_lower = expected_ext.lower()
        if ext_lower in image_signatures:
            sigs = image_signatures[ext_lower]
            if ext_lower == 'webp':
                if not header.startswith(b'RIFF') or header[8:12] != b'WEBP':
                    return False
            elif not any(header.startswith(s) for s in sigs):
                return False
            return True

        if ext_lower not in ('html', 'htm'):
            lower_header = header.lower()
            for pattern in (b'<html', b'<script', b'<?php'):
                if pattern in lower_header:
                    return False

        return True
    except Exception:
        return True



def _log_safe(obj):
    """Redact sensitive data from log messages. Returns a sanitized string."""
    s = str(obj)
    # Redact emails: user@domain.com -> u***@domain.com
    import re
    s = re.sub(r'([a-zA-Z0-9])[a-zA-Z0-9._%+-]*@', lambda m: m.group(1) + '***@', s)
    # Redact phone numbers: +919876543210 -> +91******3210
    s = re.sub(r'(\+\d{2})\d{6}(\d{4})', r'******', s)
    return s




def _validate_cors_origin(request):
    """
    Validate Origin/Referer header against allowed origins for state-changing requests.
    Only blocks actual mismatches; allows if headers absent.
    """
    allowed_origins = {'http://localhost:8080', 'http://127.0.0.1:8080'}
    prod_origin = os.getenv('ALLOWED_ORIGIN', '').strip()
    if prod_origin:
        allowed_origins.add(prod_origin)

    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return True

    origin = request.headers.get('Origin', '').strip().rstrip('/')
    referer = request.headers.get('Referer', '').strip().rstrip('/')

    if not origin and not referer:
        return True

    check = origin or referer
    for allowed in allowed_origins:
        if check.startswith(allowed):
            return True

    import logging
    log = logging.getLogger(__name__)
    log.warning(f"⚠️ CSRF check failed: method={request.method}, origin={origin}, referer={referer}")
    return False


# ==================== RATE LIMITER ====================


def _is_admin(request):
    """Check if the request user is an admin. Also enabled if DEBUG=true."""
    if os.getenv('DEBUG', '').lower() in ('true', '1', 'yes'):
        return True
    admin_ids_str = os.getenv('ADMIN_USER_IDS', '').strip()
    if not admin_ids_str:
        return False
    admin_ids = set(a.strip() for a in admin_ids_str.split(',') if a.strip())
    try:
        import jwt
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return False
        token = auth.replace('Bearer ', '')
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload.get('user_id') in admin_ids
    except Exception:
        return False


# ==================== CSRF PROTECTION ====================


