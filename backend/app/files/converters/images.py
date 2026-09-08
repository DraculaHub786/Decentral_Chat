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
def convert_image_format(input_path, output_path, target_format):
    """Convert image to target format - Production-ready with comprehensive format support"""
    try:
        # Open and auto-orient image based on EXIF data
        img = Image.open(input_path)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass  # No EXIF data or already oriented
        
        original_mode = img.mode
        logger.info(f"🖼️ Converting image: {original_mode} mode → {target_format.upper()}")
        
        # Special case: Image to PDF
        if target_format.lower() == 'pdf':
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else img.split()[1])
                    img = background
                else:
                    img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save as PDF with high quality
            img.save(output_path, 'PDF', resolution=100.0, quality=95)
            logger.info(f"✅ Image to PDF conversion successful")
            return output_path
        
        # Handle transparency for formats that don't support it (JPG, BMP, ICO)
        if target_format.lower() in ['jpg', 'jpeg', 'bmp', 'ico'] and img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
        
        # Handle palette mode for formats that need RGB
        if img.mode == 'P' and target_format.lower() not in ['gif', 'png']:
            img = img.convert('RGB')
        
        # Ensure RGBA for formats that support it
        if target_format.lower() in ['png', 'webp'] and img.mode == 'RGB':
            img = img.convert('RGBA')
        
        # Save with format-specific optimizations
        save_kwargs = {}
        
        if target_format.lower() in ['jpg', 'jpeg']:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            save_kwargs = {'format': 'JPEG', 'quality': 95, 'optimize': True, 'progressive': True}
            
        elif target_format.lower() == 'png':
            save_kwargs = {'format': 'PNG', 'optimize': True, 'compress_level': 6}
            
        elif target_format.lower() == 'webp':
            save_kwargs = {'format': 'WEBP', 'quality': 90, 'method': 6}
            
        elif target_format.lower() == 'gif':
            # Optimize GIF with proper quantization
            if img.mode != 'P':
                img = img.convert('P', palette=Image.ADAPTIVE, colors=256)
            save_kwargs = {'format': 'GIF', 'optimize': True, 'save_all': True}
            
        elif target_format.lower() == 'bmp':
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            save_kwargs = {'format': 'BMP'}
            
        elif target_format.lower() in ['tiff', 'tif']:
            save_kwargs = {'format': 'TIFF', 'compression': 'tiff_lzw'}
            
        elif target_format.lower() == 'ico':
            # ICO format: Create multi-resolution icon
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Create multiple sizes for better quality icons
            icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
            resized_images = []
            
            for size in icon_sizes:
                resized_img = img.copy()
                resized_img.thumbnail(size, Image.Resampling.LANCZOS)
                # Ensure exact size by creating new image and pasting
                sized_img = Image.new('RGBA', size, (0, 0, 0, 0))
                paste_x = (size[0] - resized_img.size[0]) // 2
                paste_y = (size[1] - resized_img.size[1]) // 2
                sized_img.paste(resized_img, (paste_x, paste_y))
                resized_images.append(sized_img)
            
            # Save multi-resolution ICO
            resized_images[0].save(output_path, format='ICO', sizes=[(img.size[0], img.size[1]) for img in resized_images])
            logger.info(f"✅ Multi-resolution ICO created with {len(icon_sizes)} sizes")
            return output_path
            
        else:
            # Generic format handling
            save_kwargs = {'format': target_format.upper()}
        
        # Save the image
        img.save(output_path, **save_kwargs)
        logger.info(f"✅ Image conversion successful: {target_format.upper()}")
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Image conversion failed: {str(e)}")
        raise Exception(f"Image conversion failed: {str(e)}")

