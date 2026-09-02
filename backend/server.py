#!/usr/bin/env python3
"""
DecentralChat - Production-Ready Backend
Features: Firebase Auth, WebRTC Calls, File Uploads, Voice Messages, Decentralized Storage
"""
from dotenv import load_dotenv
load_dotenv() 

import os
print("=" * 70)
print("🔍 ENVIRONMENT VARIABLES CHECK:")
print(f"TWILIO_CONFIGURED: {bool(os.getenv('TWILIO_ACCOUNT_SID') and os.getenv('TWILIO_AUTH_TOKEN') and os.getenv('TWILIO_PHONE_NUMBER'))}")
print(f"Current working directory: {os.getcwd()}")
print(f".env file exists: {os.path.exists('.env')}")
print("=" * 70)

import asyncio
import json
import hashlib
import jwt
import datetime
import uuid
import os
import base64
import bcrypt
import random
import mimetypes
import secrets
import string
from datetime import timedelta
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
from typing import Dict, Set, Optional, List
from aiohttp import web
import aiohttp_cors
from aiohttp_session import setup as setup_session, get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, storage as firebase_storage, firestore
import redis.asyncio as redis
from cryptography.fernet import Fernet
import logging
from pathlib import Path
# File conversion imports
from PIL import Image, ImageOps
import PyPDF2
from docx import Document
from pptx import Presentation
import openpyxl
import subprocess
import io
import tempfile

# Advanced PDF conversion (install with: pip install pdf2docx)
try:
    from pdf2docx import Converter as PDFConverter
    HAS_PDF2DOCX = True
except ImportError:
    HAS_PDF2DOCX = False
    PDFConverter = None
    
# Check for LibreOffice/unoconv for document conversions
import shutil
HAS_LIBREOFFICE = shutil.which('soffice') or shutil.which('libreoffice')
HAS_UNOCONV = shutil.which('unoconv')

# Robust FFmpeg discovery - search common locations as fallback
FFMPEG_PATH = None
_ffmpeg_checked = shutil.which('ffmpeg')
if _ffmpeg_checked:
    FFMPEG_PATH = _ffmpeg_checked
else:
    # Typical install paths on Windows
    _common_ffmpeg_paths = [
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\ProgramData\chocolatey\bin\ffmpeg.exe',
        os.path.expanduser(r'~\scoop\apps\ffmpeg\current\bin\ffmpeg.exe'),
        os.path.expanduser(r'~\AppData\Local\Microsoft\WinGet\Packages\ffmpeg\ffmpeg.exe'),
    ]
    # Search for ffmpeg.exe recursively in common parent dirs
    _search_dirs = [
        r'C:\Program Files',
        r'C:\Program Files (x86)',
        os.path.expanduser(r'~\Documents'),
        os.path.expanduser(r'~\Downloads'),
    ]
    for _d in _search_dirs:
        if os.path.isdir(_d):
            try:
                for _root, _dirs, _files in os.walk(_d):
                    if 'ffmpeg.exe' in _files:
                        FFMPEG_PATH = os.path.join(_root, 'ffmpeg.exe')
                        break
                    # Don't walk too deep
                    if _root.count(os.sep) > 6:
                        break
            except Exception:
                pass
            if FFMPEG_PATH:
                break
    if not FFMPEG_PATH:
        # Try with PATH including User PATH
        _user_path = os.environ.get('PATH', '')
        _possible = shutil.which('ffmpeg', path=_user_path)
        if _possible:
            FFMPEG_PATH = _possible
    if not FFMPEG_PATH:
        # Last resort: try to find via where.exe
        try:
            _r = subprocess.run(['where.exe', 'ffmpeg'], capture_output=True, text=True, timeout=5)
            if _r.returncode == 0:
                _line = _r.stdout.strip().split('\n')[0].strip()
                if _line:
                    FFMPEG_PATH = _line
        except Exception:
            pass

if FFMPEG_PATH:
    # Add the directory to PATH so subprocess calls find it
    _ffmpeg_dir = str(Path(FFMPEG_PATH).parent)
    if _ffmpeg_dir not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')

# Configure logging early so it can be used below
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# HTML parsing for better conversions
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger.warning("⚠️ beautifulsoup4 not installed. HTML conversions will be basic.")

# Markdown conversion
try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False
    logger.warning("⚠️ markdown not installed. Markdown conversions will be basic.")

# Print conversion capabilities at startup
def print_conversion_capabilities():
    """Print available conversion tools and capabilities"""
    logger.info("=" * 70)
    logger.info("🔄 FILE CONVERSION CAPABILITIES")
    logger.info("=" * 70)
    
    # Check PDF conversion
    if HAS_PDF2DOCX:
        logger.info("✅ pdf2docx: INSTALLED - High-quality PDF→DOCX with images")
    else:
        logger.warning("⚠️ pdf2docx: NOT INSTALLED - PDF conversions will be text-only")
        logger.info("   Install with: pip install pdf2docx")
    
    # Check LibreOffice
    if HAS_LIBREOFFICE:
        logger.info(f"✅ LibreOffice: FOUND at {shutil.which('soffice') or shutil.which('libreoffice')}")
        logger.info("   Supports: PDF↔DOCX, PPT→PDF, with images & formatting")
    else:
        logger.warning("⚠️ LibreOffice: NOT FOUND - Advanced document conversions unavailable")
        logger.info("   Install: https://www.libreoffice.org/download/")
    
    # Check other tools
    if HAS_BS4:
        logger.info("✅ BeautifulSoup4: INSTALLED - Enhanced HTML parsing")
    else:
        logger.warning("⚠️ beautifulsoup4: NOT INSTALLED - Basic HTML parsing only")
    
    if HAS_MARKDOWN:
        logger.info("✅ Markdown: INSTALLED - Markdown conversions available")
    
    # Check ffmpeg for media conversions
    if shutil.which('ffmpeg') or FFMPEG_PATH:
        _ffmpeg_loc = FFMPEG_PATH or shutil.which('ffmpeg')
        logger.info(f"✅ FFmpeg: FOUND at {_ffmpeg_loc} - Audio/video conversions available")
    else:
        logger.warning("⚠️ FFmpeg: NOT FOUND - Media conversions unavailable")
    
    logger.info("=" * 70)
    
    # Provide recommendations
    if not HAS_PDF2DOCX or not HAS_LIBREOFFICE:
        logger.warning("⚠️ RECOMMENDATION: Install LibreOffice and pdf2docx for best conversion quality")
        logger.info("   With these tools, conversions will preserve:")
        logger.info("   • Images and graphics")
        logger.info("   • Text formatting (fonts, colors, sizes)")
        logger.info("   • Page layouts and structure")
        logger.info("   • Tables and charts")
    else:
        logger.info("✅ All conversion tools installed - Full capability available!")
    
    logger.info("=" * 70)

print_conversion_capabilities()

# ==================== SECURE KEY MANAGEMENT ====================

def _ensure_secret_key(path=None):
    """
    Load SECRET_KEY from env var, or from a file on disk, or generate once and persist.
    Ensures JWT signing key never changes across restarts.
    """
    env_key = os.getenv('SECRET_KEY')
    if env_key:
        return env_key
    if path is None:
        path = os.path.join(os.path.dirname(__file__), '.secret_key')
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
        path = os.path.join(os.path.dirname(__file__), '.fernet_key')
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


def _log_safe(obj):
    """Redact sensitive data from log messages. Returns a sanitized string."""
    s = str(obj)
    # Redact emails: user@domain.com -> u***@domain.com
    import re
    s = re.sub(r'([a-zA-Z0-9])[a-zA-Z0-9._%+-]*@', lambda m: m.group(1) + '***@', s)
    # Redact phone numbers: +919876543210 -> +91******3210
    s = re.sub(r'(\+\d{2})\d{6}(\d{4})', r'******', s)
    return s



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

class RateLimiter:
    """Simple in-memory rate limiter (no locks needed — single event loop)."""
    
    def __init__(self, max_attempts=5, window_seconds=60):
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._store = {}  # key -> list[float] timestamps

    def is_rate_limited(self, key):
        """Check and record an attempt. Returns True if limited."""
        import time
        now = time.time()
        window = self._window
        if key not in self._store:
            self._store[key] = []
        timestamps = self._store[key]
        cutoff = now - window
        self._store[key] = [t for t in timestamps if t > cutoff]
        if len(self._store[key]) >= self._max_attempts:
            return True
        self._store[key].append(now)
        return False


class DecentralChatServer:
    def __init__(self):
        self.app = web.Application(client_max_size=MAX_FILE_SIZE)
        self.firebase_app = None
        self.storage_bucket = None
        self.rate_limiter = RateLimiter(max_attempts=5, window_seconds=60)
        
    async def initialize(self):
        """Initialize all services"""
        await self.init_redis()
        self.init_firebase()
        await self.migrate_existing_files()
        # ✅ ALWAYS reload data from Firestore on startup
        await self.preload_critical_data_from_firestore()
        
        # Add CSRF middleware
        @web.middleware
        async def csrf_middleware(request, handler):
            if not _validate_cors_origin(request):
                return web.json_response({"error": "Forbidden"}, status=403)
            return await handler(request)
        self.app.middlewares.append(csrf_middleware)

        # Security headers middleware
        @web.middleware
        async def security_headers_middleware(request, handler):
            resp = await handler(request)
            resp.headers['X-Content-Type-Options'] = 'nosniff'
            resp.headers['X-Frame-Options'] = 'DENY'
            resp.headers['X-XSS-Protection'] = '1; mode=block'
            resp.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "img-src 'self' data: https:; "
                "media-src 'self' https:; "
                "connect-src 'self' ws: wss:; "
                "font-src 'self' https:; "
                "style-src 'self' 'unsafe-inline' https:; "
                "script-src 'self' 'unsafe-inline' https:; "
                "frame-src 'none'"
            )
            return resp
        self.app.middlewares.append(security_headers_middleware)
        
        self.setup_routes()
        self.setup_cors()   
        self.setup_session()
        
        if self.db:
            asyncio.create_task(self.sync_redis_to_firestore_periodically())
            logger.info("✅ Started periodic Firestore sync")
        
        logger.info("✅ Server initialized successfully")

    # ==================== REDIS INITIALIZATION ====================
    
    async def init_redis(self):
        """Initialize Redis for decentralized storage"""
        global redis_client
        try:
            redis_client = await redis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5
            )
            await redis_client.ping()
            logger.info("✅ Redis connected successfully")
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed: {e}")
            logger.info("ℹ️  Running with Firestore-only mode (Redis is optional)")
            logger.info("   Redis provides caching but is not required for operation")
            logger.info("   To install Redis: https://redis.io/docs/install/")
            # Fallback to in-memory mock
            redis_client = MockRedis()

    # ==================== FIREBASE INITIALIZATION ====================
    
    def init_firebase(self):
        """Initialize Firebase for authentication and Firestore ONLY (no Storage)"""
        try:
            if os.path.exists(FIREBASE_CRED):
                cred = credentials.Certificate(FIREBASE_CRED)
                
                # Check if app already exists
                try:
                    self.firebase_app = firebase_admin.get_app()
                    logger.info("✅ Using existing Firebase app")
                except ValueError:
                    # App doesn't exist, initialize it
                    self.firebase_app = firebase_admin.initialize_app(cred)
                    logger.info("✅ Firebase initialized")
                
                self.db = firestore.client()
                self.storage_bucket = None
                
            else:
                logger.warning("⚠️ Firebase config not found")
                self.firebase_app = None
                self.db = None
                self.storage_bucket = None
        except Exception as e:
            logger.error(f"❌ Firebase error: {e}")
            self.firebase_app = None
            self.db = None
            self.storage_bucket = None

    # ==================== SESSION & CORS ====================
    
    def setup_session(self):
        """Setup encrypted session storage"""
        secret_key = SECRET_KEY.encode()[:32].ljust(32, b'0')
        setup_session(self.app, EncryptedCookieStorage(secret_key))

    def setup_cors(self):
        """Setup CORS for all routes"""
        allowed_origin = os.getenv('ALLOWED_ORIGIN', '*')
        cors = aiohttp_cors.setup(self.app, defaults={
            allowed_origin: aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })
        for route in list(self.app.router.routes()):
            cors.add(route)

    # ==================== ROUTES ====================
    
    def setup_routes(self):
        """Setup all API routes"""
                # Custom file-serving route that supports ?token= JWT auth
        # (Backward-compatible: still falls through to static dir)
        self.app.router.add_get('/api/uploads/{filename:.*}', self.serve_upload)
        # Also register the static dir as fallback
        self.app.router.add_static('/api/uploads/', path=str(UPLOAD_DIR), name='uploads')
        # Root
        self.app.router.add_get('/', self.serve_frontend)  
        self.app.router.add_get('/index.html', self.serve_frontend)
        self.app.router.add_get('/favicon.ico', self.serve_favicon)
        self.app.router.add_get('/api', self.index)
        self.app.router.add_get('/health', self.health_check)
        
        # Authentication
        self.app.router.add_post('/api/auth/register', self.handle_register)
        self.app.router.add_post('/api/auth/login', self.handle_login)
        self.app.router.add_post('/api/auth/google', self.handle_google_auth)
        self.app.router.add_post('/api/auth/logout', self.handle_logout)
        self.app.router.add_post('/api/auth/refresh', self.refresh_token)
        
        # User management
        self.app.router.add_get('/api/users/me', self.get_current_user)
        self.app.router.add_put('/api/users/me', self.update_profile)
        self.app.router.add_post('/api/users/avatar', self.upload_avatar)
        self.app.router.add_get('/api/users/search', self.search_users)
        self.app.router.add_get('/api/users/{user_id}/public_key', self.get_user_public_key)
        
        # Contacts
        self.app.router.add_get('/api/contacts', self.get_contacts)
        self.app.router.add_post('/api/contacts', self.add_contact)
        self.app.router.add_delete('/api/contacts/{contact_id}', self.remove_contact)
        
        # Chats
        self.app.router.add_get('/api/chats', self.get_chats)
        self.app.router.add_post('/api/chats', self.create_chat)
        self.app.router.add_get('/api/chats/{chat_id}', self.get_chat)
        self.app.router.add_delete('/api/chats/{chat_id}', self.delete_chat)
        self.app.router.add_post('/api/chats/{chat_id}/members', self.add_chat_member)
        self.app.router.add_delete('/api/chats/{chat_id}/members/{user_id}', self.remove_chat_member)
        
        # Messages
        self.app.router.add_get('/api/chats/{chat_id}/messages', self.get_messages)
        self.app.router.add_post('/api/chats/{chat_id}/messages', self.send_message_http)
        self.app.router.add_delete('/api/messages/{message_id}', self.delete_message)
        self.app.router.add_put('/api/messages/{message_id}', self.edit_message)
        self.app.router.add_get('/api/chats/{chat_id}/messages/search', self.search_messages_in_chat)

        
        # File uploads
        self.app.router.add_post('/api/upload/file', self.upload_file)
        self.app.router.add_post('/api/upload/voice', self.upload_voice)
        self.app.router.add_get('/api/files/{file_id}', self.get_file)
        self.app.router.add_get('/api/files/{file_id}/thumbnail', self.get_thumbnail)
        
        # File conversion routes
        self.app.router.add_post('/api/files/convert', self.convert_uploaded_file)
        self.app.router.add_get('/api/files/conversion-formats', self.get_conversion_formats)
        self.app.router.add_get('/api/files/conversion-progress/{conversion_id}', self.get_conversion_progress)


        # Calls (WebRTC signaling)
        self.app.router.add_post('/api/calls/initiate', self.initiate_call)
        self.app.router.add_post('/api/calls/{call_id}/signal', self.handle_call_signal)
        self.app.router.add_post('/api/calls/{call_id}/end', self.end_call)
        self.app.router.add_get('/api/calls/history', self.get_call_history)
        self.app.router.add_get('/api/calls/{call_id}/signals', self.get_call_signals)
        
        # Group Calls
        self.app.router.add_post('/api/calls/group/initiate', self.initiate_group_call)
        self.app.router.add_post('/api/calls/group/{call_id}/join', self.join_group_call)
        self.app.router.add_post('/api/calls/group/{call_id}/leave', self.leave_group_call)
        self.app.router.add_get('/api/calls/group/{call_id}/participants', self.get_group_call_participants)
        
        # WebSocket
        self.app.router.add_get('/api/ws', self.websocket_handler)

        # Settings routes
        self.app.router.add_get('/api/users/settings', self.get_user_settings)
        self.app.router.add_put('/api/users/settings', self.update_user_settings)
        self.app.router.add_put('/api/users/profile', self.update_user_profile)

        # Phone verification routes
        self.app.router.add_post('/api/auth/send-verification-code', self.send_verification_code)
        self.app.router.add_post('/api/auth/verify-phone', self.verify_phone_code)

        # Enhanced message actions
        self.app.router.add_delete('/api/messages/{message_id}/for-all', self.delete_message_for_all)
        self.app.router.add_delete('/api/messages/{message_id}/for-me', self.delete_message_for_me)
        self.app.router.add_post('/api/messages/forward', self.forward_message)
        
        # Static files
        self.app.router.add_get('/api/debug/check-user/{username}', self.debug_check_user)
        self.app.router.add_get('/api/debug/redis/{username}', self.debug_redis_state)

        self.app.router.add_get('/api/debug/my-chats', self.debug_user_chats)
        self.app.router.add_get('/api/users/{user_id}/blocked-status', self.check_blocked_status)


        #Updates in profile
        self.app.router.add_put('/api/chats/{chat_id}/info', self.update_group_chat)
        self.app.router.add_put('/api/users/email', self.update_email)
        self.app.router.add_put('/api/users/phone', self.update_phone)
        self.app.router.add_get('/api/users/search-all', self.search_all_users)
        self.app.router.add_get('/api/users/{user_id}', self.get_user_by_id)


        # Blocking routes
        self.app.router.add_post('/api/users/block', self.block_user)
        self.app.router.add_post('/api/users/unblock', self.unblock_user)
        self.app.router.add_get('/api/users/blocked', self.get_blocked_users)


        # **NEW: Log all registered routes on startup**
        logger.info("=" * 70)
        logger.info("📋 Registered API Routes:")
        for route in self.app.router.routes():
            logger.info(f"  {route.method:6s} {route.resource.canonical}")
        logger.info("=" * 70)


    # ==================== AUTHENTICATION ====================

    async def handle_register(self, request):
        """Register new user with bcrypt password hashing"""
        try:
            # Rate limiting
            ip = request.remote or request.headers.get('X-Forwarded-For', 'unknown')
            if self.rate_limiter.is_rate_limited(f"register:{ip}"):
                logger.warning(f"⚠️ Rate limited registration attempt from {ip}")
                return web.json_response({"error": "Too many attempts. Please try again later."}, status=429)

            data = await request.json()
            
            # ADD THESE SAFETY CHECKS
            if not isinstance(data, dict):
                logger.error(f"❌ Invalid request data type: {type(data)}")
                return web.json_response(
                    {"error": "Invalid request format"},
                    status=400
                )
        
            # Log incoming data for debugging
            logger.info(f"📥 Registration data keys: {list(data.keys())}")
            
            # FIXED: Properly extract and validate each field
            username = str(data.get('username', '')).strip() if data.get('username') else ''
            password = str(data.get('password', '')) if data.get('password') else ''
            email = str(data.get('email', '')).strip() if data.get('email') else ''
            phone = str(data.get('phone', '')).strip() if data.get('phone') else ''
            
            logger.info(f"📝 Parsed values - username: '{username}', email: '{_log_safe(email)}', phone: '{_log_safe(phone)}'")

            # Validation
            if not username or len(username) < 3:
                return web.json_response(
                    {"error": "Username must be at least 3 characters"},
                    status=400
                )
            
            is_valid, pw_msg = _validate_password(password) if password else (False, "Password is required")
            if not is_valid:
                return web.json_response(
                    {"error": pw_msg},
                    status=400
                )

            # Check if username already exists in Redis
            existing_user_id = await redis_client.hget("username_map", username.lower())
            if existing_user_id:
                logger.warning(f"⚠️ Username '{username}' already exists in Redis (user_id: {existing_user_id})")
                
                # Check if this is a ghost entry (user data doesn't exist)
                user_data_check = await redis_client.hgetall(f"user:{existing_user_id}")
                
                if not user_data_check:
                    logger.error(f"🔧 GHOST ENTRY DETECTED: username_map has '{username}' -> '{existing_user_id}' but user data doesn't exist!")
                    logger.info(f"🔧 Cleaning up ghost entry...")
                    await redis_client.hdel("username_map", username.lower())
                    logger.info(f"✅ Ghost entry cleaned, proceeding with registration")
                    # Continue to Firestore check below
                else:
                    logger.info(f"✅ Valid existing user found: {user_data_check.get('username')} (created: {user_data_check.get('created_at')})")
                    return web.json_response(
                        {"error": f"Username '{username}' is already taken"},
                        status=409
                    )

            # Check Firestore only if Redis didn't find a valid user
            if self.db:
                try:
                    docs = list(self.db.collection('users').where('username', '==', username).limit(1).stream())
                    if docs:
                        logger.warning(f"⚠️ Username '{username}' exists in Firestore")
                        doc_data = docs[0].to_dict()
                        logger.info(f"📋 Firestore user: ID={docs[0].id}, created_at={doc_data.get('created_at')}")
                        return web.json_response(
                            {"error": f"Username '{username}' is already taken"},
                            status=409
                        )
                except Exception as fb_err:
                    logger.error(f"Firestore check error: {fb_err}")

            # Check if email already exists
            if email:
                existing_email_user = await redis_client.hget("email_map", email.lower())
                if existing_email_user:
                    return web.json_response(
                        {"error": "Email already exists"},
                        status=409
                    )

            # Hash password with bcrypt
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            logger.info(f"✅ Password hashed successfully")

            # Generate user ID
            user_id = str(uuid.uuid4())
            logger.info(f"📝 Creating user with ID: {user_id}")

            # Store user data in Redis
            user_data = {
                "id": user_id,
                "username": username,
                "email": email,
                "phone": phone,
                "password_hash": password_hash,
                "role": "user",
                "status": "offline",
                "avatar_url": "",
                "bio": "",
                "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "last_seen": "",
                "auth_provider": "local",
                "settings": json.dumps({
                    "notifications": True,
                    "read_receipts": True,
                    "typing_indicator": True,
                    "online_status": True
                })
            }

            # Save to Redis with ALL mappings
            await redis_client.hset(f"user:{user_id}", mapping=user_data)
            await redis_client.sadd("users:all", user_id)
            # Store username in lowercase for case-insensitive lookups
            await redis_client.hset("username_map", username.lower(), user_id)
            
            if email:
                # Store email in lowercase for case-insensitive lookups
                await redis_client.hset("email_map", email.lower(), user_id)
            
            if phone:
                await redis_client.hset("phone_map", phone, user_id)

            logger.info(f"✅ User saved to Redis: {user_id}")

            # Save to Firestore
            if self.db:
                try:
                    self.db.collection('users').document(user_id).set({
                        'id': user_id,
                        'username': username,
                        'email': email or '',
                        'phone': phone or '',
                        'password_hash': password_hash,
                        'role': 'user',
                        'status': 'offline',
                        'avatar_url': '',
                        'bio': '',
                        'created_at': firestore.SERVER_TIMESTAMP,
                        'auth_provider': 'local',
                        'last_seen': firestore.SERVER_TIMESTAMP,
                        'settings': {
                            "notifications": True,
                            "read_receipts": True,
                            "typing_indicator": True,
                            "online_status": True
                        }
                    })
                    logger.info(f"✅ User {user_id} saved to Firestore")
                except Exception as fb_err:
                    logger.error(f"Firestore save failed: {fb_err}")

            # Generate JWT tokens
            token = self.generate_token(user_id)
            refresh_token = self._generate_refresh_token(user_id, request.headers.get('User-Agent', '')[:128])

            logger.info(f"✅ User registered successfully: {username} (ID: {user_id})")

            return web.json_response({
                "success": True,
                "token": token,
                "refresh_token": refresh_token,
                "user": {
                    "id": user_id,
                    "username": username,
                    "email": email,
                    "phone": phone,
                    "role": "user",
                    "avatar_url": "",
                    "bio": ""
                }
            })

        except Exception as e:
            logger.error(f"❌ Registration error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def debug_redis_state(self, request):
        """Debug: Check Redis state"""
        if not _is_admin(request):
            return web.json_response({"error": "Not found"}, status=404)
        username = request.match_info.get('username', 'all')
        
        if username == 'all':
            all_users = await redis_client.smembers("users:all")
            username_map = {}
            for key in await redis_client.hkeys("username_map"):
                username_map[key] = await redis_client.hget("username_map", key)
            
            return web.json_response({
                "total_users": len(all_users),
                "user_ids": list(all_users),
                "username_mappings": username_map
            })
        else:
            user_id = await redis_client.hget("username_map", username)
            if user_id:
                user_data = await redis_client.hgetall(f"user:{user_id}")
                return web.json_response({
                    "found": True,
                    "user_id": user_id,
                    "has_password": bool(user_data.get('password_hash')),
                    "fields": list(user_data.keys())
                })
            else:
                return web.json_response({"found": False})

    async def handle_login(self, request):
        """Login user with bcrypt password verification"""
        try:
            # Rate limiting
            ip = request.remote or request.headers.get('X-Forwarded-For', 'unknown')
            if self.rate_limiter.is_rate_limited(f"login:{ip}"):
                logger.warning(f"⚠️ Rate limited login attempt from {ip}")
                return web.json_response({"error": "Too many attempts. Please try again later."}, status=429)

            data = await request.json()
            identifier = data.get('username', '').strip()
            password = data.get('password', '')

            logger.info(f"🔐 Login attempt for: {_log_safe(identifier)}")

            if not identifier or not password:
                return web.json_response(
                    {"error": "Username/email and password required"},
                    status=400
                )

            # ✅ CRITICAL FIX: Try ALL possible lookups with case-insensitive search
            user_id = None
            user_data = None

            # Step 1: Try Redis username lookup (case-insensitive)
            user_id = await redis_client.hget("username_map", identifier.lower())
            logger.info(f"🔍 Redis username_map check: {user_id}")
            
            # Step 2: Try Redis email lookup (case-insensitive)
            if not user_id and '@' in identifier:
                user_id = await redis_client.hget("email_map", identifier.lower())
                logger.info(f"🔍 Redis email_map check: {user_id}")
            
            # Step 3: Try Redis phone lookup
            if not user_id and identifier.startswith('+'):
                user_id = await redis_client.hget("phone_map", identifier)
                logger.info(f"🔍 Redis phone_map check: {user_id}")

            # Step 4: Get user data from Redis if found
            if user_id:
                user_data = await redis_client.hgetall(f"user:{user_id}")
                logger.info(f"🔍 Redis user data found: {bool(user_data)}, has password: {bool(user_data.get('password_hash'))}")

            # Step 5: If Redis fails, check Firestore
            if not user_data or not user_data.get('password_hash'):
                logger.warning(f"⚠️ Redis incomplete, checking Firestore for: {identifier}")
                
                if self.db:
                    try:
                        users_ref = self.db.collection('users')
                        docs = []
                        
                        # Try all identifiers
                        for field, value in [
                            ('username', identifier),
                            ('email', identifier if '@' in identifier else None),
                            ('phone', identifier if identifier.startswith('+') else None)
                        ]:
                            if value:
                                query_docs = list(users_ref.where(field, '==', value).limit(1).stream())
                                if query_docs:
                                    docs = query_docs
                                    break
                        
                        if docs:
                            doc = docs[0]
                            user_id = doc.id
                            user_data_fb = doc.to_dict()
                            
                            logger.info(f"✅ Found in Firestore: {user_id}")
                            
                            # Reconstruct complete user data
                            user_data = {
                                'id': user_id,
                                'username': user_data_fb.get('username', ''),
                                'email': user_data_fb.get('email', ''),
                                'phone': user_data_fb.get('phone', ''),
                                'password_hash': user_data_fb.get('password_hash', ''),
                                'role': user_data_fb.get('role', 'user'),
                                'status': 'offline',
                                'avatar_url': user_data_fb.get('avatar_url', ''),
                                'bio': user_data_fb.get('bio', ''),
                                'auth_provider': user_data_fb.get('auth_provider', 'local'),
                                'google_id': user_data_fb.get('google_id', ''),
                                'created_at': str(user_data_fb.get('created_at', datetime.datetime.now(datetime.UTC).isoformat())),
                                'last_seen': '',
                                'settings': json.dumps(user_data_fb.get('settings', {
                                    "notifications": True,
                                    "read_receipts": True,
                                    "typing_indicator": True,
                                    "online_status": True
                                }))
                            }
                            
                            # ✅ CRITICAL: Restore ALL mappings to Redis
                            await redis_client.hset(f"user:{user_id}", mapping=user_data)
                            await redis_client.sadd("users:all", user_id)
                            
                            if user_data['username']:
                                await redis_client.hset("username_map", user_data['username'], user_id)
                            if user_data['email']:
                                await redis_client.hset("email_map", user_data['email'], user_id)
                            if user_data['phone']:
                                await redis_client.hset("phone_map", user_data['phone'], user_id)
                            if user_data['google_id']:
                                await redis_client.hset("google_id_map", user_data['google_id'], user_id)
                            
                            logger.info(f"✅ User {user_id} fully restored to Redis with all mappings")
                            
                    except Exception as fb_err:
                        logger.error(f"❌ Firestore query error: {fb_err}")

            # Step 6: Final check
            if not user_data:
                logger.error(f"❌ User not found anywhere: {identifier}")
                return web.json_response({"error": "User not found"}, status=404)

            if not user_data.get('password_hash'):
                logger.error(f"❌ No password hash for: {identifier}")
                return web.json_response(
                    {"error": "Account has no password set"},
                    status=400
                )

            # Step 7: Check auth provider
            auth_provider = user_data.get('auth_provider', 'local')
            if auth_provider == 'google':
                return web.json_response(
                    {"error": "This account uses Google Sign-In"},
                    status=400
                )

            # Step 8: Verify password
            stored_hash = user_data.get('password_hash', '')
            
            logger.info(f"🔐 Attempting password verification for: {identifier}")
            
            try:
                if not bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                    logger.warning(f"❌ Invalid password for: {identifier}")
                    return web.json_response({"error": "Invalid password"}, status=401)
            except Exception as e:
                logger.error(f"❌ Password verification error: {e}")
                return web.json_response({"error": "Authentication failed"}, status=401)

            # Step 9: Generate tokens
            token = self.generate_token(user_id)
            refresh_token = self._generate_refresh_token(user_id, request.headers.get('User-Agent', '')[:128])

            # Step 10: Update status
            await redis_client.hset(f"user:{user_id}", mapping={
                "status": "online",
                "last_seen": datetime.datetime.now(datetime.UTC).isoformat(),
                "last_login": datetime.datetime.now(datetime.UTC).isoformat()
            })

            logger.info(f"✅ Login successful: {user_data.get('username')} (ID: {user_id})")

            return web.json_response({
                "success": True,
                "token": token,
                "refresh_token": refresh_token,
                "user": {
                    "id": user_id,
                    "username": user_data.get('username'),
                    "email": user_data.get('email'),
                    "phone": user_data.get('phone'),
                    "role": user_data.get('role'),
                    "avatar_url": user_data.get('avatar_url'),
                    "bio": user_data.get('bio'),
                    "status": "online"
                }
            })

        except Exception as e:
            logger.error(f"❌ Login error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_logout(self, request):
        """Logout user"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            # Update status
            await redis_client.hset(f"user:{user_id}", "status", "offline")
            await redis_client.hset(f"user:{user_id}", "last_seen", datetime.datetime.now(datetime.UTC).isoformat())

            # Close WebSocket connections
            if user_id in active_connections:
                for ws in list(active_connections[user_id]):
                    await ws.close()
                del active_connections[user_id]

            logger.info(f"✅ User logged out: {user_id}")

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Logout error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def debug_check_user(self, request):
        """Debug: Check if user exists in Redis and Firestore"""
        if not _is_admin(request):
            return web.json_response({"error": "Not found"}, status=404)
        username = request.match_info['username']
        
        result = {
            'username': username,
            'redis_username_map': None,
            'redis_user_data': None,
            'firestore_user': None
        }
        
        # Check Redis
        user_id = await redis_client.hget("username_map", username)
        result['redis_username_map'] = user_id
        
        if user_id:
            user_data = await redis_client.hgetall(f"user:{user_id}")
            result['redis_user_data'] = {
                'id': user_data.get('id'),
                'username': user_data.get('username'),
                'has_password_hash': bool(user_data.get('password_hash')),
                'auth_provider': user_data.get('auth_provider')
            }
        
        # Check Firestore
        if self.db:
            try:
                docs = list(self.db.collection('users').where('username', '==', username).limit(1).stream())
                if docs:
                    doc_data = docs[0].to_dict()
                    result['firestore_user'] = {
                        'id': docs[0].id,
                        'username': doc_data.get('username'),
                        'has_password_hash': bool(doc_data.get('password_hash')),
                        'auth_provider': doc_data.get('auth_provider')
                    }
            except Exception as e:
                result['firestore_error'] = str(e)
        
        return web.json_response(result)
    async def debug_user_chats(self, request):
        """Debug: Check user's chats"""
        if not _is_admin(request):
            return web.json_response({"error": "Not found"}, status=404)
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)
            
            # Get user's chats from Redis
            chat_ids = await redis_client.smembers(f"user_chats:{user_id}")
            
            chats_info = []
            for chat_id in chat_ids:
                chat_data = await redis_client.hgetall(f"chat:{chat_id}")
                members = await redis_client.smembers(f"chat_members:{chat_id}")
                
                chats_info.append({
                    "chat_id": chat_id,
                    "type": chat_data.get('type'),
                    "name": chat_data.get('name'),
                    "member_count": len(members),
                    "members": list(members)
                })
            
            return web.json_response({
                "user_id": user_id,
                "total_chats": len(chat_ids),
                "chats": chats_info
            })
            
        except Exception as e:
            logger.error(f"Debug user chats error: {e}")
            return web.json_response({"error": str(e)}, status=500)
            
    async def refresh_token(self, request):
        """Refresh JWT access token using a refresh token."""
        try:
            data = await request.json()
            refresh_token_str = data.get('refresh_token', '')
            if not refresh_token_str:
                return web.json_response({"error": "Refresh token required"}, status=400)

            # Decode the refresh token
            try:
                payload = jwt.decode(refresh_token_str, SECRET_KEY, algorithms=['HS256'])
            except jwt.ExpiredSignatureError:
                return web.json_response({"error": "Refresh token expired. Please log in again."}, status=401)
            except jwt.InvalidTokenError:
                return web.json_response({"error": "Invalid refresh token"}, status=401)

            if payload.get('type') != 'refresh':
                return web.json_response({"error": "Invalid token type"}, status=401)

            token_id = payload.get('token_id')
            user_id = payload.get('user_id')

            if not token_id or not user_id:
                return web.json_response({"error": "Invalid refresh token payload"}, status=401)

            # Check if refresh token was revoked (exists in Redis)
            stored = await redis_client.hgetall(f"refresh_token:{token_id}")
            if stored and stored.get('revoked') == 'true':
                logger.warning(f"⚠️ Attempted use of revoked refresh token {token_id} for user {user_id}")
                return web.json_response({"error": "Refresh token revoked. Please log in again."}, status=401)

            # Optionally rotate: revoke old, issue new
            if stored:
                await redis_client.hset(f"refresh_token:{token_id}", "revoked", "true")

            # Generate new access + refresh tokens
            device_fp = request.headers.get('User-Agent', '')[:128]
            new_access = self.generate_token(user_id)
            new_refresh = self._generate_refresh_token(user_id, device_fp)

            return web.json_response({
                "success": True,
                "token": new_access,
                "refresh_token": new_refresh
            })

        except Exception as e:
            logger.error(f"❌ Refresh token error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    def generate_token(self, user_id: str) -> str:
        """Generate JWT access token (15-minute expiry)"""
        payload = {
            'user_id': user_id,
            'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15),
            'iat': datetime.datetime.now(datetime.UTC)
        }
        return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

    def _generate_refresh_token(self, user_id: str, device_fingerprint: str = '') -> str:
        """Generate a 30-day refresh token, stored in Redis for rotation."""
        token_id = str(uuid.uuid4())
        payload = {
            'user_id': user_id,
            'token_id': token_id,
            'type': 'refresh',
            'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30),
            'iat': datetime.datetime.now(datetime.UTC)
        }
        refresh_token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
        # Store in Redis with device fingerprint for revocation / rotation
        loop = asyncio.get_event_loop()
        try:
            token_data = {
                'user_id': user_id,
                'device_fingerprint': device_fingerprint,
                'created_at': datetime.datetime.now(datetime.UTC).isoformat()
            }
            asyncio.run_coroutine_threadsafe(
                self._store_refresh_token(token_id, token_data),
                loop
            )
        except Exception:
            pass  # Gracefully degrade: refresh still works, just no persistence
        return refresh_token

    async def _store_refresh_token(self, token_id: str, token_data: dict):
        """Persist refresh token metadata in Redis."""
        try:
            await redis_client.hset(f"refresh_token:{token_id}", mapping=token_data)
            await redis_client.expire(f"refresh_token:{token_id}", 30 * 24 * 3600)  # 30 days
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


    async def serve_frontend(self, request):
        """Serve the frontend HTML file"""
        try:
            # Path relative to backend directory
            frontend_path = Path(__file__).parent.parent / 'frontend' / 'index.html'
            
            if frontend_path.exists():
                return web.FileResponse(frontend_path)
            else:
                return web.Response(
                    text=f"Frontend not found at: {frontend_path}\n\nPlease ensure index.html exists in the frontend folder.",
                    status=404,
                    content_type='text/plain'
                )
        except Exception as e:
            logger.error(f"Serve frontend error: {e}")
            return web.Response(
                text=f"Error loading frontend: {str(e)}",
                status=500,
                content_type='text/plain'
            )

    async def serve_favicon(self, request):
        """Serve favicon"""
        try:
            favicon_path = Path(__file__).parent.parent / 'frontend' / 'favicon.ico'
            if favicon_path.exists():
                return web.FileResponse(favicon_path)
            return web.Response(status=204)
        except Exception as e:
            logger.error(f"Favicon error: {e}")
            return web.Response(status=204)

    # ==================== USER MANAGEMENT ====================
    
    async def preload_critical_data_from_firestore(self):
        """Load critical data from Firestore to Redis on startup"""
        if not self.db:
            logger.warning("⚠️ Firestore not available, skipping data preload")
            return
        
        try:
            logger.info("📥 Preloading data from Firestore to Redis...")
            
            # ========== LOAD USERS ==========
            users_ref = self.db.collection('users')
            users_docs = users_ref.stream()
            user_count = 0
            
            for doc in users_docs:
                user_id = doc.id
                user_data_fb = doc.to_dict()
                
                # Reconstruct Redis user data
                user_data = {
                    'id': user_id,
                    'username': user_data_fb.get('username', ''),
                    'email': user_data_fb.get('email', ''),
                    'phone': user_data_fb.get('phone', ''),
                    'password_hash': user_data_fb.get('password_hash', ''),
                    'role': user_data_fb.get('role', 'user'),
                    'status': 'offline',
                    'avatar_url': user_data_fb.get('avatar_url', ''),
                    'bio': user_data_fb.get('bio', ''),
                    'auth_provider': user_data_fb.get('auth_provider', 'local'),
                    'google_id': user_data_fb.get('google_id', ''),
                    'created_at': str(user_data_fb.get('created_at', datetime.datetime.now(datetime.UTC).isoformat())),
                    'last_seen': '',
                    'phone_verified': str(user_data_fb.get('phone_verified', False)),
                    'settings': json.dumps(user_data_fb.get('settings', {
                        "notifications": True,
                        "read_receipts": True,
                        "typing_indicator": True,
                        "online_status": True
                    }))
                }
                
                # Store in Redis
                await redis_client.hset(f"user:{user_id}", mapping=user_data)
                await redis_client.sadd("users:all", user_id)
                
                # Create mappings
                if user_data['username']:
                    await redis_client.hset("username_map", user_data['username'], user_id)
                if user_data['email']:
                    await redis_client.hset("email_map", user_data['email'], user_id)
                if user_data['phone']:
                    await redis_client.hset("phone_map", user_data['phone'], user_id)
                if user_data['google_id']:
                    await redis_client.hset("google_id_map", user_data['google_id'], user_id)
                
                user_count += 1
            
            logger.info(f"✅ Preloaded {user_count} users from Firestore to Redis")
            
            # ========== LOAD CHATS ==========
            chats_ref = self.db.collection('chats')
            chats_docs = list(chats_ref.stream())
            chat_count = 0
            total_messages = 0
            
            for doc in chats_docs:
                chat_id = doc.id
                chat_data = doc.to_dict()
                
                # Store chat in Redis
                redis_chat_data = {
                    'id': chat_id,
                    'type': chat_data.get('type', 'direct'),
                    'name': chat_data.get('name', ''),
                    'description': chat_data.get('description', ''),
                    'avatar_url': chat_data.get('avatar_url', ''),
                    'created_by': chat_data.get('created_by', ''),
                    'created_at': str(chat_data.get('created_at', datetime.datetime.now(datetime.UTC).isoformat()))
                }
                
                await redis_client.hset(f"chat:{chat_id}", mapping=redis_chat_data)
                await redis_client.sadd("chats:all", chat_id)
                
                # Load members
                members = chat_data.get('members', [])
                for member_id in members:
                    await redis_client.sadd(f"chat_members:{chat_id}", member_id)
                    await redis_client.sadd(f"user_chats:{member_id}", chat_id)
                    logger.info(f"✅ Mapped chat {chat_id} to user {member_id}")
                
                # Load messages for this chat
                try:
                    messages_ref = self.db.collection('chats').document(chat_id).collection('messages')
                    messages_query = messages_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(1000)
                    messages_docs = list(messages_query.stream())
                    
                    message_count = 0
                    for msg_doc in reversed(messages_docs):  # Reverse to get oldest first
                        msg_id = msg_doc.id
                        msg_data = msg_doc.to_dict()
                        
                        # Store message in Redis
                        redis_msg_data = {
                            'id': msg_id,
                            'chat_id': chat_id,
                            'sender_id': msg_data.get('sender_id', ''),
                            'content': msg_data.get('content', ''),
                            'message_type': msg_data.get('message_type', 'text'),
                            'encrypted': str(msg_data.get('encrypted', False)),
                            'attachments': json.dumps(msg_data.get('attachments', [])),
                            'reply_to': msg_data.get('reply_to', ''),
                            'created_at': str(msg_data.get('created_at', datetime.datetime.now(datetime.UTC).isoformat())),
                            'edited': str(msg_data.get('edited', False)),
                            'deleted': str(msg_data.get('deleted', False))
                        }
                        # 🔥 RESTORE delete-for-everyone state
                        if msg_data.get('deleted') is True:
                            redis_msg_data['deleted'] = "True"

                        await redis_client.hset(f"message:{msg_id}", mapping=redis_msg_data)
                        await redis_client.lpush(f"chat_messages:{chat_id}", msg_id)
                        message_count += 1
                        total_messages += 1
                    
                    # Trim to keep only last 1000 messages
                    await redis_client.ltrim(f"chat_messages:{chat_id}", 0, 999)
                    
                    if message_count > 0:
                        logger.info(f"✅ Loaded {message_count} messages for chat {chat_id}")
                        
                except Exception as msg_error:
                    logger.warning(f"Could not load messages for chat {chat_id}: {msg_error}")
                
                chat_count += 1
            
            logger.info(f"✅ Preloaded {chat_count} chats and {total_messages} messages from Firestore to Redis")
            
            # ========== LOAD CONTACTS ==========
            users_list = await redis_client.smembers("users:all")
            # 🔥 ONLY REQUIRED ADDITION (DO NOT REMOVE)
            users_list = [
                u.decode() if isinstance(u, bytes) else u
                for u in users_list
            ]

            # ========== RESTORE DELETE-FOR-ME ==========
            logger.info("📥 Restoring delete-for-me message states...")
            restored_count = 0

            for user_id in users_list:
                try:
                    deleted_ref = self.db.collection('users') \
                        .document(user_id) \
                        .collection('deleted_messages')

                    deleted_docs = deleted_ref.stream()

                    for doc in deleted_docs:
                        msg_id = doc.id
                        await redis_client.sadd(f"deleted_messages:{user_id}", msg_id)
                        restored_count += 1

                except Exception as e:
                    logger.warning(f"Could not restore deleted messages for user {user_id}: {e}")

            logger.info(f"✅ Restored {restored_count} delete-for-me entries")

            contact_count = 0
            
            for user_id in users_list:
                try:
                    contacts_ref = self.db.collection('users').document(user_id).collection('contacts')
                    contacts_docs = contacts_ref.stream()
                    
                    for contact_doc in contacts_docs:
                        contact_id = contact_doc.id
                        await redis_client.sadd(f"user_contacts:{user_id}", contact_id)
                        contact_count += 1
                        
                except Exception as e:
                    logger.warning(f"Could not load contacts for user {user_id}: {e}")
            
            logger.info(f"✅ Preloaded {contact_count} contact relationships from Firestore")

            # ========== LOAD FILES METADATA ==========
            logger.info("📥 Preloading file metadata from Firestore...")
            try:
                files_ref = self.db.collection('files')
                files_docs = files_ref.stream()
                file_count = 0
                missing_file_count = 0
                
                for doc in files_docs:
                    file_id = doc.id
                    file_data = doc.to_dict()
                    
                    # **CRITICAL: Check if file exists on disk**
                    file_path_str = file_data.get('path', '')
                    
                    if not file_path_str:
                        logger.warning(f"⚠️ No path stored for file {file_id}, skipping")
                        missing_file_count += 1
                        continue
                    
                    file_path = Path(file_path_str)
                    
                    if not file_path.exists():
                        logger.warning(f"⚠️ File missing on disk: {file_path}, skipping {file_id}")
                        missing_file_count += 1
                        continue
                    
                    # Reconstruct file metadata for Redis
                    redis_file_data = {
                        'id': file_id,
                        'user_id': file_data.get('user_id', ''),
                        'filename': file_data.get('filename', ''),
                        'file_type': file_data.get('file_type', 'document'),
                        'extension': file_data.get('extension', ''),
                        'size': str(file_data.get('size', 0)),
                        'url': file_data.get('url', ''),
                        'path': str(file_path.absolute()),
                        'thumbnail_url': file_data.get('thumbnail_url', ''),
                        'uploaded_at': str(file_data.get('uploaded_at', datetime.datetime.now(datetime.UTC).isoformat()))
                    }
                    
                    # Add duration for audio/voice files
                    if file_data.get('duration'):
                        redis_file_data['duration'] = str(file_data.get('duration'))
                    
                    # Store in Redis
                    await redis_client.hset(f"file:{file_id}", mapping=redis_file_data)
                    
                    user_id = file_data.get('user_id')
                    if user_id:
                        await redis_client.sadd(f"user_files:{user_id}", file_id)
                    
                    file_count += 1
                    
                    # Log every 50 files
                    if file_count % 50 == 0:
                        logger.info(f"   Loaded {file_count} files...")
                
                logger.info(f"✅ Preloaded {file_count} file metadata records from Firestore")
                
                if missing_file_count > 0:
                    logger.warning(f"⚠️ {missing_file_count} files missing from disk (not loaded)")
                
            except Exception as file_error:
                logger.error(f"❌ Could not load files metadata: {file_error}", exc_info=True)

            logger.info("🎉 Data preload complete!")


            # ========== LOAD BLOCKED USERS ==========
            logger.info("📥 Preloading blocked users from Firestore...")
            blocked_count = 0
            
            for user_id in users_list:
                try:
                    blocked_ref = self.db.collection('users').document(user_id).collection('blocked')
                    blocked_docs = blocked_ref.stream()
                    
                    for blocked_doc in blocked_docs:
                        blocked_user_id = blocked_doc.id
                        await redis_client.sadd(f"user_blocked:{user_id}", blocked_user_id)
                        blocked_count += 1
                        
                except Exception as e:
                    logger.warning(f"Could not load blocked users for {user_id}: {e}")
            
            logger.info(f"✅ Preloaded {blocked_count} blocked relationships from Firestore")

            logger.info("🎉 Data preload complete!")
            
        except Exception as e:
            logger.error(f"❌ Error preloading data from Firestore: {e}", exc_info=True)

    async def get_current_user(self, request):
        """Get current user profile"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            user_data = await redis_client.hgetall(f"user:{user_id}")
            if not user_data:
                return web.json_response({"error": "User not found"}, status=404)

            return web.json_response({
                "user": {
                    "id": user_id,
                    "username": user_data.get('username'),
                    "email": user_data.get('email'),
                    "phone": user_data.get('phone'),
                    "role": user_data.get('role'),
                    "status": user_data.get('status'),
                    "avatar_url": user_data.get('avatar_url'),
                    "bio": user_data.get('bio'),
                    "created_at": user_data.get('created_at'),
                    "settings": json.loads(user_data.get('settings', '{}'))
                }
            })

        except Exception as e:
            logger.error(f"Get user error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_profile(self, request):
        """Update user profile - ENHANCED VERSION with better error handling"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            updates = {}
            
            # Handle username change
            if 'username' in data:
                new_username = data['username'].strip()
                if len(new_username) >= 3:
                    # Check if username is taken
                    existing_user = await redis_client.hget("username_map", new_username)
                    if existing_user and existing_user != user_id:
                        return web.json_response({"error": "Username already taken"}, status=400)
                    
                    # Remove old username mapping
                    old_username = await redis_client.hget(f"user:{user_id}", "username")
                    if old_username and old_username != new_username:
                        try:
                            await redis_client.hdel("username_map", old_username)
                            logger.info(f"✅ Removed old username mapping: {old_username}")
                        except Exception as hdel_error:
                            logger.warning(f"⚠️ Could not remove old username mapping: {hdel_error}")
                    
                    # Add new username mapping
                    await redis_client.hset("username_map", new_username, user_id)
                    updates['username'] = new_username
                    logger.info(f"✅ Updated username: {old_username} -> {new_username}")
                else:
                    return web.json_response({"error": "Username must be at least 3 characters"}, status=400)
            
            # Handle bio
            if 'bio' in data:
                updates['bio'] = data['bio'][:500]  # Limit to 500 chars
            
            # Handle public key for E2E encryption (base64-encoded ECDH public key)
            if 'public_key' in data and data['public_key']:
                pk = data['public_key'].strip()
                if len(pk) < 2000:  # Reasonable size limit for a P-256 public key
                    updates['public_key'] = pk
                    logger.info(f"✅ Stored public key for user {user_id}")
            
            # Handle avatar_url (when uploaded separately)
            if 'avatar_url' in data:
                updates['avatar_url'] = data['avatar_url']
            
            # Update Redis
            if updates:
                await redis_client.hset(f"user:{user_id}", mapping=updates)
                logger.info(f"✅ Updated user {user_id} in Redis: {list(updates.keys())}")
                
                # Update Firestore
                if self.db:
                    try:
                        self.db.collection('users').document(user_id).set(updates, merge=True)
                        logger.info(f"✅ User {user_id} profile updated in Firestore")
                    except Exception as fb_err:
                        logger.error(f"Firestore profile update failed: {fb_err}")
                
                # Notify contacts about profile change
                try:
                    contact_ids = await redis_client.smembers(f"user_contacts:{user_id}")
                    if contact_ids:
                        await self.broadcast_to_users(list(contact_ids), {
                            "type": "user_profile_updated",
                            "user_id": user_id,
                            "updates": updates
                        })
                        logger.info(f"✅ Notified {len(contact_ids)} contacts about profile update")
                except Exception as broadcast_err:
                    logger.warning(f"⚠️ Could not notify contacts: {broadcast_err}")

            return web.json_response({"success": True, "updates": updates})

        except Exception as e:
            logger.error(f"Update profile error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_user_public_key(self, request):
        """Get a user's E2E encryption public key (ECDH)"""
        try:
            # Caller must be authenticated
            caller_id = await self.get_user_from_token(request)
            if not caller_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            target_user_id = request.match_info['user_id']

            # Fetch public key from Redis
            public_key = await redis_client.hget(f"user:{target_user_id}", "public_key")

            if not public_key:
                # Try Firestore as fallback
                if self.db:
                    try:
                        doc = self.db.collection('users').document(target_user_id).get()
                        if doc.exists:
                            public_key = doc.to_dict().get('public_key')
                    except Exception:
                        pass

            if not public_key:
                return web.json_response({"success": False, "public_key": None,
                                          "message": "User has not set up E2E encryption"}, status=200)

            return web.json_response({"success": True, "public_key": public_key})

        except Exception as e:
            logger.error(f"get_user_public_key error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def upload_avatar(self, request):
        """Upload user avatar - ENHANCED"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            reader = await request.multipart()
            field = await reader.next()

            if not field or field.name != 'file':
                return web.json_response({"error": "No file provided"}, status=400)

            # Save file
            file_id = str(uuid.uuid4())
            ext = field.filename.rsplit('.', 1)[-1].lower() if '.' in field.filename else 'jpg'
            
            # Validate extension
            if ext not in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
                return web.json_response({"error": "Invalid image format"}, status=400)
            
            file_path = UPLOAD_DIR / 'avatars' / f"{file_id}.{ext}"

            size = 0
            with open(file_path, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 5 * 1024 * 1024:  # 5MB limit
                        file_path.unlink()
                        return web.json_response({"error": "File too large (max 5MB)"}, status=400)
                    f.write(chunk)

            avatar_url = f"/uploads/avatars/{file_id}.{ext}"
            
            # Delete old avatar if exists
            old_avatar = await redis_client.hget(f"user:{user_id}", "avatar_url")
            if old_avatar and old_avatar.startswith('/uploads/avatars/'):
                old_path = UPLOAD_DIR.parent / old_avatar.lstrip('/')
                if old_path.exists():
                    try:
                        old_path.unlink()
                    except:
                        pass
            
            # Update user
            await redis_client.hset(f"user:{user_id}", "avatar_url", avatar_url)
            
            # Update Firestore
            if self.db:
                try:
                    self.db.collection('users').document(user_id).set({'avatar_url': avatar_url}, merge=True)
                except Exception as fb_err:
                    logger.error(f"Firestore avatar update: {fb_err}")

            logger.info(f"✅ Avatar uploaded: {user_id}")

            return web.json_response({
                "success": True,
                "avatar_url": avatar_url
            })

        except Exception as e:
            logger.error(f"Avatar upload error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def update_email(self, request):
        """Update user email with verification"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            new_email = data.get('email', '').strip().lower()

            if not new_email or '@' not in new_email:
                return web.json_response({"error": "Invalid email"}, status=400)

            # Check if email already exists
            existing_user = await redis_client.hget("email_map", new_email)
            if existing_user and existing_user != user_id:
                return web.json_response({"error": "Email already in use"}, status=400)

            # Get old email
            old_email = await redis_client.hget(f"user:{user_id}", "email")
            
            # Remove old email mapping
            if old_email:
                await redis_client.hdel("email_map", old_email)
            
            # Update to new email
            await redis_client.hset(f"user:{user_id}", "email", new_email)
            await redis_client.hset("email_map", new_email, user_id)
            
            # Update Firestore
            if self.db:
                try:
                    self.db.collection('users').document(user_id).set({'email': new_email}, merge=True)
                except Exception as fb_err:
                    logger.error(f"Firestore email update: {fb_err}")

            return web.json_response({"success": True, "email": new_email})

        except Exception as e:
            logger.error(f"Update email error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def update_phone(self, request):
        """Update user phone number with verification"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            new_phone = data.get('phone', '').strip()
            verification_code = data.get('code', '').strip()

            if not new_phone or not new_phone.startswith('+'):
                return web.json_response({"error": "Invalid phone format (must include country code)"}, status=400)

            # Verify OTP
            if verification_code:
                stored_otp = await redis_client.get(f"otp:{new_phone}")
                if not stored_otp or stored_otp != verification_code:
                    return web.json_response({"error": "Invalid or expired verification code"}, status=400)
                
                # Check if phone already exists
                existing_user = await redis_client.hget("phone_map", new_phone)
                if existing_user and existing_user != user_id:
                    return web.json_response({"error": "Phone already in use"}, status=400)

                # Get old phone
                old_phone = await redis_client.hget(f"user:{user_id}", "phone")
                
                # Remove old phone mapping
                if old_phone:
                    await redis_client.hdel("phone_map", old_phone)
                
                # Update to new phone
                await redis_client.hset(f"user:{user_id}", mapping={
                    "phone": new_phone,
                    "phone_verified": "true"
                })
                await redis_client.hset("phone_map", new_phone, user_id)
                await redis_client.delete(f"otp:{new_phone}")
                
                # Update Firestore
                if self.db:
                    try:
                        self.db.collection('users').document(user_id).set({
                            'phone': new_phone,
                            'phone_verified': True
                        }, merge=True)
                    except Exception as fb_err:
                        logger.error(f"Firestore phone update: {fb_err}")

                return web.json_response({"success": True, "phone": new_phone})
            else:
                return web.json_response({"error": "Verification code required"}, status=400)

        except Exception as e:
            logger.error(f"Update phone error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def search_users(self, request):
        """Search users by username/email"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            query = request.query.get('q', '').strip().lower()
            if not query:
                return web.json_response({"users": []})

            # Get all users
            all_user_ids = await redis_client.smembers("users:all")
            results = []

            for uid in all_user_ids:
                if uid == user_id:
                    continue
                    
                user_data = await redis_client.hgetall(f"user:{uid}")
                if not user_data:
                    continue
                
                username = user_data.get('username', '').lower()
                email = user_data.get('email', '').lower()
                
                if query in username or query in email:
                    results.append({
                        "id": uid,
                        "username": user_data.get('username'),
                        "email": user_data.get('email'),
                        "avatar_url": user_data.get('avatar_url'),
                        "status": user_data.get('status')
                    })

            return web.json_response({"users": results[:20]})  # Limit to 20 results

        except Exception as e:
            logger.error(f"Search users error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def search_all_users(self, request):
        """Search all users from Firestore (for adding to groups)"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            query = request.query.get('q', '').strip().lower()
            
            if not query or len(query) < 2:
                return web.json_response({"users": []})

            logger.info(f"🔍 Searching all users for: {query}")

            results = []
            
            # Search in Firestore
            if self.db:
                try:
                    users_ref = self.db.collection('users')
                    
                    # Search by username (case-insensitive)
                    docs = users_ref.where('username', '>=', query).where('username', '<=', query + '\uf8ff').limit(20).stream()
                    
                    for doc in docs:
                        user_data = doc.to_dict()
                        if doc.id != user_id:  # Exclude current user
                            results.append({
                                "id": doc.id,
                                "username": user_data.get('username'),
                                "email": user_data.get('email', ''),
                                "avatar_url": user_data.get('avatar_url', ''),
                                "status": "offline"  # Default for search results
                            })
                    
                    # Also search by email if query contains @
                    if '@' in query and len(results) < 20:
                        email_docs = users_ref.where('email', '>=', query).where('email', '<=', query + '\uf8ff').limit(10).stream()
                        
                        existing_ids = set(u['id'] for u in results)
                        
                        for doc in email_docs:
                            if doc.id not in existing_ids and doc.id != user_id:
                                user_data = doc.to_dict()
                                results.append({
                                    "id": doc.id,
                                    "username": user_data.get('username'),
                                    "email": user_data.get('email', ''),
                                    "avatar_url": user_data.get('avatar_url', ''),
                                    "status": "offline"
                                })
                    
                    logger.info(f"✅ Found {len(results)} users matching '{query}'")
                    
                except Exception as fb_err:
                    logger.error(f"Firestore search error: {fb_err}")

            return web.json_response({"users": results})

        except Exception as e:
            logger.error(f"Search all users error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_group_chat(self, request):
        """Update group chat name, description, avatar"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']
            data = await request.json()

            # Check if user is admin
            chat_data = await redis_client.hgetall(f"chat:{chat_id}")
            if chat_data.get('type') != 'group':
                return web.json_response({"error": "Not a group chat"}, status=400)

            member_role = await redis_client.hgetall(f"chat_member:{chat_id}:{user_id}")
            if member_role.get('role') != 'admin' and chat_data.get('created_by') != user_id:
                return web.json_response({"error": "Only admins can update group"}, status=403)

            updates = {}
            
            if 'name' in data and data['name'].strip():
                updates['name'] = data['name'].strip()[:100]
            
            if 'description' in data:
                updates['description'] = data['description'].strip()[:500]
            
            if 'avatar_url' in data:
                updates['avatar_url'] = data['avatar_url']

            if updates:
                updates['updated_at'] = datetime.datetime.now(datetime.UTC).isoformat()
                
                # Update Redis
                await redis_client.hset(f"chat:{chat_id}", mapping=updates)
                
                # Update Firestore
                if self.db:
                    try:
                        self.db.collection('chats').document(chat_id).update(updates)
                        logger.info(f"✅ Group {chat_id} updated in Firestore")
                    except Exception as fb_err:
                        logger.error(f"Firestore group update failed: {fb_err}")
                
                # Notify members
                member_ids = await redis_client.smembers(f"chat_members:{chat_id}")
                await self.broadcast_to_users(list(member_ids), {
                    "type": "group_updated",
                    "chat_id": chat_id,
                    "updates": updates
                })

            return web.json_response({"success": True, "updates": updates})

        except Exception as e:
            logger.error(f"Update group error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    # ==================== CONTACTS ====================
    
    async def get_contacts(self, request):
        """Get user contacts"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            contact_ids = await redis_client.smembers(f"user_contacts:{user_id}")
            contacts = []

            for contact_id in contact_ids:
                contact_data = await redis_client.hgetall(f"user:{contact_id}")
                if contact_data:
                    contacts.append({
                        "id": contact_id,
                        "username": contact_data.get('username'),
                        "email": contact_data.get('email'),
                        "avatar_url": contact_data.get('avatar_url'),
                        "status": contact_data.get('status'),
                        "last_seen": contact_data.get('last_seen')
                    })

            return web.json_response({"contacts": contacts})

        except Exception as e:
            logger.error(f"Get contacts error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def add_contact(self, request):
        """Add contact by username/email"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            identifier = data.get('identifier', '').strip()

            # Find user - try case-insensitive username search first
            contact_id = await redis_client.hget("username_map", identifier)
            
            # If not found, try lowercase version for case-insensitive search
            if not contact_id:
                contact_id = await redis_client.hget("username_map", identifier.lower())
            
            # If still not found and looks like email, search email map
            if not contact_id and '@' in identifier:
                contact_id = await redis_client.hget("email_map", identifier)
                if not contact_id:
                    contact_id = await redis_client.hget("email_map", identifier.lower())

            if not contact_id:
                return web.json_response({"error": "User not found", "success": False}, status=404)

            if contact_id == user_id:
                return web.json_response({"error": "Cannot add yourself", "success": False}, status=400)
            
            # Check if contact already exists
            is_already_contact = await redis_client.sismember(f"user_contacts:{user_id}", contact_id)
            if is_already_contact:
                logger.info(f"ℹ️ Contact already exists: {user_id} -> {contact_id}")
                return web.json_response({"success": True, "message": "Contact already added"})

            # Add to contacts
            await redis_client.sadd(f"user_contacts:{user_id}", contact_id)
            await redis_client.sadd(f"user_contacts:{contact_id}", user_id)
            if self.db:
                try:
                    self.db.collection('users').document(user_id).collection('contacts').document(contact_id).set({
                        'added_at': firestore.SERVER_TIMESTAMP,
                        'status': 'active'
                    })
                    self.db.collection('users').document(contact_id).collection('contacts').document(user_id).set({
                        'added_at': firestore.SERVER_TIMESTAMP,
                        'status': 'active'
                    })
                    logger.info(f"✅ Contact saved to Firestore: {user_id} <-> {contact_id}")
                except Exception as fb_err:
                    logger.error(f"Firestore contact save failed: {fb_err}")

            logger.info(f"✅ Contact added: {user_id} -> {contact_id}")

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Add contact error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def remove_contact(self, request):
        """Remove contact and associated direct chat"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            contact_id = request.match_info['contact_id']

            # Remove from contacts
            await redis_client.srem(f"user_contacts:{user_id}", contact_id)
            await redis_client.srem(f"user_contacts:{contact_id}", user_id)
            
            # ✅ NEW: Find and remove direct chat between these users
            user_chats = await redis_client.smembers(f"user_chats:{user_id}")
            
            for chat_id in user_chats:
                chat_data = await redis_client.hgetall(f"chat:{chat_id}")
                
                # Only remove direct chats, not groups
                if chat_data.get('type') == 'direct':
                    members = await redis_client.smembers(f"chat_members:{chat_id}")
                    
                    # If this chat is between user and contact, remove it
                    if contact_id in members and user_id in members and len(members) == 2:
                        logger.info(f"🗑️ Removing direct chat {chat_id} between {user_id} and {contact_id}")
                        
                        # Remove chat from both users
                        await redis_client.srem(f"user_chats:{user_id}", chat_id)
                        await redis_client.srem(f"user_chats:{contact_id}", chat_id)
                        
                        # Remove members
                        await redis_client.delete(f"chat_members:{chat_id}")
                        
                        # Delete chat messages
                        message_ids = await redis_client.lrange(f"chat_messages:{chat_id}", 0, -1)
                        for msg_id in message_ids:
                            await redis_client.delete(f"message:{msg_id}")
                        await redis_client.delete(f"chat_messages:{chat_id}")
                        
                        # Delete chat itself
                        await redis_client.delete(f"chat:{chat_id}")
                        await redis_client.srem("chats:all", chat_id)
                        
                        # Delete from Firestore
                        if self.db:
                            try:
                                # Delete messages subcollection
                                messages_ref = self.db.collection('chats').document(chat_id).collection('messages')
                                for msg_doc in messages_ref.stream():
                                    msg_doc.reference.delete()
                                
                                # Delete chat document
                                self.db.collection('chats').document(chat_id).delete()
                                logger.info(f"✅ Deleted chat {chat_id} from Firestore")
                            except Exception as fb_err:
                                logger.error(f"Firestore chat delete failed: {fb_err}")
            
            # Remove from Firestore contacts
            if self.db:
                try:
                    self.db.collection('users').document(user_id).collection('contacts').document(contact_id).delete()
                    self.db.collection('users').document(contact_id).collection('contacts').document(user_id).delete()
                except Exception as fb_err:
                    logger.error(f"Firestore contact delete failed: {fb_err}")

            logger.info(f"✅ Contact and chat removed: {user_id} removed {contact_id}")

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Remove contact error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def block_user(self, request):
        """Block a user - Complete implementation"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            blocked_user_id = data.get('user_id')

            if not blocked_user_id:
                return web.json_response({"error": "User ID required"}, status=400)

            if blocked_user_id == user_id:
                return web.json_response({"error": "Cannot block yourself"}, status=400)

            # Check if already blocked
            is_already_blocked = await redis_client.sismember(f"user_blocked:{user_id}", blocked_user_id)
            if is_already_blocked:
                return web.json_response({"error": "User already blocked"}, status=400)

            # Add to blocked list in Redis
            await redis_client.sadd(f"user_blocked:{user_id}", blocked_user_id)
            
            # Remove from contacts if exists
            await redis_client.srem(f"user_contacts:{user_id}", blocked_user_id)
            await redis_client.srem(f"user_contacts:{blocked_user_id}", user_id)

            # Save to Firestore
            if self.db:
                try:
                    self.db.collection('users').document(user_id).collection('blocked').document(blocked_user_id).set({
                        'blocked_at': firestore.SERVER_TIMESTAMP,
                        'status': 'blocked'
                    })
                    # Remove contact relationship
                    self.db.collection('users').document(user_id).collection('contacts').document(blocked_user_id).delete()
                    self.db.collection('users').document(blocked_user_id).collection('contacts').document(user_id).delete()
                    logger.info(f"✅ User {blocked_user_id} blocked by {user_id} in Firestore")
                except Exception as fb_err:
                    logger.error(f"Firestore block save failed: {fb_err}")

            logger.info(f"✅ User {user_id} blocked {blocked_user_id}")

            # Notify the blocked user via WebSocket
            await self.broadcast_to_users([blocked_user_id], {
                "type": "user_blocked",
                "blocked_by": user_id
            })

            return web.json_response({
                "success": True,
                "message": "User blocked successfully"
            })

        except Exception as e:
            logger.error(f"Block user error: {e}")
            return web.json_response({"error": str(e)}, status=500)


    async def unblock_user(self, request):
        """Unblock a user - Complete implementation"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            blocked_user_id = data.get('user_id')

            if not blocked_user_id:
                return web.json_response({"error": "User ID required"}, status=400)

            # Check if actually blocked
            is_blocked = await redis_client.sismember(f"user_blocked:{user_id}", blocked_user_id)
            if not is_blocked:
                return web.json_response({"error": "User is not blocked"}, status=400)

            # Remove from blocked list
            await redis_client.srem(f"user_blocked:{user_id}", blocked_user_id)

            # Remove from Firestore
            if self.db:
                try:
                    self.db.collection('users').document(user_id).collection('blocked').document(blocked_user_id).delete()
                    logger.info(f"✅ User {blocked_user_id} unblocked by {user_id} in Firestore")
                except Exception as fb_err:
                    logger.error(f"Firestore unblock failed: {fb_err}")

            logger.info(f"✅ User {user_id} unblocked {blocked_user_id}")

            # Notify via WebSocket
            await self.broadcast_to_users([blocked_user_id], {
                "type": "user_unblocked",
                "unblocked_by": user_id
            })

            return web.json_response({
                "success": True,
                "message": "User unblocked successfully"
            })

        except Exception as e:
            logger.error(f"Unblock user error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def check_blocked_status(self, request):
        """Check if a user is blocked"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            other_user_id = request.match_info.get('user_id')
            if not other_user_id:
                return web.json_response({"error": "User ID required"}, status=400)

            # Check both directions
            i_blocked_them = await redis_client.sismember(f"user_blocked:{user_id}", other_user_id)
            they_blocked_me = await redis_client.sismember(f"user_blocked:{other_user_id}", user_id)

            return web.json_response({
                "i_blocked_them": bool(i_blocked_them),
                "they_blocked_me": bool(they_blocked_me),
                "is_blocked": bool(i_blocked_them or they_blocked_me)
            })

        except Exception as e:
            logger.error(f"Check blocked status error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_blocked_users(self, request):
        """Get list of blocked users"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            blocked_ids = await redis_client.smembers(f"user_blocked:{user_id}")
            blocked_users = []

            for blocked_id in blocked_ids:
                user_data = await redis_client.hgetall(f"user:{blocked_id}")
                if user_data:
                    blocked_users.append({
                        "id": blocked_id,
                        "username": user_data.get('username'),
                        "avatar_url": user_data.get('avatar_url')
                    })

            return web.json_response({"blocked_users": blocked_users})

        except Exception as e:
            logger.error(f"Get blocked users error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # ==================== FILE CONVERSION FUNCTIONS ====================
    def get_supported_conversions(self, file_extension):
        """Return supported conversion formats for given file type - SUPER CONVERTER"""
        conversion_map = {
            # Image formats - comprehensive conversions
            'jpg': ['png', 'webp', 'pdf', 'bmp', 'tiff', 'ico', 'gif', 'jpeg'],
            'jpeg': ['png', 'webp', 'pdf', 'bmp', 'tiff', 'ico', 'gif', 'jpg'],
            'png': ['jpg', 'jpeg', 'webp', 'pdf', 'bmp', 'tiff', 'ico', 'gif'],
            'webp': ['jpg', 'jpeg', 'png', 'pdf', 'bmp', 'tiff', 'gif'],
            'gif': ['jpg', 'jpeg', 'png', 'webp', 'bmp', 'pdf', 'mp4'],
            'bmp': ['jpg', 'jpeg', 'png', 'webp', 'pdf', 'tiff', 'gif'],
            'tiff': ['jpg', 'jpeg', 'png', 'webp', 'pdf', 'bmp'],
            'ico': ['png', 'jpg', 'jpeg', 'bmp'],
            
            # Document formats - comprehensive conversions
            'pdf': ['docx', 'txt', 'html', 'md', 'rtf'],
            'docx': ['pdf', 'txt', 'html', 'md', 'rtf'],
            'doc': ['pdf', 'txt', 'html', 'docx'],
            'pptx': ['pdf', 'txt', 'html', 'docx'],  # Added docx support
            'ppt': ['pdf', 'txt', 'pptx', 'docx'],   # Added docx support
            'xlsx': ['csv', 'pdf', 'txt', 'html'],
            'xls': ['csv', 'pdf', 'txt', 'xlsx'],
            'txt': ['pdf', 'docx', 'html', 'md', 'rtf'],
            'html': ['pdf', 'txt', 'docx', 'md'],
            'md': ['pdf', 'html', 'txt', 'docx'],
            'rtf': ['pdf', 'txt', 'docx', 'html'],
            'csv': ['xlsx', 'pdf', 'txt', 'html'],
            
            # Audio formats - comprehensive conversions
            'mp3': ['wav', 'ogg', 'aac', 'flac', 'm4a', 'wma', 'opus'],
            'wav': ['mp3', 'ogg', 'aac', 'flac', 'm4a', 'opus'],
            'ogg': ['mp3', 'wav', 'aac', 'flac', 'm4a'],
            'aac': ['mp3', 'wav', 'ogg', 'flac', 'm4a'],
            'flac': ['mp3', 'wav', 'ogg', 'aac', 'm4a'],
            'm4a': ['mp3', 'wav', 'ogg', 'aac', 'flac'],
            'wma': ['mp3', 'wav', 'ogg', 'aac'],
            'opus': ['mp3', 'wav', 'ogg', 'aac'],
            
            # Video formats - comprehensive conversions
            'mp4': ['mp3', 'wav', 'avi', 'webm', 'mkv', 'mov', 'flv', 'wmv', 'gif'],
            'avi': ['mp4', 'mp3', 'webm', 'mkv', 'mov'],
            'mov': ['mp4', 'mp3', 'avi', 'webm', 'mkv'],
            'webm': ['mp4', 'mp3', 'avi', 'mkv'],
            'mkv': ['mp4', 'mp3', 'avi', 'webm', 'mov'],
            'flv': ['mp4', 'mp3', 'avi', 'webm'],
            'wmv': ['mp4', 'mp3', 'avi'],
            
            # Archive formats
            'zip': ['tar', 'gz', '7z'],
            'tar': ['zip', 'gz'],
            'gz': ['zip', 'tar'],
            '7z': ['zip', 'tar'],
            'rar': ['zip', 'tar']
        }
        return conversion_map.get(file_extension.lower(), [])

    def convert_image_format(self, input_path, output_path, target_format):
        """Convert image to target format - Production-ready with comprehensive format support"""
        try:
            # Open and auto-orient image based on EXIF data
            img = Image.open(input_path)
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass  # No EXIF data or already oriented
            
            original_mode = img.mode
            logger.info(f"🖼️ Converting image: {original_mode} mode → {target_format.upper()}")
            
            # Special case: Image to PDF
            if target_format.lower() == 'pdf':
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode in ('RGBA', 'LA'):
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else img.split()[1])
                        img = background
                    else:
                        img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Save as PDF with high quality
                img.save(output_path, 'PDF', resolution=100.0, quality=95)
                logger.info(f"✅ Image to PDF conversion successful")
                return output_path
            
            # Handle transparency for formats that don't support it (JPG, BMP, ICO)
            if target_format.lower() in ['jpg', 'jpeg', 'bmp', 'ico'] and img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
            
            # Handle palette mode for formats that need RGB
            if img.mode == 'P' and target_format.lower() not in ['gif', 'png']:
                img = img.convert('RGB')
            
            # Ensure RGBA for formats that support it
            if target_format.lower() in ['png', 'webp'] and img.mode == 'RGB':
                img = img.convert('RGBA')
            
            # Save with format-specific optimizations
            save_kwargs = {}
            
            if target_format.lower() in ['jpg', 'jpeg']:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                save_kwargs = {'format': 'JPEG', 'quality': 95, 'optimize': True, 'progressive': True}
                
            elif target_format.lower() == 'png':
                save_kwargs = {'format': 'PNG', 'optimize': True, 'compress_level': 6}
                
            elif target_format.lower() == 'webp':
                save_kwargs = {'format': 'WEBP', 'quality': 90, 'method': 6}
                
            elif target_format.lower() == 'gif':
                # Optimize GIF with proper quantization
                if img.mode != 'P':
                    img = img.convert('P', palette=Image.ADAPTIVE, colors=256)
                save_kwargs = {'format': 'GIF', 'optimize': True, 'save_all': True}
                
            elif target_format.lower() == 'bmp':
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                save_kwargs = {'format': 'BMP'}
                
            elif target_format.lower() in ['tiff', 'tif']:
                save_kwargs = {'format': 'TIFF', 'compression': 'tiff_lzw'}
                
            elif target_format.lower() == 'ico':
                # ICO format: Create multi-resolution icon
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                # Create multiple sizes for better quality icons
                icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
                resized_images = []
                
                for size in icon_sizes:
                    resized_img = img.copy()
                    resized_img.thumbnail(size, Image.Resampling.LANCZOS)
                    # Ensure exact size by creating new image and pasting
                    sized_img = Image.new('RGBA', size, (0, 0, 0, 0))
                    paste_x = (size[0] - resized_img.size[0]) // 2
                    paste_y = (size[1] - resized_img.size[1]) // 2
                    sized_img.paste(resized_img, (paste_x, paste_y))
                    resized_images.append(sized_img)
                
                # Save multi-resolution ICO
                resized_images[0].save(output_path, format='ICO', sizes=[(img.size[0], img.size[1]) for img in resized_images])
                logger.info(f"✅ Multi-resolution ICO created with {len(icon_sizes)} sizes")
                return output_path
                
            else:
                # Generic format handling
                save_kwargs = {'format': target_format.upper()}
            
            # Save the image
            img.save(output_path, **save_kwargs)
            logger.info(f"✅ Image conversion successful: {target_format.upper()}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Image conversion failed: {str(e)}")
            raise Exception(f"Image conversion failed: {str(e)}")

    def convert_document_format(self, input_path, output_path, source_ext, target_ext):
        """Convert document formats - supports all major document types"""
        try:
            # Debug logging
            logger.info(f"🔍 Document conversion DEBUG - source_ext: '{source_ext}' (type: {type(source_ext)}), target_ext: '{target_ext}' (type: {type(target_ext)})")
            
            # PDF to text conversions
            if source_ext == 'pdf' and target_ext in ['txt', 'md', 'html', 'rtf']:
                text = ""
                with open(input_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n\n"
                
                if target_ext == 'html':
                    text = f"<html><body><pre>{text}</pre></body></html>"
                elif target_ext == 'rtf':
                    text = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}}\f0\fs24 " + text.replace('\n', r'\par ') + "}"
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                return output_path
            
            # PDF to DOCX conversion (WITH IMAGES SUPPORT)
            elif source_ext == 'pdf' and target_ext == 'docx':
                conversion_successful = False
                
                # Method 1: Try pdf2docx (best quality, preserves images and formatting)
                if HAS_PDF2DOCX and PDFConverter:
                    try:
                        logger.info("🔄 Method 1: Using pdf2docx for high-quality PDF→DOCX conversion (preserves images & formatting)")
                        cv = PDFConverter(input_path)
                        cv.convert(output_path, start=0, end=None)
                        cv.close()
                        
                        # Verify the output file was created and has content
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                            logger.info("✅ PDF to DOCX conversion successful with images preserved (pdf2docx)")
                            return output_path
                        else:
                            logger.warning("⚠️ pdf2docx created empty/invalid file, trying next method")
                            if os.path.exists(output_path):
                                os.remove(output_path)
                    except Exception as pdf2docx_err:
                        logger.warning(f"⚠️ pdf2docx failed: {pdf2docx_err}, trying next method")
                        if os.path.exists(output_path):
                            try:
                                os.remove(output_path)
                            except:
                                pass
                
                # Method 2: Try LibreOffice (good quality, preserves some formatting)
                if not conversion_successful and HAS_LIBREOFFICE:
                    try:
                        logger.info("🔄 Method 2: Using LibreOffice for PDF→DOCX conversion")
                        result = subprocess.run([
                            'soffice' if shutil.which('soffice') else 'libreoffice',
                            '--headless',
                            '--convert-to', 'docx',
                            '--outdir', os.path.dirname(output_path),
                            input_path
                        ], capture_output=True, text=True, timeout=120)
                        
                        # LibreOffice creates file with original name + .docx
                        expected_output = os.path.join(
                            os.path.dirname(output_path),
                            os.path.splitext(os.path.basename(input_path))[0] + '.docx'
                        )
                        
                        if os.path.exists(expected_output):
                            if expected_output != output_path:
                                shutil.move(expected_output, output_path)
                            logger.info("✅ PDF to DOCX conversion successful (LibreOffice)")
                            return output_path
                        else:
                            logger.warning(f"⚠️ LibreOffice conversion failed: {result.stderr}")
                    except subprocess.TimeoutExpired:
                        logger.warning("⚠️ LibreOffice conversion timed out")
                    except Exception as libre_err:
                        logger.warning(f"⚠️ LibreOffice conversion failed: {libre_err}")
                
                # Method 3: Fallback to text-only extraction with PyPDF2
                logger.info("🔄 Method 3: Using PyPDF2 for text-only PDF→DOCX conversion (WARNING: No images)")
                try:
                    doc = Document()
                    with open(input_path, 'rb') as file:
                        pdf_reader = PyPDF2.PdfReader(file)
                        for i, page in enumerate(pdf_reader.pages):
                            text = page.extract_text()
                            if text.strip():
                                if i == 0:
                                    doc.add_paragraph(text)
                                else:
                                    doc.add_page_break()
                                    doc.add_paragraph(text)
                    doc.save(output_path)
                    logger.info("✅ PDF to DOCX conversion successful (text-only)")
                    return output_path
                except Exception as pdf_docx_err:
                    logger.error(f"❌ PDF to DOCX conversion error: {pdf_docx_err}")
                    raise Exception(f"PDF to DOCX conversion failed: {str(pdf_docx_err)}")
            
            # DOCX conversions
            elif source_ext in ['docx', 'doc'] and target_ext in ['txt', 'md', 'html', 'rtf']:
                doc = Document(input_path)
                text = '\n\n'.join([p.text for p in doc.paragraphs if p.text.strip()])
                
                if target_ext == 'html':
                    html_text = '<html><body>'
                    for p in doc.paragraphs:
                        if p.text.strip():
                            html_text += f'<p>{p.text}</p>'
                    html_text += '</body></html>'
                    text = html_text
                elif target_ext == 'rtf':
                    text = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}}\f0\fs24 " + text.replace('\n', r'\par ') + "}"
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                return output_path
            
            elif source_ext == 'docx' and target_ext == 'pdf':
                # Method 1: Try LibreOffice (best quality, preserves images)
                if HAS_LIBREOFFICE:
                    try:
                        logger.info("🔄 Using LibreOffice for DOCX→PDF conversion (preserves images)")
                        result = subprocess.run([
                            'soffice' if shutil.which('soffice') else 'libreoffice',
                            '--headless',
                            '--convert-to', 'pdf',
                            '--outdir', os.path.dirname(output_path),
                            input_path
                        ], capture_output=True, text=True, timeout=120)
                        
                        expected_output = os.path.join(
                            os.path.dirname(output_path),
                            os.path.splitext(os.path.basename(input_path))[0] + '.pdf'
                        )
                        
                        if os.path.exists(expected_output):
                            if expected_output != output_path:
                                shutil.move(expected_output, output_path)
                            logger.info("✅ DOCX to PDF conversion successful (LibreOffice)")
                            return output_path
                    except Exception as libre_err:
                        logger.warning(f"⚠️ LibreOffice DOCX→PDF failed: {libre_err}, trying docx2pdf")
                
                # Method 2: Try docx2pdf (Windows only, may not preserve all images)
                try:
                    logger.info("🔄 Using docx2pdf for DOCX→PDF conversion")
                    from docx2pdf import convert as docx_to_pdf
                    docx_to_pdf(input_path, output_path)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        logger.info("✅ DOCX to PDF conversion successful (docx2pdf)")
                        return output_path
                except ImportError:
                    logger.error("❌ docx2pdf not available and LibreOffice failed")
                    raise Exception("PDF conversion requires either LibreOffice or docx2pdf. Install LibreOffice for better results.")
                except Exception as docx2pdf_err:
                    logger.error(f"❌ docx2pdf conversion failed: {docx2pdf_err}")
                    raise Exception(f"DOCX to PDF conversion failed: {docx2pdf_err}")
            
            # Text to document conversions
            elif source_ext == 'txt' and target_ext in ['html', 'md', 'rtf']:
                with open(input_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                if target_ext == 'html':
                    text = f"<html><body><pre>{text}</pre></body></html>"
                elif target_ext == 'rtf':
                    text = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}}\f0\fs24 " + text.replace('\n', r'\par ') + "}"
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                return output_path
            
            elif source_ext == 'txt' and target_ext == 'docx':
                doc = Document()
                with open(input_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            doc.add_paragraph(line.strip())
                doc.save(output_path)
                return output_path
            
            elif source_ext == 'txt' and target_ext == 'pdf':
                # Convert TXT to PDF via DOCX
                try:
                    from docx2pdf import convert as docx_to_pdf
                    # Create temp DOCX
                    temp_docx = output_path + '.temp.docx'
                    doc = Document()
                    with open(input_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip():
                                doc.add_paragraph(line.strip())
                    doc.save(temp_docx)
                    # Convert to PDF
                    docx_to_pdf(temp_docx, output_path)
                    # Clean up temp file
                    try:
                        os.remove(temp_docx)
                    except:
                        pass
                    return output_path
                except ImportError:
                    raise Exception("docx2pdf library not installed. Run: pip install docx2pdf")
            
            # HTML to text conversions
            elif source_ext == 'html' and target_ext in ['txt', 'md', 'docx', 'pdf']:
                with open(input_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                # Parse HTML and extract text using BeautifulSoup if available
                if HAS_BS4:
                    logger.info("🔄 Using BeautifulSoup for HTML parsing")
                    soup = BeautifulSoup(html_content, 'html.parser')
                    text = soup.get_text(separator='\\n')
                else:
                    # Basic HTML tag removal
                    logger.info("🔄 Using basic regex for HTML parsing")
                    import re
                    text = re.sub('<[^<]+?>', '', html_content)
                
                if not text.strip():
                    raise Exception("No text content found in HTML")
                
                if target_ext == 'docx':
                    doc = Document()
                    for line in text.split('\n'):
                        if line.strip():
                            doc.add_paragraph(line.strip())
                    doc.save(output_path)
                    return output_path
                elif target_ext == 'pdf':
                    # Convert HTML to PDF via DOCX
                    try:
                        from docx2pdf import convert as docx_to_pdf
                        temp_docx = output_path + '.temp.docx'
                        doc = Document()
                        for line in text.split('\n'):
                            if line.strip():
                                doc.add_paragraph(line.strip())
                        doc.save(temp_docx)
                        docx_to_pdf(temp_docx, output_path)
                        try:
                            os.remove(temp_docx)
                        except:
                            pass
                        logger.info("✅ HTML to PDF conversion successful")
                    except ImportError:
                        raise Exception("docx2pdf library not installed")
                else:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                    logger.info(f"✅ HTML to {target_ext.upper()} conversion successful")
                return output_path
            
            # Markdown conversions
            elif source_ext == 'md' and target_ext in ['txt', 'html', 'docx', 'pdf']:
                with open(input_path, 'r', encoding='utf-8') as f:
                    md_content = f.read()
                
                if not md_content.strip():
                    raise Exception("Source markdown file is empty")
                
                if target_ext == 'html':
                    if HAS_MARKDOWN:
                        logger.info("🔄 Using markdown library for MD→HTML conversion")
                        html_body = markdown.markdown(md_content, extensions=['extra', 'codehilite'])
                        html = f"<html><head><meta charset='utf-8'></head><body>{html_body}</body></html>"
                    else:
                        logger.info("🔄 Using basic HTML wrapping for MD→HTML conversion")
                        html = f"<html><head><meta charset='utf-8'></head><body><pre>{md_content}</pre></body></html>"
                    text = html
                elif target_ext == 'docx':
                    doc = Document()
                    for line in md_content.split('\n'):
                        if line.strip():
                            doc.add_paragraph(line.strip())
                    doc.save(output_path)
                    return output_path
                elif target_ext == 'pdf':
                    # Convert MD to PDF via DOCX
                    try:
                        from docx2pdf import convert as docx_to_pdf
                        temp_docx = output_path + '.temp.docx'
                        doc = Document()
                        for line in md_content.split('\n'):
                            if line.strip():
                                doc.add_paragraph(line.strip())
                        doc.save(temp_docx)
                        docx_to_pdf(temp_docx, output_path)
                        try:
                            os.remove(temp_docx)
                        except:
                            pass
                        return output_path
                    except ImportError:
                        raise Exception("docx2pdf library not installed")
                else:
                    text = md_content
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                return output_path
            
            # Excel/CSV conversions
            elif source_ext in ['xlsx', 'xls'] and target_ext == 'csv':
                wb = openpyxl.load_workbook(input_path)
                sheet = wb.active
                with open(output_path, 'w', encoding='utf-8', newline='') as f:
                    import csv
                    writer = csv.writer(f)
                    for row in sheet.iter_rows(values_only=True):
                        writer.writerow(row)
                return output_path
            
            elif source_ext == 'csv' and target_ext in ['xlsx', 'txt']:
                if target_ext == 'xlsx':
                    wb = openpyxl.Workbook()
                    sheet = wb.active
                    with open(input_path, 'r', encoding='utf-8') as f:
                        import csv
                        reader = csv.reader(f)
                        for row in reader:
                            sheet.append(row)
                    wb.save(output_path)
                else:
                    # CSV to TXT
                    with open(input_path, 'r', encoding='utf-8') as fin:
                        with open(output_path, 'w', encoding='utf-8') as fout:
                            fout.write(fin.read())
                return output_path
            
            # PowerPoint conversions (IMPROVED - preserves images and formatting)
            elif source_ext in ['pptx', 'ppt'] and target_ext in ['txt', 'pdf', 'html', 'docx']:
                conversion_successful = False
                
                # Method 1: Use LibreOffice for PDF conversion (preserves images and formatting)
                if target_ext == 'pdf' and HAS_LIBREOFFICE:
                    try:
                        logger.info("🔄 Method 1: Using LibreOffice for PPT→PDF conversion (preserves images & formatting)")
                        result = subprocess.run([
                            'soffice' if shutil.which('soffice') else 'libreoffice',
                            '--headless',
                            '--convert-to', 'pdf',
                            '--outdir', os.path.dirname(output_path),
                            input_path
                        ], capture_output=True, text=True, timeout=120)
                        
                        expected_output = os.path.join(
                            os.path.dirname(output_path),
                            os.path.splitext(os.path.basename(input_path))[0] + '.pdf'
                        )
                        
                        if os.path.exists(expected_output):
                            if expected_output != output_path:
                                shutil.move(expected_output, output_path)
                            logger.info("✅ PPT to PDF conversion successful with images preserved (LibreOffice)")
                            return output_path
                        else:
                            logger.warning(f"⚠️ LibreOffice PPT conversion failed: {result.stderr}")
                    except Exception as libre_err:
                        logger.warning(f"⚠️ LibreOffice PPT conversion error: {libre_err}")
                
                # Method 2: Use LibreOffice for DOCX conversion
                if target_ext == 'docx' and HAS_LIBREOFFICE:
                    try:
                        logger.info("🔄 Using LibreOffice for PPT→DOCX conversion (preserves formatting)")
                        result = subprocess.run([
                            'soffice' if shutil.which('soffice') else 'libreoffice',
                            '--headless',
                            '--convert-to', 'docx',
                            '--outdir', os.path.dirname(output_path),
                            input_path
                        ], capture_output=True, text=True, timeout=120)
                        
                        expected_output = os.path.join(
                            os.path.dirname(output_path),
                            os.path.splitext(os.path.basename(input_path))[0] + '.docx'
                        )
                        
                        if os.path.exists(expected_output):
                            if expected_output != output_path:
                                shutil.move(expected_output, output_path)
                            logger.info("✅ PPT to DOCX conversion successful (LibreOffice)")
                            return output_path
                    except Exception as libre_err:
                        logger.warning(f"⚠️ LibreOffice conversion error: {libre_err}")
                
                # Method 3: Fallback to text-only extraction
                logger.info("🔄 Fallback: Text-only PPT conversion (WARNING: No images or formatting)")
                prs = Presentation(input_path)
                text = []
                for slide_num, slide in enumerate(prs.slides, 1):
                    text.append(f"\n=== Slide {slide_num} ===")
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            text.append(shape.text)
                text_content = '\n\n'.join(text)
                
                if target_ext == 'txt':
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(text_content)
                    return output_path
                elif target_ext == 'html':
                    html = f"<html><head><meta charset='utf-8'></head><body><pre>{text_content}</pre></body></html>"
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(html)
                    return output_path
                elif target_ext == 'docx':
                    doc = Document()
                    for slide_num, slide in enumerate(prs.slides, 1):
                        if slide_num > 1:
                            doc.add_page_break()
                        doc.add_heading(f'Slide {slide_num}', level=1)
                        for shape in slide.shapes:
                            if hasattr(shape, "text") and shape.text.strip():
                                doc.add_paragraph(shape.text)
                    doc.save(output_path)
                    return output_path
                elif target_ext == 'pdf':
                    # Last resort: text-only PDF
                    try:
                        from docx2pdf import convert as docx_to_pdf
                        temp_docx = output_path + '.temp.docx'
                        doc = Document()
                        for slide_num, slide in enumerate(prs.slides, 1):
                            if slide_num > 1:
                                doc.add_page_break()
                            doc.add_heading(f'Slide {slide_num}', level=1)
                            for shape in slide.shapes:
                                if hasattr(shape, "text") and shape.text.strip():
                                    doc.add_paragraph(shape.text)
                        doc.save(temp_docx)
                        docx_to_pdf(temp_docx, output_path)
                        try:
                            os.remove(temp_docx)
                        except:
                            pass
                        logger.info("✅ PPT to PDF conversion complete (text-only)")
                        return output_path
                    except ImportError:
                        raise Exception("docx2pdf library not installed and LibreOffice not available. Install LibreOffice for better conversion.")
            
            # RTF conversions
            elif source_ext == 'rtf' and target_ext in ['txt', 'docx', 'pdf', 'html']:
                # Basic RTF to text extraction (remove RTF codes)
                with open(input_path, 'r', encoding='utf-8') as f:
                    rtf_content = f.read()
                import re
                text = re.sub(r'\\[a-z]+\d*\s?', '', rtf_content)
                text = re.sub(r'[{}]', '', text)
                
                if target_ext == 'txt':
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                elif target_ext == 'docx':
                    doc = Document()
                    for line in text.split('\n'):
                        if line.strip():
                            doc.add_paragraph(line.strip())
                    doc.save(output_path)
                elif target_ext == 'html':
                    html = f"<html><body><pre>{text}</pre></body></html>"
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(html)
                elif target_ext == 'pdf':
                    try:
                        from docx2pdf import convert as docx_to_pdf
                        temp_docx = output_path + '.temp.docx'
                        doc = Document()
                        for line in text.split('\n'):
                            if line.strip():
                                doc.add_paragraph(line.strip())
                        doc.save(temp_docx)
                        docx_to_pdf(temp_docx, output_path)
                        try:
                            os.remove(temp_docx)
                        except:
                            pass
                    except ImportError:
                        raise Exception("docx2pdf library not installed")
                return output_path
            
            # Excel conversions
            elif source_ext in ['xlsx', 'xls'] and target_ext in ['csv', 'txt', 'html', 'pdf']:
                wb = openpyxl.load_workbook(input_path)
                sheet = wb.active
                
                if target_ext == 'csv':
                    with open(output_path, 'w', encoding='utf-8', newline='') as f:
                        import csv
                        writer = csv.writer(f)
                        for row in sheet.iter_rows(values_only=True):
                            writer.writerow(row)
                elif target_ext == 'txt':
                    with open(output_path, 'w', encoding='utf-8') as f:
                        for row in sheet.iter_rows(values_only=True):
                            f.write('\t'.join([str(cell) if cell else '' for cell in row]) + '\n')
                elif target_ext == 'html':
                    html = '<html><body><table border="1">'
                    for row in sheet.iter_rows(values_only=True):
                        html += '<tr>'
                        for cell in row:
                            html += f'<td>{cell if cell else ""}</td>'
                        html += '</tr>'
                    html += '</table></body></html>'
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(html)
                elif target_ext == 'pdf':
                    # Convert Excel to PDF via text
                    try:
                        from docx2pdf import convert as docx_to_pdf
                        temp_docx = output_path + '.temp.docx'
                        doc = Document()
                        for row in sheet.iter_rows(values_only=True):
                            line = '\t'.join([str(cell) if cell else '' for cell in row])
                            if line.strip():
                                doc.add_paragraph(line)
                        doc.save(temp_docx)
                        docx_to_pdf(temp_docx, output_path)
                        try:
                            os.remove(temp_docx)
                        except:
                            pass
                    except ImportError:
                        raise Exception("docx2pdf library not installed")
                return output_path
            
            elif source_ext == 'csv' and target_ext in ['xlsx', 'txt', 'html', 'pdf']:
                if target_ext == 'xlsx':
                    wb = openpyxl.Workbook()
                    sheet = wb.active
                    with open(input_path, 'r', encoding='utf-8') as f:
                        import csv
                        reader = csv.reader(f)
                        for row in reader:
                            sheet.append(row)
                    wb.save(output_path)
                elif target_ext in ['txt', 'html', 'pdf']:
                    with open(input_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if target_ext == 'txt':
                        with open(output_path, 'w', encoding='utf-8') as fout:
                            fout.write(content)
                    elif target_ext == 'html':
                        html = f"<html><body><pre>{content}</pre></body></html>"
                        with open(output_path, 'w', encoding='utf-8') as fout:
                            fout.write(html)
                    elif target_ext == 'pdf':
                        try:
                            from docx2pdf import convert as docx_to_pdf
                            temp_docx = output_path + '.temp.docx'
                            doc = Document()
                            doc.add_paragraph(content)
                            doc.save(temp_docx)
                            docx_to_pdf(temp_docx, output_path)
                            try:
                                os.remove(temp_docx)
                            except:
                                pass
                        except ImportError:
                            raise Exception("docx2pdf library not installed")
                return output_path
            
            # Unsupported conversion
            logger.error(f"❌ Unsupported document conversion: {source_ext} → {target_ext}")
            raise Exception(f"Document conversion {source_ext} → {target_ext} not implemented")
            
        except Exception as e:
            if "not implemented" in str(e) or "not installed" in str(e):
                raise
            logger.error(f"❌ Document conversion failed: {str(e)}")
            raise Exception(f"Document conversion failed: {str(e)}")

    def convert_audio_format(self, input_path, output_path, target_format):
        """Convert audio using ffmpeg - Production-ready with comprehensive format support"""
        try:
            logger.info(f"🎵 Converting audio to {target_format.upper()}")
            
            codec_map = {
                'mp3': 'libmp3lame',
                'wav': 'pcm_s16le',
                'ogg': 'libvorbis',
                'aac': 'aac',
                'flac': 'flac',
                'm4a': 'aac',
                'wma': 'wmav2',
                'opus': 'libopus'
            }
            codec = codec_map.get(target_format.lower(), 'libmp3lame')
            
            cmd = ['ffmpeg', '-i', input_path, '-acodec', codec]
            
            # Add format-specific options
            if target_format == 'mp3':
                cmd.extend(['-b:a', '192k'])
            elif target_format == 'aac':
                cmd.extend(['-b:a', '192k'])
            elif target_format == 'opus':
                cmd.extend(['-b:a', '128k'])
            elif target_format == 'flac':
                cmd.extend(['-compression_level', '5'])
            
            cmd.extend(['-y', output_path])
            
            result = subprocess.run(cmd, check=True, capture_output=True, stderr=subprocess.PIPE)
            logger.info(f"✅ Audio conversion successful: {target_format.upper()}")
            return output_path
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"❌ FFmpeg audio conversion failed: {error_msg}")
            raise Exception(f"Audio conversion failed: {error_msg}")
        except FileNotFoundError:
            logger.error("❌ FFmpeg not found. Please install FFmpeg")
            raise Exception("FFmpeg not found. Install it from: https://ffmpeg.org/download.html")
        except Exception as e:
            logger.error(f"❌ Audio conversion error: {str(e)}")
            raise Exception(f"Audio conversion error: {str(e)}")

    def convert_video_format(self, input_path, output_path, target_format):
        """Convert video using ffmpeg - Production-ready with comprehensive format support"""
        try:
            logger.info(f"🎬 Converting video to {target_format.upper()}")
            # Extract audio only
            if target_format in ['mp3', 'wav', 'aac', 'ogg']:
                codec_map = {
                    'mp3': 'libmp3lame',
                    'wav': 'pcm_s16le',
                    'aac': 'aac',
                    'ogg': 'libvorbis'
                }
                codec = codec_map.get(target_format, 'libmp3lame')
                cmd = ['ffmpeg', '-i', input_path, '-vn', '-acodec', codec]
                if target_format in ['mp3', 'aac']:
                    cmd.extend(['-b:a', '192k'])
                cmd.extend(['-y', output_path])
            
            # Convert to GIF (for short videos)
            elif target_format == 'gif':
                logger.info("🔄 Creating GIF with optimized palette...")
                # Generate palette for better quality
                palette_path = output_path + '.palette.png'
                subprocess.run([
                    'ffmpeg', '-i', input_path, '-vf',
                    'fps=15,scale=480:-1:flags=lanczos,palettegen',
                    '-y', palette_path
                ], check=True, capture_output=True)
                
                # Create GIF using palette
                cmd = [
                    'ffmpeg', '-i', input_path, '-i', palette_path,
                    '-filter_complex',
                    'fps=15,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse',
                    '-y', output_path
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                
                # Clean up palette
                try:
                    os.remove(palette_path)
                except:
                    pass
                logger.info("✅ Video to GIF conversion successful")
                return output_path
            
            # Video to video conversion
            else:
                codec_map = {
                    'mp4': ('libx264', 'aac'),
                    'webm': ('libvpx-vp9', 'libopus'),
                    'avi': ('mpeg4', 'libmp3lame'),
                    'mkv': ('libx264', 'aac'),
                    'mov': ('libx264', 'aac'),
                    'flv': ('flv', 'libmp3lame'),
                    'wmv': ('wmv2', 'wmav2')
                }
                
                vcodec, acodec = codec_map.get(target_format, ('libx264', 'aac'))
                
                cmd = [
                    'ffmpeg', '-i', input_path,
                    '-c:v', vcodec,
                    '-c:a', acodec
                ]
                
                # Add format-specific options
                if target_format == 'mp4':
                    cmd.extend(['-preset', 'medium', '-crf', '23'])
                elif target_format == 'webm':
                    cmd.extend(['-b:v', '1M', '-b:a', '128k'])
                
                cmd.extend(['-y', output_path])
            
            result = subprocess.run(cmd, check=True, capture_output=True, stderr=subprocess.PIPE)
            logger.info(f"✅ Video conversion successful: {target_format.upper()}")
            return output_path
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"❌ FFmpeg video conversion failed: {error_msg}")
            raise Exception(f"Video conversion failed: {error_msg}")
        except FileNotFoundError:
            logger.error("❌ FFmpeg not found. Please install FFmpeg")
            raise Exception("FFmpeg not found. Install it from: https://ffmpeg.org/download.html")
        except Exception as e:
            logger.error(f"❌ Video conversion error: {str(e)}")
            raise Exception(f"Video conversion error: {str(e)}")

    def perform_file_conversion(self, input_path, output_path, source_ext, target_ext):
        """Route conversion to appropriate handler - SUPER CONVERTER"""
        image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif', 'ico']
        audio_exts = ['mp3', 'wav', 'ogg', 'aac', 'm4a', 'flac', 'wma', 'opus']
        video_exts = ['mp4', 'avi', 'mov', 'webm', 'mkv', 'flv', 'wmv']
        document_exts = ['pdf', 'docx', 'doc', 'txt', 'html', 'md', 'rtf', 'xlsx', 'xls', 'csv', 'pptx', 'ppt']
        
        # Image conversions (including image to PDF)
        if source_ext in image_exts and (target_ext in image_exts or target_ext == 'pdf'):
            return self.convert_image_format(input_path, output_path, target_ext)
        
        # Video conversions (including video to audio and video to gif)
        elif source_ext in video_exts and (target_ext in video_exts or target_ext in audio_exts or target_ext == 'gif'):
            return self.convert_video_format(input_path, output_path, target_ext)
        
        # Audio conversions
        elif source_ext in audio_exts and target_ext in audio_exts:
            return self.convert_audio_format(input_path, output_path, target_ext)
        
        # Document conversions (anything involving documents)
        elif source_ext in document_exts or target_ext in document_exts:
            return self.convert_document_format(input_path, output_path, source_ext, target_ext)
        
        else:
            raise Exception(f"Conversion {source_ext} → {target_ext} not supported")

    # ==================== REDIS SYNC====================
    async def sync_redis_to_firestore_periodically(self):
        """Periodically sync critical Redis data back to Firestore"""
        while True:
            try:
                await asyncio.sleep(300)  # Sync every 5 minutes
                
                if not self.db:
                    continue
                
                logger.info("🔄 Starting periodic Redis → Firestore sync...")
                
                # Get all users from Redis
                user_ids = await redis_client.smembers("users:all")
                sync_count = 0
                
                for user_id in user_ids:
                    try:
                        user_data = await redis_client.hgetall(f"user:{user_id}")
                        
                        if not user_data:
                            continue
                        
                        # Update Firestore with current Redis data
                        update_data = {
                            'status': user_data.get('status', 'offline'),
                            'last_seen': firestore.SERVER_TIMESTAMP,
                            'avatar_url': user_data.get('avatar_url', ''),
                            'bio': user_data.get('bio', '')
                        }
                        
                        # Only update settings if they exist
                        if user_data.get('settings'):
                            try:
                                update_data['settings'] = json.loads(user_data.get('settings', '{}'))
                            except:
                                pass
                        
                        self.db.collection('users').document(user_id).set(update_data, merge=True)
                        sync_count += 1
                        
                    except Exception as e:
                        logger.warning(f"Could not sync user {user_id}: {e}")
                
                logger.info(f"✅ Synced {sync_count} users to Firestore")
                
            except Exception as e:
                logger.error(f"Periodic sync error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error before retrying

    # ==================== CHATS ====================
    
    async def get_chats(self, request):
        """Get user's chats - with Firestore fallback for missing data"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_ids = await redis_client.smembers(f"user_chats:{user_id}")
            
            # 🔥 FIX: If Redis returns empty, try Firestore
            if not chat_ids and self.db:
                logger.warning(f"⚠️ Redis has no chats for user {user_id}, attempting Firestore fallback...")
                try:
                    # Search all chats in Firestore where user is a member
                    chats_ref = self.db.collection('chats')
                    # Firestore doesn't support array-contains-any with large lists well,
                    # so scan all chats and filter
                    all_chats = list(chats_ref.stream())
                    for chat_doc in all_chats:
                        chat_data_fb = chat_doc.to_dict()
                        members = chat_data_fb.get('members', [])
                        if user_id in members:
                            # Found a chat for this user - restore to Redis
                            chat_id = chat_doc.id
                            await redis_client.sadd(f"user_chats:{user_id}", chat_id)
                            chat_ids.add(chat_id)
                            logger.info(f"✅ Restored chat {chat_id} to Redis for user {user_id}")
                    
                    if chat_ids:
                        logger.info(f"✅ Restored {len(chat_ids)} chats from Firestore to Redis")
                except Exception as fb_err:
                    logger.error(f"Firestore fallback failed: {fb_err}")

            chats = []

            for chat_id in chat_ids:
                chat_data = await redis_client.hgetall(f"chat:{chat_id}")
                if not chat_data:
                    # Try Firestore fallback for individual chat data
                    if self.db:
                        try:
                            chat_doc = self.db.collection('chats').document(chat_id).get()
                            if chat_doc.exists:
                                fb_data = chat_doc.to_dict()
                                chat_data = {
                                    'id': chat_id,
                                    'type': fb_data.get('type', 'direct'),
                                    'name': fb_data.get('name', ''),
                                    'description': fb_data.get('description', ''),
                                    'avatar_url': fb_data.get('avatar_url', ''),
                                    'created_by': fb_data.get('created_by', ''),
                                    'created_at': str(fb_data.get('created_at', ''))
                                }
                                await redis_client.hset(f"chat:{chat_id}", mapping=chat_data)
                                logger.info(f"✅ Restored chat {chat_id} data from Firestore")
                                
                                # Also restore members
                                members = fb_data.get('members', [])
                                for member_id in members:
                                    await redis_client.sadd(f"chat_members:{chat_id}", member_id)
                                    await redis_client.sadd(f"user_chats:{member_id}", chat_id)
                        except Exception as fb_err:
                            logger.warning(f"Chat Firestore fallback failed for {chat_id}: {fb_err}")
                    
                    if not chat_data:
                        continue

                # Get last message
                last_msg_ids = await redis_client.lrange(f"chat_messages:{chat_id}", 0, 0)
                last_message = ""
                last_message_time = None
                last_message_type = "text"

                if last_msg_ids:
                    last_msg_data = await redis_client.hgetall(f"message:{last_msg_ids[0]}")
                    if last_msg_data:
                        last_message = last_msg_data.get('content', '')[:50]
                        last_message_time = last_msg_data.get('created_at')
                        last_message_type = last_msg_data.get('message_type', 'text')

                # Get members
                member_ids = await redis_client.smembers(f"chat_members:{chat_id}")

                chat_info = {
                    "id": chat_id,
                    "type": chat_data.get('type'),
                    "last_message": last_message,
                    "last_message_time": last_message_time,
                    "last_message_type": last_message_type,
                    "unread_count": 0
                }

                if chat_data.get('type') == 'direct':
                    # Find other user
                    other_user_id = next((m for m in member_ids if m != user_id), None)
                    if other_user_id:
                        other_user = await redis_client.hgetall(f"user:{other_user_id}")
                        chat_info.update({
                            "name": other_user.get('username'),
                            "avatar_url": other_user.get('avatar_url'),
                            "status": other_user.get('status'),
                            "last_seen": other_user.get('last_seen'),
                            "other_user_id": other_user_id
                        })
                else:
                    # Group chat
                    chat_info.update({
                        "name": chat_data.get('name'),
                        "description": chat_data.get('description'),
                        "avatar_url": chat_data.get('avatar_url'),
                        "member_count": len(member_ids),
                        "member_ids": list(member_ids)  # 🔒 Include member IDs for E2E group encryption
                    })

                chats.append(chat_info)

            # Sort by last message time
            chats.sort(key=lambda x: x.get('last_message_time') or '', reverse=True)

            return web.json_response({"chats": chats})

        except Exception as e:
            logger.error(f"Get chats error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def create_chat(self, request):
        """Create new chat (direct or group) - FIXED VERSION"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            chat_type = data.get('type', 'direct')
            participants = data.get('participants', [])

            logger.info(f"📝 Creating {chat_type} chat: user {user_id} with {participants}")

            if chat_type == 'direct':
                if len(participants) != 1:
                    return web.json_response({"error": "Direct chat requires 1 participant"}, status=400)

                other_user_id = participants[0]

                # Check if chat already exists
                user_chats = await redis_client.smembers(f"user_chats:{user_id}")
                for existing_chat_id in user_chats:
                    chat_data = await redis_client.hgetall(f"chat:{existing_chat_id}")
                    if chat_data.get('type') == 'direct':
                        members = await redis_client.smembers(f"chat_members:{existing_chat_id}")
                        if other_user_id in members and user_id in members:
                            logger.info(f"✅ Chat already exists: {existing_chat_id}")
                            return web.json_response({
                                "success": True,
                                "chat_id": existing_chat_id,
                                "message": "Chat already exists"
                            })

                # Create new direct chat
                chat_id = str(uuid.uuid4())
                chat_data = {
                    "id": chat_id,
                    "type": "direct",
                    "created_by": user_id,
                    "created_at": datetime.datetime.now(datetime.UTC).isoformat()
                }

                await redis_client.hset(f"chat:{chat_id}", mapping=chat_data)
                await redis_client.sadd("chats:all", chat_id)

                # ✅ CRITICAL: Add members to chat AND chat to user lists
                for member_id in [user_id, other_user_id]:
                    await redis_client.sadd(f"chat_members:{chat_id}", member_id)
                    await redis_client.sadd(f"user_chats:{member_id}", chat_id)
                    logger.info(f"✅ Added chat {chat_id} to user {member_id}")

                # Save to Firestore
                if self.db:
                    try:
                        self.db.collection('chats').document(chat_id).set({
                            'id': chat_id,
                            'type': 'direct',
                            'created_by': user_id,
                            'created_at': firestore.SERVER_TIMESTAMP,
                            'members': [user_id, other_user_id]
                        })
                        logger.info(f"✅ Chat {chat_id} saved to Firestore")
                    except Exception as fb_err:
                        logger.error(f"Firestore save failed: {fb_err}")

            else:  # Group chat
                if len(participants) < 2:
                    return web.json_response({"error": "Group requires at least 2 participants"}, status=400)

                name = data.get('name', 'New Group')
                description = data.get('description', '')

                chat_id = str(uuid.uuid4())
                chat_data = {
                    "id": chat_id,
                    "type": "group",
                    "name": name,
                    "description": description,
                    "avatar_url": "",
                    "created_by": user_id,
                    "created_at": datetime.datetime.now(datetime.UTC).isoformat()
                }

                await redis_client.hset(f"chat:{chat_id}", mapping=chat_data)
                await redis_client.sadd("chats:all", chat_id)

                # Add creator as admin
                await redis_client.hset(f"chat_member:{chat_id}:{user_id}", mapping={
                    "role": "admin",
                    "joined_at": datetime.datetime.now(datetime.UTC).isoformat()
                })
                await redis_client.sadd(f"chat_members:{chat_id}", user_id)
                await redis_client.sadd(f"user_chats:{user_id}", chat_id)

                # Add participants as members
                for member_id in participants:
                    await redis_client.hset(f"chat_member:{chat_id}:{member_id}", mapping={
                        "role": "member",
                        "joined_at": datetime.datetime.now(datetime.UTC).isoformat()
                    })
                    await redis_client.sadd(f"chat_members:{chat_id}", member_id)
                    await redis_client.sadd(f"user_chats:{member_id}", chat_id)

                # Save to Firestore
                if self.db:
                    try:
                        self.db.collection('chats').document(chat_id).set({
                            'id': chat_id,
                            'type': 'group',
                            'name': name,
                            'description': description,
                            'created_by': user_id,
                            'created_at': firestore.SERVER_TIMESTAMP,
                            'members': [user_id] + participants
                        })
                        logger.info(f"✅ Group chat {chat_id} saved to Firestore")
                    except Exception as fb_err:
                        logger.error(f"Firestore save failed: {fb_err}")

            logger.info(f"✅ Chat created successfully: {chat_id}")

            return web.json_response({
                "success": True,
                "chat_id": chat_id
            })

        except Exception as e:
            logger.error(f"❌ Create chat error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_chat(self, request):
        """Get chat details - FIXED to return complete member info"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']

            # Check membership
            is_member = await redis_client.sismember(f"chat_members:{chat_id}", user_id)
            if not is_member:
                return web.json_response({"error": "Forbidden"}, status=403)

            chat_data = await redis_client.hgetall(f"chat:{chat_id}")
            if not chat_data:
                return web.json_response({"error": "Chat not found"}, status=404)
            # Get member IDs from Firestore (REAL source of truth)
            if self.db:
                chat_doc = self.db.collection('chats').document(chat_id).get()
                if chat_doc.exists:
                    member_ids = chat_doc.to_dict().get("members", [])
                else:
                    member_ids = []
            else:
                member_ids = []

            member_ids = [m.decode() if isinstance(m, bytes) else m for m in member_ids]
            members = []

            logger.info(f"📋 Loading {len(member_ids)} members for chat {chat_id}")

            for member_id in member_ids:
                # Try Redis first
                member_data = await redis_client.hgetall(f"user:{member_id}")
                
                # If not in Redis, try Firestore
                if not member_data and self.db:
                    try:
                        user_doc = self.db.collection('users').document(member_id).get()
                        if user_doc.exists:
                            fb_data = user_doc.to_dict()
                            member_data = {
                                'id': member_id,
                                'username': fb_data.get('username', 'Unknown'),
                                'email': fb_data.get('email', ''),
                                'avatar_url': fb_data.get('avatar_url', ''),
                                'status': 'offline'
                            }
                            # Cache in Redis
                            await redis_client.hset(f"user:{member_id}", mapping=member_data)
                            logger.info(f"✅ Loaded user {member_id} from Firestore")
                    except Exception as fb_err:
                        logger.error(f"Failed to load user {member_id} from Firestore: {fb_err}")
                
                if member_data:
                    # Get role for group chats
                    if chat_data.get('type') == 'group':
                        if member_id == chat_data.get('created_by'):
                            member_role = 'admin'
                        else:
                            member_role_data = await redis_client.hgetall(f"chat_member:{chat_id}:{member_id}")
                            member_role = member_role_data.get('role', 'member')
                    else:
                        member_role = None

                    members.append({
                        "id": member_id,
                        "username": member_data.get('username', 'Unknown'),
                        "email": member_data.get('email', ''),
                        "avatar_url": member_data.get('avatar_url', ''),
                        "status": member_data.get('status', 'offline'),
                        "role": member_role
                    })
                else:
                    logger.warning(f"⚠️ Could not load data for member {member_id}")

            logger.info(f"✅ Loaded {len(members)} members successfully")

            return web.json_response({
                "chat": {
                    "id": chat_id,
                    "type": chat_data.get('type'),
                    "name": chat_data.get('name'),
                    "description": chat_data.get('description'),
                    "avatar_url": chat_data.get('avatar_url'),
                    "created_by": chat_data.get('created_by'),
                    "created_at": chat_data.get('created_at'),
                    "members": members
                }
            })

        except Exception as e:
            logger.error(f"Get chat error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def delete_chat(self, request):
        """Delete chat"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']

            chat_data = await redis_client.hgetall(f"chat:{chat_id}")
            if chat_data.get('created_by') != user_id:
                return web.json_response({"error": "Only creator can delete chat"}, status=403)

            # Remove from all members
            member_ids = await redis_client.smembers(f"chat_members:{chat_id}")
            for member_id in member_ids:
                await redis_client.srem(f"user_chats:{member_id}", chat_id)

            # Delete chat data
            await redis_client.delete(f"chat:{chat_id}")
            await redis_client.delete(f"chat_members:{chat_id}")
            await redis_client.delete(f"chat_messages:{chat_id}")
            await redis_client.srem("chats:all", chat_id)

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Delete chat error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def add_chat_member(self, request):
        """Add member to group chat - FIXED VERSION"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']
            data = await request.json()
            new_member_id = data.get('user_id')

            if not new_member_id:
                return web.json_response({"error": "User ID required"}, status=400)

            # Get chat data
            chat_data = await redis_client.hgetall(f"chat:{chat_id}")
            
            if chat_data.get('type') != 'group':
                return web.json_response({"error": "Not a group chat"}, status=400)

            # Check if user is admin or creator
            is_creator = chat_data.get('created_by') == user_id
            member_role = await redis_client.hgetall(f"chat_member:{chat_id}:{user_id}")
            is_admin = member_role.get('role') == 'admin'

            if not is_creator and not is_admin:
                return web.json_response({"error": "Only admins can add members"}, status=403)

            # Check if user already a member
            is_already_member = await redis_client.sismember(f"chat_members:{chat_id}", new_member_id)
            if is_already_member:
                return web.json_response({"error": "User is already a member"}, status=400)

            # Add member to Redis
            await redis_client.hset(f"chat_member:{chat_id}:{new_member_id}", mapping={
                "role": "member",
                "joined_at": datetime.datetime.now(datetime.UTC).isoformat()
            })
            await redis_client.sadd(f"chat_members:{chat_id}", new_member_id)
            await redis_client.sadd(f"user_chats:{new_member_id}", chat_id)

            # Update Firestore
            if self.db:
                try:
                    chat_ref = self.db.collection('chats').document(chat_id)

                    # Ensure Firestore always has proper members array
                    chat_snapshot = chat_ref.get()
                    if chat_snapshot.exists:
                        chat_doc = chat_snapshot.to_dict()
                        existing_members = chat_doc.get("members", [])
                    else:
                        existing_members = []

                    # Add member ONLY if not already present
                    if new_member_id not in existing_members:
                        existing_members.append(new_member_id)

                    chat_ref.update({
                        "members": existing_members
                    })

                    logger.info(f"🔥 Firestore members updated: {existing_members}")

                except Exception as fb_err:
                    logger.error(f"Firestore member add failed: {fb_err}")

            # Notify all members including new member
            member_ids = await redis_client.smembers(f"chat_members:{chat_id}")
            await self.broadcast_to_users(list(member_ids), {
                "type": "member_added",
                "chat_id": chat_id,
                "member_id": new_member_id
            })

            logger.info(f"✅ Added member {new_member_id} to chat {chat_id}")

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Add member error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)
            
    async def remove_chat_member(self, request):
        """Remove member from group chat"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']
            member_to_remove = request.match_info['user_id']

            # Check if user is admin
            member_role = await redis_client.hgetall(f"chat_member:{chat_id}:{user_id}")
            if member_role.get('role') != 'admin' and user_id != member_to_remove:
                return web.json_response({"error": "Only admins can remove members"}, status=403)

            # Remove member
            await redis_client.delete(f"chat_member:{chat_id}:{member_to_remove}")
            await redis_client.srem(f"chat_members:{chat_id}", member_to_remove)
            await redis_client.srem(f"user_chats:{member_to_remove}", chat_id)

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Remove member error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # ==================== MESSAGES ====================
    
    async def get_messages(self, request):
        """Get chat messages - with Firestore fallback for older messages"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']
            limit = int(request.query.get('limit', 50))
            offset = int(request.query.get('offset', 0))

            # Check membership
            is_member = await redis_client.sismember(f"chat_members:{chat_id}", user_id)
            if not is_member:
                return web.json_response({"error": "Forbidden"}, status=403)

            # Load delete-for-me set
            deleted_for_me = await redis_client.smembers(f"deleted_messages:{user_id}")
            deleted_for_me = set(
                m.decode() if isinstance(m, bytes) else m
                for m in deleted_for_me
            )

            message_ids = await redis_client.lrange(
                f"chat_messages:{chat_id}",
                offset,
                offset + limit - 1
            )

            # ⭐ FIX: If Redis returns fewer messages than requested AND we have Firestore,
            # try to fetch older messages from Firestore directly
            if (not message_ids or len(message_ids) < limit) and self.db:
                logger.warning(f"⚠️ Redis had only {len(message_ids)} messages for chat {chat_id} (requested {limit}), checking Firestore...")
                try:
                    messages_ref = self.db.collection('chats').document(chat_id).collection('messages')
                    # Fetch from Firestore in descending order with offset
                    fb_query = messages_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(limit)
                    fb_docs = list(fb_query.stream())
                    
                    if fb_docs:
                        logger.info(f"✅ Found {len(fb_docs)} messages in Firestore for chat {chat_id}")
                        # Store them in Redis for next time
                        for msg_doc in reversed(fb_docs):
                            msg_data = msg_doc.to_dict()
                            msg_id = msg_doc.id
                            
                            redis_msg_data = {
                                'id': msg_id,
                                'chat_id': chat_id,
                                'sender_id': msg_data.get('sender_id', ''),
                                'content': msg_data.get('content', ''),
                                'message_type': msg_data.get('message_type', 'text'),
                                'encrypted': str(msg_data.get('encrypted', False)),
                                'attachments': json.dumps(msg_data.get('attachments', [])),
                                'reply_to': msg_data.get('reply_to', ''),
                                'created_at': str(msg_data.get('created_at', datetime.datetime.now(datetime.UTC).isoformat())),
                                'edited': str(msg_data.get('edited', False)),
                                'deleted': str(msg_data.get('deleted', False))
                            }
                            
                            await redis_client.hset(f"message:{msg_id}", mapping=redis_msg_data)
                            await redis_client.lpush(f"chat_messages:{chat_id}", msg_id)
                        
                        await redis_client.ltrim(f"chat_messages:{chat_id}", 0, 999)
                        
                        # Re-fetch from Redis after restoring from Firestore
                        message_ids = await redis_client.lrange(
                            f"chat_messages:{chat_id}",
                            offset,
                            offset + limit - 1
                        )
                        logger.info(f"✅ Restored messages to Redis, now have {len(message_ids)} messages available")
                except Exception as fb_err:
                    logger.warning(f"Firestore fallback for messages failed: {fb_err}")

            messages = []

            for raw_msg_id in message_ids:
                # 🔥 CRITICAL FIX (DO NOT REMOVE)
                msg_id = raw_msg_id.decode() if isinstance(raw_msg_id, bytes) else raw_msg_id

                # Delete-for-me filtering
                if msg_id in deleted_for_me:
                    continue

                msg_data = await redis_client.hgetall(f"message:{msg_id}")
                if not msg_data:
                    continue

                sender_id = msg_data.get('sender_id')

                # Delete-for-everyone handling
                if msg_data.get('deleted') == 'True':
                    messages.append({
                        "id": msg_id,
                        "content": "🚫 This message was deleted",
                        "deleted": True,
                        "deleted_for_everyone": True,
                        "created_at": msg_data.get('created_at'),
                        "edited": False,
                        "reply_to": None,
                        "reply_to_data": None,
                        "sender": {
                            "id": sender_id,
                            "username": "Deleted",
                            "avatar_url": ""
                        }
                    })
                    continue

                sender_data = await redis_client.hgetall(f"user:{sender_id}")

                attachments = []
                attachment_ids = json.loads(msg_data.get('attachments', '[]'))
                for att_id in attachment_ids:
                    att_meta = await redis_client.hgetall(f"file:{att_id}")
                    
                    # Firestore fallback for file metadata
                    if not att_meta and self.db:
                        try:
                            file_doc = self.db.collection('files').document(att_id).get()
                            if file_doc.exists:
                                fb_data = file_doc.to_dict()
                                att_meta = {
                                    'id': att_id,
                                    'filename': fb_data.get('filename', ''),
                                    'file_type': fb_data.get('file_type', 'document'),
                                    'size': str(fb_data.get('size', 0)),
                                    'url': fb_data.get('url', ''),
                                    'thumbnail_url': fb_data.get('thumbnail_url', '')
                                }
                                # Cache back to Redis
                                await redis_client.hset(f"file:{att_id}", mapping=att_meta)
                                logger.info(f"✅ Restored file {att_id} metadata from Firestore")
                        except Exception as fb_err:
                            logger.warning(f"Firestore file fallback failed for {att_id}: {fb_err}")
                    
                    if att_meta:
                        attachments.append({
                            "id": att_id,
                            "filename": att_meta.get('filename'),
                            "type": att_meta.get('file_type'),
                            "size": int(att_meta.get('size', 0)),
                            "url": att_meta.get('url'),
                            "thumbnail_url": att_meta.get('thumbnail_url')
                        })

                reply_to_info = None
                if msg_data.get('reply_to_data'):
                    try:
                        reply_to_info = json.loads(msg_data.get('reply_to_data'))
                    except:
                        reply_to_info = None
                elif msg_data.get('reply_to'):
                    reply_msg = await redis_client.hgetall(f"message:{msg_data.get('reply_to')}")
                    if reply_msg:
                        reply_sender = await redis_client.hgetall(
                            f"user:{reply_msg.get('sender_id')}"
                        )
                        reply_to_info = {
                            "id": msg_data.get('reply_to'),
                            "content": reply_msg.get('content', ''),
                            "sender": {
                                "id": reply_msg.get('sender_id'),
                                "username": reply_sender.get('username', 'Unknown'),
                                "avatar_url": reply_sender.get('avatar_url', '')
                            },
                            "message_type": reply_msg.get('message_type', 'text')
                        }

                messages.append({
                    "id": msg_id,
                    "content": msg_data.get('content'),
                    "encrypted": msg_data.get('encrypted') == 'True',
                    "message_type": msg_data.get('message_type'),
                    "attachments": attachments,
                    "created_at": msg_data.get('created_at'),
                    "edited": msg_data.get('edited') == 'True',
                    "reply_to": msg_data.get('reply_to') or None,
                    "reply_to_data": reply_to_info,
                    "sender": {
                        "id": sender_id,
                        "username": sender_data.get('username'),
                        "avatar_url": sender_data.get('avatar_url')
                    }
                })

            messages.reverse()
            return web.json_response({"messages": messages})

        except Exception as e:
            logger.error(f"Get messages error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def search_messages_in_chat(self, request):
        """Search messages in a specific chat - FIXED VERSION"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']
            query = request.query.get('q', '').strip().lower()

            logger.info(f"🔍 Searching chat {chat_id} for: '{query}'")

            if not query:
                return web.json_response({"messages": []})

            # --- PATCH START: membership check with Firestore fallback ---
            is_member = False
            try:
                is_member = await redis_client.sismember(f"chat_members:{chat_id}", user_id)
            except Exception as e:
                logger.warning(f"Redis membership check failed for chat {chat_id}: {e}")

            if not is_member and getattr(self, "db", None):
                try:
                    chat_doc = self.db.collection('chats').document(chat_id).get()
                    if chat_doc and chat_doc.exists:
                        chat_data = chat_doc.to_dict()
                        members = (
                            chat_data.get('members')
                            or chat_data.get('participant_ids')
                            or chat_data.get('member_ids')
                            or []
                        )
                        member_ids = []
                        if isinstance(members, list):
                            if members and isinstance(members[0], dict):
                                member_ids = [
                                    m.get('id') or m.get('user_id') or m.get('uid')
                                    for m in members if isinstance(m, dict)
                                ]
                            else:
                                member_ids = [m for m in members if isinstance(m, (str, int))]
                        if str(user_id) in [str(mid) for mid in member_ids]:
                            is_member = True
                except Exception as fb_err:
                    logger.error(f"Firestore membership check error for chat {chat_id}: {fb_err}")

            if not is_member:
                return web.json_response({"error": "Forbidden"}, status=403)
            # --- PATCH END ---

            # ✅ PATCH: load delete-for-me messages
            deleted_for_me = await redis_client.smembers(f"deleted_messages:{user_id}")
            deleted_for_me = set(
                m.decode() if isinstance(m, bytes) else m
                for m in deleted_for_me
            )

            results = []

            # --- REDIS SEARCH ---
            message_ids = await redis_client.lrange(f"chat_messages:{chat_id}", 0, -1)
            logger.info(f"📋 Searching {len(message_ids)} messages in Redis")

            for msg_id in message_ids:
                # ✅ Respect delete-for-me
                if msg_id in deleted_for_me:
                    continue

                msg_data = await redis_client.hgetall(f"message:{msg_id}")
                if not msg_data or msg_data.get('deleted') == 'True':
                    continue

                content = msg_data.get('content', '').lower()
                if query not in content:
                    continue

                sender_id = msg_data.get('sender_id')
                sender_data = await redis_client.hgetall(f"user:{sender_id}")

                results.append({
                    "id": msg_id,  # ✅ FIXED (was msg_data.get('id'))
                    "content": msg_data.get('content'),
                    "created_at": msg_data.get('created_at'),
                    "sender": {
                        "id": sender_id,
                        "username": sender_data.get('username', 'Unknown'),
                        "avatar_url": sender_data.get('avatar_url', '')
                    }
                })

            # --- FIRESTORE FALLBACK ---
            if not results and getattr(self, "db", None):
                logger.info(f"📥 Redis empty, checking Firestore...")

                try:
                    messages_ref = (
                        self.db.collection('chats')
                        .document(chat_id)
                        .collection('messages')
                    )
                    messages_query = messages_ref.order_by(
                        'created_at',
                        direction=firestore.Query.DESCENDING
                    ).limit(500)

                    for msg_doc in messages_query.stream():
                        msg_data = msg_doc.to_dict()

                        if msg_data.get('deleted'):
                            continue

                        # ✅ Respect delete-for-me
                        if str(msg_doc.id) in deleted_for_me:
                            continue

                        content = (msg_data.get('content') or '').lower()
                        if query not in content:
                            continue

                        sender_id = msg_data.get('sender_id')
                        sender_data = await redis_client.hgetall(f"user:{sender_id}")

                        created_at_raw = msg_data.get('created_at')
                        if created_at_raw:
                            try:
                                created_at_str = (
                                    created_at_raw.isoformat()
                                    if hasattr(created_at_raw, 'isoformat')
                                    else str(created_at_raw)
                                )
                            except Exception:
                                created_at_str = datetime.datetime.now(datetime.UTC).isoformat()
                        else:
                            created_at_str = datetime.datetime.now(datetime.UTC).isoformat()

                        results.append({
                            "id": msg_doc.id,
                            "content": msg_data.get('content', ''),
                            "created_at": created_at_str,
                            "sender": {
                                "id": sender_id,
                                "username": sender_data.get('username', 'Unknown') if sender_data else 'Unknown',
                                "avatar_url": sender_data.get('avatar_url', '') if sender_data else ''
                            }
                        })

                except Exception as fb_err:
                    logger.error(f"❌ Firestore search error: {fb_err}")

            logger.info(f"✅ Found {len(results)} matching messages")

            results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return web.json_response({"messages": results[:50]})

        except Exception as e:
            logger.error(f"❌ Search error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def send_message_http(self, request):
        """Send message via HTTP"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            chat_id = request.match_info['chat_id']
            data = await request.json()

            # Check membership
            is_member = await redis_client.sismember(f"chat_members:{chat_id}", user_id)
            if not is_member:
                return web.json_response({"error": "Forbidden"}, status=403)

            # Create message
            message_id = await self.create_message(
                chat_id=chat_id,
                sender_id=user_id,
                content=data.get('content', ''),
                message_type=data.get('message_type', 'text'),
                encrypted=data.get('encrypted', True),
                attachments=data.get('attachments', []),
                reply_to=data.get('reply_to')
            )

            return web.json_response({
                "success": True,
                "message_id": message_id
            })

        except Exception as e:
            logger.error(f"Send message error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def create_message(self, chat_id: str, sender_id: str, content: str,
                        message_type: str = 'text', encrypted: bool = True,
                        attachments: List[str] = None, reply_to: str = None) -> str:
        """Create and store message"""
        message_id = str(uuid.uuid4())
        
        if attachments is None:
            attachments = []
        reply_to_data = None
        if reply_to:
            reply_msg = await redis_client.hgetall(f"message:{reply_to}")
            if reply_msg:
                reply_sender = await redis_client.hgetall(f"user:{reply_msg.get('sender_id')}")
                reply_to_data = {
                    'id': reply_to,
                    'content': reply_msg.get('content', ''),
                    'sender': {
                        'id': reply_msg.get('sender_id'),
                        'username': reply_sender.get('username', 'Unknown'),
                        'avatar_url': reply_sender.get('avatar_url', '')
                    },
                    'message_type': reply_msg.get('message_type', 'text')
                }
        message_data = {
            "id": message_id,
            "chat_id": chat_id,
            "sender_id": sender_id,
            "content": content,
            "encrypted": str(encrypted),
            "message_type": message_type,
            "reply_to": reply_to or "",
            "attachments": json.dumps(attachments),
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "edited": "False",
            "deleted": "False"
        }
        if reply_to_data:
            message_data["reply_to_data"] = json.dumps(reply_to_data)


        await redis_client.hset(f"message:{message_id}", mapping=message_data)
        if self.db:
            try:
                # Prepare message document
                firestore_msg = {
                    'id': message_id,
                    'sender_id': sender_id,
                    'content': content,
                    'message_type': message_type,
                    'encrypted': encrypted,
                    'attachments': attachments if attachments else [],  # Ensure array
                    'reply_to': reply_to or None,
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'edited': False,
                    'deleted': False
                }
                if reply_to_data:
                    firestore_msg['reply_to_data'] = reply_to_data
                    
                # Save message
                self.db.collection('chats').document(chat_id).collection('messages').document(message_id).set(firestore_msg)
                logger.info(f"✅ Message {message_id} saved to Firestore with {len(attachments) if attachments else 0} attachments")
                
            except Exception as fb_err:
                logger.error(f"❌ Firestore message save failed: {fb_err}")
        await redis_client.lpush(f"chat_messages:{chat_id}", message_id)
        await redis_client.ltrim(f"chat_messages:{chat_id}", 0, 999)

        # ✅ Update chat's last_message for quick preview in contact list
        preview_content = content[:50] if message_type == 'text' else ''
        await redis_client.hset(f"chat:{chat_id}", mapping={
            "last_message": preview_content,
            "last_message_type": message_type,
            "last_message_time": message_data["created_at"]
        })
        
        await self.broadcast_message(chat_id, message_id, sender_id)

        return message_id

    async def broadcast_message(self, chat_id: str, message_id: str, sender_id: str):
        """Broadcast message to chat members with blocking checks"""
        try:
            # Get message data
            msg_data = await redis_client.hgetall(f"message:{message_id}")
            
            if not msg_data:
                logger.error(f"❌ Message {message_id} not found in Redis!")
                return
            
            logger.info(f"📢 Broadcasting message {message_id}, type: {msg_data.get('message_type')}")
            
            sender_data = await redis_client.hgetall(f"user:{sender_id}")

            # ✅ CRITICAL FIX: Initialize reply_to_info FIRST, before any loops
            reply_to_info = None
            if msg_data.get('reply_to_data'):
                try:
                    reply_to_info = json.loads(msg_data.get('reply_to_data'))
                    logger.info(f"✅ Loaded reply_to_data from message")
                except Exception as e:
                    logger.error(f"Failed to parse reply_to_data: {e}")
            elif msg_data.get('reply_to'):
                # Fallback: fetch reply message if reply_to_data not stored
                try:
                    reply_msg = await redis_client.hgetall(f"message:{msg_data.get('reply_to')}")
                    if reply_msg:
                        reply_sender = await redis_client.hgetall(f"user:{reply_msg.get('sender_id')}")
                        reply_to_info = {
                            'id': msg_data.get('reply_to'),
                            'content': reply_msg.get('content', ''),
                            'sender': {
                                'id': reply_msg.get('sender_id'),
                                'username': reply_sender.get('username', 'Unknown'),
                                'avatar_url': reply_sender.get('avatar_url', '')
                            },
                            'message_type': reply_msg.get('message_type', 'text')
                        }
                        logger.info(f"✅ Fetched reply_to message data")
                except Exception as e:
                    logger.error(f"Failed to fetch reply_to message: {e}")

            # Parse attachments
            attachments = []
            attachment_ids_str = msg_data.get('attachments', '[]')
            
            try:
                attachment_ids = json.loads(attachment_ids_str) if attachment_ids_str else []
            except Exception as e:
                logger.error(f"Failed to parse attachments JSON: {e}")
                attachment_ids = []
            
            for att_id in attachment_ids:
                if not att_id:
                    continue
                    
                att_meta = await redis_client.hgetall(f"file:{att_id}")
                
                if att_meta:
                    attachment_data = {
                        "id": att_id,
                        "filename": att_meta.get('filename'),
                        "type": att_meta.get('file_type'),
                        "size": int(att_meta.get('size', 0)),
                        "url": att_meta.get('url'),
                        "thumbnail_url": att_meta.get('thumbnail_url')
                    }
                    
                    if att_meta.get('duration'):
                        attachment_data['duration'] = att_meta.get('duration')
                    
                    attachments.append(attachment_data)

            # Get chat members
            member_ids = await redis_client.smembers(f"chat_members:{chat_id}")

            # Filter out blocked users for direct chats
            chat_data = await redis_client.hgetall(f"chat:{chat_id}")
            allowed_recipients = []
            
            for member_id in member_ids:
                if member_id == sender_id:
                    # Sender always gets their own message
                    allowed_recipients.append(member_id)
                    continue
                
                # Check blocking for direct chats only
                if chat_data.get('type') == 'direct':
                    # Check if sender blocked this recipient
                    sender_blocked_recipient = await redis_client.sismember(
                        f"user_blocked:{sender_id}", 
                        member_id
                    )
                    
                    # Check if recipient blocked sender
                    recipient_blocked_sender = await redis_client.sismember(
                        f"user_blocked:{member_id}", 
                        sender_id
                    )
                    
                    if sender_blocked_recipient or recipient_blocked_sender:
                        logger.warning(f"⚠️ Skipping broadcast to {member_id} - blocking active")
                        continue
                
                allowed_recipients.append(member_id)

            # Broadcast only to allowed recipients
            broadcast_data = {
                "type": "new_message",
                "chat_id": chat_id,
                "message": {
                    "id": message_id,
                    "content": msg_data.get('content'),
                    "encrypted": msg_data.get('encrypted') == 'True',
                    "message_type": msg_data.get('message_type'),
                    "attachments": attachments,
                    "created_at": msg_data.get('created_at'),
                    "reply_to": msg_data.get('reply_to') or None,
                    "reply_to_data": reply_to_info,  # ✅ Now guaranteed to be defined
                    "sender": {
                        "id": sender_id,
                        "username": sender_data.get('username'),
                        "avatar_url": sender_data.get('avatar_url')
                    }
                },
                "last_message_type": msg_data.get('message_type'),  # ✅ Include for chat list preview
                "last_message_preview": msg_data.get('content', '')[:50] if msg_data.get('message_type') == 'text' else ''
            }

            logger.info(f"📢 Broadcasting to {len(allowed_recipients)}/{len(member_ids)} members")

            await self.broadcast_to_users(allowed_recipients, broadcast_data)
            
            logger.info(f"✅ Message {message_id} broadcast complete")

        except Exception as e:
            logger.error(f"❌ Broadcast message error: {e}", exc_info=True)
    async def delete_message(self, request):
        """Delete message"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            message_id = request.match_info['message_id']
            msg_data = await redis_client.hgetall(f"message:{message_id}")

            if msg_data.get('sender_id') != user_id:
                return web.json_response({"error": "Can only delete own messages"}, status=403)

            await redis_client.hset(f"message:{message_id}", "deleted", "True")

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Delete message error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def edit_message(self, request):
        """Edit message"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            message_id = request.match_info['message_id']
            data = await request.json()
            new_content = data.get('content', '').strip()

            if not new_content:
                return web.json_response({"error": "Content required"}, status=400)

            msg_data = await redis_client.hgetall(f"message:{message_id}")

            if msg_data.get('sender_id') != user_id:
                return web.json_response({"error": "Can only edit own messages"}, status=403)

            await redis_client.hset(f"message:{message_id}", mapping={
                "content": new_content,
                "edited": "True",
                "edited_at": datetime.datetime.now(datetime.UTC).isoformat()
            })

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Edit message error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # ==================== FILE UPLOADS ====================
    
    async def upload_file(self, request):
        """Upload file with mobile-specific handling — FINAL FIXED VERSION"""
        try:
            import mimetypes  # ensure available

            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            # Per-user upload rate limit check
            if await self._check_upload_rate_limit(user_id):
                return web.json_response({"error": "Upload rate limit exceeded (50/hour)"}, status=429)

            # Detect mobile device
            user_agent = request.headers.get('User-Agent', '')
            is_mobile = any(x in user_agent for x in ['iPhone', 'iPad', 'Android', 'Mobile'])

            logger.info(f"📤 File upload - User: {user_id}, Mobile: {is_mobile}, UA: {user_agent[:50]}")

            reader = await request.multipart()

            # Robust: iterate until we find a file part with a filename
            field = None
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.filename:
                    field = part
                    break

            if not field:
                logger.error("❌ No file part found in multipart payload")
                return web.json_response({"error": "No file provided"}, status=400)



            filename = field.filename
            if not filename:
                logger.error("❌ No filename in upload")
                return web.json_response({"error": "Invalid filename"}, status=400)

            # SAFELY DETERMINE CONTENT TYPE (NO .content_type USED ANYWHERE)
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            if not content_type:
                content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

            logger.info(f"📄 Uploading: {filename} ({content_type})")

            # Determine file extension + type
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
            file_type = self.get_file_type(ext)

            # Subdirectory selection
            subdir = {
                'image': 'images',
                'video': 'videos',
                'audio': 'audio',
                'document': 'documents',
                'archive': 'archives'
            }.get(file_type, 'documents')

            upload_subdir = UPLOAD_DIR / subdir
            upload_subdir.mkdir(parents=True, exist_ok=True)

            # Generate file ID + path
            file_id = str(uuid.uuid4())
            file_path = upload_subdir / f"{file_id}.{ext}"

            # Save file in chunks
            size = 0
            with open(file_path, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break

                    size += len(chunk)
                    if size > MAX_FILE_SIZE:
                        file_path.unlink()
                        return web.json_response({"error": "File too large"}, status=400)

                    f.write(chunk)

            logger.info(f"✅ File saved locally: {size} bytes at {file_path}")

            if not file_path.exists() or file_path.stat().st_size == 0:
                logger.error(f"❌ File missing after save: {file_path}")
                return web.json_response({"error": "File save failed"}, status=500)

            # Magic byte validation
            if not _validate_file_magic(file_path, ext):
                file_path.unlink(missing_ok=True)
                logger.warning(f"❌ File rejected by magic byte check: {filename} (ext={ext})")
                return web.json_response({"error": "File content does not match its extension"}, status=400)

            # Thumbnail generation (only for images)
            thumbnail_url = None
            if file_type == 'image':
                try:
                    thumbnail_url = await self.generate_thumbnail(file_path, file_id, ext)
                except Exception as thumb_error:
                    logger.warning(f"⚠️ Thumbnail generation failed: {thumb_error}")

            # Relative URL for client
            file_url = f"/api/uploads/{subdir}/{file_id}.{ext}"

            # Metadata
            file_meta = {
                "id": file_id,
                "user_id": user_id,
                "filename": filename,
                "file_type": file_type,
                "extension": ext,
                "size": str(size),
                "path": str(file_path.absolute()),
                "url": file_url,
                "uploaded_at": datetime.datetime.now(datetime.UTC).isoformat()
            }

            if thumbnail_url:
                file_meta["thumbnail_url"] = thumbnail_url

            # Save to Redis
            await redis_client.hset(f"file:{file_id}", mapping=file_meta)
            await redis_client.sadd(f"user_files:{user_id}", file_id)

            # Save to Firestore
            if self.db:
                try:
                    firestore_doc = {
                        **file_meta,
                        "size": size,
                        "uploaded_at": firestore.SERVER_TIMESTAMP
                    }
                    self.db.collection("files").document(file_id).set(firestore_doc)
                    logger.info(f"✅ File metadata saved to Firestore: {file_id}")

                except Exception as fb_err:
                    logger.error(f"❌ Firestore file save failed: {fb_err}")

            return web.json_response({
                "success": True,
                "file": {
                    "id": file_id,
                    "filename": filename,
                    "type": file_type,
                    "size": size,
                    "url": file_url,
                    "thumbnail_url": thumbnail_url
                }
            })

        except Exception as e:
            logger.error(f"❌ File upload error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def _check_upload_rate_limit(self, user_id: str) -> bool:
        """Check per-user upload rate limit (50/hour via Redis). Returns True if limited."""
        key = f"user_upload_count:{user_id}"
        try:
            count = await redis_client.get(key)
            if count is None:
                await redis_client.setex(key, 3600, 1)
                return False
            count = int(count)
            if count >= 50:
                logger.warning(f"⚠️ Upload rate limit hit for user {user_id}")
                return True
            await redis_client.incr(key)
            await redis_client.expire(key, 3600)
            return False
        except Exception:
            return False  # Graceful degradation

    async def upload_voice(self, request):
        """Upload voice message with Firestore persistence"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            # Per-user upload rate limit check
            if await self._check_upload_rate_limit(user_id):
                return web.json_response({"error": "Upload rate limit exceeded (50/hour)"}, status=429)

            logger.info(f"🎤 Voice upload started by user: {user_id}")

            reader = await request.multipart()
            field = await reader.next()

            if not field:
                return web.json_response({"error": "No audio provided"}, status=400)

            # Save voice
            voice_id = str(uuid.uuid4())
            filename = field.filename or "voice.webm"
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'webm'
            
            voice_path = UPLOAD_DIR / 'audio' / f"{voice_id}.{ext}"

            size = 0
            with open(voice_path, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 10 * 1024 * 1024:  # 10MB limit
                        voice_path.unlink()
                        return web.json_response({"error": "Voice too large"}, status=400)
                    f.write(chunk)

            # Calculate duration
            estimated_duration = int(size / 16000)
            minutes = estimated_duration // 60
            seconds = estimated_duration % 60
            duration_str = f"{minutes}:{seconds:02d}"

            voice_url = f"/api/uploads/audio/{voice_id}.{ext}"
            
            voice_meta = {
                "id": voice_id,
                "user_id": user_id,
                "filename": f"voice_{voice_id}.{ext}",
                "file_type": "audio",
                "extension": ext,
                "size": str(size),
                "path": str(voice_path.absolute()),  # Absolute path
                "url": voice_url,
                "uploaded_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "duration": duration_str
            }

            # Save to Redis
            await redis_client.hset(f"file:{voice_id}", mapping=voice_meta)
            await redis_client.sadd(f"user_files:{user_id}", voice_id)

            # ✅ CRITICAL: ALWAYS save to Firestore
            if self.db:
                try:
                    firestore_doc = {
                        'id': voice_id,
                        'user_id': user_id,
                        'filename': voice_meta['filename'],
                        'file_type': 'audio',
                        'extension': ext,
                        'size': size,
                        'url': voice_url,
                        'path': str(voice_path.absolute()),
                        'duration': duration_str,
                        'uploaded_at': firestore.SERVER_TIMESTAMP
                    }
                    
                    self.db.collection('files').document(voice_id).set(firestore_doc)
                    logger.info(f"✅ Voice metadata saved to Firestore: {voice_id}")
                    
                except Exception as fb_err:
                    logger.error(f"❌ CRITICAL: Firestore voice save failed: {fb_err}")

            logger.info(f"✅ Voice uploaded: {voice_id} ({size} bytes, {duration_str})")

            return web.json_response({
                "success": True,
                "voice": {
                    "id": voice_id,
                    "filename": voice_meta['filename'],
                    "type": "audio",
                    "size": size,
                    "url": voice_url,
                    "duration": duration_str
                }
            })

        except Exception as e:
            logger.error(f"❌ Voice upload error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def convert_uploaded_file(self, request):
        """Convert file format endpoint with real-time progress tracking"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)
            
            data = await request.json()
            file_id = data.get('file_id')
            target_format = data.get('target_format', '').lower()
            
            if not file_id or not target_format:
                return web.json_response({"error": "Missing parameters"}, status=400)
            
            # Get file metadata
            file_meta = await redis_client.hgetall(f"file:{file_id}")
            
            # Firestore fallback for file metadata
            if not file_meta and self.db:
                try:
                    file_doc = self.db.collection('files').document(file_id).get()
                    if file_doc.exists:
                        fb_data = file_doc.to_dict()
                        file_meta = {
                            'id': file_id,
                            'user_id': fb_data.get('user_id', ''),
                            'filename': fb_data.get('filename', ''),
                            'file_type': fb_data.get('file_type', 'document'),
                            'extension': fb_data.get('extension', ''),
                            'size': str(fb_data.get('size', 0)),
                            'path': fb_data.get('path', ''),
                            'url': fb_data.get('url', ''),
                            'thumbnail_url': fb_data.get('thumbnail_url', ''),
                            'uploaded_at': str(fb_data.get('uploaded_at', '')),
                        }
                        # Cache back to Redis
                        await redis_client.hset(f"file:{file_id}", mapping=file_meta)
                        logger.info(f"✅ Restored file {file_id} metadata from Firestore")
                except Exception as fb_err:
                    logger.warning(f"Firestore file fallback failed for {file_id}: {fb_err}")
            
            if not file_meta:
                return web.json_response({"error": "File not found"}, status=404)

            try:
                source_path = _resolve_safe_path(UPLOAD_DIR, file_meta['path'])
            except ValueError as e:
                logger.error(f"❌ Blocked path traversal in convert_uploaded_file: {e}")
                return web.json_response({"error": "Invalid file path"}, status=400)

            if not source_path.exists():
                return web.json_response({"error": "Source file missing"}, status=404)
            
            source_ext = file_meta['extension']
            
            # Validate conversion support
            supported_formats = self.get_supported_conversions(source_ext)
            if target_format not in supported_formats:
                return web.json_response({
                    "error": f"Cannot convert {source_ext} to {target_format}",
                    "supported_formats": supported_formats
                }, status=400)
            
            # ✅ FIX 1: Create output in correct subdirectory based on target format
            target_file_type = self.get_file_type(target_format)
            target_subdir_name = {
                'image': 'images',
                'video': 'videos',
                'audio': 'audio',
                'document': 'documents',
                'archive': 'archives'
            }.get(target_file_type, 'documents')
            
            target_subdir = UPLOAD_DIR / target_subdir_name
            target_subdir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename for converted file
            converted_id = str(uuid.uuid4())
            output_filename = f"{converted_id}.{target_format}"
            output_path = target_subdir / output_filename
            
            # Initialize progress tracking
            conversion_id = f"conversion:{file_id}:{target_format}"
            await redis_client.hset(conversion_id, mapping={
                "status": "processing",
                "progress": "0",
                "started_at": datetime.datetime.now(datetime.UTC).isoformat()
            })
            await redis_client.expire(conversion_id, 600)
            
            logger.info(f"🔄 Starting conversion: {source_ext} → {target_format} for file {file_id}")
            
            try:
                # Update progress: Preparation phase (0-10%)
                await redis_client.hset(conversion_id, "progress", "5")
                
                # Determine file type category
                image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
                audio_exts = ['mp3', 'wav', 'ogg', 'aac', 'm4a']
                video_exts = ['mp4', 'avi', 'mov', 'webm', 'mkv']
                
                # Progress tracking varies by conversion type
                if source_ext in image_exts and (target_format in image_exts or target_format == 'pdf'):
                    await redis_client.hset(conversion_id, "progress", "20")
                    result_path = self.convert_image_format(str(source_path), str(output_path), target_format)
                    await redis_client.hset(conversion_id, "progress", "90")
                    
                elif source_ext in ['pdf', 'docx', 'txt'] or target_format in ['pdf', 'docx', 'txt']:
                    await redis_client.hset(conversion_id, "progress", "25")
                    result_path = self.convert_document_format(str(source_path), str(output_path), source_ext, target_format)
                    await redis_client.hset(conversion_id, "progress", "85")
                    
                elif source_ext in audio_exts and target_format in audio_exts:
                    await redis_client.hset(conversion_id, "progress", "15")
                    
                    async def audio_progress():
                        for i in [30, 50, 70]:
                            await asyncio.sleep(0.5)
                            await redis_client.hset(conversion_id, "progress", str(i))
                    
                    progress_task = asyncio.create_task(audio_progress())
                    result_path = self.convert_audio_format(str(source_path), str(output_path), target_format)
                    await progress_task
                    await redis_client.hset(conversion_id, "progress", "90")
                    
                elif source_ext in video_exts and (target_format in video_exts or target_format in audio_exts):
                    await redis_client.hset(conversion_id, "progress", "10")
                    
                    async def video_progress():
                        for i in [25, 40, 55, 70, 85]:
                            await asyncio.sleep(1.0)
                            await redis_client.hset(conversion_id, "progress", str(i))
                    
                    progress_task = asyncio.create_task(video_progress())
                    result_path = self.convert_video_format(str(source_path), str(output_path), target_format)
                    await progress_task
                    await redis_client.hset(conversion_id, "progress", "95")
                    
                else:
                    raise Exception(f"Conversion {source_ext} → {target_format} not supported")
                
                # Finalization (95-100%)
                await redis_client.hset(conversion_id, "progress", "95")
                
                converted_size = output_path.stat().st_size
                
                # Generate thumbnail if it's an image
                thumbnail_url = None
                if target_file_type == 'image':
                    try:
                        thumbnail_url = await self.generate_thumbnail(output_path, converted_id, target_format)
                    except Exception as thumb_err:
                        logger.warning(f"⚠️ Thumbnail generation failed: {thumb_err}")
                
                await redis_client.hset(conversion_id, "progress", "98")
                
                # ✅ FIX 2: Correct URL construction
                file_url = f"/api/uploads/{target_subdir_name}/{converted_id}.{target_format}"
                
                # Save converted file metadata
                converted_meta = {
                    "id": converted_id,
                    "user_id": user_id,
                    "filename": f"{file_meta['filename'].rsplit('.', 1)[0]}.{target_format}",
                    "file_type": target_file_type,
                    "extension": target_format,
                    "size": str(converted_size),
                    "path": str(output_path.absolute()),
                    "url": file_url,
                    "uploaded_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "original_file_id": file_id
                }
                
                if thumbnail_url:
                    converted_meta["thumbnail_url"] = thumbnail_url
                
                # Save to Redis
                await redis_client.hset(f"file:{converted_id}", mapping=converted_meta)
                await redis_client.sadd(f"user_files:{user_id}", converted_id)
                
                # Save to Firestore
                if self.db:
                    try:
                        firestore_doc = {
                            **converted_meta,
                            "size": converted_size,
                            "uploaded_at": firestore.SERVER_TIMESTAMP
                        }
                        self.db.collection('files').document(converted_id).set(firestore_doc)
                        logger.info(f"✅ Converted file saved to Firestore: {converted_id}")
                    except Exception as fb_err:
                        logger.error(f"Firestore save failed: {fb_err}")
                
                # Mark conversion as complete
                await redis_client.hset(conversion_id, mapping={
                    "status": "completed",
                    "progress": "100",
                    "completed_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "converted_file_id": converted_id
                })
                
                logger.info(f"✅ File converted: {file_id} → {converted_id} ({source_ext} → {target_format})")
                logger.info(f"✅ Converted file path: {output_path}")
                logger.info(f"✅ Converted file URL: {file_url}")
                
                return web.json_response({
                    "success": True,
                    "conversion_id": conversion_id,
                    "converted_file": {
                        "id": converted_id,
                        "filename": converted_meta['filename'],
                        "type": target_file_type,
                        "size": converted_size,
                        "url": file_url,
                        "thumbnail_url": thumbnail_url
                    }
                })
                
            except subprocess.CalledProcessError as ffmpeg_err:
                await redis_client.hset(conversion_id, mapping={
                    "status": "failed",
                    "error": f"Conversion tool error: {str(ffmpeg_err.stderr[:200])}"
                })
                logger.error(f"Conversion tool error: {ffmpeg_err}")
                return web.json_response({
                    "error": "File conversion failed. The file may be corrupted or in an unsupported format."
                }, status=500)
                
            except Exception as conv_err:
                await redis_client.hset(conversion_id, mapping={
                    "status": "failed",
                    "error": str(conv_err)
                })
                logger.error(f"Conversion error: {conv_err}", exc_info=True)
                return web.json_response({
                    "error": f"Conversion failed: {str(conv_err)}"
                }, status=500)
                
        except Exception as e:
            logger.error(f"Convert file error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)
            
    # Add this method to your server class
    async def get_conversion_progress(self, request):
        """Get real-time conversion progress"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)
                
            conversion_id = request.match_info['conversion_id']
                
            conversion_data = await redis_client.hgetall(conversion_id)
                
            if not conversion_data:
                return web.json_response({"error": "Conversion not found"}, status=404)
                
            return web.json_response({
                "status": conversion_data.get('status', 'unknown'),
                "progress": int(conversion_data.get('progress', 0)),
                "error": conversion_data.get('error'),
                "converted_file_id": conversion_data.get('converted_file_id')
            })
                
        except Exception as e:
            logger.error(f"Get progress error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_conversion_formats(self, request):
        """Get supported conversion formats for a file extension"""
        try:
            file_extension = request.query.get('ext', '').lower()
            
            if not file_extension:
                # Return general categories if no specific extension provided
                return web.json_response({
                    "image": ["png", "jpg", "jpeg", "webp", "pdf", "bmp", "gif", "tiff", "ico"],
                    "document": ["pdf", "docx", "doc", "txt", "html", "md", "rtf", "pptx", "xlsx", "csv"],
                    "audio": ["mp3", "wav", "ogg", "aac", "flac", "m4a", "opus"],
                    "video": ["mp4", "webm", "avi", "mov", "mkv", "flv", "wmv", "gif"]
                })
            
            # Get specific formats for the given extension
            formats = self.get_supported_conversions(file_extension)
            return web.json_response({"formats": formats})
        except Exception as e:
            logger.error(f"Error getting conversion formats: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def serve_upload(self, request):
        """Serve uploaded files with optional token-based auth fallback."""
        try:
            filename = request.match_info.get('filename', '')
            if not filename:
                return web.json_response({"error": "Not found"}, status=404)

            # Token-based auth fallback: ?token=<jwt> 
            token = request.query.get('token', '')
            user_id = None
            if token:
                try:
                    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
                    user_id = payload.get('user_id')
                except Exception:
                    pass

            # If no token, try Authorization header
            if not user_id:
                user_id = await self.get_user_from_token(request)

            # If authenticated via either method, try to authorize the file access
            if user_id:
                try:
                    file_path = _resolve_safe_path(UPLOAD_DIR, UPLOAD_DIR / filename)
                except ValueError:
                    return web.json_response({"error": "Not found"}, status=404)
                if file_path.exists():
                    return web.FileResponse(file_path)

            # Fall through to static dir for unauthenticated access (backward compat)
            # but _resolve_safe_path validates path safety
            try:
                fallback_path = _resolve_safe_path(UPLOAD_DIR, UPLOAD_DIR / filename)
            except ValueError:
                return web.json_response({"error": "Not found"}, status=404)

            if fallback_path.exists():
                return web.FileResponse(fallback_path)
            return web.json_response({"error": "Not found"}, status=404)
        except Exception as e:
            logger.error(f"Serve upload error: {e}")
            return web.json_response({"error": "Not found"}, status=404)

    async def get_file(self, request):
        """Get uploaded file"""
        try:
            file_id = request.match_info['file_id']
            
            file_meta = await redis_client.hgetall(f"file:{file_id}")
            
            if not file_meta:
                return web.json_response({"error": "File not found"}, status=404)

            try:
                file_path = _resolve_safe_path(UPLOAD_DIR, file_meta['path'])
            except ValueError as e:
                logger.error(f"❌ Blocked path traversal in get_file: {e}")
                return web.json_response({"error": "Invalid file path"}, status=400)

            if not file_path.exists():
                return web.json_response({"error": "File not found"}, status=404)

            return web.FileResponse(
                file_path,
                headers={'Content-Disposition': f'inline; filename="{file_meta.get("filename", "file")}"'}
            )

        except Exception as e:
            logger.error(f"Get file error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_thumbnail(self, request):
        """Get file thumbnail"""
        try:
            file_id = request.match_info['file_id']
            
            file_meta = await redis_client.hgetall(f"file:{file_id}")
            
            if not file_meta or not file_meta.get('thumbnail_url'):
                return web.json_response({"error": "Thumbnail not found"}, status=404)

            # Construct thumbnail path from file_id and validate it's within UPLOAD_DIR/thumbnails
            thumb_relative = Path('thumbnails') / f"{file_id}_thumb.jpg"
            try:
                thumb_path = _resolve_safe_path(UPLOAD_DIR, UPLOAD_DIR / thumb_relative)
            except ValueError as e:
                logger.error(f"❌ Blocked path traversal in get_thumbnail: {e}")
                return web.json_response({"error": "Invalid thumbnail path"}, status=400)

            if not thumb_path.exists():
                return web.json_response({"error": "Thumbnail not found"}, status=404)

            return web.FileResponse(thumb_path)

        except Exception as e:
            logger.error(f"Get thumbnail error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    def get_file_type(self, extension: str) -> Optional[str]:
        """Determine file type from extension"""
        extension = extension.lower().strip()
        
        for file_type, extensions in ALLOWED_EXTENSIONS.items():
            if extension in extensions:
                return file_type
        
        # Return 'document' as fallback instead of None
        return 'document'

    async def generate_thumbnail(self, file_path: Path, file_id: str, ext: str) -> Optional[str]:
        """Generate thumbnail for image"""
        try:
            from PIL import Image
            
            img = Image.open(file_path)
            img.thumbnail((300, 300))
            
            thumbnail_dir = UPLOAD_DIR / 'thumbnails'
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            
            thumbnail_path = thumbnail_dir / f"{file_id}_thumb.jpg"
            img.save(thumbnail_path, "JPEG")
            
            return f"/api/uploads/thumbnails/{file_id}_thumb.jpg"
        except Exception as e:
            logger.error(f"Thumbnail generation error: {e}")
            return None

    # ==================== CALLS (WebRTC Signaling) ====================
    
    async def initiate_call(self, request):
        """Initiate voice/video call with blocking checks"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            recipient_id = data.get('recipient_id')
            call_type = data.get('type', 'audio')

            if not recipient_id:
                return web.json_response({"error": "Recipient required"}, status=400)

            # ✅ CRITICAL: Check if users have blocked each other
            caller_blocked_recipient = await redis_client.sismember(f"user_blocked:{user_id}", recipient_id)
            recipient_blocked_caller = await redis_client.sismember(f"user_blocked:{recipient_id}", user_id)
            
            if caller_blocked_recipient:
                logger.warning(f"⚠️ Call blocked: {user_id} has blocked {recipient_id}")
                return web.json_response({
                    "error": "Cannot call this user. You have blocked them."
                }, status=403)
            
            if recipient_blocked_caller:
                logger.warning(f"⚠️ Call blocked: {user_id} is blocked by {recipient_id}")
                return web.json_response({
                    "error": "Cannot call this user. They have blocked you."
                }, status=403)

            # Create call session
            call_id = str(uuid.uuid4())
            call_data = {
                "id": call_id,
                "caller_id": user_id,
                "recipient_id": recipient_id,
                "type": call_type,
                "status": "ringing",
                "started_at": datetime.datetime.now(datetime.UTC).isoformat()
            }

            active_calls[call_id] = call_data
            await redis_client.hset(f"call:{call_id}", mapping=call_data)
            await redis_client.setex(f"active_call:{call_id}", 300, "true")

            # Get caller info
            caller_data = await redis_client.hgetall(f"user:{user_id}")

            # Notify recipient
            await self.broadcast_to_users(
                [recipient_id],
                {
                    "type": "incoming_call",
                    "call": {
                        **call_data,
                        "caller_name": caller_data.get('username'),
                        "caller_avatar": caller_data.get('avatar_url')
                    }
                }
            )

            logger.info(f"📞 Call initiated: {call_id} ({call_type})")

            # ✅ Fetch dynamic TURN credentials from Metered.ca
            ice_servers = []
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        'https://chatcentral.metered.live/api/v1/turn/credentials?apiKey=e39874b8e274c80c452f27c6eb1622a856b8'
                    ) as resp:
                        if resp.status == 200:
                            ice_servers = await resp.json()
                            logger.info(f"✅ Fetched {len(ice_servers)} TURN servers from Metered.ca")
                        else:
                            raise Exception(f"HTTP {resp.status}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to fetch TURN credentials: {e}, using fallback")

            # Return with ICE server configuration
            return web.json_response({
                "success": True,
                "call_id": call_id,
                "ice_servers": [
                    # Google STUN
                    { 'urls': 'stun:stun.l.google.com:19302' },
                    { 'urls': 'stun:stun1.l.google.com:19302' },
                    
                    # OpenRelay TURN (Free)
                    {
                        'urls': 'turn:openrelay.metered.ca:80',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    },
                    {
                        'urls': 'turn:openrelay.metered.ca:443',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    },
                    {
                        'urls': 'turn:openrelay.metered.ca:443?transport=tcp',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    }
                ]
            })

        except Exception as e:
            logger.error(f"Initiate call error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_call_signal(self, request):
        """Handle WebRTC signaling with GUARANTEED storage"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            call_id = request.match_info['call_id']
            data = await request.json()
            signal_type = data.get('signal_type')
            signal_data = data.get('signal_data')

            logger.info(f"📞 Received {signal_type} for call {call_id} from user {user_id}")

            if not signal_type:
                return web.json_response({"error": "Signal type required"}, status=400)

            # Get call info
            call_data = await redis_client.hgetall(f"call:{call_id}")
            
            if not call_data:
                logger.error(f"❌ Call {call_id} not found in Redis")
                return web.json_response({"error": "Call not found"}, status=404)

            # Determine recipient
            recipient_id = (
                call_data['recipient_id'] 
                if user_id == call_data['caller_id'] 
                else call_data['caller_id']
            )

            # **CRITICAL FIX: Store signal with DOUBLE CONFIRMATION**
            if signal_type in ['offer', 'answer']:
                signal_key = f"call_signal:{call_id}:{signal_type}"
                signal_json = json.dumps(signal_data)
                
                # Store with pipeline for atomic operation
                pipe = redis_client.pipeline()
                pipe.set(signal_key, signal_json, ex=600)
                pipe.get(signal_key)  # Verify immediately
                results = await pipe.execute()
                
                if not results[1]:
                    logger.error(f"❌ Failed to store {signal_type} - verification failed")
                    return web.json_response({"error": "Storage failed"}, status=500)
                
                logger.info(f"✅ Stored and verified {signal_type} for call {call_id}")
                
                # **NEW: Extra delay for mobile networks**
                await asyncio.sleep(0.1)  # 100ms to ensure Redis persistence

            # Forward to recipient via WebSocket
            signal_type_map = {
                'offer': 'call_offer',
                'answer': 'call_answer',
                'ice_candidate': 'ice_candidate'
            }

            await self.broadcast_to_users(
                [recipient_id],
                {
                    "type": signal_type_map.get(signal_type, signal_type),
                    "call_id": call_id,
                    "signal_data": signal_data,
                    "from_user": user_id
                }
            )
            
            logger.info(f"✅ Forwarded {signal_type} to user {recipient_id}")

            # Update call status
            if signal_type == 'answer':
                await redis_client.hset(f"call:{call_id}", "status", "active")
                if call_id in active_calls:
                    active_calls[call_id]['status'] = "active"

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"❌ Call signal handler error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_call_signals(self, request):
        """Retrieve stored call signals with AGGRESSIVE retry logic"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            call_id = request.match_info['call_id']
            
            logger.info(f"📥 Fetching signals for call {call_id} by user {user_id}")
            
            # Check if user is part of the call
            call_data = await redis_client.hgetall(f"call:{call_id}")
            if not call_data:
                return web.json_response({"error": "Call not found"}, status=404)
                
            if user_id not in [call_data.get('caller_id'), call_data.get('recipient_id')]:
                return web.json_response({"error": "Forbidden"}, status=403)
            
            signals = {}
            
            # **CRITICAL: Retry up to 20 times with exponential backoff**
            for attempt in range(20):
                offer_json = await redis_client.get(f"call_signal:{call_id}:offer")
                if offer_json:
                    try:
                        signals['offer'] = json.loads(offer_json)
                        logger.info(f"✅ Retrieved offer (attempt {attempt + 1})")
                        break
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Invalid offer JSON: {e}")
                else:
                    if attempt < 19:
                        # Exponential backoff: 100ms, 150ms, 225ms, 337ms, 500ms...
                        delay = min(0.1 * (1.5 ** attempt), 1.0)
                        logger.warning(f"⏳ Offer not ready, waiting {int(delay*1000)}ms (attempt {attempt + 1}/20)")
                        await asyncio.sleep(delay)
            
            if not signals.get('offer'):
                logger.error(f"❌ Could not retrieve offer after 20 attempts")
                return web.json_response({"error": "Offer not available"}, status=404)
            
            # Get answer (might not exist yet)
            answer_json = await redis_client.get(f"call_signal:{call_id}:answer")
            if answer_json:
                try:
                    signals['answer'] = json.loads(answer_json)
                except json.JSONDecodeError:
                    pass
            
            return web.json_response({"success": True, "signals": signals})
            
        except Exception as e:
            logger.error(f"❌ Get call signals error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def end_call(self, request):
        """End active call"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            call_id = request.match_info['call_id']
            
            call_data = await redis_client.hgetall(f"call:{call_id}")
            if not call_data:
                return web.json_response({"error": "Call not found"}, status=404)

            # Calculate duration
            started_at = datetime.datetime.fromisoformat(call_data.get('started_at'))
            duration = int((datetime.datetime.now(datetime.UTC) - started_at).total_seconds())

            # Update call status
            await redis_client.hset(f"call:{call_id}", mapping={
                "status": "ended",
                "ended_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "duration": str(duration)
            })

            # Remove from active calls
            if call_id in active_calls:
                del active_calls[call_id]

            # Notify other party
            other_user_id = (
                call_data['recipient_id'] 
                if user_id == call_data['caller_id'] 
                else call_data['caller_id']
            )

            await self.broadcast_to_users(
                [other_user_id],
                {
                    "type": "call_ended",
                    "call_id": call_id,
                    "duration": duration
                }
            )

            logger.info(f"📞 Call ended: {call_id} (duration: {duration}s)")

            return web.json_response({
                "success": True,
                "duration": duration
            })

        except Exception as e:
            logger.error(f"End call error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_call_history(self, request):
        """Get call history"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            # Get all calls where user is caller or recipient
            all_call_ids = await redis_client.keys("call:*")
            calls_list = []

            for call_key in all_call_ids:
                call_data = await redis_client.hgetall(call_key)
                
                if not call_data:
                    continue

                if call_data.get('caller_id') == user_id or call_data.get('recipient_id') == user_id:
                    # Get other user info
                    other_user_id = (
                        call_data['recipient_id'] 
                        if user_id == call_data['caller_id'] 
                        else call_data['caller_id']
                    )
                    
                    other_user = await redis_client.hgetall(f"user:{other_user_id}")

                    calls_list.append({
                        "id": call_data.get('id'),
                        "type": call_data.get('type'),
                        "status": call_data.get('status'),
                        "duration": int(call_data.get('duration', 0)),
                        "started_at": call_data.get('started_at'),
                        "ended_at": call_data.get('ended_at'),
                        "is_outgoing": call_data.get('caller_id') == user_id,
                        "other_user": {
                            "id": other_user_id,
                            "username": other_user.get('username'),
                            "avatar_url": other_user.get('avatar_url')
                        }
                    })

            # Sort by started_at descending
            calls_list.sort(key=lambda x: x.get('started_at', ''), reverse=True)

            return web.json_response({"calls": calls_list[:50]})  # Last 50 calls

        except Exception as e:
            logger.error(f"Get call history error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # ==================== GROUP CALL ENDPOINTS ====================

    async def initiate_group_call(self, request):
        """Initiate a group audio/video call"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            group_id = data.get('group_id')
            call_type = data.get('type', 'audio')  # 'audio' or 'video'

            if not group_id:
                return web.json_response({"error": "Group ID required"}, status=400)

            # Verify user is a member of the group
            is_member = await redis_client.sismember(f"chat_members:{group_id}", user_id)
            if not is_member:
                return web.json_response({"error": "Not a member of this group"}, status=403)

            # Get all group members
            member_ids = await redis_client.smembers(f"chat_members:{group_id}")
            
            if len(member_ids) < 2:
                return web.json_response({"error": "Group must have at least 2 members"}, status=400)

            # Create group call session
            call_id = str(uuid.uuid4())
            call_data = {
                "id": call_id,
                "group_id": group_id,
                "initiator_id": user_id,
                "type": call_type,
                "status": "active",
                "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "participants": json.dumps({user_id: "active"})  # Store as JSON string
            }

            # Store in Redis
            await redis_client.hset(f"group_call:{call_id}", mapping=call_data)
            await redis_client.setex(f"active_group_call:{call_id}", 3600, "true")  # 1 hour expiry
            
            # Store in memory
            active_group_calls[call_id] = {
                "id": call_id,
                "group_id": group_id,
                "initiator_id": user_id,
                "type": call_type,
                "status": "active",
                "started_at": call_data["started_at"],
                "participants": {user_id: "active"}
            }

            # Get initiator info
            initiator_data = await redis_client.hgetall(f"user:{user_id}")
            group_data = await redis_client.hgetall(f"chat:{group_id}")

            # Notify all group members
            await self.broadcast_to_users(
                list(member_ids),
                {
                    "type": "group_call_started",
                    "call_id": call_id,
                    "group_id": group_id,
                    "group_name": group_data.get('name', 'Group'),
                    "call_type": call_type,
                    "initiator": {
                        "id": user_id,
                        "username": initiator_data.get('username'),
                        "avatar_url": initiator_data.get('avatar_url')
                    }
                }
            )

            logger.info(f"📞 Group call initiated: {call_id} in group {group_id} ({call_type})")

            # Return ICE servers configuration
            return web.json_response({
                "success": True,
                "call_id": call_id,
                "group_id": group_id,
                "ice_servers": [
                    {'urls': 'stun:stun.l.google.com:19302'},
                    {'urls': 'stun:stun1.l.google.com:19302'},
                    {
                        'urls': 'turn:openrelay.metered.ca:80',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    },
                    {
                        'urls': 'turn:openrelay.metered.ca:443',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    },
                    {
                        'urls': 'turn:openrelay.metered.ca:443?transport=tcp',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    }
                ]
            })

        except Exception as e:
            logger.error(f"Initiate group call error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def join_group_call(self, request):
        """Join an active group call"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            call_id = request.match_info['call_id']
            
            # Get call data
            call_data = await redis_client.hgetall(f"group_call:{call_id}")
            if not call_data:
                return web.json_response({"error": "Call not found"}, status=404)

            group_id = call_data.get('group_id')
            
            # Verify user is a member of the group
            is_member = await redis_client.sismember(f"chat_members:{group_id}", user_id)
            if not is_member:
                return web.json_response({"error": "Not a member of this group"}, status=403)

            # Add user to participants
            participants = json.loads(call_data.get('participants', '{}'))
            participants[user_id] = "active"
            
            # Update Redis
            await redis_client.hset(f"group_call:{call_id}", "participants", json.dumps(participants))
            
            # Update memory
            if call_id in active_group_calls:
                active_group_calls[call_id]['participants'][user_id] = "active"

            # Get user info
            user_data = await redis_client.hgetall(f"user:{user_id}")

            # Notify all participants that a new user joined
            participant_ids = list(participants.keys())
            await self.broadcast_to_users(
                [pid for pid in participant_ids if pid != user_id],
                {
                    "type": "group_call_participant_joined",
                    "call_id": call_id,
                    "user": {
                        "id": user_id,
                        "username": user_data.get('username'),
                        "avatar_url": user_data.get('avatar_url')
                    }
                }
            )

            logger.info(f"📞 User {user_id} joined group call {call_id}")

            # Return current participants and ICE servers
            participants_info = []
            for participant_id in participant_ids:
                if participant_id != user_id:
                    p_data = await redis_client.hgetall(f"user:{participant_id}")
                    participants_info.append({
                        "id": participant_id,
                        "username": p_data.get('username'),
                        "avatar_url": p_data.get('avatar_url'),
                        "status": participants.get(participant_id, "active")
                    })

            return web.json_response({
                "success": True,
                "call_id": call_id,
                "participants": participants_info,
                "ice_servers": [
                    {'urls': 'stun:stun.l.google.com:19302'},
                    {'urls': 'stun:stun1.l.google.com:19302'},
                    {
                        'urls': 'turn:openrelay.metered.ca:80',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    },
                    {
                        'urls': 'turn:openrelay.metered.ca:443',
                        'username': 'openrelayproject',
                        'credential': 'openrelayproject'
                    }
                ]
            })

        except Exception as e:
            logger.error(f"Join group call error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def leave_group_call(self, request):
        """Leave a group call"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            call_id = request.match_info['call_id']
            
            # Get call data
            call_data = await redis_client.hgetall(f"group_call:{call_id}")
            if not call_data:
                return web.json_response({"error": "Call not found"}, status=404)

            # Remove user from participants
            participants = json.loads(call_data.get('participants', '{}'))
            if user_id in participants:
                del participants[user_id]

            # If no participants left, end the call
            if not participants:
                await redis_client.hset(f"group_call:{call_id}", mapping={
                    "status": "ended",
                    "ended_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "participants": json.dumps({})
                })
                
                if call_id in active_group_calls:
                    del active_group_calls[call_id]
                
                logger.info(f"📞 Group call {call_id} ended - no participants left")
            else:
                # Update participants
                await redis_client.hset(f"group_call:{call_id}", "participants", json.dumps(participants))
                
                if call_id in active_group_calls:
                    if user_id in active_group_calls[call_id]['participants']:
                        del active_group_calls[call_id]['participants'][user_id]

                # Notify remaining participants
                await self.broadcast_to_users(
                    list(participants.keys()),
                    {
                        "type": "group_call_participant_left",
                        "call_id": call_id,
                        "user_id": user_id
                    }
                )

            logger.info(f"📞 User {user_id} left group call {call_id}")

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Leave group call error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_group_call_participants(self, request):
        """Get current participants in a group call"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            call_id = request.match_info['call_id']
            
            # Get call data
            call_data = await redis_client.hgetall(f"group_call:{call_id}")
            if not call_data:
                return web.json_response({"error": "Call not found"}, status=404)

            participants = json.loads(call_data.get('participants', '{}'))
            
            # Get participant info
            participants_info = []
            for participant_id, status in participants.items():
                p_data = await redis_client.hgetall(f"user:{participant_id}")
                participants_info.append({
                    "id": participant_id,
                    "username": p_data.get('username'),
                    "avatar_url": p_data.get('avatar_url'),
                    "status": status
                })

            return web.json_response({
                "success": True,
                "participants": participants_info
            })

        except Exception as e:
            logger.error(f"Get group call participants error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    # ==================== WEBSOCKET HANDLER ====================
    
    async def websocket_handler(self, request):
        """Enhanced WebSocket handler with call signaling and blocking checks"""
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        user_id = None

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    if data.get('type') == 'auth':
                        token = data.get('token')
                        try:
                            payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
                            user_id = payload['user_id']
                            
                            if user_id not in active_connections:
                                active_connections[user_id] = set()
                            active_connections[user_id].add(ws)
                            
                            # Update status
                            await redis_client.hset(f"user:{user_id}", "status", "online")
                            
                            await ws.send_json({
                                "type": "auth_success",
                                "message": "Connected"
                            })
                            
                            await self.broadcast_user_status(user_id, "online")
                            logger.info(f"🔌 WebSocket connected: {user_id}")
                            
                        except jwt.ExpiredSignatureError:
                            await ws.send_json({"type": "error", "message": "Token expired"})
                            await ws.close()
                            break
                        except jwt.InvalidTokenError:
                            await ws.send_json({"type": "error", "message": "Invalid token"})
                            await ws.close()
                            break
                    
                    elif user_id:
                        # Handle message with blocking checks
                        if data.get('type') == 'message':
                            chat_id = data.get('chat_id')
                            
                            if not chat_id:
                                logger.warning("No chat_id provided")
                                continue
                            
                            # Check if user is member
                            is_member = await redis_client.sismember(f"chat_members:{chat_id}", user_id)
                            if not is_member:
                                await ws.send_json({
                                    "type": "error",
                                    "message": "Not a member of this chat"
                                })
                                continue
                            
                            # Get chat data
                            chat_data = await redis_client.hgetall(f"chat:{chat_id}")
                            
                            # **BLOCKING CHECK FOR DIRECT CHATS**
                            if chat_data.get('type') == 'direct':
                                member_ids = await redis_client.smembers(f"chat_members:{chat_id}")
                                other_user_id = next((m for m in member_ids if m != user_id), None)
                                
                                if other_user_id:
                                    # Check if current user has blocked the other
                                    is_blocked_by_me = await redis_client.sismember(f"user_blocked:{user_id}", other_user_id)
                                    
                                    # Check if current user is blocked by the other
                                    is_blocked_by_them = await redis_client.sismember(f"user_blocked:{other_user_id}", user_id)
                                    
                                    if is_blocked_by_me:
                                        await ws.send_json({
                                            "type": "error",
                                            "message": "You have blocked this user. Unblock them to send messages."
                                        })
                                        continue
                                    
                                    if is_blocked_by_them:
                                        await ws.send_json({
                                            "type": "error",
                                            "message": "This user has blocked you. Cannot send messages."
                                        })
                                        continue
                            
                            # If all checks pass, handle the message
                            await self.handle_ws_message(user_id, data)
                        
                        elif data.get('type') == 'typing':
                            await self.broadcast_typing(user_id, data.get('chat_id'), data.get('is_typing'))
                        
                        elif data.get('type') == 'read_receipt':
                            await self.handle_read_receipt(user_id, data)
                        
                        # WebRTC signaling
                        elif data.get('type') in ['call_offer', 'call_answer', 'ice_candidate']:
                            await self.handle_ws_call_signal(user_id, data)
                        
                        # Group call signaling
                        elif data.get('type') == 'group_call_start':
                            await self.handle_group_call_start(user_id, data)
                        
                        elif data.get('type') == 'group_call_offer':
                            await self.handle_group_call_signal(user_id, data, 'offer')
                        
                        elif data.get('type') == 'group_call_answer':
                            await self.handle_group_call_signal(user_id, data, 'answer')
                        
                        elif data.get('type') == 'group_call_ice':
                            await self.handle_group_call_ice(user_id, data)
                        
                        elif data.get('type') == 'group_call_leave':
                            await self.handle_group_call_leave_ws(user_id, data)
                        
                        elif data.get('type') == 'ping':
                            await ws.send_json({"type": "pong"})
                
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")

        except Exception as e:
            logger.error(f"WebSocket handler error: {e}", exc_info=True)
        
        finally:
            if user_id:
                if user_id in active_connections:
                    active_connections[user_id].discard(ws)
                    if not active_connections[user_id]:
                        del active_connections[user_id]
                        
                        # Update status
                        await redis_client.hset(f"user:{user_id}", mapping={
                            "status": "offline",
                            "last_seen": datetime.datetime.now(datetime.UTC).isoformat()
                        })
                        
                        await self.broadcast_user_status(user_id, "offline")
                
                logger.info(f"🔌 Disconnected: {user_id}")

        return ws

    async def handle_ws_call_signal(self, user_id: str, data: dict):
        """Handle WebRTC signaling via WebSocket"""
        try:
            signal_type = data.get('type')
            call_id = data.get('call_id')
            signal_data = data.get('signal_data')
            
            logger.info(f"📞 WS Call signal: {signal_type} for call {call_id}")
            
            if not call_id:
                logger.error("No call_id in signal")
                return
            
            # Get call info
            call_data = await redis_client.hgetall(f"call:{call_id}")
            
            if not call_data:
                logger.error(f"Call {call_id} not found")
                return
            
            # Determine recipient
            if user_id == call_data.get('caller_id'):
                recipient_id = call_data.get('recipient_id')
            elif user_id == call_data.get('recipient_id'):
                recipient_id = call_data.get('caller_id')
            else:
                logger.error(f"User {user_id} not part of call {call_id}")
                return
            
            logger.info(f"📤 Forwarding {signal_type} from {user_id} to {recipient_id}")
            
            # Forward the signal to the other party
            await self.broadcast_to_users(
                [recipient_id],
                {
                    "type": signal_type,  # call_offer, call_answer, ice_candidate
                    "call_id": call_id,
                    "signal_data": signal_data
                }
            )
            
            # Update call status for answers
            if signal_type == 'call_answer':
                await redis_client.hset(f"call:{call_id}", "status", "active")
                logger.info(f"✅ Call {call_id} now active")
            
        except Exception as e:
            logger.error(f"❌ WS call signal error: {e}", exc_info=True)

    async def handle_group_call_start(self, user_id: str, data: dict):
        """Handle group call start via WebSocket"""
        try:
            group_id = data.get('group_id')
            call_type = data.get('call_type', 'audio')
            
            logger.info(f"📞 Group call start: user={user_id}, group={group_id}, type={call_type}")
            
            if not group_id:
                logger.error("No group_id in group call start")
                return
            
            # Verify user is a member
            is_member = await redis_client.sismember(f"chat_members:{group_id}", user_id)
            if not is_member:
                logger.error(f"User {user_id} not a member of group {group_id}")
                return
            
            # Get all group members
            member_ids = await redis_client.smembers(f"chat_members:{group_id}")
            
            # Create group call (similar to REST endpoint)
            call_id = str(uuid.uuid4())
            call_data = {
                "id": call_id,
                "group_id": group_id,
                "initiator_id": user_id,
                "type": call_type,
                "status": "active",
                "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "participants": json.dumps({user_id: "active"})
            }
            
            await redis_client.hset(f"group_call:{call_id}", mapping=call_data)
            await redis_client.setex(f"active_group_call:{call_id}", 3600, "true")
            
            active_group_calls[call_id] = {
                "id": call_id,
                "group_id": group_id,
                "initiator_id": user_id,
                "type": call_type,
                "status": "active",
                "started_at": call_data["started_at"],
                "participants": {user_id: "active"}
            }
            
            # Get initiator and group info
            initiator_data = await redis_client.hgetall(f"user:{user_id}")
            group_data = await redis_client.hgetall(f"chat:{group_id}")
            
            # Notify all group members
            await self.broadcast_to_users(
                list(member_ids),
                {
                    "type": "group_call_started",
                    "call_id": call_id,
                    "group_id": group_id,
                    "group_name": group_data.get('name', 'Group'),
                    "call_type": call_type,
                    "initiator": {
                        "id": user_id,
                        "username": initiator_data.get('username'),
                        "avatar_url": initiator_data.get('avatar_url')
                    }
                }
            )
            
            logger.info(f"✅ Group call {call_id} started successfully")
            
        except Exception as e:
            logger.error(f"❌ Group call start error: {e}", exc_info=True)

    async def handle_group_call_signal(self, user_id: str, data: dict, signal_type: str):
        """Handle group call WebRTC offer/answer signaling"""
        try:
            call_id = data.get('call_id')
            target_user = data.get('target_user')
            signal_data = data.get('signal_data')
            
            logger.info(f"📞 Group call {signal_type}: from={user_id}, to={target_user}, call={call_id}")
            
            if not all([call_id, target_user, signal_data]):
                logger.error("Missing required fields for group call signal")
                return
            
            # Verify call exists
            call_data = await redis_client.hgetall(f"group_call:{call_id}")
            if not call_data:
                logger.error(f"Group call {call_id} not found")
                return
            
            # Verify both users are participants
            participants = json.loads(call_data.get('participants', '{}'))
            if user_id not in participants or target_user not in participants:
                logger.error(f"Users not in call participants")
                return
            
            # Forward signal to target user
            await self.broadcast_to_users(
                [target_user],
                {
                    "type": f"group_call_{signal_type}",
                    "call_id": call_id,
                    "from_user": user_id,
                    "signal_data": signal_data
                }
            )
            
            logger.info(f"✅ Forwarded {signal_type} to {target_user}")
            
        except Exception as e:
            logger.error(f"❌ Group call signal error: {e}", exc_info=True)

    async def handle_group_call_ice(self, user_id: str, data: dict):
        """Handle group call ICE candidate exchange"""
        try:
            call_id = data.get('call_id')
            target_user = data.get('target_user')
            candidate = data.get('candidate')
            
            if not all([call_id, target_user, candidate]):
                logger.error("Missing required fields for ICE candidate")
                return
            
            # Verify call exists
            call_data = await redis_client.hgetall(f"group_call:{call_id}")
            if not call_data:
                return
            
            # Forward ICE candidate to target user
            await self.broadcast_to_users(
                [target_user],
                {
                    "type": "group_call_ice",
                    "call_id": call_id,
                    "from_user": user_id,
                    "candidate": candidate
                }
            )
            
            logger.debug(f"✅ Forwarded ICE candidate from {user_id} to {target_user}")
            
        except Exception as e:
            logger.error(f"❌ Group call ICE error: {e}", exc_info=True)

    async def handle_group_call_leave_ws(self, user_id: str, data: dict):
        """Handle user leaving group call via WebSocket"""
        try:
            call_id = data.get('call_id')
            
            if not call_id:
                logger.error("No call_id in leave request")
                return
            
            call_data = await redis_client.hgetall(f"group_call:{call_id}")
            if not call_data:
                return
            
            # Remove user from participants
            participants = json.loads(call_data.get('participants', '{}'))
            if user_id in participants:
                del participants[user_id]
            
            # If no participants left, end the call
            if not participants:
                await redis_client.hset(f"group_call:{call_id}", mapping={
                    "status": "ended",
                    "ended_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "participants": json.dumps({})
                })
                
                if call_id in active_group_calls:
                    del active_group_calls[call_id]
                
                logger.info(f"📞 Group call {call_id} ended - no participants")
            else:
                # Update participants
                await redis_client.hset(f"group_call:{call_id}", "participants", json.dumps(participants))
                
                if call_id in active_group_calls:
                    if user_id in active_group_calls[call_id]['participants']:
                        del active_group_calls[call_id]['participants'][user_id]
                
                # Notify remaining participants
                await self.broadcast_to_users(
                    list(participants.keys()),
                    {
                        "type": "group_call_participant_left",
                        "call_id": call_id,
                        "user_id": user_id
                    }
                )
            
            logger.info(f"📞 User {user_id} left group call {call_id}")
            
        except Exception as e:
            logger.error(f"❌ Group call leave error: {e}", exc_info=True)

    async def handle_ws_message(self, user_id: str, data: dict):
        """Handle WebSocket message - ENHANCED with blocking checks and reply_to"""
        try:
            chat_id = data.get('chat_id')
            content = data.get('content', '').strip()[:10000]
            message_type = data.get('message_type', 'text')
            encrypted = data.get('encrypted', True)
            reply_to = data.get('reply_to')  # ✅ CRITICAL: Extract reply_to from WebSocket data
            attachments = data.get('attachments', [])

            logger.info(f"📨 WS Message received: chat={chat_id}, type={message_type}, attachments={attachments}, reply_to={reply_to}")

            if not chat_id:
                logger.warning("No chat_id provided")
                return

            is_member = await redis_client.sismember(f"chat_members:{chat_id}", user_id)
            if not is_member:
                logger.warning(f"User {user_id} is not a member of chat {chat_id}")
                return

            # Check blocking for direct chats
            chat_data = await redis_client.hgetall(f"chat:{chat_id}")
            if chat_data.get('type') == 'direct':
                member_ids = await redis_client.smembers(f"chat_members:{chat_id}")
                other_user_id = next((m for m in member_ids if m != user_id), None)
                
                if other_user_id:
                    i_blocked_them = await redis_client.sismember(f"user_blocked:{user_id}", other_user_id)
                    they_blocked_me = await redis_client.sismember(f"user_blocked:{other_user_id}", user_id)
                    
                    if i_blocked_them:
                        logger.warning(f"⚠️ Message blocked: {user_id} has blocked {other_user_id}")
                        await self.broadcast_to_users([user_id], {
                            "type": "error",
                            "message": "You have blocked this user. Unblock them to send messages."
                        })
                        return
                    
                    if they_blocked_me:
                        logger.warning(f"⚠️ Message blocked: {user_id} is blocked by {other_user_id}")
                        await self.broadcast_to_users([user_id], {
                            "type": "error",
                            "message": "This user has blocked you. Cannot send messages."
                        })
                        return

            # ✅ CRITICAL FIX: Pass reply_to to create_message
            message_id = await self.create_message(
                chat_id=chat_id,
                sender_id=user_id,
                content=content,
                message_type=message_type,
                encrypted=encrypted,
                attachments=attachments,
                reply_to=reply_to  # ✅ THIS WAS MISSING!
            )

            logger.info(f"✅ WS Message created: {message_id} with {len(attachments)} attachments")

        except Exception as e:
            logger.error(f"❌ WS message error: {e}", exc_info=True)


    async def handle_read_receipt(self, user_id: str, data: dict):
        """Handle message read receipts"""
        try:
            message_ids = data.get('message_ids', [])
            chat_id = data.get('chat_id')

            if not message_ids or not chat_id:
                return

            # Mark messages as read
            for msg_id in message_ids:
                await redis_client.hset(f"message_read:{msg_id}", user_id, "true")

            # Notify sender
            for msg_id in message_ids:
                msg_data = await redis_client.hgetall(f"message:{msg_id}")
                sender_id = msg_data.get('sender_id')
                
                if sender_id and sender_id != user_id:
                    await self.broadcast_to_users(
                        [sender_id],
                        {
                            "type": "message_read",
                            "chat_id": chat_id,
                            "message_ids": message_ids,
                            "read_by": user_id
                        }
                    )

        except Exception as e:
            logger.error(f"Read receipt error: {e}")

    async def broadcast_user_status(self, user_id: str, status: str):
        """Broadcast user status to contacts"""
        try:
            # Get user's contacts
            contact_ids = await redis_client.smembers(f"user_contacts:{user_id}")

            if not contact_ids:
                return

            user_data = await redis_client.hgetall(f"user:{user_id}")

            await self.broadcast_to_users(
                list(contact_ids),
                {
                    "type": "user_status",
                    "user_id": user_id,
                    "status": status,
                    "last_seen": user_data.get('last_seen')
                }
            )

        except Exception as e:
            logger.error(f"Broadcast status error: {e}")

    async def broadcast_typing(self, user_id: str, chat_id: str, is_typing: bool):
        """Broadcast typing indicator"""
        try:
            # Typing cooldown: ignore repeats under 500ms
            now = datetime.datetime.now(datetime.UTC)
            last_key = f"typing_cooldown:{user_id}:{chat_id}"
            last_time = getattr(self, '_typing_cooldowns', {}).get(last_key)
            if last_time and (now - last_time).total_seconds() < 0.5:
                return
            if not hasattr(self, '_typing_cooldowns'):
                self._typing_cooldowns = {}
            self._typing_cooldowns[last_key] = now
            
            # Get chat members
            member_ids = await redis_client.smembers(f"chat_members:{chat_id}")
            member_ids = [m for m in member_ids if m != user_id]

            await self.broadcast_to_users(
                member_ids,
                {
                    "type": "typing",
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "is_typing": is_typing
                }
            )

        except Exception as e:
            logger.error(f"Broadcast typing error: {e}")

    async def broadcast_to_users(self, user_ids: List[str], message: dict):
        """Broadcast message to multiple users"""
        for user_id in user_ids:
            if user_id in active_connections:
                for ws in list(active_connections[user_id]):
                    try:
                        await ws.send_json(message)
                    except Exception as e:
                        logger.error(f"Broadcast error to {user_id}: {e}")
                        active_connections[user_id].discard(ws)

    # ==================== HEALTH CHECK ====================
    
    async def health_check(self, request):
        """Health check endpoint"""
        try:
            redis_status = "connected"
            try:
                await redis_client.ping()
            except:
                redis_status = "disconnected"

            return web.json_response({
                "status": "healthy",
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "active_connections": sum(len(conns) for conns in active_connections.values()),
                "active_calls": len(active_calls),
                "redis": redis_status,
                "firebase": "connected" if self.firebase_app else "disconnected"
            })

        except Exception as e:
            return web.json_response(
                {"status": "unhealthy", "error": str(e)},
                status=503
            )
            
    async def index(self, request):
        """API info endpoint"""
        return web.json_response({
            "service": "DecentralChat API",
            "version": "2.0.0",
            "features": [
                "Firebase Authentication",
                "WebRTC Voice/Video Calls",
                "File Uploads (images, videos, audio, documents)",
                "Voice Messages",
                "End-to-end Encryption",
                "Group Chats",
                "Decentralized Storage (Redis)",
                "Real-time WebSocket Communication",
                "Read Receipts",
                "Typing Indicators",
                "Call History"
            ],
            "status": "running",
            "websocket": f"ws://{request.host}/api/ws",
            "endpoints": {
                "auth": "/api/auth/*",
                "users": "/api/users/*",
                "contacts": "/api/contacts",
                "chats": "/api/chats/*",
                "messages": "/api/chats/{chat_id}/messages",
                "files": "/api/upload/*",
                "calls": "/api/calls/*",
                "websocket": "/api/ws",
                "health": "/health"
            }
        })

    async def handle_google_auth(self, request):
        """Handle Google OAuth authentication"""
        try:
            data = await request.json()
            email = data.get('email')
            name = data.get('name')
            picture = data.get('picture', '')
            google_id = data.get('google_id')
            
            if not email or not google_id:
                return web.json_response({"error": "Invalid Google data"}, status=400)
            
            logger.info(f"Google auth attempt for: {_log_safe(email)}, Google ID: {google_id[-8:] if len(google_id) > 8 else google_id}")
            
            # STEP 1: Check if user exists by Google ID first
            user_id = await redis_client.hget("google_id_map", google_id)
            
            if user_id:
                logger.info(f"Found existing user by Google ID: {user_id}")
                
                # Update avatar if it changed
                current_avatar = await redis_client.hget(f"user:{user_id}", "avatar_url")
                if current_avatar != picture:
                    await redis_client.hset(f"user:{user_id}", "avatar_url", picture)
                    
            else:
                # STEP 2: Check if user exists by email
                user_id = await redis_client.hget("email_map", email)
                
                if user_id:
                    # Link existing account to Google
                    logger.info(f"Linking existing email account to Google: {email}")
                    await redis_client.hset(f"user:{user_id}", "google_id", google_id)
                    await redis_client.hset(f"user:{user_id}", "auth_provider", "google")
                    await redis_client.hset(f"user:{user_id}", "avatar_url", picture)
                    await redis_client.hset("google_id_map", google_id, user_id)
                    
                else:
                    # STEP 3: Create new user only if neither Google ID nor email exists
                    user_id = str(uuid.uuid4())
                    
                    # Generate unique username from email
                    base_username = email.split('@')[0].lower().replace('.', '_').replace('-', '_')
                    username = base_username
                    
                    # Ensure username is unique
                    counter = 1
                    while await redis_client.hget("username_map", username):
                        username = f"{base_username}_{counter}"
                        counter += 1
                    
                    logger.info(f"Creating new Google user: {username}")
                    
                    user_data = {
                        "id": user_id,
                        "username": username,
                        "email": email,
                        "phone": "",
                        "google_id": google_id,
                        "avatar_url": picture,
                        "role": "user",
                        "status": "offline",
                        "bio": "",
                        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
                        "auth_provider": "google",
                        "password_hash": "",  # No password for Google accounts
                        "settings": json.dumps({
                            "notifications": True,
                            "read_receipts": True,
                            "typing_indicator": True,
                            "online_status": True
                        })
                    }
                    
                    await redis_client.hset(f"user:{user_id}", mapping=user_data)
                    await redis_client.sadd("users:all", user_id)
                    await redis_client.hset("google_id_map", google_id, user_id)
                    await redis_client.hset("email_map", email, user_id)
                    await redis_client.hset("username_map", username, user_id)
                    
                    # Save to Firestore if available
                    if self.db:
                        try:
                            self.db.collection('users').document(user_id).set({
                                'id': user_id,
                                'username': username,
                                'email': email,
                                'google_id': google_id,
                                'avatar_url': picture,
                                'phone': '',
                                'password_hash': '',
                                'role': 'user',
                                'status': 'offline',
                                'bio': '',
                                'created_at': firestore.SERVER_TIMESTAMP,
                                'auth_provider': 'google',
                                'settings': {
                                    "notifications": True,
                                    "read_receipts": True,
                                    "typing_indicator": True,
                                    "online_status": True
                                }
                            })
                        except Exception as fb_err:
                            logger.error(f"Firestore save failed: {fb_err}")
            
            # Generate JWT token
            jwt_token = self.generate_token(user_id)
            
            # Get complete user data
            user_data = await redis_client.hgetall(f"user:{user_id}")
            
            # Update status
            await redis_client.hset(f"user:{user_id}", mapping={
                "status": "online",
                "last_login": datetime.datetime.now(datetime.UTC).isoformat()
            })
            
            # Generate refresh token for Google auth
            refresh_token = self._generate_refresh_token(user_id, request.headers.get('User-Agent', '')[:128])

            logger.info(f"✅ Google Sign-In successful: {user_data.get('username')} (ID: {user_id})")
            
            return web.json_response({
                "success": True,
                "token": jwt_token,
                "refresh_token": refresh_token,
                "user": {
                    "id": user_id,
                    "username": user_data.get('username'),
                    "email": user_data.get('email'),
                    "avatar_url": user_data.get('avatar_url'),
                    "role": user_data.get('role'),
                    "bio": user_data.get('bio'),
                    "status": "online"
                }
            })
            
        except Exception as e:
            logger.error(f"Google auth error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)
    async def send_verification_code(self, request):
        """Send OTP for phone verification using Twilio"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            phone = data.get('phone', '').strip()

            if not phone:
                return web.json_response({"error": "Phone number required"}, status=400)

            # Normalize phone number (remove spaces)
            phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

            if not phone.startswith('+'):
                return web.json_response({"error": "Phone must include country code (e.g., +1234567890)"}, status=400)

            logger.info(f"📱 Normalized phone number: {_log_safe(phone)}")

            # Generate 6-digit OTP
            otp = ''.join(secrets.choice(string.digits) for _ in range(6))
            
            # Store OTP in Redis with 10-minute expiry
            await redis_client.setex(f"otp:{phone}", 600, otp)
            
            # ✅ DEBUG: Check if environment variables are loaded
            TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
            TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
            TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
            
            logger.info(f"🔍 TWILIO_ACCOUNT_SID exists: {bool(TWILIO_ACCOUNT_SID)}")
            logger.info(f"🔍 TWILIO_AUTH_TOKEN exists: {bool(TWILIO_AUTH_TOKEN)}")
            logger.info(f"🔍 TWILIO_PHONE_NUMBER exists: {bool(TWILIO_PHONE_NUMBER)}")
            
            if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER:
                try:
                    from twilio.rest import Client
                    
                    logger.info("📞 Attempting to send SMS via Twilio...")
                    
                    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                    
                    message = client.messages.create(
                        body=f"Your DecentralChat verification code is: {otp}\n\nThis code expires in 10 minutes.",
                        from_=TWILIO_PHONE_NUMBER,
                        to=phone
                    )
                    
                    logger.info(f"✅ SMS sent successfully to {phone} - SID: {message.sid}")
                    
                    return web.json_response({
                        "success": True, 
                        "message": "Verification code sent to your phone"
                    })
                    
                except Exception as sms_error:
                    logger.error(f"❌ Twilio SMS sending failed: {sms_error}")
                    
                    error_message = str(sms_error)
                    
                    # Enhanced error messages
                    if "unverified" in error_message.lower() or "21608" in error_message:
                        return web.json_response({
                            "error": f"Phone number not verified in Twilio. Verify at: https://console.twilio.com/us1/develop/phone-numbers/manage/verified",
                            "dev_mode": True,
                            "dev_otp": otp
                        }, status=400)
                    
                    if "21211" in error_message:
                        return web.json_response({
                            "error": "Invalid phone number format",
                            "dev_otp": otp
                        }, status=400)
                    
                    # Fallback: Return OTP for testing
                    return web.json_response({
                        "success": True,
                        "message": "SMS failed, showing code for testing",
                        "dev_otp": otp,
                        "error_details": error_message
                    })
            else:
                # Development mode
                logger.warning(f"⚠️ DEV MODE - Twilio not configured")
                logger.warning(f"📱 OTP for {phone}: {otp}")
                
                return web.json_response({
                    "success": True,
                    "message": "DEV MODE: OTP shown in response",
                    "dev_otp": otp,
                    "note": "Configure Twilio environment variables"
                })

        except Exception as e:
            logger.error(f"Send OTP error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def verify_phone_code(self, request):
        """Verify OTP and update phone number"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            phone = data.get('phone', '').strip()
            code = data.get('code', '').strip()

            if not phone or not code:
                return web.json_response({"error": "Phone and code required"}, status=400)

            # Verify OTP
            stored_otp = await redis_client.get(f"otp:{phone}")
            
            if not stored_otp or stored_otp != code:
                return web.json_response({"error": "Invalid or expired code"}, status=400)

            # Update user's phone
            await redis_client.hset(f"user:{user_id}", mapping={
                "phone": phone,
                "phone_verified": "true"
            })

            await redis_client.hset("phone_map", phone, user_id)
            await redis_client.delete(f"otp:{phone}")

            if self.db:
                try:
                    self.db.collection('users').document(user_id).set({
                        'phone': phone,
                        'phone_verified': True
                    }, merge=True)
                except Exception as fb_err:
                    logger.error(f"Firestore update error: {fb_err}")

            logger.info(f"✅ Phone verified: {user_id}")

            return web.json_response({"success": True, "phone": phone})

        except Exception as e:
            logger.error(f"Verify phone error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_user_profile(self, request):
        """Update user profile"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            updates = {}
            
            if 'bio' in data:
                updates['bio'] = data['bio'][:200]
                
            if 'username' in data:
                new_username = data['username'].strip()
                if len(new_username) >= 3:
                    existing = await redis_client.hget("username_map", new_username)
                    if existing and existing != user_id:
                        return web.json_response({"error": "Username taken"}, status=400)
                    
                    old_username = await redis_client.hget(f"user:{user_id}", "username")
                    if old_username:
                        await redis_client.hdel("username_map", old_username)
                    
                    await redis_client.hset("username_map", new_username, user_id)
                    updates['username'] = new_username

            if updates:
                await redis_client.hset(f"user:{user_id}", mapping=updates)
                
                if self.db:
                    try:
                        self.db.collection('users').document(user_id).set(updates, merge=True)
                    except Exception as fb_err:
                        logger.error(f"Firestore update: {fb_err}")

            return web.json_response({"success": True, "updates": updates})

        except Exception as e:
            logger.error(f"Update profile error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_user_settings(self, request):
        """Get user settings"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            user_data = await redis_client.hgetall(f"user:{user_id}")
            settings = json.loads(user_data.get('settings', '{}'))
            
            return web.json_response({
                "settings": settings,
                "user": {
                    "id": user_id,
                    "username": user_data.get('username'),
                    "email": user_data.get('email'),
                    "phone": user_data.get('phone'),
                    "bio": user_data.get('bio'),
                    "avatar_url": user_data.get('avatar_url'),
                    "phone_verified": user_data.get('phone_verified') == 'true'
                }
            })

        except Exception as e:
            logger.error(f"Get settings error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_user_settings(self, request):
        """Update user settings"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            settings = data.get('settings', {})

            await redis_client.hset(f"user:{user_id}", "settings", json.dumps(settings))

            if self.db:
                try:
                    self.db.collection('users').document(user_id).set({'settings': settings}, merge=True)
                except Exception as fb_err:
                    logger.error(f"Firestore update: {fb_err}")

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Update settings error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def delete_message_for_all(self, request):
        """Delete message for everyone"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            message_id = request.match_info['message_id']
            msg_data = await redis_client.hgetall(f"message:{message_id}")

            if not msg_data or msg_data.get('sender_id') != user_id:
                return web.json_response({"error": "Cannot delete"}, status=403)

            # Check if less than 1 hour old
            created_at = datetime.datetime.fromisoformat(msg_data.get('created_at'))
            if datetime.datetime.now(datetime.UTC) - created_at > timedelta(hours=1):
                return web.json_response({"error": "Can only delete within 1 hour"}, status=400)

            # Redis soft delete (UNCHANGED)
            await redis_client.hset(f"message:{message_id}", mapping={
                "deleted": "True",
                "deleted_for_everyone": "True",
                "content": "This message was deleted",
                "deleted_at": datetime.datetime.now(datetime.UTC).isoformat()
            })

            chat_id = msg_data.get('chat_id')

            # 🔥 FIXED: Firestore persistence (restart-safe)
            if getattr(self, "db", None) and chat_id:
                try:
                    self.db.collection("chats") \
                        .document(chat_id) \
                        .collection("messages") \
                        .document(message_id) \
                        .set({
                            "deleted": True,
                            "deleted_for_everyone": True,
                            "content": "This message was deleted",
                            "deleted_at": firestore.SERVER_TIMESTAMP
                        }, merge=True)
                except Exception as fs_err:
                    logger.error(f"Firestore delete-for-all sync failed: {fs_err}")

            member_ids = await redis_client.smembers(f"chat_members:{chat_id}")
            
            await self.broadcast_to_users(list(member_ids), {
                "type": "message_deleted",
                "message_id": message_id,
                "chat_id": chat_id,
                "deleted_for_everyone": True
            })

            return web.json_response({"success": True})

        except Exception as e:
            logger.error(f"Delete error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def delete_message_for_me(self, request):
        """Delete message for current user only"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            message_id = request.match_info['message_id']

            # Redis cache (UNCHANGED)
            await redis_client.sadd(f"deleted_messages:{user_id}", message_id)

            # 🔥 FIXED: Firestore persistence (restart-safe)
            if getattr(self, "db", None):
                try:
                    self.db.collection("users") \
                        .document(user_id) \
                        .collection("deleted_messages") \
                        .document(message_id) \
                        .set({
                            "deleted_at": firestore.SERVER_TIMESTAMP
                        }, merge=True)
                except Exception as fs_err:
                    logger.error(f"Firestore delete-for-me sync failed: {fs_err}")

            return web.json_response({"success": True})

        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)


    async def forward_message(self, request):
        """Forward message to other chats"""
        try:
            user_id = await self.get_user_from_token(request)
            if not user_id:
                return web.json_response({"error": "Unauthorized"}, status=401)

            data = await request.json()
            message_id = data.get('message_id')
            target_chat_ids = data.get('chat_ids', [])

            logger.info(f"📤 Forwarding message {message_id} to {len(target_chat_ids)} chats")

            if not message_id or not target_chat_ids:
                return web.json_response({"error": "Invalid request"}, status=400)

            # Get original message
            msg_data = await redis_client.hgetall(f"message:{message_id}")
            if not msg_data:
                logger.error(f"❌ Message {message_id} not found")
                return web.json_response({"error": "Message not found"}, status=404)

            logger.info(f"✅ Found message to forward: {msg_data.get('content', '')[:50]}")

            forwarded_ids = []
            for chat_id in target_chat_ids:
                # Check if user is member
                is_member = await redis_client.sismember(f"chat_members:{chat_id}", user_id)
                if not is_member:
                    logger.warning(f"⚠️ User {user_id} not member of chat {chat_id}, skipping")
                    continue

                try:
                    # Create forwarded message
                    new_msg_id = await self.create_message(
                        chat_id=chat_id,
                        sender_id=user_id,
                        content=msg_data.get('content', ''),
                        message_type=msg_data.get('message_type', 'text'),
                        encrypted=msg_data.get('encrypted') == 'True',
                        attachments=json.loads(msg_data.get('attachments', '[]'))
                    )
                    
                    forwarded_ids.append(new_msg_id)
                    logger.info(f"✅ Forwarded to chat {chat_id}: {new_msg_id}")
                    
                except Exception as fwd_error:
                    logger.error(f"❌ Failed to forward to chat {chat_id}: {fwd_error}")
                    continue

            logger.info(f"✅ Successfully forwarded to {len(forwarded_ids)} chats")

            return web.json_response({
                "success": True,
                "forwarded_count": len(forwarded_ids)
            })

        except Exception as e:
            logger.error(f"❌ Forward error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def migrate_existing_files(self):
        """One-time migration: Add 'path' field to existing file records"""
        if not self.db:
            logger.warning("Firestore not available, skipping migration")
            return
        
        logger.info("🔧 Starting file migration...")
        
        try:
            files_ref = self.db.collection('files')
            docs = files_ref.stream()
            
            migrated = 0
            for doc in docs:
                file_data = doc.to_dict()
                
                # Skip if already has path
                if file_data.get('path'):
                    continue
                
                # Reconstruct path from URL
                file_url = file_data.get('url', '')
                if not file_url:
                    continue
                
                # Extract path from URL (e.g., /uploads/images/abc123.jpg)
                url_path = file_url.lstrip('/')
                file_path = Path(url_path)
                
                # Check if file exists
                if not file_path.exists():
                    logger.warning(f"⚠️ File not found: {file_path}")
                    continue
                
                # Update Firestore
                doc.reference.update({'path': str(file_path.absolute())})
                migrated += 1
                logger.info(f"✅ Migrated: {file_data.get('filename')}")
            
            logger.info(f"🎉 Migration complete! Updated {migrated} files")
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")


    async def get_user_by_id(self, request):
        """Get user by ID"""
        try:
            user_id = request.match_info['user_id']
            
            user_data = await redis_client.hgetall(f"user:{user_id}")
            
            if not user_data:
                return web.json_response({"error": "User not found"}, status=404)
            
            return web.json_response({
                "user": {
                    "id": user_id,
                    "username": user_data.get('username'),
                    "email": user_data.get('email'),
                    "avatar_url": user_data.get('avatar_url'),
                    "status": user_data.get('status'),
                    "bio": user_data.get('bio')
                }
            })
        except Exception as e:
            logger.error(f"Get user by ID error: {e}")
            return web.json_response({"error": str(e)}, status=500)

# ==================== MOCK REDIS ====================

class MockRedis:
    """Mock Redis for development without Redis server"""
    
    def __init__(self):
        self.data = {}
        self.sets = {}
        self.lists = {}
        self.expiry = {}

    async def ping(self):
        return True

    async def hset(self, name, key=None, value=None, mapping=None):
        if name not in self.data:
            self.data[name] = {}
        if mapping:
            self.data[name].update(mapping)
        elif key:
            self.data[name][key] = value

    async def hgetall(self, name):
        return self.data.get(name, {})

    async def hget(self, name, key):
        return self.data.get(name, {}).get(key)
    async def hdel(self, name, *keys):
        """Delete hash fields"""
        if name in self.data:
            for key in keys:
                self.data[name].pop(key, None)
            # Remove hash if empty
            if not self.data[name]:
                del self.data[name]
        return len(keys)
    
    async def hkeys(self, name):
        """Get all keys in a hash"""
        return list(self.data.get(name, {}).keys())
    
    async def sadd(self, name, *values):
        if name not in self.sets:
            self.sets[name] = set()
        self.sets[name].update(values)

    async def smembers(self, name):
        return self.sets.get(name, set())

    async def sismember(self, name, value):
        return value in self.sets.get(name, set())

    async def srem(self, name, *values):
        if name in self.sets:
            self.sets[name].difference_update(values)

    async def lpush(self, name, *values):
        if name not in self.lists:
            self.lists[name] = []
        self.lists[name] = list(values) + self.lists[name]

    async def lrange(self, name, start, end):
        if name not in self.lists:
            return []
        return self.lists[name][start:end+1] if end >= 0 else self.lists[name][start:]

    async def ltrim(self, name, start, end):
        if name in self.lists:
            self.lists[name] = self.lists[name][start:end+1]

    async def delete(self, *names):
        for name in names:
            self.data.pop(name, None)
            self.sets.pop(name, None)
            self.lists.pop(name, None)
            self.expiry.pop(name, None)

    async def get(self, name):
        """Get a single value"""
        return self.data.get(name)

    async def set(self, name, value, ex=None):
        """Set a value with optional expiry"""
        self.data[name] = value
        if ex:
            self.expiry[name] = ex
        return True

    async def setex(self, name, time, value):
        """Set value with expiration"""
        self.data[name] = value
        self.expiry[name] = time
        return True

    async def expire(self, name, time):
        """Set expiration time for a key"""
        self.expiry[name] = time
        return True
    
    async def ttl(self, name):
        """Get time to live for a key"""
        return self.expiry.get(name, -1)

    async def keys(self, pattern):
        """Get keys matching pattern"""
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            # Combine all dictionaries
            all_keys = list(self.data.keys()) + list(self.sets.keys()) + list(self.lists.keys())
            return [k for k in all_keys if k.startswith(prefix)]
        return []

    def pipeline(self):
        """Mock pipeline for batch operations"""
        return MockPipeline(self)

    async def execute(self):
        """Execute pipeline"""
        results = []
        for cmd in self.commands:
            if cmd[0] == 'set' or cmd[0] == 'delete' or cmd[0] == 'expire':
                await getattr(self.redis, cmd[0])(*cmd[1:])
                results.append(True)
            elif cmd[0] == 'get':
                results.append(await self.redis.get(cmd[1]))
            elif cmd[0] == 'hget':
                results.append(await self.redis.hget(cmd[1], cmd[2]))
            elif cmd[0] == 'hkeys':
                results.append(await self.redis.hkeys(cmd[1]))
            else:
                results.append(None)
        return results 
        
class MockPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []
    
    def set(self, key, value, ex=None):
        self.commands.append(('set', key, value, ex))
        return self
    
    def get(self, key):
        self.commands.append(('get', key))
        return self
    
    async def execute(self):
        results = []
        for cmd in self.commands:
            if cmd[0] == 'set':
                await self.redis.set(cmd[1], cmd[2], ex=cmd[3])
                results.append(True)
            elif cmd[0] == 'get':
                results.append(await self.redis.get(cmd[1]))
        return results

# ==================== MAIN ====================


def main():
    """Initialize and run server"""
    import sys  # Add this import
    
    # Create upload directories
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for category in ['images', 'videos', 'audio', 'documents', 'archives', 'voices', 'avatars', 'thumbnails']:
            subdir = UPLOAD_DIR / category
            subdir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Upload directory ready: {subdir.absolute()}")
            
            # Test write permissions
            test_file = subdir / '.test'
            try:
                test_file.write_text('test')
                test_file.unlink()
                logger.info(f"✅ Write permission OK: {subdir}")
            except Exception as perm_error:
                logger.error(f"❌ No write permission: {subdir} - {perm_error}")
                
    except Exception as e:
        logger.error(f"❌ Failed to create upload directories: {e}")
        sys.exit(1)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    server = DecentralChatServer()
    loop.run_until_complete(server.initialize())
    
    logger.info("=" * 70)
    logger.info("⚠️  IMPORTANT: For production use, enable Redis persistence:")
    logger.info("   Edit redis.conf and set:")
    logger.info("     appendonly yes")
    logger.info("     appendfilename 'appendonly.aof'")
    logger.info("     save 900 1")
    logger.info("     save 300 10")
    logger.info("     save 60 10000")
    logger.info("   Or use Firestore as primary data store (recommended)")
    logger.info("=" * 70)

    logger.info("=" * 70)
    logger.info("🚀 DecentralChat Server Started Successfully")
    logger.info("=" * 70)
    logger.info(f"🌐 HTTP API: http://0.0.0.0:{PORT}")
    logger.info(f"🔌 WebSocket: ws://0.0.0.0:{PORT}/api/ws")
    logger.info(f"💾 Redis: {REDIS_URL}")
    logger.info(f"🔥 Firebase: {'✅ Connected' if server.firebase_app else '❌ Not configured'}")
    logger.info(f"📁 Upload Dir: {UPLOAD_DIR.absolute()}")
    logger.info("=" * 70)
    logger.info(f"📖 API Documentation: http://0.0.0.0:{PORT}/api")
    logger.info(f"❤️  Health Check: http://0.0.0.0:{PORT}/health")
    logger.info("=" * 70)

    
    web.run_app(server.app, host='0.0.0.0', port=PORT)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n👋 Server shutting down gracefully...")
