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
async def preload_critical_data_from_firestore(self):
    """Load critical data from Firestore to Redis on startup"""
    if not self.db:
        logger.warning("⚠️ Firestore not available, skipping data preload")
        return
    
    try:
        logger.info("📥 Preloading data from Firestore to Redis...")
        
        # ========== LOAD USERS ==========
        users_ref = self.db.collection('users')
        users_docs = users_ref.stream()
        user_count = 0
        
        for doc in users_docs:
            user_id = doc.id
            user_data_fb = doc.to_dict()
            
            # Reconstruct Redis user data
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
                'phone_verified': str(user_data_fb.get('phone_verified', False)),
                'settings': json.dumps(user_data_fb.get('settings', {
                    "notifications": True,
                    "read_receipts": True,
                    "typing_indicator": True,
                    "online_status": True
                }))
            }
            
            # Store in Redis
            await g.redis_client.hset(f"user:{user_id}", mapping=user_data)
            await g.redis_client.sadd("users:all", user_id)
            
            # Create mappings
            if user_data['username']:
                await g.redis_client.hset("username_map", user_data['username'], user_id)
            if user_data['email']:
                await g.redis_client.hset("email_map", user_data['email'], user_id)
            if user_data['phone']:
                await g.redis_client.hset("phone_map", user_data['phone'], user_id)
            if user_data['google_id']:
                await g.redis_client.hset("google_id_map", user_data['google_id'], user_id)
            
            user_count += 1
        
        logger.info(f"✅ Preloaded {user_count} users from Firestore to Redis")
        
        # ========== LOAD CHATS ==========
        chats_ref = self.db.collection('chats')
        chats_docs = list(chats_ref.stream())
        chat_count = 0
        total_messages = 0
        
        for doc in chats_docs:
            chat_id = doc.id
            chat_data = doc.to_dict()
            
            # Store chat in Redis
            redis_chat_data = {
                'id': chat_id,
                'type': chat_data.get('type', 'direct'),
                'name': chat_data.get('name', ''),
                'description': chat_data.get('description', ''),
                'avatar_url': chat_data.get('avatar_url', ''),
                'created_by': chat_data.get('created_by', ''),
                'created_at': str(chat_data.get('created_at', datetime.datetime.now(datetime.UTC).isoformat()))
            }
            
            await g.redis_client.hset(f"chat:{chat_id}", mapping=redis_chat_data)
            await g.redis_client.sadd("chats:all", chat_id)
            
            # Load members
            members = chat_data.get('members', [])
            for member_id in members:
                await g.redis_client.sadd(f"chat_members:{chat_id}", member_id)
                await g.redis_client.sadd(f"user_chats:{member_id}", chat_id)
                logger.info(f"✅ Mapped chat {chat_id} to user {member_id}")
            
            # Load messages for this chat
            try:
                messages_ref = self.db.collection('chats').document(chat_id).collection('messages')
                messages_query = messages_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(1000)
                messages_docs = list(messages_query.stream())
                
                message_count = 0
                for msg_doc in reversed(messages_docs):  # Reverse to get oldest first
                    msg_id = msg_doc.id
                    msg_data = msg_doc.to_dict()
                    
                    # Store message in Redis
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
                    # 🔥 RESTORE delete-for-everyone state
                    if msg_data.get('deleted') is True:
                        redis_msg_data['deleted'] = "True"

                    await g.redis_client.hset(f"message:{msg_id}", mapping=redis_msg_data)
                    await g.redis_client.lpush(f"chat_messages:{chat_id}", msg_id)
                    message_count += 1
                    total_messages += 1
                
                # Trim to keep only last 1000 messages
                await g.redis_client.ltrim(f"chat_messages:{chat_id}", 0, 999)
                
                if message_count > 0:
                    logger.info(f"✅ Loaded {message_count} messages for chat {chat_id}")
                    
            except Exception as msg_error:
                logger.warning(f"Could not load messages for chat {chat_id}: {msg_error}")
            
            chat_count += 1
        
        logger.info(f"✅ Preloaded {chat_count} chats and {total_messages} messages from Firestore to Redis")
        
        # ========== LOAD CONTACTS ==========
        users_list = await g.redis_client.smembers("users:all")
        # 🔥 ONLY REQUIRED ADDITION (DO NOT REMOVE)
        users_list = [
            u.decode() if isinstance(u, bytes) else u
            for u in users_list
        ]

        # ========== RESTORE DELETE-FOR-ME ==========
        logger.info("📥 Restoring delete-for-me message states...")
        restored_count = 0

        for user_id in users_list:
            try:
                deleted_ref = self.db.collection('users') \
                    .document(user_id) \
                    .collection('deleted_messages')

                deleted_docs = deleted_ref.stream()

                for doc in deleted_docs:
                    msg_id = doc.id
                    await g.redis_client.sadd(f"deleted_messages:{user_id}", msg_id)
                    restored_count += 1

            except Exception as e:
                logger.warning(f"Could not restore deleted messages for user {user_id}: {e}")

        logger.info(f"✅ Restored {restored_count} delete-for-me entries")

        contact_count = 0
        
        for user_id in users_list:
            try:
                contacts_ref = self.db.collection('users').document(user_id).collection('contacts')
                contacts_docs = contacts_ref.stream()
                
                for contact_doc in contacts_docs:
                    contact_id = contact_doc.id
                    await g.redis_client.sadd(f"user_contacts:{user_id}", contact_id)
                    contact_count += 1
                    
            except Exception as e:
                logger.warning(f"Could not load contacts for user {user_id}: {e}")
        
        logger.info(f"✅ Preloaded {contact_count} contact relationships from Firestore")

        # ========== LOAD FILES METADATA ==========
        logger.info("📥 Preloading file metadata from Firestore...")
        try:
            files_ref = self.db.collection('files')
            files_docs = files_ref.stream()
            file_count = 0
            missing_file_count = 0
            
            for doc in files_docs:
                file_id = doc.id
                file_data = doc.to_dict()
                
                # **CRITICAL: Check if file exists on disk**
                file_path_str = file_data.get('path', '')
                
                if not file_path_str:
                    logger.warning(f"⚠️ No path stored for file {file_id}, skipping")
                    missing_file_count += 1
                    continue
                
                file_path = Path(file_path_str)
                
                if not file_path.exists():
                    logger.warning(f"⚠️ File missing on disk: {file_path}, skipping {file_id}")
                    missing_file_count += 1
                    continue
                
                # Reconstruct file metadata for Redis
                redis_file_data = {
                    'id': file_id,
                    'user_id': file_data.get('user_id', ''),
                    'filename': file_data.get('filename', ''),
                    'file_type': file_data.get('file_type', 'document'),
                    'extension': file_data.get('extension', ''),
                    'size': str(file_data.get('size', 0)),
                    'url': file_data.get('url', ''),
                    'path': str(file_path.absolute()),
                    'thumbnail_url': file_data.get('thumbnail_url', ''),
                    'uploaded_at': str(file_data.get('uploaded_at', datetime.datetime.now(datetime.UTC).isoformat()))
                }
                
                # Add duration for audio/voice files
                if file_data.get('duration'):
                    redis_file_data['duration'] = str(file_data.get('duration'))
                
                # Store in Redis
                await g.redis_client.hset(f"file:{file_id}", mapping=redis_file_data)
                
                user_id = file_data.get('user_id')
                if user_id:
                    await g.redis_client.sadd(f"user_files:{user_id}", file_id)
                
                file_count += 1
                
                # Log every 50 files
                if file_count % 50 == 0:
                    logger.info(f"   Loaded {file_count} files...")
            
            logger.info(f"✅ Preloaded {file_count} file metadata records from Firestore")
            
            if missing_file_count > 0:
                logger.warning(f"⚠️ {missing_file_count} files missing from disk (not loaded)")
            
        except Exception as file_error:
            logger.error(f"❌ Could not load files metadata: {file_error}", exc_info=True)

        logger.info("🎉 Data preload complete!")


        # ========== LOAD BLOCKED USERS ==========
        logger.info("📥 Preloading blocked users from Firestore...")
        blocked_count = 0
        
        for user_id in users_list:
            try:
                blocked_ref = self.db.collection('users').document(user_id).collection('blocked')
                blocked_docs = blocked_ref.stream()
                
                for blocked_doc in blocked_docs:
                    blocked_user_id = blocked_doc.id
                    await g.redis_client.sadd(f"user_blocked:{user_id}", blocked_user_id)
                    blocked_count += 1
                    
            except Exception as e:
                logger.warning(f"Could not load blocked users for {user_id}: {e}")
        
        logger.info(f"✅ Preloaded {blocked_count} blocked relationships from Firestore")

        logger.info("🎉 Data preload complete!")
        
    except Exception as e:
        logger.error(f"❌ Error preloading data from Firestore: {e}", exc_info=True)

async def sync_redis_to_firestore_periodically(self):
    """Periodically sync critical Redis data back to Firestore"""
    while True:
        try:
            await asyncio.sleep(300)  # Sync every 5 minutes
            
            if not self.db:
                continue
            
            logger.info("🔄 Starting periodic Redis → Firestore sync...")
            
            # Get all users from Redis
            user_ids = await g.redis_client.smembers("users:all")
            sync_count = 0
            
            for user_id in user_ids:
                try:
                    user_data = await g.redis_client.hgetall(f"user:{user_id}")
                    
                    if not user_data:
                        continue
                    
                    # Update Firestore with current Redis data
                    update_data = {
                        'status': user_data.get('status', 'offline'),
                        'last_seen': firestore.SERVER_TIMESTAMP,
                        'avatar_url': user_data.get('avatar_url', ''),
                        'bio': user_data.get('bio', '')
                    }
                    
                    # Only update settings if they exist
                    if user_data.get('settings'):
                        try:
                            update_data['settings'] = json.loads(user_data.get('settings', '{}'))
                        except:
                            pass
                    
                    self.db.collection('users').document(user_id).set(update_data, merge=True)
                    sync_count += 1
                    
                except Exception as e:
                    logger.warning(f"Could not sync user {user_id}: {e}")
            
            logger.info(f"✅ Synced {sync_count} users to Firestore")
            
        except Exception as e:
            logger.error(f"Periodic sync error: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error before retrying

