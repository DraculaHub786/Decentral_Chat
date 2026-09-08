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
from app.auth.tokens import get_user_from_token
from app.files.handlers import get_file_type, generate_thumbnail
from app.files.converters.images import convert_image_format
from app.files.converters.documents import convert_document_format
from app.files.converters.audio import convert_audio_format
from app.files.converters.video import convert_video_format
logger = logging.getLogger(__name__)
def perform_file_conversion(input_path, output_path, source_ext, target_ext):
    """Route conversion to appropriate handler - SUPER CONVERTER"""
    image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif', 'ico']
    audio_exts = ['mp3', 'wav', 'ogg', 'aac', 'm4a', 'flac', 'wma', 'opus']
    video_exts = ['mp4', 'avi', 'mov', 'webm', 'mkv', 'flv', 'wmv']
    document_exts = ['pdf', 'docx', 'doc', 'txt', 'html', 'md', 'rtf', 'xlsx', 'xls', 'csv', 'pptx', 'ppt']
    
    # Image conversions (including image to PDF)
    if source_ext in image_exts and (target_ext in image_exts or target_ext == 'pdf'):
        return convert_image_format(input_path, output_path, target_ext)
    
    # Video conversions (including video to audio and video to gif)
    elif source_ext in video_exts and (target_ext in video_exts or target_ext in audio_exts or target_ext == 'gif'):
        return convert_video_format(input_path, output_path, target_ext)
    
    # Audio conversions
    elif source_ext in audio_exts and target_ext in audio_exts:
        return convert_audio_format(input_path, output_path, target_ext)
    
    # Document conversions (anything involving documents)
    elif source_ext in document_exts or target_ext in document_exts:
        return convert_document_format(input_path, output_path, source_ext, target_ext)
    
    else:
        raise Exception(f"Conversion {source_ext} → {target_ext} not supported")

def get_supported_conversions(file_extension):
    """Return supported conversion formats for given file type - SUPER CONVERTER"""
    conversion_map = {
        # Image formats - comprehensive conversions
        'jpg': ['png', 'webp', 'pdf', 'bmp', 'tiff', 'ico', 'gif', 'jpeg'],
        'jpeg': ['png', 'webp', 'pdf', 'bmp', 'tiff', 'ico', 'gif', 'jpg'],
        'png': ['jpg', 'jpeg', 'webp', 'pdf', 'bmp', 'tiff', 'ico', 'gif'],
        'webp': ['jpg', 'jpeg', 'png', 'pdf', 'bmp', 'tiff', 'gif'],
        'gif': ['jpg', 'jpeg', 'png', 'webp', 'bmp', 'pdf', 'mp4'],
        'bmp': ['jpg', 'jpeg', 'png', 'webp', 'pdf', 'tiff', 'gif'],
        'tiff': ['jpg', 'jpeg', 'png', 'webp', 'pdf', 'bmp'],
        'ico': ['png', 'jpg', 'jpeg', 'bmp'],
        
        # Document formats - comprehensive conversions
        'pdf': ['docx', 'txt', 'html', 'md', 'rtf'],
        'docx': ['pdf', 'txt', 'html', 'md', 'rtf'],
        'doc': ['pdf', 'txt', 'html', 'docx'],
        'pptx': ['pdf', 'txt', 'html', 'docx'],  # Added docx support
        'ppt': ['pdf', 'txt', 'pptx', 'docx'],   # Added docx support
        'xlsx': ['csv', 'pdf', 'txt', 'html'],
        'xls': ['csv', 'pdf', 'txt', 'xlsx'],
        'txt': ['pdf', 'docx', 'html', 'md', 'rtf'],
        'html': ['pdf', 'txt', 'docx', 'md'],
        'md': ['pdf', 'html', 'txt', 'docx'],
        'rtf': ['pdf', 'txt', 'docx', 'html'],
        'csv': ['xlsx', 'pdf', 'txt', 'html'],
        
        # Audio formats - comprehensive conversions
        'mp3': ['wav', 'ogg', 'aac', 'flac', 'm4a', 'wma', 'opus'],
        'wav': ['mp3', 'ogg', 'aac', 'flac', 'm4a', 'opus'],
        'ogg': ['mp3', 'wav', 'aac', 'flac', 'm4a'],
        'aac': ['mp3', 'wav', 'ogg', 'flac', 'm4a'],
        'flac': ['mp3', 'wav', 'ogg', 'aac', 'm4a'],
        'm4a': ['mp3', 'wav', 'ogg', 'aac', 'flac'],
        'wma': ['mp3', 'wav', 'ogg', 'aac'],
        'opus': ['mp3', 'wav', 'ogg', 'aac'],
        
        # Video formats - comprehensive conversions
        'mp4': ['mp3', 'wav', 'avi', 'webm', 'mkv', 'mov', 'flv', 'wmv', 'gif'],
        'avi': ['mp4', 'mp3', 'webm', 'mkv', 'mov'],
        'mov': ['mp4', 'mp3', 'avi', 'webm', 'mkv'],
        'webm': ['mp4', 'mp3', 'avi', 'mkv'],
        'mkv': ['mp4', 'mp3', 'avi', 'webm', 'mov'],
        'flv': ['mp4', 'mp3', 'avi', 'webm'],
        'wmv': ['mp4', 'mp3', 'avi'],
        
        # Archive formats
        'zip': ['tar', 'gz', '7z'],
        'tar': ['zip', 'gz'],
        'gz': ['zip', 'tar'],
        '7z': ['zip', 'tar'],
        'rar': ['zip', 'tar']
    }
    return conversion_map.get(file_extension.lower(), [])

async def convert_uploaded_file(request):
    """Convert file format endpoint with real-time progress tracking"""
    try:
        user_id = await get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        data = await request.json()
        file_id = data.get('file_id')
        target_format = data.get('target_format', '').lower()
        
        if not file_id or not target_format:
            return web.json_response({"error": "Missing parameters"}, status=400)
        
        # Get file metadata
        file_meta = await g.redis_client.hgetall(f"file:{file_id}")
        
        # Firestore fallback for file metadata
        if not file_meta and g.db:
            try:
                file_doc = g.db.collection('files').document(file_id).get()
                if file_doc.exists:
                    fb_data = file_doc.to_dict()
                    file_meta = {
                        'id': file_id,
                        'user_id': fb_data.get('user_id', ''),
                        'filename': fb_data.get('filename', ''),
                        'file_type': fb_data.get('file_type', 'document'),
                        'extension': fb_data.get('extension', ''),
                        'size': str(fb_data.get('size', 0)),
                        'path': fb_data.get('path', ''),
                        'url': fb_data.get('url', ''),
                        'thumbnail_url': fb_data.get('thumbnail_url', ''),
                        'uploaded_at': str(fb_data.get('uploaded_at', '')),
                    }
                    # Cache back to Redis
                    await g.redis_client.hset(f"file:{file_id}", mapping=file_meta)
                    logger.info(f"✅ Restored file {file_id} metadata from Firestore")
            except Exception as fb_err:
                logger.warning(f"Firestore file fallback failed for {file_id}: {fb_err}")
        
        if not file_meta:
            return web.json_response({"error": "File not found"}, status=404)

        try:
            source_path = _resolve_safe_path(UPLOAD_DIR, file_meta['path'])
        except ValueError as e:
            logger.error(f"❌ Blocked path traversal in convert_uploaded_file: {e}")
            return web.json_response({"error": "Invalid file path"}, status=400)

        if not source_path.exists():
            return web.json_response({"error": "Source file missing"}, status=404)
        
        source_ext = file_meta['extension']
        
        # Validate conversion support
        supported_formats = get_supported_conversions(source_ext)
        if target_format not in supported_formats:
            return web.json_response({
                "error": f"Cannot convert {source_ext} to {target_format}",
                "supported_formats": supported_formats
            }, status=400)
        
        # ✅ FIX 1: Create output in correct subdirectory based on target format
        target_file_type = get_file_type(target_format)
        target_subdir_name = {
            'image': 'images',
            'video': 'videos',
            'audio': 'audio',
            'document': 'documents',
            'archive': 'archives'
        }.get(target_file_type, 'documents')
        
        target_subdir = UPLOAD_DIR / target_subdir_name
        target_subdir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename for converted file
        converted_id = str(uuid.uuid4())
        output_filename = f"{converted_id}.{target_format}"
        output_path = target_subdir / output_filename
        
        # Initialize progress tracking
        conversion_id = f"conversion:{file_id}:{target_format}"
        await g.redis_client.hset(conversion_id, mapping={
            "status": "processing",
            "progress": "0",
            "started_at": datetime.datetime.now(datetime.UTC).isoformat()
        })
        await g.redis_client.expire(conversion_id, 600)
        
        logger.info(f"🔄 Starting conversion: {source_ext} → {target_format} for file {file_id}")
        
        try:
            # Update progress: Preparation phase (0-10%)
            await g.redis_client.hset(conversion_id, "progress", "5")
            
            # Determine file type category
            image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
            audio_exts = ['mp3', 'wav', 'ogg', 'aac', 'm4a']
            video_exts = ['mp4', 'avi', 'mov', 'webm', 'mkv']
            
            # Progress tracking varies by conversion type
            if source_ext in image_exts and (target_format in image_exts or target_format == 'pdf'):
                await g.redis_client.hset(conversion_id, "progress", "20")
                result_path = convert_image_format(str(source_path), str(output_path), target_format)
                await g.redis_client.hset(conversion_id, "progress", "90")
                
            elif source_ext in ['pdf', 'docx', 'txt'] or target_format in ['pdf', 'docx', 'txt']:
                await g.redis_client.hset(conversion_id, "progress", "25")
                result_path = convert_document_format(str(source_path), str(output_path), source_ext, target_format)
                await g.redis_client.hset(conversion_id, "progress", "85")
                
            elif source_ext in audio_exts and target_format in audio_exts:
                await g.redis_client.hset(conversion_id, "progress", "15")
                
                async def audio_progress():
                    for i in [30, 50, 70]:
                        await asyncio.sleep(0.5)
                        await g.redis_client.hset(conversion_id, "progress", str(i))
                
                progress_task = asyncio.create_task(audio_progress())
                result_path = convert_audio_format(str(source_path), str(output_path), target_format)
                await progress_task
                await g.redis_client.hset(conversion_id, "progress", "90")
                
            elif source_ext in video_exts and (target_format in video_exts or target_format in audio_exts):
                await g.redis_client.hset(conversion_id, "progress", "10")
                
                async def video_progress():
                    for i in [25, 40, 55, 70, 85]:
                        await asyncio.sleep(1.0)
                        await g.redis_client.hset(conversion_id, "progress", str(i))
                
                progress_task = asyncio.create_task(video_progress())
                result_path = convert_video_format(str(source_path), str(output_path), target_format)
                await progress_task
                await g.redis_client.hset(conversion_id, "progress", "95")
                
            else:
                raise Exception(f"Conversion {source_ext} → {target_format} not supported")
            
            # Finalization (95-100%)
            await g.redis_client.hset(conversion_id, "progress", "95")
            
            converted_size = output_path.stat().st_size
            
            # Generate thumbnail if it's an image
            thumbnail_url = None
            if target_file_type == 'image':
                try:
                    thumbnail_url = await generate_thumbnail(output_path, converted_id, target_format)
                except Exception as thumb_err:
                    logger.warning(f"⚠️ Thumbnail generation failed: {thumb_err}")
            
            await g.redis_client.hset(conversion_id, "progress", "98")
            
            # ✅ FIX 2: Correct URL construction
            file_url = f"/api/uploads/{target_subdir_name}/{converted_id}.{target_format}"
            
            # Save converted file metadata
            converted_meta = {
                "id": converted_id,
                "user_id": user_id,
                "filename": f"{file_meta['filename'].rsplit('.', 1)[0]}.{target_format}",
                "file_type": target_file_type,
                "extension": target_format,
                "size": str(converted_size),
                "path": str(output_path.absolute()),
                "url": file_url,
                "uploaded_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "original_file_id": file_id
            }
            
            if thumbnail_url:
                converted_meta["thumbnail_url"] = thumbnail_url
            
            # Save to Redis
            await g.redis_client.hset(f"file:{converted_id}", mapping=converted_meta)
            await g.redis_client.sadd(f"user_files:{user_id}", converted_id)
            
            # Save to Firestore
            if g.db:
                try:
                    firestore_doc = {
                        **converted_meta,
                        "size": converted_size,
                        "uploaded_at": firestore.SERVER_TIMESTAMP
                    }
                    g.db.collection('files').document(converted_id).set(firestore_doc)
                    logger.info(f"✅ Converted file saved to Firestore: {converted_id}")
                except Exception as fb_err:
                    logger.error(f"Firestore save failed: {fb_err}")
            
            # Mark conversion as complete
            await g.redis_client.hset(conversion_id, mapping={
                "status": "completed",
                "progress": "100",
                "completed_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "converted_file_id": converted_id
            })
            
            logger.info(f"✅ File converted: {file_id} → {converted_id} ({source_ext} → {target_format})")
            logger.info(f"✅ Converted file path: {output_path}")
            logger.info(f"✅ Converted file URL: {file_url}")
            
            return web.json_response({
                "success": True,
                "conversion_id": conversion_id,
                "converted_file": {
                    "id": converted_id,
                    "filename": converted_meta['filename'],
                    "type": target_file_type,
                    "size": converted_size,
                    "url": file_url,
                    "thumbnail_url": thumbnail_url
                }
            })
            
        except subprocess.CalledProcessError as ffmpeg_err:
            await g.redis_client.hset(conversion_id, mapping={
                "status": "failed",
                "error": f"Conversion tool error: {str(ffmpeg_err.stderr[:200])}"
            })
            logger.error(f"Conversion tool error: {ffmpeg_err}")
            return web.json_response({
                "error": "File conversion failed. The file may be corrupted or in an unsupported format."
            }, status=500)
            
        except Exception as conv_err:
            await g.redis_client.hset(conversion_id, mapping={
                "status": "failed",
                "error": str(conv_err)
            })
            logger.error(f"Conversion error: {conv_err}", exc_info=True)
            return web.json_response({
                "error": f"Conversion failed: {str(conv_err)}"
            }, status=500)
            
    except Exception as e:
        logger.error(f"Convert file error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def get_conversion_progress(request):
    """Get real-time conversion progress"""
    try:
        user_id = await get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
            
        conversion_id = request.match_info['conversion_id']
            
        conversion_data = await g.redis_client.hgetall(conversion_id)
            
        if not conversion_data:
            return web.json_response({"error": "Conversion not found"}, status=404)
            
        return web.json_response({
            "status": conversion_data.get('status', 'unknown'),
            "progress": int(conversion_data.get('progress', 0)),
            "error": conversion_data.get('error'),
            "converted_file_id": conversion_data.get('converted_file_id')
        })
            
    except Exception as e:
        logger.error(f"Get progress error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_conversion_formats(request):
    """Get supported conversion formats for a file extension"""
    try:
        file_extension = request.query.get('ext', '').lower()
        
        if not file_extension:
            # Return general categories if no specific extension provided
            return web.json_response({
                "image": ["png", "jpg", "jpeg", "webp", "pdf", "bmp", "gif", "tiff", "ico"],
                "document": ["pdf", "docx", "doc", "txt", "html", "md", "rtf", "pptx", "xlsx", "csv"],
                "audio": ["mp3", "wav", "ogg", "aac", "flac", "m4a", "opus"],
                "video": ["mp4", "webm", "avi", "mov", "mkv", "flv", "wmv", "gif"]
            })
        
        # Get specific formats for the given extension
        formats = get_supported_conversions(file_extension)
        return web.json_response({"formats": formats})
    except Exception as e:
        logger.error(f"Error getting conversion formats: {e}")
        return web.json_response({"error": str(e)}, status=500)

