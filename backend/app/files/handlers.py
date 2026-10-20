import sys
import asyncio
import subprocess
import shutil
from pathlib import Path
from typing import Optional
import logging
import uuid
import datetime
import mimetypes
import jwt
from aiohttp import web
from PIL import Image

# Ensure 'backend' directory is in sys.path so 'app.*' imports resolve cleanly
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from firebase_admin import firestore
except ImportError:
    firestore = None

try:
    from app.globals import g
    from app.core.config import UPLOAD_DIR, MAX_FILE_SIZE, ALLOWED_EXTENSIONS, SECRET_KEY
    from app.core.security import _validate_file_magic, _resolve_safe_path
    from app.auth.tokens import get_user_from_token
except ImportError:
    from ..globals import g
    from ..core.config import UPLOAD_DIR, MAX_FILE_SIZE, ALLOWED_EXTENSIONS, SECRET_KEY
    from ..core.security import _validate_file_magic, _resolve_safe_path
    from ..auth.tokens import get_user_from_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper Functions (defined before request handlers for clean resolution)
# ---------------------------------------------------------------------------

def get_file_type(extension: str) -> Optional[str]:
    """Determine file type from extension"""
    if not extension:
        return 'document'
    ext_clean = extension.lower().strip().lstrip('.')
    ext_dotted = f".{ext_clean}"
    
    for file_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext_clean in extensions or ext_dotted in extensions:
            return file_type
    
    # Return 'document' as fallback instead of None
    return 'document'


async def _check_upload_rate_limit(user_id: str) -> bool:
    """Check per-user upload rate limit (50/hour via Redis). Returns True if limited."""
    if not user_id:
        return False
    key = f"user_upload_count:{user_id}"
    try:
        if not g.redis_client:
            return False
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


async def generate_thumbnail(file_path: Path, file_id: str, ext: str) -> Optional[str]:
    """Generate thumbnail for image"""
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            return None
            
        with Image.open(file_path) as img:
            # Handle RGBA/transparency safely for JPEG saving
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
                
            img.thumbnail((300, 300))
            
            thumbnail_dir = UPLOAD_DIR / 'thumbnails'
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            
            thumbnail_path = thumbnail_dir / f"{file_id}_thumb.jpg"
            img.save(thumbnail_path, "JPEG", quality=85)
            
        return f"/api/uploads/thumbnails/{file_id}_thumb.jpg"
    except Exception as e:
        logger.warning(f"⚠️ Thumbnail generation failed for {file_id}: {e}")
        return None


def _get_audio_duration(file_path: Path, size: int = 0) -> str:
    """Accurately extract audio duration using ffprobe, wave header, or bitrate fallback."""
    ffprobe = shutil.which('ffprobe')
    if ffprobe and file_path.exists():
        try:
            res = subprocess.run(
                [ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)],
                capture_output=True, text=True, timeout=5
            )
            val = res.stdout.strip()
            if val:
                total_secs = max(0, int(float(val)))
                mins = total_secs // 60
                secs = total_secs % 60
                return f"{mins}:{secs:02d}"
        except Exception as e:
            logger.warning(f"⚠️ ffprobe duration extraction error: {e}")

    # Fallback for standard WAV
    if file_path.suffix.lower() == '.wav' and file_path.exists():
        try:
            import wave
            with wave.open(str(file_path), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    total_secs = max(0, int(frames / float(rate)))
                    return f"{total_secs // 60}:{total_secs % 60:02d}"
        except Exception:
            pass

    # Heuristic fallback (16KB/s)
    estimated_duration = max(1, int(size / 16000)) if size else 0
    return f"{estimated_duration // 60}:{estimated_duration % 60:02d}"


# ---------------------------------------------------------------------------
# Request Handlers
# ---------------------------------------------------------------------------

async def upload_file(request: web.Request) -> web.Response:
    """Upload file with mobile-specific handling — FINAL FIXED VERSION"""
    try:
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

        # SAFELY DETERMINE CONTENT TYPE
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
                    file_path.unlink(missing_ok=True)
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
            thumbnail_url = await generate_thumbnail(file_path, file_id, ext)

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
        if g.redis_client:
            await g.redis_client.hset(f"file:{file_id}", mapping=file_meta)
            await g.redis_client.sadd(f"user_files:{user_id}", file_id)

        # Save to Firestore
        if g.db:
            try:
                firestore_doc = {
                    **file_meta,
                    "size": size,
                    "uploaded_at": firestore.SERVER_TIMESTAMP if firestore else file_meta["uploaded_at"]
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


async def upload_voice(request: web.Request) -> web.Response:
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
        filename = getattr(field, 'filename', None) or "voice.webm"
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'webm'
        
        audio_dir = UPLOAD_DIR / 'audio'
        audio_dir.mkdir(parents=True, exist_ok=True)
        voice_path = audio_dir / f"{voice_id}.{ext}"

        size = 0
        with open(voice_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                if size > 10 * 1024 * 1024:  # 10MB limit
                    voice_path.unlink(missing_ok=True)
                    return web.json_response({"error": "Voice too large"}, status=400)
                f.write(chunk)

        # Calculate duration accurately without blocking the event loop
        duration_str = await asyncio.to_thread(_get_audio_duration, voice_path, size)

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
        if g.redis_client:
            await g.redis_client.hset(f"file:{voice_id}", mapping=voice_meta)
            await g.redis_client.sadd(f"user_files:{user_id}", voice_id)

        # CRITICAL: ALWAYS save to Firestore if available
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
                    'uploaded_at': firestore.SERVER_TIMESTAMP if firestore else voice_meta['uploaded_at']
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


async def get_file(request: web.Request) -> web.Response:
    """Get uploaded file with mandatory authentication."""
    try:
        file_id = request.match_info.get('file_id', '')
        if not file_id:
            return web.json_response({"error": "File ID required"}, status=400)

        # Authenticate via header or query token
        user_id = await get_user_from_token(request)
        if not user_id:
            token = request.query.get('token', '')
            if token:
                try:
                    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
                    user_id = payload.get('user_id')
                except Exception:
                    pass

        if not user_id:
            return web.json_response({"error": "Unauthorized file access"}, status=401)
        
        file_meta = None
        if g.redis_client:
            file_meta = await g.redis_client.hgetall(f"file:{file_id}")
        
        # Firestore fallback if Redis misses
        if not file_meta and g.db:
            try:
                doc = g.db.collection('files').document(file_id).get()
                if doc.exists:
                    file_meta = doc.to_dict()
            except Exception as fb_err:
                logger.warning(f"Firestore lookup fallback error for {file_id}: {fb_err}")

        if not file_meta:
            return web.json_response({"error": "File not found"}, status=404)

        raw_path = file_meta.get('path', '')
        if not raw_path:
            return web.json_response({"error": "File path missing"}, status=404)

        try:
            file_path = _resolve_safe_path(UPLOAD_DIR, raw_path)
        except ValueError as e:
            logger.error(f"❌ Blocked path traversal in get_file: {e}")
            return web.json_response({"error": "Invalid file path"}, status=400)

        if not file_path.exists():
            return web.json_response({"error": "File not found"}, status=404)

        filename = file_meta.get("filename", "file")
        return web.FileResponse(
            file_path,
            headers={'Content-Disposition': f'inline; filename="{filename}"'}
        )

    except Exception as e:
        logger.error(f"Get file error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def get_thumbnail(request: web.Request) -> web.Response:
    """Get file thumbnail with mandatory authentication."""
    try:
        file_id = request.match_info.get('file_id', '')
        if not file_id:
            return web.json_response({"error": "File ID required"}, status=400)

        # Authenticate via header or query token
        user_id = await get_user_from_token(request)
        if not user_id:
            token = request.query.get('token', '')
            if token:
                try:
                    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
                    user_id = payload.get('user_id')
                except Exception:
                    pass

        if not user_id:
            return web.json_response({"error": "Unauthorized thumbnail access"}, status=401)
        
        file_meta = None
        if g.redis_client:
            file_meta = await g.redis_client.hgetall(f"file:{file_id}")
        
        if not file_meta and g.db:
            try:
                doc = g.db.collection('files').document(file_id).get()
                if doc.exists:
                    file_meta = doc.to_dict()
            except Exception as fb_err:
                logger.warning(f"Firestore thumbnail lookup error for {file_id}: {fb_err}")

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


async def serve_upload(request: web.Request) -> web.Response:
    """Serve uploaded files with mandatory authentication for private media."""
    try:
        filename = request.match_info.get('filename', '')
        if not filename:
            return web.json_response({"error": "Not found"}, status=404)

        try:
            file_path = _resolve_safe_path(UPLOAD_DIR, UPLOAD_DIR / filename)
        except ValueError:
            return web.json_response({"error": "Not found"}, status=404)

        # Allow public access only for avatars and avatar thumbnails
        norm_filename = filename.replace('\\', '/')
        is_avatar = norm_filename.startswith('avatars/') or norm_filename.startswith('thumbnails/')
        if is_avatar:
            if not file_path.exists():
                return web.json_response({"error": "Not found"}, status=404)
            return web.FileResponse(file_path)

        # For all other uploaded files (images, audio, video, documents, voices),
        # require valid authentication
        token = request.query.get('token', '')
        user_id = None
        if token:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
                user_id = payload.get('user_id')
            except Exception:
                pass

        if not user_id:
            user_id = await get_user_from_token(request)

        if not user_id:
            return web.json_response({"error": "Unauthorized file access"}, status=401)

        if not file_path.exists():
            return web.json_response({"error": "Not found"}, status=404)

        return web.FileResponse(file_path)
    except Exception as e:
        logger.error(f"Serve upload error: {e}")
        return web.json_response({"error": "Not found"}, status=404)


async def migrate_existing_files(self=None):
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


# ---------------------------------------------------------------------------
# Re-exports for converter service functions
# ---------------------------------------------------------------------------

try:
    from app.files.converters.service import (
        convert_uploaded_file,
        get_conversion_formats,
        get_conversion_progress,
    )
except ImportError:
    pass

def __getattr__(name: str):
    """Lazy module attribute resolver for converter service functions"""
    if name in ("convert_uploaded_file", "get_conversion_formats", "get_conversion_progress"):
        from app.files.converters import service
        return getattr(service, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "upload_file",
    "upload_voice",
    "get_file",
    "get_thumbnail",
    "serve_upload",
    "generate_thumbnail",
    "get_file_type",
    "_check_upload_rate_limit",
    "migrate_existing_files",
    "convert_uploaded_file",
    "get_conversion_formats",
    "get_conversion_progress",
]
