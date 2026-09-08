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
from app.calls.ws_signal import handle_ws_call_signal
from app.calls.group.ws_signal import (handle_group_call_start,
    handle_group_call_signal, handle_group_call_ice, handle_group_call_leave_ws)
from app.messages.service import broadcast_message
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
                        
                        if user_id not in g.active_connections:
                            g.active_connections[user_id] = set()
                        g.active_connections[user_id].add(ws)
                        
                        # Update status
                        await g.redis_client.hset(f"user:{user_id}", "status", "online")
                        
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
                        is_member = await g.redis_client.sismember(f"chat_members:{chat_id}", user_id)
                        if not is_member:
                            await ws.send_json({
                                "type": "error",
                                "message": "Not a member of this chat"
                            })
                            continue
                        
                        # Get chat data
                        chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
                        
                        # **BLOCKING CHECK FOR DIRECT CHATS**
                        if chat_data.get('type') == 'direct':
                            member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")
                            other_user_id = next((m for m in member_ids if m != user_id), None)
                            
                            if other_user_id:
                                # Check if current user has blocked the other
                                is_blocked_by_me = await g.redis_client.sismember(f"user_blocked:{user_id}", other_user_id)
                                
                                # Check if current user is blocked by the other
                                is_blocked_by_them = await g.redis_client.sismember(f"user_blocked:{other_user_id}", user_id)
                                
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
            if user_id in g.active_connections:
                g.active_connections[user_id].discard(ws)
                if not g.active_connections[user_id]:
                    del g.active_connections[user_id]
                    
                    # Update status
                    await g.redis_client.hset(f"user:{user_id}", mapping={
                        "status": "offline",
                        "last_seen": datetime.datetime.now(datetime.UTC).isoformat()
                    })
                    
                    await self.broadcast_user_status(user_id, "offline")
            
            logger.info(f"🔌 Disconnected: {user_id}")

    return ws

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

        is_member = await g.redis_client.sismember(f"chat_members:{chat_id}", user_id)
        if not is_member:
            logger.warning(f"User {user_id} is not a member of chat {chat_id}")
            return

        # Check blocking for direct chats
        chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
        if chat_data.get('type') == 'direct':
            member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")
            other_user_id = next((m for m in member_ids if m != user_id), None)
            
            if other_user_id:
                i_blocked_them = await g.redis_client.sismember(f"user_blocked:{user_id}", other_user_id)
                they_blocked_me = await g.redis_client.sismember(f"user_blocked:{other_user_id}", user_id)
                
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
            await g.redis_client.hset(f"message_read:{msg_id}", user_id, "true")

        # Notify sender
        for msg_id in message_ids:
            msg_data = await g.redis_client.hgetall(f"message:{msg_id}")
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

