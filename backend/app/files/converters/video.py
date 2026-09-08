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
def convert_video_format(input_path, output_path, target_format):
    """Convert video using ffmpeg - Production-ready with comprehensive format support"""
    try:
        logger.info(f"🎬 Converting video to {target_format.upper()}")
        # Extract audio only
        if target_format in ['mp3', 'wav', 'aac', 'ogg']:
            codec_map = {
                'mp3': 'libmp3lame',
                'wav': 'pcm_s16le',
                'aac': 'aac',
                'ogg': 'libvorbis'
            }
            codec = codec_map.get(target_format, 'libmp3lame')
            cmd = ['ffmpeg', '-i', input_path, '-vn', '-acodec', codec]
            if target_format in ['mp3', 'aac']:
                cmd.extend(['-b:a', '192k'])
            cmd.extend(['-y', output_path])
        
        # Convert to GIF (for short videos)
        elif target_format == 'gif':
            logger.info("🔄 Creating GIF with optimized palette...")
            # Generate palette for better quality
            palette_path = output_path + '.palette.png'
            subprocess.run([
                'ffmpeg', '-i', input_path, '-vf',
                'fps=15,scale=480:-1:flags=lanczos,palettegen',
                '-y', palette_path
            ], check=True, capture_output=True)
            
            # Create GIF using palette
            cmd = [
                'ffmpeg', '-i', input_path, '-i', palette_path,
                '-filter_complex',
                'fps=15,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse',
                '-y', output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Clean up palette
            try:
                os.remove(palette_path)
            except:
                pass
            logger.info("✅ Video to GIF conversion successful")
            return output_path
        
        # Video to video conversion
        else:
            codec_map = {
                'mp4': ('libx264', 'aac'),
                'webm': ('libvpx-vp9', 'libopus'),
                'avi': ('mpeg4', 'libmp3lame'),
                'mkv': ('libx264', 'aac'),
                'mov': ('libx264', 'aac'),
                'flv': ('flv', 'libmp3lame'),
                'wmv': ('wmv2', 'wmav2')
            }
            
            vcodec, acodec = codec_map.get(target_format, ('libx264', 'aac'))
            
            cmd = [
                'ffmpeg', '-i', input_path,
                '-c:v', vcodec,
                '-c:a', acodec
            ]
            
            # Add format-specific options
            if target_format == 'mp4':
                cmd.extend(['-preset', 'medium', '-crf', '23'])
            elif target_format == 'webm':
                cmd.extend(['-b:v', '1M', '-b:a', '128k'])
            
            cmd.extend(['-y', output_path])
        
        result = subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"✅ Video conversion successful: {target_format.upper()}")
        return output_path
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"❌ FFmpeg video conversion failed: {error_msg}")
        raise Exception(f"Video conversion failed: {error_msg}")
    except FileNotFoundError:
        logger.error("❌ FFmpeg not found. Please install FFmpeg")
        raise Exception("FFmpeg not found. Install it from: https://ffmpeg.org/download.html")
    except Exception as e:
        logger.error(f"❌ Video conversion error: {str(e)}")
        raise Exception(f"Video conversion error: {str(e)}")

