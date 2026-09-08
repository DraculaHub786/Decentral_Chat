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
async def get_messages(self, request):
    """Get chat messages - with Firestore fallback for older messages"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']
        limit = int(request.query.get('limit', 50))
        offset = int(request.query.get('offset', 0))

        # Check membership
        is_member = await g.redis_client.sismember(f"chat_members:{chat_id}", user_id)
        if not is_member:
            return web.json_response({"error": "Forbidden"}, status=403)

        # Load delete-for-me set
        deleted_for_me = await g.redis_client.smembers(f"deleted_messages:{user_id}")
        deleted_for_me = set(
            m.decode() if isinstance(m, bytes) else m
            for m in deleted_for_me
        )

        message_ids = await g.redis_client.lrange(
            f"chat_messages:{chat_id}",
            offset,
            offset + limit - 1
        )

        # ⭐ FIX: If Redis returns fewer messages than requested AND we have Firestore,
        # try to fetch older messages from Firestore directly
        if (not message_ids or len(message_ids) < limit) and self.db:
            logger.warning(f"⚠️ Redis had only {len(message_ids)} messages for chat {chat_id} (requested {limit}), checking Firestore...")
            try:
                messages_ref = self.db.collection('chats').document(chat_id).collection('messages')
                # Fetch from Firestore in descending order with offset
                fb_query = messages_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(limit)
                fb_docs = list(fb_query.stream())
                
                if fb_docs:
                    logger.info(f"✅ Found {len(fb_docs)} messages in Firestore for chat {chat_id}")
                    # Store them in Redis for next time
                    for msg_doc in reversed(fb_docs):
                        msg_data = msg_doc.to_dict()
                        msg_id = msg_doc.id
                        
                        redis_msg_data = {
                            'id': msg_id,
                            'chat_id': chat_id,
                            'sender_id': msg_data.get('sender_id', ''),
                            'content': msg_data.get('content', ''),
                            'message_type': msg_data.get('message_type', 'text'),
                            'encrypted': str(msg_data.get('encrypted', False)),
                            'attachments': json.dumps(msg_data.get('attachments', [])),
                            'reply_to': msg_data.get('reply_to', ''),
                            'created_at': str(msg_data.get('created_at', datetime.datetime.now(datetime.UTC).isoformat())),
                            'edited': str(msg_data.get('edited', False)),
                            'deleted': str(msg_data.get('deleted', False))
                        }
                        
                        await g.redis_client.hset(f"message:{msg_id}", mapping=redis_msg_data)
                        await g.redis_client.lpush(f"chat_messages:{chat_id}", msg_id)
                    
                    await g.redis_client.ltrim(f"chat_messages:{chat_id}", 0, 999)
                    
                    # Re-fetch from Redis after restoring from Firestore
                    message_ids = await g.redis_client.lrange(
                        f"chat_messages:{chat_id}",
                        offset,
                        offset + limit - 1
                    )
                    logger.info(f"✅ Restored messages to Redis, now have {len(message_ids)} messages available")
            except Exception as fb_err:
                logger.warning(f"Firestore fallback for messages failed: {fb_err}")

        messages = []

        for raw_msg_id in message_ids:
            # 🔥 CRITICAL FIX (DO NOT REMOVE)
            msg_id = raw_msg_id.decode() if isinstance(raw_msg_id, bytes) else raw_msg_id

            # Delete-for-me filtering
            if msg_id in deleted_for_me:
                continue

            msg_data = await g.redis_client.hgetall(f"message:{msg_id}")
            if not msg_data:
                continue

            sender_id = msg_data.get('sender_id')

            # Delete-for-everyone handling
            if msg_data.get('deleted') == 'True':
                messages.append({
                    "id": msg_id,
                    "content": "🚫 This message was deleted",
                    "deleted": True,
                    "deleted_for_everyone": True,
                    "created_at": msg_data.get('created_at'),
                    "edited": False,
                    "reply_to": None,
                    "reply_to_data": None,
                    "sender": {
                        "id": sender_id,
                        "username": "Deleted",
                        "avatar_url": ""
                    }
                })
                continue

            sender_data = await g.redis_client.hgetall(f"user:{sender_id}")

            attachments = []
            attachment_ids = json.loads(msg_data.get('attachments', '[]'))
            for att_id in attachment_ids:
                att_meta = await g.redis_client.hgetall(f"file:{att_id}")
                
                # Firestore fallback for file metadata
                if not att_meta and self.db:
                    try:
                        file_doc = self.db.collection('files').document(att_id).get()
                        if file_doc.exists:
                            fb_data = file_doc.to_dict()
                            att_meta = {
                                'id': att_id,
                                'filename': fb_data.get('filename', ''),
                                'file_type': fb_data.get('file_type', 'document'),
                                'size': str(fb_data.get('size', 0)),
                                'url': fb_data.get('url', ''),
                                'thumbnail_url': fb_data.get('thumbnail_url', '')
                            }
                            # Cache back to Redis
                            await g.redis_client.hset(f"file:{att_id}", mapping=att_meta)
                            logger.info(f"✅ Restored file {att_id} metadata from Firestore")
                    except Exception as fb_err:
                        logger.warning(f"Firestore file fallback failed for {att_id}: {fb_err}")
                
                if att_meta:
                    attachments.append({
                        "id": att_id,
                        "filename": att_meta.get('filename'),
                        "type": att_meta.get('file_type'),
                        "size": int(att_meta.get('size', 0)),
                        "url": att_meta.get('url'),
                        "thumbnail_url": att_meta.get('thumbnail_url')
                    })

            reply_to_info = None
            if msg_data.get('reply_to_data'):
                try:
                    reply_to_info = json.loads(msg_data.get('reply_to_data'))
                except:
                    reply_to_info = None
            elif msg_data.get('reply_to'):
                reply_msg = await g.redis_client.hgetall(f"message:{msg_data.get('reply_to')}")
                if reply_msg:
                    reply_sender = await g.redis_client.hgetall(
                        f"user:{reply_msg.get('sender_id')}"
                    )
                    reply_to_info = {
                        "id": msg_data.get('reply_to'),
                        "content": reply_msg.get('content', ''),
                        "sender": {
                            "id": reply_msg.get('sender_id'),
                            "username": reply_sender.get('username', 'Unknown'),
                            "avatar_url": reply_sender.get('avatar_url', '')
                        },
                        "message_type": reply_msg.get('message_type', 'text')
                    }

            messages.append({
                "id": msg_id,
                "content": msg_data.get('content'),
                "encrypted": msg_data.get('encrypted') == 'True',
                "message_type": msg_data.get('message_type'),
                "attachments": attachments,
                "created_at": msg_data.get('created_at'),
                "edited": msg_data.get('edited') == 'True',
                "reply_to": msg_data.get('reply_to') or None,
                "reply_to_data": reply_to_info,
                "sender": {
                    "id": sender_id,
                    "username": sender_data.get('username'),
                    "avatar_url": sender_data.get('avatar_url')
                }
            })

        messages.reverse()
        return web.json_response({"messages": messages})

    except Exception as e:
        logger.error(f"Get messages error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def search_messages_in_chat(self, request):
    """Search messages in a specific chat - FIXED VERSION"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']
        query = request.query.get('q', '').strip().lower()

        logger.info(f"🔍 Searching chat {chat_id} for: '{query}'")

        if not query:
            return web.json_response({"messages": []})

        # --- PATCH START: membership check with Firestore fallback ---
        is_member = False
        try:
            is_member = await g.redis_client.sismember(f"chat_members:{chat_id}", user_id)
        except Exception as e:
            logger.warning(f"Redis membership check failed for chat {chat_id}: {e}")

        if not is_member and getattr(self, "db", None):
            try:
                chat_doc = self.db.collection('chats').document(chat_id).get()
                if chat_doc and chat_doc.exists:
                    chat_data = chat_doc.to_dict()
                    members = (
                        chat_data.get('members')
                        or chat_data.get('participant_ids')
                        or chat_data.get('member_ids')
                        or []
                    )
                    member_ids = []
                    if isinstance(members, list):
                        if members and isinstance(members[0], dict):
                            member_ids = [
                                m.get('id') or m.get('user_id') or m.get('uid')
                                for m in members if isinstance(m, dict)
                            ]
                        else:
                            member_ids = [m for m in members if isinstance(m, (str, int))]
                    if str(user_id) in [str(mid) for mid in member_ids]:
                        is_member = True
            except Exception as fb_err:
                logger.error(f"Firestore membership check error for chat {chat_id}: {fb_err}")

        if not is_member:
            return web.json_response({"error": "Forbidden"}, status=403)
        # --- PATCH END ---

        # ✅ PATCH: load delete-for-me messages
        deleted_for_me = await g.redis_client.smembers(f"deleted_messages:{user_id}")
        deleted_for_me = set(
            m.decode() if isinstance(m, bytes) else m
            for m in deleted_for_me
        )

        results = []

        # --- REDIS SEARCH ---
        message_ids = await g.redis_client.lrange(f"chat_messages:{chat_id}", 0, -1)
        logger.info(f"📋 Searching {len(message_ids)} messages in Redis")

        for msg_id in message_ids:
            # ✅ Respect delete-for-me
            if msg_id in deleted_for_me:
                continue

            msg_data = await g.redis_client.hgetall(f"message:{msg_id}")
            if not msg_data or msg_data.get('deleted') == 'True':
                continue

            content = msg_data.get('content', '').lower()
            if query not in content:
                continue

            sender_id = msg_data.get('sender_id')
            sender_data = await g.redis_client.hgetall(f"user:{sender_id}")

            results.append({
                "id": msg_id,  # ✅ FIXED (was msg_data.get('id'))
                "content": msg_data.get('content'),
                "created_at": msg_data.get('created_at'),
                "sender": {
                    "id": sender_id,
                    "username": sender_data.get('username', 'Unknown'),
                    "avatar_url": sender_data.get('avatar_url', '')
                }
            })

        # --- FIRESTORE FALLBACK ---
        if not results and getattr(self, "db", None):
            logger.info(f"📥 Redis empty, checking Firestore...")

            try:
                messages_ref = (
                    self.db.collection('chats')
                    .document(chat_id)
                    .collection('messages')
                )
                messages_query = messages_ref.order_by(
                    'created_at',
                    direction=firestore.Query.DESCENDING
                ).limit(500)

                for msg_doc in messages_query.stream():
                    msg_data = msg_doc.to_dict()

                    if msg_data.get('deleted'):
                        continue

                    # ✅ Respect delete-for-me
                    if str(msg_doc.id) in deleted_for_me:
                        continue

                    content = (msg_data.get('content') or '').lower()
                    if query not in content:
                        continue

                    sender_id = msg_data.get('sender_id')
                    sender_data = await g.redis_client.hgetall(f"user:{sender_id}")

                    created_at_raw = msg_data.get('created_at')
                    if created_at_raw:
                        try:
                            created_at_str = (
                                created_at_raw.isoformat()
                                if hasattr(created_at_raw, 'isoformat')
                                else str(created_at_raw)
                            )
                        except Exception:
                            created_at_str = datetime.datetime.now(datetime.UTC).isoformat()
                    else:
                        created_at_str = datetime.datetime.now(datetime.UTC).isoformat()

                    results.append({
                        "id": msg_doc.id,
                        "content": msg_data.get('content', ''),
                        "created_at": created_at_str,
                        "sender": {
                            "id": sender_id,
                            "username": sender_data.get('username', 'Unknown') if sender_data else 'Unknown',
                            "avatar_url": sender_data.get('avatar_url', '') if sender_data else ''
                        }
                    })

            except Exception as fb_err:
                logger.error(f"❌ Firestore search error: {fb_err}")

        logger.info(f"✅ Found {len(results)} matching messages")

        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return web.json_response({"messages": results[:50]})

    except Exception as e:
        logger.error(f"❌ Search error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def send_message_http(self, request):
    """Send message via HTTP"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']
        data = await request.json()

        # Check membership
        is_member = await g.redis_client.sismember(f"chat_members:{chat_id}", user_id)
        if not is_member:
            return web.json_response({"error": "Forbidden"}, status=403)

        # Create message
        message_id = await self.create_message(
            chat_id=chat_id,
            sender_id=user_id,
            content=data.get('content', ''),
            message_type=data.get('message_type', 'text'),
            encrypted=data.get('encrypted', True),
            attachments=data.get('attachments', []),
            reply_to=data.get('reply_to')
        )

        return web.json_response({
            "success": True,
            "message_id": message_id
        })

    except Exception as e:
        logger.error(f"Send message error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def delete_message(self, request):
    """Delete message"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        message_id = request.match_info['message_id']
        msg_data = await g.redis_client.hgetall(f"message:{message_id}")

        if msg_data.get('sender_id') != user_id:
            return web.json_response({"error": "Can only delete own messages"}, status=403)

        await g.redis_client.hset(f"message:{message_id}", "deleted", "True")

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Delete message error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def edit_message(self, request):
    """Edit message"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        message_id = request.match_info['message_id']
        data = await request.json()
        new_content = data.get('content', '').strip()

        if not new_content:
            return web.json_response({"error": "Content required"}, status=400)

        msg_data = await g.redis_client.hgetall(f"message:{message_id}")

        if msg_data.get('sender_id') != user_id:
            return web.json_response({"error": "Can only edit own messages"}, status=403)

        await g.redis_client.hset(f"message:{message_id}", mapping={
            "content": new_content,
            "edited": "True",
            "edited_at": datetime.datetime.now(datetime.UTC).isoformat()
        })

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Edit message error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def delete_message_for_all(self, request):
    """Delete message for everyone"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        message_id = request.match_info['message_id']
        msg_data = await g.redis_client.hgetall(f"message:{message_id}")

        if not msg_data or msg_data.get('sender_id') != user_id:
            return web.json_response({"error": "Cannot delete"}, status=403)

        # Check if less than 1 hour old
        created_at = datetime.datetime.fromisoformat(msg_data.get('created_at'))
        if datetime.datetime.now(datetime.UTC) - created_at > timedelta(hours=1):
            return web.json_response({"error": "Can only delete within 1 hour"}, status=400)

        # Redis soft delete (UNCHANGED)
        await g.redis_client.hset(f"message:{message_id}", mapping={
            "deleted": "True",
            "deleted_for_everyone": "True",
            "content": "This message was deleted",
            "deleted_at": datetime.datetime.now(datetime.UTC).isoformat()
        })

        chat_id = msg_data.get('chat_id')

        # 🔥 FIXED: Firestore persistence (restart-safe)
        if getattr(self, "db", None) and chat_id:
            try:
                self.db.collection("chats") \
                    .document(chat_id) \
                    .collection("messages") \
                    .document(message_id) \
                    .set({
                        "deleted": True,
                        "deleted_for_everyone": True,
                        "content": "This message was deleted",
                        "deleted_at": firestore.SERVER_TIMESTAMP
                    }, merge=True)
            except Exception as fs_err:
                logger.error(f"Firestore delete-for-all sync failed: {fs_err}")

        member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")
        
        await self.broadcast_to_users(list(member_ids), {
            "type": "message_deleted",
            "message_id": message_id,
            "chat_id": chat_id,
            "deleted_for_everyone": True
        })

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Delete error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def delete_message_for_me(self, request):
    """Delete message for current user only"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        message_id = request.match_info['message_id']

        # Redis cache (UNCHANGED)
        await g.redis_client.sadd(f"deleted_messages:{user_id}", message_id)

        # 🔥 FIXED: Firestore persistence (restart-safe)
        if getattr(self, "db", None):
            try:
                self.db.collection("users") \
                    .document(user_id) \
                    .collection("deleted_messages") \
                    .document(message_id) \
                    .set({
                        "deleted_at": firestore.SERVER_TIMESTAMP
                    }, merge=True)
            except Exception as fs_err:
                logger.error(f"Firestore delete-for-me sync failed: {fs_err}")

        return web.json_response({"success": True})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def forward_message(self, request):
    """Forward message to other chats"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        message_id = data.get('message_id')
        target_chat_ids = data.get('chat_ids', [])

        logger.info(f"📤 Forwarding message {message_id} to {len(target_chat_ids)} chats")

        if not message_id or not target_chat_ids:
            return web.json_response({"error": "Invalid request"}, status=400)

        # Get original message
        msg_data = await g.redis_client.hgetall(f"message:{message_id}")
        if not msg_data:
            logger.error(f"❌ Message {message_id} not found")
            return web.json_response({"error": "Message not found"}, status=404)

        logger.info(f"✅ Found message to forward: {msg_data.get('content', '')[:50]}")

        forwarded_ids = []
        for chat_id in target_chat_ids:
            # Check if user is member
            is_member = await g.redis_client.sismember(f"chat_members:{chat_id}", user_id)
            if not is_member:
                logger.warning(f"⚠️ User {user_id} not member of chat {chat_id}, skipping")
                continue

            try:
                # Create forwarded message
                new_msg_id = await self.create_message(
                    chat_id=chat_id,
                    sender_id=user_id,
                    content=msg_data.get('content', ''),
                    message_type=msg_data.get('message_type', 'text'),
                    encrypted=msg_data.get('encrypted') == 'True',
                    attachments=json.loads(msg_data.get('attachments', '[]'))
                )
                
                forwarded_ids.append(new_msg_id)
                logger.info(f"✅ Forwarded to chat {chat_id}: {new_msg_id}")
                
            except Exception as fwd_error:
                logger.error(f"❌ Failed to forward to chat {chat_id}: {fwd_error}")
                continue

        logger.info(f"✅ Successfully forwarded to {len(forwarded_ids)} chats")

        return web.json_response({
            "success": True,
            "forwarded_count": len(forwarded_ids)
        })

    except Exception as e:
        logger.error(f"❌ Forward error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

