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
async def get_current_user(self, request):
    """Get current user profile"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        user_data = await g.redis_client.hgetall(f"user:{user_id}")
        if not user_data:
            return web.json_response({"error": "User not found"}, status=404)

        return web.json_response({
            "user": {
                "id": user_id,
                "username": user_data.get('username'),
                "email": user_data.get('email'),
                "phone": user_data.get('phone'),
                "role": user_data.get('role'),
                "status": user_data.get('status'),
                "avatar_url": user_data.get('avatar_url'),
                "bio": user_data.get('bio'),
                "created_at": user_data.get('created_at'),
                "settings": json.loads(user_data.get('settings', '{}'))
            }
        })

    except Exception as e:
        logger.error(f"Get user error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def update_profile(self, request):
    """Update user profile - ENHANCED VERSION with better error handling"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        updates = {}
        
        # Handle username change
        if 'username' in data:
            new_username = data['username'].strip()
            if len(new_username) >= 3:
                # Check if username is taken
                existing_user = await g.redis_client.hget("username_map", new_username)
                if existing_user and existing_user != user_id:
                    return web.json_response({"error": "Username already taken"}, status=400)
                
                # Remove old username mapping
                old_username = await g.redis_client.hget(f"user:{user_id}", "username")
                if old_username and old_username != new_username:
                    try:
                        await g.redis_client.hdel("username_map", old_username)
                        logger.info(f"✅ Removed old username mapping: {old_username}")
                    except Exception as hdel_error:
                        logger.warning(f"⚠️ Could not remove old username mapping: {hdel_error}")
                
                # Add new username mapping
                await g.redis_client.hset("username_map", new_username, user_id)
                updates['username'] = new_username
                logger.info(f"✅ Updated username: {old_username} -> {new_username}")
            else:
                return web.json_response({"error": "Username must be at least 3 characters"}, status=400)
        
        # Handle bio
        if 'bio' in data:
            updates['bio'] = data['bio'][:500]  # Limit to 500 chars
        
        # Handle public key for E2E encryption (base64-encoded ECDH public key)
        if 'public_key' in data and data['public_key']:
            pk = data['public_key'].strip()
            if len(pk) < 2000:  # Reasonable size limit for a P-256 public key
                updates['public_key'] = pk
                logger.info(f"✅ Stored public key for user {user_id}")
        
        # Handle avatar_url (when uploaded separately)
        if 'avatar_url' in data:
            updates['avatar_url'] = data['avatar_url']
        
        # Update Redis
        if updates:
            await g.redis_client.hset(f"user:{user_id}", mapping=updates)
            logger.info(f"✅ Updated user {user_id} in Redis: {list(updates.keys())}")
            
            # Update Firestore
            if self.db:
                try:
                    self.db.collection('users').document(user_id).set(updates, merge=True)
                    logger.info(f"✅ User {user_id} profile updated in Firestore")
                except Exception as fb_err:
                    logger.error(f"Firestore profile update failed: {fb_err}")
            
            # Notify contacts about profile change
            try:
                contact_ids = await g.redis_client.smembers(f"user_contacts:{user_id}")
                if contact_ids:
                    await self.broadcast_to_users(list(contact_ids), {
                        "type": "user_profile_updated",
                        "user_id": user_id,
                        "updates": updates
                    })
                    logger.info(f"✅ Notified {len(contact_ids)} contacts about profile update")
            except Exception as broadcast_err:
                logger.warning(f"⚠️ Could not notify contacts: {broadcast_err}")

        return web.json_response({"success": True, "updates": updates})

    except Exception as e:
        logger.error(f"Update profile error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def get_user_public_key(self, request):
    """Get a user's E2E encryption public key (ECDH)"""
    try:
        # Caller must be authenticated
        caller_id = await self.get_user_from_token(request)
        if not caller_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        target_user_id = request.match_info['user_id']

        # Fetch public key from Redis
        public_key = await g.redis_client.hget(f"user:{target_user_id}", "public_key")

        if not public_key:
            # Try Firestore as fallback
            if self.db:
                try:
                    doc = self.db.collection('users').document(target_user_id).get()
                    if doc.exists:
                        public_key = doc.to_dict().get('public_key')
                except Exception:
                    pass

        if not public_key:
            return web.json_response({"success": False, "public_key": None,
                                      "message": "User has not set up E2E encryption"}, status=200)

        return web.json_response({"success": True, "public_key": public_key})

    except Exception as e:
        logger.error(f"get_user_public_key error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def upload_avatar(self, request):
    """Upload user avatar - ENHANCED"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        reader = await request.multipart()
        field = await reader.next()

        if not field or field.name != 'file':
            return web.json_response({"error": "No file provided"}, status=400)

        # Save file
        file_id = str(uuid.uuid4())
        ext = field.filename.rsplit('.', 1)[-1].lower() if '.' in field.filename else 'jpg'
        
        # Validate extension
        if ext not in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
            return web.json_response({"error": "Invalid image format"}, status=400)
        
        file_path = UPLOAD_DIR / 'avatars' / f"{file_id}.{ext}"

        size = 0
        with open(file_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                if size > 5 * 1024 * 1024:  # 5MB limit
                    file_path.unlink()
                    return web.json_response({"error": "File too large (max 5MB)"}, status=400)
                f.write(chunk)

        avatar_url = f"/uploads/avatars/{file_id}.{ext}"
        
        # Delete old avatar if exists
        old_avatar = await g.redis_client.hget(f"user:{user_id}", "avatar_url")
        if old_avatar and old_avatar.startswith('/uploads/avatars/'):
            old_path = UPLOAD_DIR.parent / old_avatar.lstrip('/')
            if old_path.exists():
                try:
                    old_path.unlink()
                except:
                    pass
        
        # Update user
        await g.redis_client.hset(f"user:{user_id}", "avatar_url", avatar_url)
        
        # Update Firestore
        if self.db:
            try:
                self.db.collection('users').document(user_id).set({'avatar_url': avatar_url}, merge=True)
            except Exception as fb_err:
                logger.error(f"Firestore avatar update: {fb_err}")

        logger.info(f"✅ Avatar uploaded: {user_id}")

        return web.json_response({
            "success": True,
            "avatar_url": avatar_url
        })

    except Exception as e:
        logger.error(f"Avatar upload error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def update_email(self, request):
    """Update user email with verification"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        new_email = data.get('email', '').strip().lower()

        if not new_email or '@' not in new_email:
            return web.json_response({"error": "Invalid email"}, status=400)

        # Check if email already exists
        existing_user = await g.redis_client.hget("email_map", new_email)
        if existing_user and existing_user != user_id:
            return web.json_response({"error": "Email already in use"}, status=400)

        # Get old email
        old_email = await g.redis_client.hget(f"user:{user_id}", "email")
        
        # Remove old email mapping
        if old_email:
            await g.redis_client.hdel("email_map", old_email)
        
        # Update to new email
        await g.redis_client.hset(f"user:{user_id}", "email", new_email)
        await g.redis_client.hset("email_map", new_email, user_id)
        
        # Update Firestore
        if self.db:
            try:
                self.db.collection('users').document(user_id).set({'email': new_email}, merge=True)
            except Exception as fb_err:
                logger.error(f"Firestore email update: {fb_err}")

        return web.json_response({"success": True, "email": new_email})

    except Exception as e:
        logger.error(f"Update email error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def update_phone(self, request):
    """Update user phone number with verification"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        new_phone = data.get('phone', '').strip()
        verification_code = data.get('code', '').strip()

        if not new_phone or not new_phone.startswith('+'):
            return web.json_response({"error": "Invalid phone format (must include country code)"}, status=400)

        # Verify OTP
        if verification_code:
            stored_otp = await g.redis_client.get(f"otp:{new_phone}")
            if not stored_otp or stored_otp != verification_code:
                return web.json_response({"error": "Invalid or expired verification code"}, status=400)
            
            # Check if phone already exists
            existing_user = await g.redis_client.hget("phone_map", new_phone)
            if existing_user and existing_user != user_id:
                return web.json_response({"error": "Phone already in use"}, status=400)

            # Get old phone
            old_phone = await g.redis_client.hget(f"user:{user_id}", "phone")
            
            # Remove old phone mapping
            if old_phone:
                await g.redis_client.hdel("phone_map", old_phone)
            
            # Update to new phone
            await g.redis_client.hset(f"user:{user_id}", mapping={
                "phone": new_phone,
                "phone_verified": "true"
            })
            await g.redis_client.hset("phone_map", new_phone, user_id)
            await g.redis_client.delete(f"otp:{new_phone}")
            
            # Update Firestore
            if self.db:
                try:
                    self.db.collection('users').document(user_id).set({
                        'phone': new_phone,
                        'phone_verified': True
                    }, merge=True)
                except Exception as fb_err:
                    logger.error(f"Firestore phone update: {fb_err}")

            return web.json_response({"success": True, "phone": new_phone})
        else:
            return web.json_response({"error": "Verification code required"}, status=400)

    except Exception as e:
        logger.error(f"Update phone error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def search_users(self, request):
    """Search users by username/email"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        query = request.query.get('q', '').strip().lower()
        if not query:
            return web.json_response({"users": []})

        # Get all users
        all_user_ids = await g.redis_client.smembers("users:all")
        results = []

        for uid in all_user_ids:
            if uid == user_id:
                continue
                
            user_data = await g.redis_client.hgetall(f"user:{uid}")
            if not user_data:
                continue
            
            username = user_data.get('username', '').lower()
            email = user_data.get('email', '').lower()
            
            if query in username or query in email:
                results.append({
                    "id": uid,
                    "username": user_data.get('username'),
                    "email": user_data.get('email'),
                    "avatar_url": user_data.get('avatar_url'),
                    "status": user_data.get('status')
                })

        return web.json_response({"users": results[:20]})  # Limit to 20 results

    except Exception as e:
        logger.error(f"Search users error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def search_all_users(self, request):
    """Search all users from Firestore (for adding to groups)"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        query = request.query.get('q', '').strip().lower()
        
        if not query or len(query) < 2:
            return web.json_response({"users": []})

        logger.info(f"🔍 Searching all users for: {query}")

        results = []
        
        # Search in Firestore
        if self.db:
            try:
                users_ref = self.db.collection('users')
                
                # Search by username (case-insensitive)
                docs = users_ref.where('username', '>=', query).where('username', '<=', query + '\uf8ff').limit(20).stream()
                
                for doc in docs:
                    user_data = doc.to_dict()
                    if doc.id != user_id:  # Exclude current user
                        results.append({
                            "id": doc.id,
                            "username": user_data.get('username'),
                            "email": user_data.get('email', ''),
                            "avatar_url": user_data.get('avatar_url', ''),
                            "status": "offline"  # Default for search results
                        })
                
                # Also search by email if query contains @
                if '@' in query and len(results) < 20:
                    email_docs = users_ref.where('email', '>=', query).where('email', '<=', query + '\uf8ff').limit(10).stream()
                    
                    existing_ids = set(u['id'] for u in results)
                    
                    for doc in email_docs:
                        if doc.id not in existing_ids and doc.id != user_id:
                            user_data = doc.to_dict()
                            results.append({
                                "id": doc.id,
                                "username": user_data.get('username'),
                                "email": user_data.get('email', ''),
                                "avatar_url": user_data.get('avatar_url', ''),
                                "status": "offline"
                            })
                
                logger.info(f"✅ Found {len(results)} users matching '{query}'")
                
            except Exception as fb_err:
                logger.error(f"Firestore search error: {fb_err}")

        return web.json_response({"users": results})

    except Exception as e:
        logger.error(f"Search all users error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def update_user_profile(self, request):
    """Update user profile"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        updates = {}
        
        if 'bio' in data:
            updates['bio'] = data['bio'][:200]
            
        if 'username' in data:
            new_username = data['username'].strip()
            if len(new_username) >= 3:
                existing = await g.redis_client.hget("username_map", new_username)
                if existing and existing != user_id:
                    return web.json_response({"error": "Username taken"}, status=400)
                
                old_username = await g.redis_client.hget(f"user:{user_id}", "username")
                if old_username:
                    await g.redis_client.hdel("username_map", old_username)
                
                await g.redis_client.hset("username_map", new_username, user_id)
                updates['username'] = new_username

        if updates:
            await g.redis_client.hset(f"user:{user_id}", mapping=updates)
            
            if self.db:
                try:
                    self.db.collection('users').document(user_id).set(updates, merge=True)
                except Exception as fb_err:
                    logger.error(f"Firestore update: {fb_err}")

        return web.json_response({"success": True, "updates": updates})

    except Exception as e:
        logger.error(f"Update profile error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_user_by_id(self, request):
    """Get user by ID"""
    try:
        user_id = request.match_info['user_id']
        
        user_data = await g.redis_client.hgetall(f"user:{user_id}")
        
        if not user_data:
            return web.json_response({"error": "User not found"}, status=404)
        
        return web.json_response({
            "user": {
                "id": user_id,
                "username": user_data.get('username'),
                "email": user_data.get('email'),
                "avatar_url": user_data.get('avatar_url'),
                "status": user_data.get('status'),
                "bio": user_data.get('bio')
            }
        })
    except Exception as e:
        logger.error(f"Get user by ID error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_user_settings(self, request):
    """Get user settings"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        user_data = await g.redis_client.hgetall(f"user:{user_id}")
        settings = json.loads(user_data.get('settings', '{}'))
        
        return web.json_response({
            "settings": settings,
            "user": {
                "id": user_id,
                "username": user_data.get('username'),
                "email": user_data.get('email'),
                "phone": user_data.get('phone'),
                "bio": user_data.get('bio'),
                "avatar_url": user_data.get('avatar_url'),
                "phone_verified": user_data.get('phone_verified') == 'true'
            }
        })

    except Exception as e:
        logger.error(f"Get settings error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def update_user_settings(self, request):
    """Update user settings"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        settings = data.get('settings', {})

        await g.redis_client.hset(f"user:{user_id}", "settings", json.dumps(settings))

        if self.db:
            try:
                self.db.collection('users').document(user_id).set({'settings': settings}, merge=True)
            except Exception as fb_err:
                logger.error(f"Firestore update: {fb_err}")

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Update settings error: {e}")
        return web.json_response({"error": str(e)}, status=500)

