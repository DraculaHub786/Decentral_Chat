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
    _validate_password, _validate_file_magic, _resolve_safe_path, _log_safe,
    _is_admin, _validate_cors_origin)
from app.core.rate_limiter import RateLimiter
from app.core.redis_client import MockRedis, MockPipeline
from app.core.firebase_client import init_firebase
logger = logging.getLogger(__name__)
@web.middleware
async def csrf_middleware(request, handler):
    if not _validate_cors_origin(request):
        return web.json_response({"error": "Forbidden"}, status=403)
    return await handler(request)


@web.middleware
async def security_headers_middleware(request, handler):
    resp = await handler(request)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['X-XSS-Protection'] = '1; mode=block'

    # Build a Content-Security-Policy that:
    #  - allows same-origin ('self') for everything,
    #  - allows the server's OWN origin (covers the API when the SPA is served
    #    from a forwarded / proxied hostname that points at this same backend),
    #  - allows Google's OAuth / userinfo endpoints (used by Google Sign-In in
    #    frontend/app.js -> https://www.googleapis.com/oauth2/v3/userinfo),
    #  - allows websocket schemes for the live chat socket.
    #
    # NOTE: A static connect-src 'self' ONLY previously blocked the Google
    # userinfo call AND every cross-origin API request (port-forwarded URLs,
    # proxies, 127.0.0.1 vs localhost), surfacing in the browser as
    # "network error when trying to fetch resources" on login/register/Google.
    scheme = getattr(request, 'scheme', None) or 'http'
    host = getattr(request, 'host', None) or 'localhost'
    own_origin = f"{scheme}://{host}"

    connect_src = (
        f"'self' {own_origin} ws: wss: "
        f"https://www.googleapis.com https://accounts.google.com"
    )
    frame_src = (
        f"'self' {own_origin} "
        f"https://accounts.google.com https://*.google.com"
    )
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "media-src 'self' https:; "
        f"connect-src {connect_src}; "
        "font-src 'self' https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' 'unsafe-inline' https:; "
        f"frame-src {frame_src}"
    )
    return resp
