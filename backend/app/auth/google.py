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
async def handle_google_auth(self, request):
    """Handle Google OAuth authentication"""
    try:
        data = await request.json()
        email = data.get('email')
        name = data.get('name')
        picture = data.get('picture', '')
        google_id = data.get('google_id')
        
        if not email or not google_id:
            return web.json_response({"error": "Invalid Google data"}, status=400)
        
        logger.info(f"Google auth attempt for: {_log_safe(email)}, Google ID: {google_id[-8:] if len(google_id) > 8 else google_id}")
        
        # STEP 1: Check if user exists by Google ID first
        user_id = await g.redis_client.hget("google_id_map", google_id)
        
        if user_id:
            logger.info(f"Found existing user by Google ID: {user_id}")
            
            # Update avatar if it changed
            current_avatar = await g.redis_client.hget(f"user:{user_id}", "avatar_url")
            if current_avatar != picture:
                await g.redis_client.hset(f"user:{user_id}", "avatar_url", picture)
                
        else:
            # STEP 2: Check if user exists by email
            user_id = await g.redis_client.hget("email_map", email)
            
            if user_id:
                # Link existing account to Google
                logger.info(f"Linking existing email account to Google: {email}")
                await g.redis_client.hset(f"user:{user_id}", "google_id", google_id)
                await g.redis_client.hset(f"user:{user_id}", "auth_provider", "google")
                await g.redis_client.hset(f"user:{user_id}", "avatar_url", picture)
                await g.redis_client.hset("google_id_map", google_id, user_id)
                
            else:
                # STEP 3: Create new user only if neither Google ID nor email exists
                user_id = str(uuid.uuid4())
                
                # Generate unique username from email
                base_username = email.split('@')[0].lower().replace('.', '_').replace('-', '_')
                username = base_username
                
                # Ensure username is unique
                counter = 1
                while await g.redis_client.hget("username_map", username):
                    username = f"{base_username}_{counter}"
                    counter += 1
                
                logger.info(f"Creating new Google user: {username}")
                
                user_data = {
                    "id": user_id,
                    "username": username,
                    "email": email,
                    "phone": "",
                    "google_id": google_id,
                    "avatar_url": picture,
                    "role": "user",
                    "status": "offline",
                    "bio": "",
                    "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "auth_provider": "google",
                    "password_hash": "",  # No password for Google accounts
                    "settings": json.dumps({
                        "notifications": True,
                        "read_receipts": True,
                        "typing_indicator": True,
                        "online_status": True
                    })
                }
                
                await g.redis_client.hset(f"user:{user_id}", mapping=user_data)
                await g.redis_client.sadd("users:all", user_id)
                await g.redis_client.hset("google_id_map", google_id, user_id)
                await g.redis_client.hset("email_map", email, user_id)
                await g.redis_client.hset("username_map", username, user_id)
                
                # Save to Firestore if available
                if self.db:
                    try:
                        self.db.collection('users').document(user_id).set({
                            'id': user_id,
                            'username': username,
                            'email': email,
                            'google_id': google_id,
                            'avatar_url': picture,
                            'phone': '',
                            'password_hash': '',
                            'role': 'user',
                            'status': 'offline',
                            'bio': '',
                            'created_at': firestore.SERVER_TIMESTAMP,
                            'auth_provider': 'google',
                            'settings': {
                                "notifications": True,
                                "read_receipts": True,
                                "typing_indicator": True,
                                "online_status": True
                            }
                        })
                    except Exception as fb_err:
                        logger.error(f"Firestore save failed: {fb_err}")
        
        # Generate JWT token
        jwt_token = self.generate_token(user_id)
        
        # Get complete user data
        user_data = await g.redis_client.hgetall(f"user:{user_id}")
        
        # Update status
        await g.redis_client.hset(f"user:{user_id}", mapping={
            "status": "online",
            "last_login": datetime.datetime.now(datetime.UTC).isoformat()
        })
        
        # Generate refresh token for Google auth
        refresh_token = await self._generate_refresh_token(user_id, request.headers.get('User-Agent', '')[:128])

        logger.info(f"✅ Google Sign-In successful: {user_data.get('username')} (ID: {user_id})")
        
        return web.json_response({
            "success": True,
            "token": jwt_token,
            "refresh_token": refresh_token,
            "user": {
                "id": user_id,
                "username": user_data.get('username'),
                "email": user_data.get('email'),
                "avatar_url": user_data.get('avatar_url'),
                "role": user_data.get('role'),
                "bio": user_data.get('bio'),
                "status": "online"
            }
        })
        
    except Exception as e:
        logger.error(f"Google auth error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

