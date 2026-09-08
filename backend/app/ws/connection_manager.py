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
async def broadcast_user_status(self, user_id: str, status: str):
    """Broadcast user status to contacts"""
    try:
        # Get user's contacts
        contact_ids = await g.redis_client.smembers(f"user_contacts:{user_id}")

        if not contact_ids:
            return

        user_data = await g.redis_client.hgetall(f"user:{user_id}")

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
        member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")
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
        if user_id in g.active_connections:
            for ws in list(g.active_connections[user_id]):
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.error(f"Broadcast error to {user_id}: {e}")
                    g.active_connections[user_id].discard(ws)

