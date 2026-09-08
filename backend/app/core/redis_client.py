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
from app.core._mockredis import MockRedis, MockPipeline
logger = logging.getLogger(__name__)
async def init_redis(self):
    """Initialize Redis for decentralized storage"""
    try:
        g.redis_client = await redis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5
        )
        await g.redis_client.ping()
        logger.info("✅ Redis connected successfully")
    except Exception as e:
        # Redis is REQUIRED in production (cloud-native deployments).
        # In production, a connection failure must be fatal so the
        # orchestrator/scheduler restarts the instance (fail-fast).
        if os.getenv("ENVIRONMENT", "development").lower() in ("production", "prod"):
            logger.error(f"❌ Redis connection failed in production: {e}")
            raise
        logger.warning(f"⚠️ Redis connection failed: {e}")
        logger.info("ℹ️  Running with in-memory mock (development only)")
        logger.info("   To install Redis: https://redis.io/docs/install/")
        # Fallback to in-memory mock
        g.redis_client = MockRedis()
