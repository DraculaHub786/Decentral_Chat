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
        call_data = await g.redis_client.hgetall(f"call:{call_id}")
        
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
            await g.redis_client.hset(f"call:{call_id}", "status", "active")
            logger.info(f"✅ Call {call_id} now active")
        
    except Exception as e:
        logger.error(f"❌ WS call signal error: {e}", exc_info=True)

