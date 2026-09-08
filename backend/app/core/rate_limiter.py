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

