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
logger = logging.getLogger(__name__)
def init_firebase(self):
    """Initialize Firebase for authentication and Firestore ONLY (no Storage)"""
    try:
        if os.path.exists(FIREBASE_CRED):
            cred = credentials.Certificate(FIREBASE_CRED)
            
            # Check if app already exists
            try:
                self.firebase_app = firebase_admin.get_app()
                logger.info("✅ Using existing Firebase app")
            except ValueError:
                # App doesn't exist, initialize it
                self.firebase_app = firebase_admin.initialize_app(cred)
                logger.info("✅ Firebase initialized")
            
            self.db = firestore.client()
            self.storage_bucket = None
            
        else:
            logger.warning("⚠️ Firebase config not found")
            self.firebase_app = None
            self.db = None
            self.storage_bucket = None
    except Exception as e:
        logger.error(f"❌ Firebase error: {e}")
        self.firebase_app = None
        self.db = None
        self.storage_bucket = None
    # Mirror into the shared state namespace so module-level handlers
    # (frontend_routes, health_check) can access them without `self`.
    g.db = self.db
    g.firebase_app = self.firebase_app
