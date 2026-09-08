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
async def get_contacts(self, request):
    """Get user contacts"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        contact_ids = await g.redis_client.smembers(f"user_contacts:{user_id}")
        contacts = []

        for contact_id in contact_ids:
            contact_data = await g.redis_client.hgetall(f"user:{contact_id}")
            if contact_data:
                contacts.append({
                    "id": contact_id,
                    "username": contact_data.get('username'),
                    "email": contact_data.get('email'),
                    "avatar_url": contact_data.get('avatar_url'),
                    "status": contact_data.get('status'),
                    "last_seen": contact_data.get('last_seen')
                })

        return web.json_response({"contacts": contacts})

    except Exception as e:
        logger.error(f"Get contacts error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def add_contact(self, request):
    """Add contact by username/email"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        identifier = data.get('identifier', '').strip()

        # Find user - try case-insensitive username search first
        contact_id = await g.redis_client.hget("username_map", identifier)
        
        # If not found, try lowercase version for case-insensitive search
        if not contact_id:
            contact_id = await g.redis_client.hget("username_map", identifier.lower())
        
        # If still not found and looks like email, search email map
        if not contact_id and '@' in identifier:
            contact_id = await g.redis_client.hget("email_map", identifier)
            if not contact_id:
                contact_id = await g.redis_client.hget("email_map", identifier.lower())

        if not contact_id:
            return web.json_response({"error": "User not found", "success": False}, status=404)

        if contact_id == user_id:
            return web.json_response({"error": "Cannot add yourself", "success": False}, status=400)
        
        # Check if contact already exists
        is_already_contact = await g.redis_client.sismember(f"user_contacts:{user_id}", contact_id)
        if is_already_contact:
            logger.info(f"ℹ️ Contact already exists: {user_id} -> {contact_id}")
            return web.json_response({"success": True, "message": "Contact already added"})

        # Add to contacts
        await g.redis_client.sadd(f"user_contacts:{user_id}", contact_id)
        await g.redis_client.sadd(f"user_contacts:{contact_id}", user_id)
        if self.db:
            try:
                self.db.collection('users').document(user_id).collection('contacts').document(contact_id).set({
                    'added_at': firestore.SERVER_TIMESTAMP,
                    'status': 'active'
                })
                self.db.collection('users').document(contact_id).collection('contacts').document(user_id).set({
                    'added_at': firestore.SERVER_TIMESTAMP,
                    'status': 'active'
                })
                logger.info(f"✅ Contact saved to Firestore: {user_id} <-> {contact_id}")
            except Exception as fb_err:
                logger.error(f"Firestore contact save failed: {fb_err}")

        logger.info(f"✅ Contact added: {user_id} -> {contact_id}")

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Add contact error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def remove_contact(self, request):
    """Remove contact and associated direct chat"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        contact_id = request.match_info['contact_id']

        # Remove from contacts
        await g.redis_client.srem(f"user_contacts:{user_id}", contact_id)
        await g.redis_client.srem(f"user_contacts:{contact_id}", user_id)
        
        # ✅ NEW: Find and remove direct chat between these users
        user_chats = await g.redis_client.smembers(f"user_chats:{user_id}")
        
        for chat_id in user_chats:
            chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
            
            # Only remove direct chats, not groups
            if chat_data.get('type') == 'direct':
                members = await g.redis_client.smembers(f"chat_members:{chat_id}")
                
                # If this chat is between user and contact, remove it
                if contact_id in members and user_id in members and len(members) == 2:
                    logger.info(f"🗑️ Removing direct chat {chat_id} between {user_id} and {contact_id}")
                    
                    # Remove chat from both users
                    await g.redis_client.srem(f"user_chats:{user_id}", chat_id)
                    await g.redis_client.srem(f"user_chats:{contact_id}", chat_id)
                    
                    # Remove members
                    await g.redis_client.delete(f"chat_members:{chat_id}")
                    
                    # Delete chat messages
                    message_ids = await g.redis_client.lrange(f"chat_messages:{chat_id}", 0, -1)
                    for msg_id in message_ids:
                        await g.redis_client.delete(f"message:{msg_id}")
                    await g.redis_client.delete(f"chat_messages:{chat_id}")
                    
                    # Delete chat itself
                    await g.redis_client.delete(f"chat:{chat_id}")
                    await g.redis_client.srem("chats:all", chat_id)
                    
                    # Delete from Firestore
                    if self.db:
                        try:
                            # Delete messages subcollection
                            messages_ref = self.db.collection('chats').document(chat_id).collection('messages')
                            for msg_doc in messages_ref.stream():
                                msg_doc.reference.delete()
                            
                            # Delete chat document
                            self.db.collection('chats').document(chat_id).delete()
                            logger.info(f"✅ Deleted chat {chat_id} from Firestore")
                        except Exception as fb_err:
                            logger.error(f"Firestore chat delete failed: {fb_err}")
        
        # Remove from Firestore contacts
        if self.db:
            try:
                self.db.collection('users').document(user_id).collection('contacts').document(contact_id).delete()
                self.db.collection('users').document(contact_id).collection('contacts').document(user_id).delete()
            except Exception as fb_err:
                logger.error(f"Firestore contact delete failed: {fb_err}")

        logger.info(f"✅ Contact and chat removed: {user_id} removed {contact_id}")

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Remove contact error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def block_user(self, request):
    """Block a user - Complete implementation"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        blocked_user_id = data.get('user_id')

        if not blocked_user_id:
            return web.json_response({"error": "User ID required"}, status=400)

        if blocked_user_id == user_id:
            return web.json_response({"error": "Cannot block yourself"}, status=400)

        # Check if already blocked
        is_already_blocked = await g.redis_client.sismember(f"user_blocked:{user_id}", blocked_user_id)
        if is_already_blocked:
            return web.json_response({"error": "User already blocked"}, status=400)

        # Add to blocked list in Redis
        await g.redis_client.sadd(f"user_blocked:{user_id}", blocked_user_id)
        
        # Remove from contacts if exists
        await g.redis_client.srem(f"user_contacts:{user_id}", blocked_user_id)
        await g.redis_client.srem(f"user_contacts:{blocked_user_id}", user_id)

        # Save to Firestore
        if self.db:
            try:
                self.db.collection('users').document(user_id).collection('blocked').document(blocked_user_id).set({
                    'blocked_at': firestore.SERVER_TIMESTAMP,
                    'status': 'blocked'
                })
                # Remove contact relationship
                self.db.collection('users').document(user_id).collection('contacts').document(blocked_user_id).delete()
                self.db.collection('users').document(blocked_user_id).collection('contacts').document(user_id).delete()
                logger.info(f"✅ User {blocked_user_id} blocked by {user_id} in Firestore")
            except Exception as fb_err:
                logger.error(f"Firestore block save failed: {fb_err}")

        logger.info(f"✅ User {user_id} blocked {blocked_user_id}")

        # Notify the blocked user via WebSocket
        await self.broadcast_to_users([blocked_user_id], {
            "type": "user_blocked",
            "blocked_by": user_id
        })

        return web.json_response({
            "success": True,
            "message": "User blocked successfully"
        })

    except Exception as e:
        logger.error(f"Block user error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def unblock_user(self, request):
    """Unblock a user - Complete implementation"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        blocked_user_id = data.get('user_id')

        if not blocked_user_id:
            return web.json_response({"error": "User ID required"}, status=400)

        # Check if actually blocked
        is_blocked = await g.redis_client.sismember(f"user_blocked:{user_id}", blocked_user_id)
        if not is_blocked:
            return web.json_response({"error": "User is not blocked"}, status=400)

        # Remove from blocked list
        await g.redis_client.srem(f"user_blocked:{user_id}", blocked_user_id)

        # Remove from Firestore
        if self.db:
            try:
                self.db.collection('users').document(user_id).collection('blocked').document(blocked_user_id).delete()
                logger.info(f"✅ User {blocked_user_id} unblocked by {user_id} in Firestore")
            except Exception as fb_err:
                logger.error(f"Firestore unblock failed: {fb_err}")

        logger.info(f"✅ User {user_id} unblocked {blocked_user_id}")

        # Notify via WebSocket
        await self.broadcast_to_users([blocked_user_id], {
            "type": "user_unblocked",
            "unblocked_by": user_id
        })

        return web.json_response({
            "success": True,
            "message": "User unblocked successfully"
        })

    except Exception as e:
        logger.error(f"Unblock user error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def check_blocked_status(self, request):
    """Check if a user is blocked"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        other_user_id = request.match_info.get('user_id')
        if not other_user_id:
            return web.json_response({"error": "User ID required"}, status=400)

        # Check both directions
        i_blocked_them = await g.redis_client.sismember(f"user_blocked:{user_id}", other_user_id)
        they_blocked_me = await g.redis_client.sismember(f"user_blocked:{other_user_id}", user_id)

        return web.json_response({
            "i_blocked_them": bool(i_blocked_them),
            "they_blocked_me": bool(they_blocked_me),
            "is_blocked": bool(i_blocked_them or they_blocked_me)
        })

    except Exception as e:
        logger.error(f"Check blocked status error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_blocked_users(self, request):
    """Get list of blocked users"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        blocked_ids = await g.redis_client.smembers(f"user_blocked:{user_id}")
        blocked_users = []

        for blocked_id in blocked_ids:
            user_data = await g.redis_client.hgetall(f"user:{blocked_id}")
            if user_data:
                blocked_users.append({
                    "id": blocked_id,
                    "username": user_data.get('username'),
                    "avatar_url": user_data.get('avatar_url')
                })

        return web.json_response({"blocked_users": blocked_users})

    except Exception as e:
        logger.error(f"Get blocked users error: {e}")
        return web.json_response({"error": str(e)}, status=500)

