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
def convert_audio_format(input_path, output_path, target_format):
    """Convert audio using ffmpeg - Production-ready with comprehensive format support"""
    try:
        logger.info(f"🎵 Converting audio to {target_format.upper()}")
        
        codec_map = {
            'mp3': 'libmp3lame',
            'wav': 'pcm_s16le',
            'ogg': 'libvorbis',
            'aac': 'aac',
            'flac': 'flac',
            'm4a': 'aac',
            'wma': 'wmav2',
            'opus': 'libopus'
        }
        codec = codec_map.get(target_format.lower(), 'libmp3lame')
        
        cmd = ['ffmpeg', '-i', input_path, '-acodec', codec]
        
        # Add format-specific options
        if target_format == 'mp3':
            cmd.extend(['-b:a', '192k'])
        elif target_format == 'aac':
            cmd.extend(['-b:a', '192k'])
        elif target_format == 'opus':
            cmd.extend(['-b:a', '128k'])
        elif target_format == 'flac':
            cmd.extend(['-compression_level', '5'])
        
        cmd.extend(['-y', output_path])
        
        result = subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"✅ Audio conversion successful: {target_format.upper()}")
        return output_path
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"❌ FFmpeg audio conversion failed: {error_msg}")
        raise Exception(f"Audio conversion failed: {error_msg}")
    except FileNotFoundError:
        logger.error("❌ FFmpeg not found. Please install FFmpeg")
        raise Exception("FFmpeg not found. Install it from: https://ffmpeg.org/download.html")
    except Exception as e:
        logger.error(f"❌ Audio conversion error: {str(e)}")
        raise Exception(f"Audio conversion error: {str(e)}")

