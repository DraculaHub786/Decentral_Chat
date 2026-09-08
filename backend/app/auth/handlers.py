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
async def handle_register(self, request):
    """Register new user with bcrypt password hashing"""
    try:
        # Rate limiting
        ip = request.remote or request.headers.get('X-Forwarded-For', 'unknown')
        if self.rate_limiter.is_rate_limited(f"register:{ip}"):
            logger.warning(f"⚠️ Rate limited registration attempt from {ip}")
            return web.json_response({"error": "Too many attempts. Please try again later."}, status=429)

        data = await request.json()
        
        # ADD THESE SAFETY CHECKS
        if not isinstance(data, dict):
            logger.error(f"❌ Invalid request data type: {type(data)}")
            return web.json_response(
                {"error": "Invalid request format"},
                status=400
            )
    
        # Log incoming data for debugging
        logger.info(f"📥 Registration data keys: {list(data.keys())}")
        
        # FIXED: Properly extract and validate each field
        username = str(data.get('username', '')).strip() if data.get('username') else ''
        password = str(data.get('password', '')) if data.get('password') else ''
        email = str(data.get('email', '')).strip() if data.get('email') else ''
        phone = str(data.get('phone', '')).strip() if data.get('phone') else ''
        
        logger.info(f"📝 Parsed values - username: '{username}', email: '{_log_safe(email)}', phone: '{_log_safe(phone)}'")

        # Validation
        if not username or len(username) < 3:
            return web.json_response(
                {"error": "Username must be at least 3 characters"},
                status=400
            )
        
        is_valid, pw_msg = _validate_password(password) if password else (False, "Password is required")
        if not is_valid:
            return web.json_response(
                {"error": pw_msg},
                status=400
            )

        # Check if username already exists in Redis
        existing_user_id = await g.redis_client.hget("username_map", username.lower())
        if existing_user_id:
            logger.warning(f"⚠️ Username '{username}' already exists in Redis (user_id: {existing_user_id})")
            
            # Check if this is a ghost entry (user data doesn't exist)
            user_data_check = await g.redis_client.hgetall(f"user:{existing_user_id}")
            
            if not user_data_check:
                logger.error(f"🔧 GHOST ENTRY DETECTED: username_map has '{username}' -> '{existing_user_id}' but user data doesn't exist!")
                logger.info(f"🔧 Cleaning up ghost entry...")
                await g.redis_client.hdel("username_map", username.lower())
                logger.info(f"✅ Ghost entry cleaned, proceeding with registration")
                # Continue to Firestore check below
            else:
                logger.info(f"✅ Valid existing user found: {user_data_check.get('username')} (created: {user_data_check.get('created_at')})")
                return web.json_response(
                    {"error": f"Username '{username}' is already taken"},
                    status=409
                )

        # Check Firestore only if Redis didn't find a valid user
        if self.db:
            try:
                docs = list(self.db.collection('users').where('username', '==', username).limit(1).stream())
                if docs:
                    logger.warning(f"⚠️ Username '{username}' exists in Firestore")
                    doc_data = docs[0].to_dict()
                    logger.info(f"📋 Firestore user: ID={docs[0].id}, created_at={doc_data.get('created_at')}")
                    return web.json_response(
                        {"error": f"Username '{username}' is already taken"},
                        status=409
                    )
            except Exception as fb_err:
                logger.error(f"Firestore check error: {fb_err}")

        # Check if email already exists
        if email:
            existing_email_user = await g.redis_client.hget("email_map", email.lower())
            if existing_email_user:
                return web.json_response(
                    {"error": "Email already exists"},
                    status=409
                )

        # Hash password with bcrypt
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        logger.info(f"✅ Password hashed successfully")

        # Generate user ID
        user_id = str(uuid.uuid4())
        logger.info(f"📝 Creating user with ID: {user_id}")

        # Store user data in Redis
        user_data = {
            "id": user_id,
            "username": username,
            "email": email,
            "phone": phone,
            "password_hash": password_hash,
            "role": "user",
            "status": "offline",
            "avatar_url": "",
            "bio": "",
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "last_seen": "",
            "auth_provider": "local",
            "settings": json.dumps({
                "notifications": True,
                "read_receipts": True,
                "typing_indicator": True,
                "online_status": True
            })
        }

        # Save to Redis with ALL mappings
        await g.redis_client.hset(f"user:{user_id}", mapping=user_data)
        await g.redis_client.sadd("users:all", user_id)
        # Store username in lowercase for case-insensitive lookups
        await g.redis_client.hset("username_map", username.lower(), user_id)
        
        if email:
            # Store email in lowercase for case-insensitive lookups
            await g.redis_client.hset("email_map", email.lower(), user_id)
        
        if phone:
            await g.redis_client.hset("phone_map", phone, user_id)

        logger.info(f"✅ User saved to Redis: {user_id}")

        # Save to Firestore
        if self.db:
            try:
                self.db.collection('users').document(user_id).set({
                    'id': user_id,
                    'username': username,
                    'email': email or '',
                    'phone': phone or '',
                    'password_hash': password_hash,
                    'role': 'user',
                    'status': 'offline',
                    'avatar_url': '',
                    'bio': '',
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'auth_provider': 'local',
                    'last_seen': firestore.SERVER_TIMESTAMP,
                    'settings': {
                        "notifications": True,
                        "read_receipts": True,
                        "typing_indicator": True,
                        "online_status": True
                    }
                })
                logger.info(f"✅ User {user_id} saved to Firestore")
            except Exception as fb_err:
                logger.error(f"Firestore save failed: {fb_err}")

        # Generate JWT tokens
        token = self.generate_token(user_id)
        refresh_token = await self._generate_refresh_token(user_id, request.headers.get('User-Agent', '')[:128])

        logger.info(f"✅ User registered successfully: {username} (ID: {user_id})")

        return web.json_response({
            "success": True,
            "token": token,
            "refresh_token": refresh_token,
            "user": {
                "id": user_id,
                "username": username,
                "email": email,
                "phone": phone,
                "role": "user",
                "avatar_url": "",
                "bio": ""
            }
        })

    except Exception as e:
        logger.error(f"❌ Registration error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def handle_login(self, request):
    """Login user with bcrypt password verification"""
    try:
        # Rate limiting
        ip = request.remote or request.headers.get('X-Forwarded-For', 'unknown')
        if self.rate_limiter.is_rate_limited(f"login:{ip}"):
            logger.warning(f"⚠️ Rate limited login attempt from {ip}")
            return web.json_response({"error": "Too many attempts. Please try again later."}, status=429)

        data = await request.json()
        identifier = data.get('username', '').strip()
        password = data.get('password', '')

        logger.info(f"🔐 Login attempt for: {_log_safe(identifier)}")

        if not identifier or not password:
            return web.json_response(
                {"error": "Username/email and password required"},
                status=400
            )

        # ✅ CRITICAL FIX: Try ALL possible lookups with case-insensitive search
        user_id = None
        user_data = None

        # Step 1: Try Redis username lookup (case-insensitive)
        user_id = await g.redis_client.hget("username_map", identifier.lower())
        logger.info(f"🔍 Redis username_map check: {user_id}")
        
        # Step 2: Try Redis email lookup (case-insensitive)
        if not user_id and '@' in identifier:
            user_id = await g.redis_client.hget("email_map", identifier.lower())
            logger.info(f"🔍 Redis email_map check: {user_id}")
        
        # Step 3: Try Redis phone lookup
        if not user_id and identifier.startswith('+'):
            user_id = await g.redis_client.hget("phone_map", identifier)
            logger.info(f"🔍 Redis phone_map check: {user_id}")

        # Step 4: Get user data from Redis if found
        if user_id:
            user_data = await g.redis_client.hgetall(f"user:{user_id}")
            logger.info(f"🔍 Redis user data found: {bool(user_data)}, has password: {bool(user_data.get('password_hash'))}")

        # Step 5: If Redis fails, check Firestore
        if not user_data or not user_data.get('password_hash'):
            logger.warning(f"⚠️ Redis incomplete, checking Firestore for: {identifier}")
            
            if self.db:
                try:
                    users_ref = self.db.collection('users')
                    docs = []
                    
                    # Try all identifiers
                    for field, value in [
                        ('username', identifier),
                        ('email', identifier if '@' in identifier else None),
                        ('phone', identifier if identifier.startswith('+') else None)
                    ]:
                        if value:
                            query_docs = list(users_ref.where(field, '==', value).limit(1).stream())
                            if query_docs:
                                docs = query_docs
                                break
                    
                    if docs:
                        doc = docs[0]
                        user_id = doc.id
                        user_data_fb = doc.to_dict()
                        
                        logger.info(f"✅ Found in Firestore: {user_id}")
                        
                        # Reconstruct complete user data
                        user_data = {
                            'id': user_id,
                            'username': user_data_fb.get('username', ''),
                            'email': user_data_fb.get('email', ''),
                            'phone': user_data_fb.get('phone', ''),
                            'password_hash': user_data_fb.get('password_hash', ''),
                            'role': user_data_fb.get('role', 'user'),
                            'status': 'offline',
                            'avatar_url': user_data_fb.get('avatar_url', ''),
                            'bio': user_data_fb.get('bio', ''),
                            'auth_provider': user_data_fb.get('auth_provider', 'local'),
                            'google_id': user_data_fb.get('google_id', ''),
                            'created_at': str(user_data_fb.get('created_at', datetime.datetime.now(datetime.UTC).isoformat())),
                            'last_seen': '',
                            'settings': json.dumps(user_data_fb.get('settings', {
                                "notifications": True,
                                "read_receipts": True,
                                "typing_indicator": True,
                                "online_status": True
                            }))
                        }
                        
                        # ✅ CRITICAL: Restore ALL mappings to Redis
                        await g.redis_client.hset(f"user:{user_id}", mapping=user_data)
                        await g.redis_client.sadd("users:all", user_id)
                        
                        if user_data['username']:
                            await g.redis_client.hset("username_map", user_data['username'], user_id)
                        if user_data['email']:
                            await g.redis_client.hset("email_map", user_data['email'], user_id)
                        if user_data['phone']:
                            await g.redis_client.hset("phone_map", user_data['phone'], user_id)
                        if user_data['google_id']:
                            await g.redis_client.hset("google_id_map", user_data['google_id'], user_id)
                        
                        logger.info(f"✅ User {user_id} fully restored to Redis with all mappings")
                        
                except Exception as fb_err:
                    logger.error(f"❌ Firestore query error: {fb_err}")

        # Step 6: Final check
        if not user_data:
            logger.error(f"❌ User not found anywhere: {identifier}")
            return web.json_response({"error": "User not found"}, status=404)

        if not user_data.get('password_hash'):
            logger.error(f"❌ No password hash for: {identifier}")
            return web.json_response(
                {"error": "Account has no password set"},
                status=400
            )

        # Step 7: Check auth provider
        auth_provider = user_data.get('auth_provider', 'local')
        if auth_provider == 'google':
            return web.json_response(
                {"error": "This account uses Google Sign-In"},
                status=400
            )

        # Step 8: Verify password
        stored_hash = user_data.get('password_hash', '')
        
        logger.info(f"🔐 Attempting password verification for: {identifier}")
        
        try:
            if not bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                logger.warning(f"❌ Invalid password for: {identifier}")
                return web.json_response({"error": "Invalid password"}, status=401)
        except Exception as e:
            logger.error(f"❌ Password verification error: {e}")
            return web.json_response({"error": "Authentication failed"}, status=401)

        # Step 9: Generate tokens
        token = self.generate_token(user_id)
        refresh_token = await self._generate_refresh_token(user_id, request.headers.get('User-Agent', '')[:128])

        # Step 10: Update status
        await g.redis_client.hset(f"user:{user_id}", mapping={
            "status": "online",
            "last_seen": datetime.datetime.now(datetime.UTC).isoformat(),
            "last_login": datetime.datetime.now(datetime.UTC).isoformat()
        })

        logger.info(f"✅ Login successful: {user_data.get('username')} (ID: {user_id})")

        return web.json_response({
            "success": True,
            "token": token,
            "refresh_token": refresh_token,
            "user": {
                "id": user_id,
                "username": user_data.get('username'),
                "email": user_data.get('email'),
                "phone": user_data.get('phone'),
                "role": user_data.get('role'),
                "avatar_url": user_data.get('avatar_url'),
                "bio": user_data.get('bio'),
                "status": "online"
            }
        })

    except Exception as e:
        logger.error(f"❌ Login error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def handle_logout(self, request):
    """Logout user"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        # Update status
        await g.redis_client.hset(f"user:{user_id}", "status", "offline")
        await g.redis_client.hset(f"user:{user_id}", "last_seen", datetime.datetime.now(datetime.UTC).isoformat())

        # Close WebSocket connections
        if user_id in g.active_connections:
            for ws in list(g.active_connections[user_id]):
                await ws.close()
            del g.active_connections[user_id]

        logger.info(f"✅ User logged out: {user_id}")

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"Logout error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def refresh_token(self, request):
    """Refresh JWT access token using a refresh token."""
    try:
        data = await request.json()
        refresh_token_str = data.get('refresh_token', '')
        if not refresh_token_str:
            return web.json_response({"error": "Refresh token required"}, status=400)

        # Decode the refresh token
        try:
            payload = jwt.decode(refresh_token_str, SECRET_KEY, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return web.json_response({"error": "Refresh token expired. Please log in again."}, status=401)
        except jwt.InvalidTokenError:
            return web.json_response({"error": "Invalid refresh token"}, status=401)

        if payload.get('type') != 'refresh':
            return web.json_response({"error": "Invalid token type"}, status=401)

        token_id = payload.get('token_id')
        user_id = payload.get('user_id')

        if not token_id or not user_id:
            return web.json_response({"error": "Invalid refresh token payload"}, status=401)

        # Check if refresh token was revoked (exists in Redis)
        stored = await g.redis_client.hgetall(f"refresh_token:{token_id}")
        if stored and stored.get('revoked') == 'true':
            logger.warning(f"⚠️ Attempted use of revoked refresh token {token_id} for user {user_id}")
            return web.json_response({"error": "Refresh token revoked. Please log in again."}, status=401)

        # Optionally rotate: revoke old, issue new
        if stored:
            await g.redis_client.hset(f"refresh_token:{token_id}", "revoked", "true")

        # Generate new access + refresh tokens
        device_fp = request.headers.get('User-Agent', '')[:128]
        new_access = self.generate_token(user_id)
        new_refresh = await self._generate_refresh_token(user_id, device_fp)

        return web.json_response({
            "success": True,
            "token": new_access,
            "refresh_token": new_refresh
        })

    except Exception as e:
        logger.error(f"❌ Refresh token error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

