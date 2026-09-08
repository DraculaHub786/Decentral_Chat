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
async def get_chats(self, request):
    """Get user's chats - with Firestore fallback for missing data"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_ids = await g.redis_client.smembers(f"user_chats:{user_id}")
        
        # 🔥 FIX: If Redis returns empty, try Firestore
        if not chat_ids and self.db:
            logger.warning(f"⚠️ Redis has no chats for user {user_id}, attempting Firestore fallback...")
            try:
                # Search all chats in Firestore where user is a member
                chats_ref = self.db.collection('chats')
                # Firestore doesn't support array-contains-any with large lists well,
                # so scan all chats and filter
                all_chats = list(chats_ref.stream())
                for chat_doc in all_chats:
                    chat_data_fb = chat_doc.to_dict()
                    members = chat_data_fb.get('members', [])
                    if user_id in members:
                        # Found a chat for this user - restore to Redis
                        chat_id = chat_doc.id
                        await g.redis_client.sadd(f"user_chats:{user_id}", chat_id)
                        chat_ids.add(chat_id)
                        logger.info(f"✅ Restored chat {chat_id} to Redis for user {user_id}")
                
                if chat_ids:
                    logger.info(f"✅ Restored {len(chat_ids)} chats from Firestore to Redis")
            except Exception as fb_err:
                logger.error(f"Firestore fallback failed: {fb_err}")

        chats = []

        for chat_id in chat_ids:
            chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
            if not chat_data:
                # Try Firestore fallback for individual chat data
                if self.db:
                    try:
                        chat_doc = self.db.collection('chats').document(chat_id).get()
                        if chat_doc.exists:
                            fb_data = chat_doc.to_dict()
                            chat_data = {
                                'id': chat_id,
                                'type': fb_data.get('type', 'direct'),
                                'name': fb_data.get('name', ''),
                                'description': fb_data.get('description', ''),
                                'avatar_url': fb_data.get('avatar_url', ''),
                                'created_by': fb_data.get('created_by', ''),
                                'created_at': str(fb_data.get('created_at', ''))
                            }
                            await g.redis_client.hset(f"chat:{chat_id}", mapping=chat_data)
                            logger.info(f"✅ Restored chat {chat_id} data from Firestore")
                            
                            # Also restore members
                            members = fb_data.get('members', [])
                            for member_id in members:
                                await g.redis_client.sadd(f"chat_members:{chat_id}", member_id)
                                await g.redis_client.sadd(f"user_chats:{member_id}", chat_id)
                    except Exception as fb_err:
                        logger.warning(f"Chat Firestore fallback failed for {chat_id}: {fb_err}")
                
                if not chat_data:
                    continue

            # Get last message
            last_msg_ids = await g.redis_client.lrange(f"chat_messages:{chat_id}", 0, 0)
            last_message = ""
            last_message_time = None
            last_message_type = "text"

            if last_msg_ids:
                last_msg_data = await g.redis_client.hgetall(f"message:{last_msg_ids[0]}")
                if last_msg_data:
                    last_message = last_msg_data.get('content', '')[:50]
                    last_message_time = last_msg_data.get('created_at')
                    last_message_type = last_msg_data.get('message_type', 'text')

            # Get members
            member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")

            chat_info = {
                "id": chat_id,
                "type": chat_data.get('type'),
                "last_message": last_message,
                "last_message_time": last_message_time,
                "last_message_type": last_message_type,
                "unread_count": 0
            }

            if chat_data.get('type') == 'direct':
                # Find other user
                other_user_id = next((m for m in member_ids if m != user_id), None)
                if other_user_id:
                    other_user = await g.redis_client.hgetall(f"user:{other_user_id}")
                    chat_info.update({
                        "name": other_user.get('username'),
                        "avatar_url": other_user.get('avatar_url'),
                        "status": other_user.get('status'),
                        "last_seen": other_user.get('last_seen'),
                        "other_user_id": other_user_id
                    })
            else:
                # Group chat
                chat_info.update({
                    "name": chat_data.get('name'),
                    "description": chat_data.get('description'),
                    "avatar_url": chat_data.get('avatar_url'),
                    "member_count": len(member_ids),
                    "member_ids": list(member_ids)  # 🔒 Include member IDs for E2E group encryption
                })

            chats.append(chat_info)

        # Sort by last message time
        chats.sort(key=lambda x: x.get('last_message_time') or '', reverse=True)

        return web.json_response({"chats": chats})

    except Exception as e:
        logger.error(f"Get chats error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def create_chat(self, request):
    """Create new chat (direct or group) - FIXED VERSION"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        chat_type = data.get('type', 'direct')
        participants = data.get('participants', [])

        logger.info(f"📝 Creating {chat_type} chat: user {user_id} with {participants}")

        if chat_type == 'direct':
            if len(participants) != 1:
                return web.json_response({"error": "Direct chat requires 1 participant"}, status=400)

            other_user_id = participants[0]

            # Check if chat already exists
            user_chats = await g.redis_client.smembers(f"user_chats:{user_id}")
            for existing_chat_id in user_chats:
                chat_data = await g.redis_client.hgetall(f"chat:{existing_chat_id}")
                if chat_data.get('type') == 'direct':
                    members = await g.redis_client.smembers(f"chat_members:{existing_chat_id}")
                    if other_user_id in members and user_id in members:
                        logger.info(f"✅ Chat already exists: {existing_chat_id}")
                        return web.json_response({
                            "success": True,
                            "chat_id": existing_chat_id,
                            "message": "Chat already exists"
                        })

            # Create new direct chat
            chat_id = str(uuid.uuid4())
            chat_data = {
                "id": chat_id,
                "type": "direct",
                "created_by": user_id,
                "created_at": datetime.datetime.now(datetime.UTC).isoformat()
            }

            await g.redis_client.hset(f"chat:{chat_id}", mapping=chat_data)
            await g.redis_client.sadd("chats:all", chat_id)

            # ✅ CRITICAL: Add members to chat AND chat to user lists
            for member_id in [user_id, other_user_id]:
                await g.redis_client.sadd(f"chat_members:{chat_id}", member_id)
                await g.redis_client.sadd(f"user_chats:{member_id}", chat_id)
                logger.info(f"✅ Added chat {chat_id} to user {member_id}")

            # Save to Firestore
            if self.db:
                try:
                    self.db.collection('chats').document(chat_id).set({
                        'id': chat_id,
                        'type': 'direct',
                        'created_by': user_id,
                        'created_at': firestore.SERVER_TIMESTAMP,
                        'members': [user_id, other_user_id]
                    })
                    logger.info(f"✅ Chat {chat_id} saved to Firestore")
                except Exception as fb_err:
                    logger.error(f"Firestore save failed: {fb_err}")

        else:  # Group chat
            if len(participants) < 2:
                return web.json_response({"error": "Group requires at least 2 participants"}, status=400)

            name = data.get('name', 'New Group')
            description = data.get('description', '')

            chat_id = str(uuid.uuid4())
            chat_data = {
                "id": chat_id,
                "type": "group",
                "name": name,
                "description": description,
                "avatar_url": "",
                "created_by": user_id,
                "created_at": datetime.datetime.now(datetime.UTC).isoformat()
            }

            await g.redis_client.hset(f"chat:{chat_id}", mapping=chat_data)
            await g.redis_client.sadd("chats:all", chat_id)

            # Add creator as admin
            await g.redis_client.hset(f"chat_member:{chat_id}:{user_id}", mapping={
                "role": "admin",
                "joined_at": datetime.datetime.now(datetime.UTC).isoformat()
            })
            await g.redis_client.sadd(f"chat_members:{chat_id}", user_id)
            await g.redis_client.sadd(f"user_chats:{user_id}", chat_id)

            # Add participants as members
            for member_id in participants:
                await g.redis_client.hset(f"chat_member:{chat_id}:{member_id}", mapping={
                    "role": "member",
                    "joined_at": datetime.datetime.now(datetime.UTC).isoformat()
                })
                await g.redis_client.sadd(f"chat_members:{chat_id}", member_id)
                await g.redis_client.sadd(f"user_chats:{member_id}", chat_id)

            # Save to Firestore
            if self.db:
                try:
                    self.db.collection('chats').document(chat_id).set({
                        'id': chat_id,
                        'type': 'group',
                        'name': name,
                        'description': description,
                        'created_by': user_id,
                        'created_at': firestore.SERVER_TIMESTAMP,
                        'members': [user_id] + participants
                    })
                    logger.info(f"✅ Group chat {chat_id} saved to Firestore")
                except Exception as fb_err:
                    logger.error(f"Firestore save failed: {fb_err}")

        logger.info(f"✅ Chat created successfully: {chat_id}")

        return web.json_response({
            "success": True,
            "chat_id": chat_id
        })

    except Exception as e:
        logger.error(f"❌ Create chat error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def get_chat(self, request):
    """Get chat details - FIXED to return complete member info"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']

        # Check membership
        is_member = await g.redis_client.sismember(f"chat_members:{chat_id}", user_id)
        if not is_member:
            return web.json_response({"error": "Forbidden"}, status=403)

        chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
        if not chat_data:
            return web.json_response({"error": "Chat not found"}, status=404)
        # Get member IDs from Firestore (REAL source of truth)
        if self.db:
            chat_doc = self.db.collection('chats').document(chat_id).get()
            if chat_doc.exists:
                member_ids = chat_doc.to_dict().get("members", [])
            else:
                member_ids = []
        else:
            member_ids = []

        member_ids = [m.decode() if isinstance(m, bytes) else m for m in member_ids]
        members = []

        logger.info(f"📋 Loading {len(member_ids)} members for chat {chat_id}")

        for member_id in member_ids:
            # Try Redis first
            member_data = await g.redis_client.hgetall(f"user:{member_id}")
            
            # If not in Redis, try Firestore
            if not member_data and self.db:
                try:
                    user_doc = self.db.collection('users').document(member_id).get()
                    if user_doc.exists:
                        fb_data = user_doc.to_dict()
                        member_data = {
                            'id': member_id,
                            'username': fb_data.get('username', 'Unknown'),
                            'email': fb_data.get('email', ''),
                            'avatar_url': fb_data.get('avatar_url', ''),
                            'status': 'offline'
                        }
                        # Cache in Redis
                        await g.redis_client.hset(f"user:{member_id}", mapping=member_data)
                        logger.info(f"✅ Loaded user {member_id} from Firestore")
                except Exception as fb_err:
                    logger.error(f"Failed to load user {member_id} from Firestore: {fb_err}")
            
            if member_data:
                # Get role for group chats
                if chat_data.get('type') == 'group':
                    if member_id == chat_data.get('created_by'):
                        member_role = 'admin'
                    else:
                        member_role_data = await g.redis_client.hgetall(f"chat_member:{chat_id}:{member_id}")
                        member_role = member_role_data.get('role', 'member')
                else:
                    member_role = None

                members.append({
                    "id": member_id,
                    "username": member_data.get('username', 'Unknown'),
                    "email": member_data.get('email', ''),
                    "avatar_url": member_data.get('avatar_url', ''),
                    "status": member_data.get('status', 'offline'),
                    "role": member_role
                })
            else:
                logger.warning(f"⚠️ Could not load data for member {member_id}")

        logger.info(f"✅ Loaded {len(members)} members successfully")

        return web.json_response({
            "chat": {
                "id": chat_id,
                "type": chat_data.get('type'),
                "name": chat_data.get('name'),
                "description": chat_data.get('description'),
                "avatar_url": chat_data.get('avatar_url'),
                "created_by": chat_data.get('created_by'),
                "created_at": chat_data.get('created_at'),
                "members": members
            }
        })

    except Exception as e:
        logger.error(f"Get chat error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def delete_chat(self, request):
    """Delete chat"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']

        chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
        if chat_data.get('created_by') != user_id:
            return web.json_response({"error": "Only creator can delete chat"}, status=403)

        # Remove from all members
        member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")
        for member_id in member_ids:
            await g.redis_client.srem(f"user_chats:{member_id}", chat_id)

        # Delete chat data
        await g.redis_client.delete(f"chat:{chat_id}")
        await g.redis_client.delete(f"chat_members:{chat_id}")
        await g.redis_client.delete(f"chat_messages:{chat_id}")
        await g.redis_client.srem("chats:all", chat_id)

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Delete chat error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def add_chat_member(self, request):
    """Add member to group chat - FIXED VERSION"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']
        data = await request.json()
        new_member_id = data.get('user_id')

        if not new_member_id:
            return web.json_response({"error": "User ID required"}, status=400)

        # Get chat data
        chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
        
        if chat_data.get('type') != 'group':
            return web.json_response({"error": "Not a group chat"}, status=400)

        # Check if user is admin or creator
        is_creator = chat_data.get('created_by') == user_id
        member_role = await g.redis_client.hgetall(f"chat_member:{chat_id}:{user_id}")
        is_admin = member_role.get('role') == 'admin'

        if not is_creator and not is_admin:
            return web.json_response({"error": "Only admins can add members"}, status=403)

        # Check if user already a member
        is_already_member = await g.redis_client.sismember(f"chat_members:{chat_id}", new_member_id)
        if is_already_member:
            return web.json_response({"error": "User is already a member"}, status=400)

        # Add member to Redis
        await g.redis_client.hset(f"chat_member:{chat_id}:{new_member_id}", mapping={
            "role": "member",
            "joined_at": datetime.datetime.now(datetime.UTC).isoformat()
        })
        await g.redis_client.sadd(f"chat_members:{chat_id}", new_member_id)
        await g.redis_client.sadd(f"user_chats:{new_member_id}", chat_id)

        # Update Firestore
        if self.db:
            try:
                chat_ref = self.db.collection('chats').document(chat_id)

                # Ensure Firestore always has proper members array
                chat_snapshot = chat_ref.get()
                if chat_snapshot.exists:
                    chat_doc = chat_snapshot.to_dict()
                    existing_members = chat_doc.get("members", [])
                else:
                    existing_members = []

                # Add member ONLY if not already present
                if new_member_id not in existing_members:
                    existing_members.append(new_member_id)

                chat_ref.update({
                    "members": existing_members
                })

                logger.info(f"🔥 Firestore members updated: {existing_members}")

            except Exception as fb_err:
                logger.error(f"Firestore member add failed: {fb_err}")

        # Notify all members including new member
        member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")
        await self.broadcast_to_users(list(member_ids), {
            "type": "member_added",
            "chat_id": chat_id,
            "member_id": new_member_id
        })

        logger.info(f"✅ Added member {new_member_id} to chat {chat_id}")

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Add member error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def remove_chat_member(self, request):
    """Remove member from group chat"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']
        member_to_remove = request.match_info['user_id']

        # Check if user is admin
        member_role = await g.redis_client.hgetall(f"chat_member:{chat_id}:{user_id}")
        if member_role.get('role') != 'admin' and user_id != member_to_remove:
            return web.json_response({"error": "Only admins can remove members"}, status=403)

        # Remove member
        await g.redis_client.delete(f"chat_member:{chat_id}:{member_to_remove}")
        await g.redis_client.srem(f"chat_members:{chat_id}", member_to_remove)
        await g.redis_client.srem(f"user_chats:{member_to_remove}", chat_id)

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Remove member error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def update_group_chat(self, request):
    """Update group chat name, description, avatar"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        chat_id = request.match_info['chat_id']
        data = await request.json()

        # Check if user is admin
        chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
        if chat_data.get('type') != 'group':
            return web.json_response({"error": "Not a group chat"}, status=400)

        member_role = await g.redis_client.hgetall(f"chat_member:{chat_id}:{user_id}")
        if member_role.get('role') != 'admin' and chat_data.get('created_by') != user_id:
            return web.json_response({"error": "Only admins can update group"}, status=403)

        updates = {}
        
        if 'name' in data and data['name'].strip():
            updates['name'] = data['name'].strip()[:100]
        
        if 'description' in data:
            updates['description'] = data['description'].strip()[:500]
        
        if 'avatar_url' in data:
            updates['avatar_url'] = data['avatar_url']

        if updates:
            updates['updated_at'] = datetime.datetime.now(datetime.UTC).isoformat()
            
            # Update Redis
            await g.redis_client.hset(f"chat:{chat_id}", mapping=updates)
            
            # Update Firestore
            if self.db:
                try:
                    self.db.collection('chats').document(chat_id).update(updates)
                    logger.info(f"✅ Group {chat_id} updated in Firestore")
                except Exception as fb_err:
                    logger.error(f"Firestore group update failed: {fb_err}")
            
            # Notify members
            member_ids = await g.redis_client.smembers(f"chat_members:{chat_id}")
            await self.broadcast_to_users(list(member_ids), {
                "type": "group_updated",
                "chat_id": chat_id,
                "updates": updates
            })

        return web.json_response({"success": True, "updates": updates})

    except Exception as e:
        logger.error(f"Update group error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

