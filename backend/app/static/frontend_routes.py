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
async def serve_frontend(request):
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

async def serve_favicon(request):
    """Serve favicon"""
    try:
        favicon_path = Path(__file__).parent.parent / 'frontend' / 'favicon.ico'
        if favicon_path.exists():
            return web.FileResponse(favicon_path)
        return web.Response(status=204)
    except Exception as e:
        logger.error(f"Favicon error: {e}")
        return web.Response(status=204)

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
                # Read a single trivial doc to validate connectivity.
                col = g.db.collection("health_check")
                await col.limit(1).get()
            else:
                db_status = "unavailable"
        except Exception as db_err:
            logger.warning(f"⚠️ Health check: storage unreachable: {db_err}")
            db_status = "disconnected"

        # A real health check must surface dependency failures so the
        # orchestrator can restart/avoid routing to a broken instance
        # (cloud-native requirement: report 503 when Redis/Storage are down).
        deps_up = (redis_status == "connected") and (db_status == "connected")
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

