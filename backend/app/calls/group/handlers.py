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
        is_member = await g.redis_client.sismember(f"chat_members:{group_id}", user_id)
        if not is_member:
            return web.json_response({"error": "Not a member of this group"}, status=403)

        # Get all group members
        member_ids = await g.redis_client.smembers(f"chat_members:{group_id}")
        
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
        await g.redis_client.hset(f"group_call:{call_id}", mapping=call_data)
        await g.redis_client.setex(f"active_group_call:{call_id}", 3600, "true")  # 1 hour expiry
        
        # Store in memory
        g.active_group_calls[call_id] = {
            "id": call_id,
            "group_id": group_id,
            "initiator_id": user_id,
            "type": call_type,
            "status": "active",
            "started_at": call_data["started_at"],
            "participants": {user_id: "active"}
        }

        # Get initiator info
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
        call_data = await g.redis_client.hgetall(f"group_call:{call_id}")
        if not call_data:
            return web.json_response({"error": "Call not found"}, status=404)

        group_id = call_data.get('group_id')
        
        # Verify user is a member of the group
        is_member = await g.redis_client.sismember(f"chat_members:{group_id}", user_id)
        if not is_member:
            return web.json_response({"error": "Not a member of this group"}, status=403)

        # Add user to participants
        participants = json.loads(call_data.get('participants', '{}'))
        participants[user_id] = "active"
        
        # Update Redis
        await g.redis_client.hset(f"group_call:{call_id}", "participants", json.dumps(participants))
        
        # Update memory
        if call_id in g.active_group_calls:
            g.active_group_calls[call_id]['participants'][user_id] = "active"

        # Get user info
        user_data = await g.redis_client.hgetall(f"user:{user_id}")

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
                p_data = await g.redis_client.hgetall(f"user:{participant_id}")
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
        call_data = await g.redis_client.hgetall(f"group_call:{call_id}")
        if not call_data:
            return web.json_response({"error": "Call not found"}, status=404)

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
            
            logger.info(f"📞 Group call {call_id} ended - no participants left")
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
        call_data = await g.redis_client.hgetall(f"group_call:{call_id}")
        if not call_data:
            return web.json_response({"error": "Call not found"}, status=404)

        participants = json.loads(call_data.get('participants', '{}'))
        
        # Get participant info
        participants_info = []
        for participant_id, status in participants.items():
            p_data = await g.redis_client.hgetall(f"user:{participant_id}")
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

