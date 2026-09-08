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
        is_member = await g.redis_client.sismember(f"chat_members:{group_id}", user_id)
        if not is_member:
            logger.error(f"User {user_id} not a member of group {group_id}")
            return
        
        # Get all group members
        member_ids = await g.redis_client.smembers(f"chat_members:{group_id}")
        
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
        
        await g.redis_client.hset(f"group_call:{call_id}", mapping=call_data)
        await g.redis_client.setex(f"active_group_call:{call_id}", 3600, "true")
        
        g.active_group_calls[call_id] = {
            "id": call_id,
            "group_id": group_id,
            "initiator_id": user_id,
            "type": call_type,
            "status": "active",
            "started_at": call_data["started_at"],
            "participants": {user_id: "active"}
        }
        
        # Get initiator and group info
        initiator_data = await g.redis_client.hgetall(f"user:{user_id}")
        group_data = await g.redis_client.hgetall(f"chat:{group_id}")
        
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
        call_data = await g.redis_client.hgetall(f"group_call:{call_id}")
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
        call_data = await g.redis_client.hgetall(f"group_call:{call_id}")
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
        
        call_data = await g.redis_client.hgetall(f"group_call:{call_id}")
        if not call_data:
            return
        
        # Remove user from participants
        participants = json.loads(call_data.get('participants', '{}'))
        if user_id in participants:
            del participants[user_id]
        
        # If no participants left, end the call
        if not participants:
            await g.redis_client.hset(f"group_call:{call_id}", mapping={
                "status": "ended",
                "ended_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "participants": json.dumps({})
            })
            
            if call_id in g.active_group_calls:
                del g.active_group_calls[call_id]
            
            logger.info(f"📞 Group call {call_id} ended - no participants")
        else:
            # Update participants
            await g.redis_client.hset(f"group_call:{call_id}", "participants", json.dumps(participants))
            
            if call_id in g.active_group_calls:
                if user_id in g.active_group_calls[call_id]['participants']:
                    del g.active_group_calls[call_id]['participants'][user_id]
            
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

