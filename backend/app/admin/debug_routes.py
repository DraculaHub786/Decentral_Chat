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
async def debug_check_user(self, request):
    """Debug: Check if user exists in Redis and Firestore"""
    if not _is_admin(request):
        return web.json_response({"error": "Not found"}, status=404)
    username = request.match_info['username']
    
    result = {
        'username': username,
        'redis_username_map': None,
        'redis_user_data': None,
        'firestore_user': None
    }
    
    # Check Redis
    user_id = await g.redis_client.hget("username_map", username)
    result['redis_username_map'] = user_id
    
    if user_id:
        user_data = await g.redis_client.hgetall(f"user:{user_id}")
        result['redis_user_data'] = {
            'id': user_data.get('id'),
            'username': user_data.get('username'),
            'has_password_hash': bool(user_data.get('password_hash')),
            'auth_provider': user_data.get('auth_provider')
        }
    
    # Check Firestore
    if self.db:
        try:
            docs = list(self.db.collection('users').where('username', '==', username).limit(1).stream())
            if docs:
                doc_data = docs[0].to_dict()
                result['firestore_user'] = {
                    'id': docs[0].id,
                    'username': doc_data.get('username'),
                    'has_password_hash': bool(doc_data.get('password_hash')),
                    'auth_provider': doc_data.get('auth_provider')
                }
        except Exception as e:
            result['firestore_error'] = str(e)
    
    return web.json_response(result)

async def debug_redis_state(self, request):
    """Debug: Check Redis state"""
    if not _is_admin(request):
        return web.json_response({"error": "Not found"}, status=404)
    username = request.match_info.get('username', 'all')
    
    if username == 'all':
        all_users = await g.redis_client.smembers("users:all")
        username_map = {}
        for key in await g.redis_client.hkeys("username_map"):
            username_map[key] = await g.redis_client.hget("username_map", key)
        
        return web.json_response({
            "total_users": len(all_users),
            "user_ids": list(all_users),
            "username_mappings": username_map
        })
    else:
        user_id = await g.redis_client.hget("username_map", username)
        if user_id:
            user_data = await g.redis_client.hgetall(f"user:{user_id}")
            return web.json_response({
                "found": True,
                "user_id": user_id,
                "has_password": bool(user_data.get('password_hash')),
                "fields": list(user_data.keys())
            })
        else:
            return web.json_response({"found": False})

async def debug_user_chats(self, request):
    """Debug: Check user's chats"""
    if not _is_admin(request):
        return web.json_response({"error": "Not found"}, status=404)
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        # Get user's chats from Redis
        chat_ids = await g.redis_client.smembers(f"user_chats:{user_id}")
        
        chats_info = []
        for chat_id in chat_ids:
            chat_data = await g.redis_client.hgetall(f"chat:{chat_id}")
            members = await g.redis_client.smembers(f"chat_members:{chat_id}")
            
            chats_info.append({
                "chat_id": chat_id,
                "type": chat_data.get('type'),
                "name": chat_data.get('name'),
                "member_count": len(members),
                "members": list(members)
            })
        
        return web.json_response({
            "user_id": user_id,
            "total_chats": len(chat_ids),
            "chats": chats_info
        })
        
    except Exception as e:
        logger.error(f"Debug user chats error: {e}")
        return web.json_response({"error": str(e)}, status=500)

