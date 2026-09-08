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
from app.ws.connection_manager import broadcast_to_users, broadcast_user_status, broadcast_typing
async def create_message(self, chat_id: str, sender_id: str, content: str,
                    message_type: str = 'text', encrypted: bool = True,
                    attachments: List[str] = None, reply_to: str = None) -> str:
    """Create and store message"""
    message_id = str(uuid.uuid4())
    
    if attachments is None:
        attachments = []
    reply_to_data = None
    if reply_to:
        reply_msg = await g.redis_client.hgetall(f"message:{reply_to}")
        if reply_msg:
            reply_sender = await g.redis_client.hgetall(f"user:{reply_msg.get('sender_id')}")
            reply_to_data = {
                'id': reply_to,
                'content': reply_msg.get('content', ''),
                'sender': {
                    'id': reply_msg.get('sender_id'),
                    'username': reply_sender.get('username', 'Unknown'),
                    'avatar_url': reply_sender.get('avatar_url', '')
                },
                'message_type': reply_msg.get('message_type', 'text')
            }
    message_data = {
        "id": message_id,
        "chat_id": chat_id,
        "sender_id": sender_id,
        "content": content,
        "encrypted": str(encrypted),
        "message_type": message_type,
        "reply_to": reply_to or "",
        "attachments": json.dumps(attachments),
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "edited": "False",
        "deleted": "False"
    }
    if reply_to_data:
        message_data["reply_to_data"] = json.dumps(reply_to_data)


    await g.redis_client.hset(f"message:{message_id}", mapping=message_data)
    if self.db:
        try:
            # Prepare message document
            firestore_msg = {
                'id': message_id,
                'sender_id': sender_id,
                'content': content,
                'message_type': message_type,
                'encrypted': encrypted,
                'attachments': attachments if attachments else [],  # Ensure array
                'reply_to': reply_to or None,
                'created_at': firestore.SERVER_TIMESTAMP,
                'edited': False,
                'deleted': False
            }
            if reply_to_data:
                firestore_msg['reply_to_data'] = reply_to_data
                
            # Save message
            self.db.collection('chats').document(chat_id).collection('messages').document(message_id).set(firestore_msg)
            logger.info(f"✅ Message {message_id} saved to Firestore with {len(attachments) if attachments else 0} attachments")
            
        except Exception as fb_err:
            logger.error(f"❌ Firestore message save failed: {fb_err}")
    await g.redis_client.lpush(f"chat_messages:{chat_id}", message_id)
    await g.redis_client.ltrim(f"chat_messages:{chat_id}", 0, 999)

    # ✅ Update chat's last_message for quick preview in contact list
    preview_content = content[:50] if message_type == 'text' else ''
    await g.redis_client.hset(f"chat:{chat_id}", mapping={
        "last_message": preview_content,
        "last_message_type": message_type,
        "last_message_time": message_data["created_at"]
    })
    
    await self.broadcast_message(chat_id, message_id, sender_id)

    return message_id

async def broadcast_message(self, chat_id: str, message_id: str, sender_id: str):
    """Broadcast message to chat members with blocking checks"""
    try:
        # Get message data
        msg_data = await g.redis_client.hgetall(f"message:{message_id}")
        
        if not msg_data:
            logger.error(f"❌ Message {message_id} not found in Redis!")
            return
        
        logger.info(f"📢 Broadcasting message {message_id}, type: {msg_data.get('message_type')}")
        
        sender_data = await g.redis_client.hgetall(f"user:{sender_id}")

        # ✅ CRITICAL FIX: Initialize reply_to_info FIRST, before any loops
        reply_to_info = None
        if msg_data.get('reply_to_data'):
            try:
                reply_to_info = json.loads(msg_data.get('reply_to_data'))
                logger.info(f"✅ Loaded reply_to_data from message")
            except Exception as e:
                logger.error(f"Failed to parse reply_to_data: {e}")
        elif msg_data.get('reply_to'):
            # Fallback: fetch reply message if reply_to_data not stored
            try:
                reply_msg = await g.redis_client.hgetall(f"message:{msg_data.get('reply_to')}")
                if reply_msg:
                    reply_sender = await g.redis_client.hgetall(f"user:{reply_msg.get('sender_id')}")
                    reply_to_info = {
                        'id': msg_data.get('reply_to'),
                        'content': reply_msg.get('content', ''),
                        'sender': {
                            'id': reply_msg.get('sender_id'),
                            'username': reply_sender.get('username', 'Unknown'),
                            'avatar_url': reply_sender.get('avatar_url', '')
                        },
                        'message_type': reply_msg.get('message_type', 'text')
                    }
                    logger.info(f"✅ Fetched reply_to message data")
            except Exception as e:
                logger.error(f"Failed to fetch reply_to message: {e}")

        # Parse attachments
        attachments = []
        attachment_ids_str = msg_data.get('attachments', '[]')
        
        try:
            attachment_ids = json.loads(attachment_ids_str) if attachment_ids_str else []
        except Exception as e:
            logger.error(f"Failed to parse attachments JSON: {e}")
            attachment_ids = []
        
        for att_id in attachment_ids:
            if not att_id:
                continue
                
            att_meta = await g.redis_client.hgetall(f"file:{att_id}")
            
            if att_meta:
                attachment_data = {
                    "id": att_id,
                    "filename": att_meta.get('filename'),
                    "type": att_meta.get('file_type'),
                    "size": int(att_meta.get('size', 0)),
                    "url": att_meta.get('url'),
                    "thumbnail_url": att_meta.get('thumbnail_url')
                }
                
                if att_meta.get('duration'):
                    attachment_data['duration'] = att_meta.get('duration')
                
                attachments.append(attachment_data)

        # Get chat members
        member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")

        # Filter out blocked users for direct chats
        chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
        allowed_recipients = []
        
        for member_id in member_ids:
            if member_id == sender_id:
                # Sender always gets their own message
                allowed_recipients.append(member_id)
                continue
            
            # Check blocking for direct chats only
            if chat_data.get('type') == 'direct':
                # Check if sender blocked this recipient
                sender_blocked_recipient = await g.redis_client.sismember(
                    f"user_blocked:{sender_id}", 
                    member_id
                )
                
                # Check if recipient blocked sender
                recipient_blocked_sender = await g.redis_client.sismember(
                    f"user_blocked:{member_id}", 
                    sender_id
                )
                
                if sender_blocked_recipient or recipient_blocked_sender:
                    logger.warning(f"⚠️ Skipping broadcast to {member_id} - blocking active")
                    continue
            
            allowed_recipients.append(member_id)

        # Broadcast only to allowed recipients
        broadcast_data = {
            "type": "new_message",
            "chat_id": chat_id,
            "message": {
                "id": message_id,
                "content": msg_data.get('content'),
                "encrypted": msg_data.get('encrypted') == 'True',
                "message_type": msg_data.get('message_type'),
                "attachments": attachments,
                "created_at": msg_data.get('created_at'),
                "reply_to": msg_data.get('reply_to') or None,
                "reply_to_data": reply_to_info,  # ✅ Now guaranteed to be defined
                "sender": {
                    "id": sender_id,
                    "username": sender_data.get('username'),
                    "avatar_url": sender_data.get('avatar_url')
                }
            },
            "last_message_type": msg_data.get('message_type'),  # ✅ Include for chat list preview
            "last_message_preview": msg_data.get('content', '')[:50] if msg_data.get('message_type') == 'text' else ''
        }

        logger.info(f"📢 Broadcasting to {len(allowed_recipients)}/{len(member_ids)} members")

        await self.broadcast_to_users(allowed_recipients, broadcast_data)
        
        logger.info(f"✅ Message {message_id} broadcast complete")

    except Exception as e:
        logger.error(f"❌ Broadcast message error: {e}", exc_info=True)

