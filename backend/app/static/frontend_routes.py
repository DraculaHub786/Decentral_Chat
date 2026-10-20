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
import sys

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from PIL import Image, ImageOps
import PyPDF2
from docx import Document
from pptx import Presentation
import openpyxl

try:
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
except ImportError:
    from ..globals import g
    from ..core.config import (REDIS_URL, SECRET_KEY, FIREBASE_CRED, PORT,
        MAX_FILE_SIZE, UPLOAD_DIR, ALLOWED_EXTENSIONS, ENCRYPTION_KEY,
        HAS_LIBREOFFICE, HAS_UNOCONV, FFMPEG_PATH, HAS_PDF2DOCX, PDFConverter,
        HAS_BS4, HAS_MARKDOWN, print_conversion_capabilities)
    from ..core.security import (_ensure_secret_key, _ensure_fernet_key,
        _validate_password, _validate_file_magic, _resolve_safe_path, _log_safe, _is_admin)
    from ..core.rate_limiter import RateLimiter
    from ..core.redis_client import MockRedis, MockPipeline
    from ..core.firebase_client import init_firebase

logger = logging.getLogger(__name__)

# Resolve the frontend directory robustly. The frontend lives at the project
# root (<repo>/frontend), but this module is nested at
# <repo>/backend/app/static/frontend_routes.py. Depending on how the repo is
# laid out, the frontend may also be found at <repo>/backend/frontend or
# alongside this file. Try the known candidates once and cache the result.
_FRONTEND_DIR = None


def _resolve_frontend_dir():
    """Locate the frontend directory containing index.html (cached)."""
    global _FRONTEND_DIR
    if _FRONTEND_DIR is not None:
        return _FRONTEND_DIR

    here = Path(__file__).resolve()
    # Candidate base directories to search for a `frontend/` folder.
    candidates = [
        here.parent.parent.parent.parent,  # repo root (/frontend)
        here.parent.parent.parent,         # backend/  (/frontend)
        here.parent.parent,                # backend/app  (/frontend)
    ]
    for base in candidates:
        candidate = base / 'frontend'
        if (candidate / 'index.html').exists():
            _FRONTEND_DIR = candidate
            logger.info(f"📁 Resolved frontend directory: {candidate}")
            return _FRONTEND_DIR

    # Fall back to the most likely location even if not found yet.
    _FRONTEND_DIR = candidates[0] / 'frontend'
    return _FRONTEND_DIR


async def serve_frontend(request):
    """Serve the frontend HTML file"""
    try:
        frontend_dir = _resolve_frontend_dir()
        frontend_path = frontend_dir / 'index.html'

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

async def serve_favicon(request):
    """Serve favicon"""
    try:
        favicon_path = _resolve_frontend_dir() / 'favicon.ico'
        if favicon_path.exists():
            return web.FileResponse(favicon_path)
        return web.Response(status=204)
    except Exception as e:
        logger.error(f"Favicon error: {e}")
        return web.Response(status=204)


async def serve_static_asset(request):
    """Serve a static asset (css/js/img/etc.) from the frontend directory.

    Frontend HTML references assets with relative paths (e.g. ``styles.css``,
    ``app.js``), so the browser requests ``/styles.css`` and ``/app.js``.
    aiohttp does not auto-serve these, so we resolve them safely against the
    frontend directory with path-traversal protection.
    """
    filename = request.match_info.get('filename', '')
    try:
        frontend_dir = _resolve_frontend_dir().resolve()
        # Build the absolute target path and ensure it stays inside the
        # frontend directory (blocks ``/static/../../etc/passwd`` etc.).
        target = (frontend_dir / filename).resolve()
        if not str(target).startswith(str(frontend_dir)):
            logger.warning(f"⚠️ Blocked path-traversal attempt: {filename}")
            return web.Response(text="Forbidden", status=403)
        if target.is_file():
            return web.FileResponse(target)
        return web.Response(text="Not Found", status=404)
    except Exception as e:
        logger.error(f"Static asset error ({filename}): {e}")
        return web.Response(text="Not Found", status=404)

async def index(request):
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

async def health_check(request):
    """Health check endpoint"""
    try:
        redis_status = "connected"
        try:
            await g.redis_client.ping()
        except:
            redis_status = "disconnected"

        # Storage (Firestore) health: a lightweight read proves the DB
        # backend is reachable. We do NOT fail the whole endpoint on a
        # storage hiccup, but we surface the status explicitly.
        db_status = "connected"
        try:
            if g.db is not None:
                # Read a single trivial doc off the event loop via worker thread
                def _ping_db():
                    col = g.db.collection("health_check")
                    return list(col.limit(1).stream())
                await asyncio.to_thread(_ping_db)
            else:
                db_status = "unavailable"
        except Exception as db_err:
            logger.warning(f"⚠️ Health check: storage unreachable: {db_err}")
            db_status = "disconnected"

        # A real health check surfaces critical dependency failures (Redis down).
        # Cloud-native requirement: report 503 when Redis is down or configured storage failed.
        deps_up = (redis_status == "connected") and (db_status != "disconnected")
        return web.json_response({
            "status": "healthy" if deps_up else "unhealthy",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "active_connections": sum(len(conns) for conns in g.active_connections.values()),
            "active_calls": len(g.active_calls),
            "redis": redis_status,
            "storage": db_status,
            "firebase": "connected" if g.firebase_app else "disconnected"
        }, status=200 if deps_up else 503)

    except Exception as e:
        return web.json_response(
            {"status": "unhealthy", "error": str(e)},
            status=503
        )

