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
async def upload_file(request):
    """Upload file with mobile-specific handling — FINAL FIXED VERSION"""
    try:
        import mimetypes  # ensure available

        user_id = await get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        # Per-user upload rate limit check
        if await _check_upload_rate_limit(user_id):
            return web.json_response({"error": "Upload rate limit exceeded (50/hour)"}, status=429)

        # Detect mobile device
        user_agent = request.headers.get('User-Agent', '')
        is_mobile = any(x in user_agent for x in ['iPhone', 'iPad', 'Android', 'Mobile'])

        logger.info(f"📤 File upload - User: {user_id}, Mobile: {is_mobile}, UA: {user_agent[:50]}")

        reader = await request.multipart()

        # Robust: iterate until we find a file part with a filename
        field = None
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.filename:
                field = part
                break

        if not field:
            logger.error("❌ No file part found in multipart payload")
            return web.json_response({"error": "No file provided"}, status=400)



        filename = field.filename
        if not filename:
            logger.error("❌ No filename in upload")
            return web.json_response({"error": "Invalid filename"}, status=400)

        # SAFELY DETERMINE CONTENT TYPE (NO .content_type USED ANYWHERE)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if not content_type:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        logger.info(f"📄 Uploading: {filename} ({content_type})")

        # Determine file extension + type
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
        file_type = get_file_type(ext)

        # Subdirectory selection
        subdir = {
            'image': 'images',
            'video': 'videos',
            'audio': 'audio',
            'document': 'documents',
            'archive': 'archives'
        }.get(file_type, 'documents')

        upload_subdir = UPLOAD_DIR / subdir
        upload_subdir.mkdir(parents=True, exist_ok=True)

        # Generate file ID + path
        file_id = str(uuid.uuid4())
        file_path = upload_subdir / f"{file_id}.{ext}"

        # Save file in chunks
        size = 0
        with open(file_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break

                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    file_path.unlink()
                    return web.json_response({"error": "File too large"}, status=400)

                f.write(chunk)

        logger.info(f"✅ File saved locally: {size} bytes at {file_path}")

        if not file_path.exists() or file_path.stat().st_size == 0:
            logger.error(f"❌ File missing after save: {file_path}")
            return web.json_response({"error": "File save failed"}, status=500)

        # Magic byte validation
        if not _validate_file_magic(file_path, ext):
            file_path.unlink(missing_ok=True)
            logger.warning(f"❌ File rejected by magic byte check: {filename} (ext={ext})")
            return web.json_response({"error": "File content does not match its extension"}, status=400)

        # Thumbnail generation (only for images)
        thumbnail_url = None
        if file_type == 'image':
            try:
                thumbnail_url = await generate_thumbnail(file_path, file_id, ext)
            except Exception as thumb_error:
                logger.warning(f"⚠️ Thumbnail generation failed: {thumb_error}")

        # Relative URL for client
        file_url = f"/api/uploads/{subdir}/{file_id}.{ext}"

        # Metadata
        file_meta = {
            "id": file_id,
            "user_id": user_id,
            "filename": filename,
            "file_type": file_type,
            "extension": ext,
            "size": str(size),
            "path": str(file_path.absolute()),
            "url": file_url,
            "uploaded_at": datetime.datetime.now(datetime.UTC).isoformat()
        }

        if thumbnail_url:
            file_meta["thumbnail_url"] = thumbnail_url

        # Save to Redis
        await g.redis_client.hset(f"file:{file_id}", mapping=file_meta)
        await g.redis_client.sadd(f"user_files:{user_id}", file_id)

        # Save to Firestore
        if g.db:
            try:
                firestore_doc = {
                    **file_meta,
                    "size": size,
                    "uploaded_at": firestore.SERVER_TIMESTAMP
                }
                g.db.collection("files").document(file_id).set(firestore_doc)
                logger.info(f"✅ File metadata saved to Firestore: {file_id}")

            except Exception as fb_err:
                logger.error(f"❌ Firestore file save failed: {fb_err}")

        return web.json_response({
            "success": True,
            "file": {
                "id": file_id,
                "filename": filename,
                "type": file_type,
                "size": size,
                "url": file_url,
                "thumbnail_url": thumbnail_url
            }
        })

    except Exception as e:
        logger.error(f"❌ File upload error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def upload_voice(request):
    """Upload voice message with Firestore persistence"""
    try:
        user_id = await get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        # Per-user upload rate limit check
        if await _check_upload_rate_limit(user_id):
            return web.json_response({"error": "Upload rate limit exceeded (50/hour)"}, status=429)

        logger.info(f"🎤 Voice upload started by user: {user_id}")

        reader = await request.multipart()
        field = await reader.next()

        if not field:
            return web.json_response({"error": "No audio provided"}, status=400)

        # Save voice
        voice_id = str(uuid.uuid4())
        filename = field.filename or "voice.webm"
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'webm'
        
        voice_path = UPLOAD_DIR / 'audio' / f"{voice_id}.{ext}"

        size = 0
        with open(voice_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                if size > 10 * 1024 * 1024:  # 10MB limit
                    voice_path.unlink()
                    return web.json_response({"error": "Voice too large"}, status=400)
                f.write(chunk)

        # Calculate duration
        estimated_duration = int(size / 16000)
        minutes = estimated_duration // 60
        seconds = estimated_duration % 60
        duration_str = f"{minutes}:{seconds:02d}"

        voice_url = f"/api/uploads/audio/{voice_id}.{ext}"
        
        voice_meta = {
            "id": voice_id,
            "user_id": user_id,
            "filename": f"voice_{voice_id}.{ext}",
            "file_type": "audio",
            "extension": ext,
            "size": str(size),
            "path": str(voice_path.absolute()),  # Absolute path
            "url": voice_url,
            "uploaded_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "duration": duration_str
        }

        # Save to Redis
        await g.redis_client.hset(f"file:{voice_id}", mapping=voice_meta)
        await g.redis_client.sadd(f"user_files:{user_id}", voice_id)

        # ✅ CRITICAL: ALWAYS save to Firestore
        if g.db:
            try:
                firestore_doc = {
                    'id': voice_id,
                    'user_id': user_id,
                    'filename': voice_meta['filename'],
                    'file_type': 'audio',
                    'extension': ext,
                    'size': size,
                    'url': voice_url,
                    'path': str(voice_path.absolute()),
                    'duration': duration_str,
                    'uploaded_at': firestore.SERVER_TIMESTAMP
                }
                
                g.db.collection('files').document(voice_id).set(firestore_doc)
                logger.info(f"✅ Voice metadata saved to Firestore: {voice_id}")
                
            except Exception as fb_err:
                logger.error(f"❌ CRITICAL: Firestore voice save failed: {fb_err}")

        logger.info(f"✅ Voice uploaded: {voice_id} ({size} bytes, {duration_str})")

        return web.json_response({
            "success": True,
            "voice": {
                "id": voice_id,
                "filename": voice_meta['filename'],
                "type": "audio",
                "size": size,
                "url": voice_url,
                "duration": duration_str
            }
        })

    except Exception as e:
        logger.error(f"❌ Voice upload error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def get_file(request):
    """Get uploaded file"""
    try:
        file_id = request.match_info['file_id']
        
        file_meta = await g.redis_client.hgetall(f"file:{file_id}")
        
        if not file_meta:
            return web.json_response({"error": "File not found"}, status=404)

        try:
            file_path = _resolve_safe_path(UPLOAD_DIR, file_meta['path'])
        except ValueError as e:
            logger.error(f"❌ Blocked path traversal in get_file: {e}")
            return web.json_response({"error": "Invalid file path"}, status=400)

        if not file_path.exists():
            return web.json_response({"error": "File not found"}, status=404)

        return web.FileResponse(
            file_path,
            headers={'Content-Disposition': f'inline; filename="{file_meta.get("filename", "file")}"'}
        )

    except Exception as e:
        logger.error(f"Get file error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_thumbnail(request):
    """Get file thumbnail"""
    try:
        file_id = request.match_info['file_id']
        
        file_meta = await g.redis_client.hgetall(f"file:{file_id}")
        
        if not file_meta or not file_meta.get('thumbnail_url'):
            return web.json_response({"error": "Thumbnail not found"}, status=404)

        # Construct thumbnail path from file_id and validate it's within UPLOAD_DIR/thumbnails
        thumb_relative = Path('thumbnails') / f"{file_id}_thumb.jpg"
        try:
            thumb_path = _resolve_safe_path(UPLOAD_DIR, UPLOAD_DIR / thumb_relative)
        except ValueError as e:
            logger.error(f"❌ Blocked path traversal in get_thumbnail: {e}")
            return web.json_response({"error": "Invalid thumbnail path"}, status=400)

        if not thumb_path.exists():
            return web.json_response({"error": "Thumbnail not found"}, status=404)

        return web.FileResponse(thumb_path)

    except Exception as e:
        logger.error(f"Get thumbnail error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def serve_upload(request):
    """Serve uploaded files with optional token-based auth fallback."""
    try:
        filename = request.match_info.get('filename', '')
        if not filename:
            return web.json_response({"error": "Not found"}, status=404)

        # Token-based auth fallback: ?token=<jwt> 
        token = request.query.get('token', '')
        user_id = None
        if token:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
                user_id = payload.get('user_id')
            except Exception:
                pass

        # If no token, try Authorization header
        if not user_id:
            user_id = await get_user_from_token(request)

        # If authenticated via either method, try to authorize the file access
        if user_id:
            try:
                file_path = _resolve_safe_path(UPLOAD_DIR, UPLOAD_DIR / filename)
            except ValueError:
                return web.json_response({"error": "Not found"}, status=404)
            if file_path.exists():
                return web.FileResponse(file_path)

        # Fall through to static dir for unauthenticated access (backward compat)
        # but _resolve_safe_path validates path safety
        try:
            fallback_path = _resolve_safe_path(UPLOAD_DIR, UPLOAD_DIR / filename)
        except ValueError:
            return web.json_response({"error": "Not found"}, status=404)

        if fallback_path.exists():
            return web.FileResponse(fallback_path)
        return web.json_response({"error": "Not found"}, status=404)
    except Exception as e:
        logger.error(f"Serve upload error: {e}")
        return web.json_response({"error": "Not found"}, status=404)

async def generate_thumbnail(file_path: Path, file_id: str, ext: str) -> Optional[str]:
    """Generate thumbnail for image"""
    try:
        from PIL import Image
        
        img = Image.open(file_path)
        img.thumbnail((300, 300))
        
        thumbnail_dir = UPLOAD_DIR / 'thumbnails'
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        
        thumbnail_path = thumbnail_dir / f"{file_id}_thumb.jpg"
        img.save(thumbnail_path, "JPEG")
        
        return f"/api/uploads/thumbnails/{file_id}_thumb.jpg"
    except Exception as e:
        logger.error(f"Thumbnail generation error: {e}")
        return None

def get_file_type(extension: str) -> Optional[str]:
    """Determine file type from extension"""
    extension = extension.lower().strip()
    
    for file_type, extensions in ALLOWED_EXTENSIONS.items():
        if extension in extensions:
            return file_type
    
    # Return 'document' as fallback instead of None
    return 'document'

async def _check_upload_rate_limit(user_id: str) -> bool:
    """Check per-user upload rate limit (50/hour via Redis). Returns True if limited."""
    key = f"user_upload_count:{user_id}"
    try:
        count = await g.redis_client.get(key)
        if count is None:
            await g.redis_client.setex(key, 3600, 1)
            return False
        count = int(count)
        if count >= 50:
            logger.warning(f"⚠️ Upload rate limit hit for user {user_id}")
            return True
        await g.redis_client.incr(key)
        await g.redis_client.expire(key, 3600)
        return False
    except Exception:
        return False  # Graceful degradation

async def migrate_existing_files(self):
    """One-time migration: Add 'path' field to existing file records"""
    if not g.db:
        logger.warning("Firestore not available, skipping migration")
        return
    
    logger.info("🔧 Starting file migration...")
    
    try:
        files_ref = g.db.collection('files')
        docs = files_ref.stream()
        
        migrated = 0
        for doc in docs:
            file_data = doc.to_dict()
            
            # Skip if already has path
            if file_data.get('path'):
                continue
            
            # Reconstruct path from URL
            file_url = file_data.get('url', '')
            if not file_url:
                continue
            
            # Extract path from URL (e.g., /uploads/images/abc123.jpg)
            url_path = file_url.lstrip('/')
            file_path = Path(url_path)
            
            # Check if file exists
            if not file_path.exists():
                logger.warning(f"⚠️ File not found: {file_path}")
                continue
            
            # Update Firestore
            doc.reference.update({'path': str(file_path.absolute())})
            migrated += 1
            logger.info(f"✅ Migrated: {file_data.get('filename')}")
        
        logger.info(f"🎉 Migration complete! Updated {migrated} files")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")

