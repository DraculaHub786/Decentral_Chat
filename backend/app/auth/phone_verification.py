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
async def send_verification_code(self, request):
    """Send OTP for phone verification using Twilio"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        phone = data.get('phone', '').strip()

        if not phone:
            return web.json_response({"error": "Phone number required"}, status=400)

        # Normalize phone number (remove spaces)
        phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

        if not phone.startswith('+'):
            return web.json_response({"error": "Phone must include country code (e.g., +1234567890)"}, status=400)

        logger.info(f"📱 Normalized phone number: {_log_safe(phone)}")

        # Generate 6-digit OTP
        otp = ''.join(secrets.choice(string.digits) for _ in range(6))
        
        # Store OTP in Redis with 10-minute expiry
        await g.redis_client.setex(f"otp:{phone}", 600, otp)
        
        # ✅ DEBUG: Check if environment variables are loaded
        TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
        TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
        TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
        
        logger.info(f"🔍 TWILIO_ACCOUNT_SID exists: {bool(TWILIO_ACCOUNT_SID)}")
        logger.info(f"🔍 TWILIO_AUTH_TOKEN exists: {bool(TWILIO_AUTH_TOKEN)}")
        logger.info(f"🔍 TWILIO_PHONE_NUMBER exists: {bool(TWILIO_PHONE_NUMBER)}")
        
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER:
            try:
                from twilio.rest import Client
                
                logger.info("📞 Attempting to send SMS via Twilio...")
                
                client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                
                message = client.messages.create(
                    body=f"Your DecentralChat verification code is: {otp}\n\nThis code expires in 10 minutes.",
                    from_=TWILIO_PHONE_NUMBER,
                    to=phone
                )
                
                logger.info(f"✅ SMS sent successfully to {phone} - SID: {message.sid}")
                
                return web.json_response({
                    "success": True, 
                    "message": "Verification code sent to your phone"
                })
                
            except Exception as sms_error:
                logger.error(f"❌ Twilio SMS sending failed: {sms_error}")
                
                error_message = str(sms_error)
                
                # Enhanced error messages
                if "unverified" in error_message.lower() or "21608" in error_message:
                    return web.json_response({
                        "error": f"Phone number not verified in Twilio. Verify at: https://console.twilio.com/us1/develop/phone-numbers/manage/verified",
                        "dev_mode": True,
                        "dev_otp": otp
                    }, status=400)
                
                if "21211" in error_message:
                    return web.json_response({
                        "error": "Invalid phone number format",
                        "dev_otp": otp
                    }, status=400)
                
                # Fallback: Return OTP for testing
                return web.json_response({
                    "success": True,
                    "message": "SMS failed, showing code for testing",
                    "dev_otp": otp,
                    "error_details": error_message
                })
        else:
            # Development mode
            logger.warning(f"⚠️ DEV MODE - Twilio not configured")
            logger.warning(f"📱 OTP for {phone}: {otp}")
            
            return web.json_response({
                "success": True,
                "message": "DEV MODE: OTP shown in response",
                "dev_otp": otp,
                "note": "Configure Twilio environment variables"
            })

    except Exception as e:
        logger.error(f"Send OTP error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def verify_phone_code(self, request):
    """Verify OTP and update phone number"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        phone = data.get('phone', '').strip()
        code = data.get('code', '').strip()

        if not phone or not code:
            return web.json_response({"error": "Phone and code required"}, status=400)

        # Verify OTP
        stored_otp = await g.redis_client.get(f"otp:{phone}")
        
        if not stored_otp or stored_otp != code:
            return web.json_response({"error": "Invalid or expired code"}, status=400)

        # Update user's phone
        await g.redis_client.hset(f"user:{user_id}", mapping={
            "phone": phone,
            "phone_verified": "true"
        })

        await g.redis_client.hset("phone_map", phone, user_id)
        await g.redis_client.delete(f"otp:{phone}")

        if self.db:
            try:
                self.db.collection('users').document(user_id).set({
                    'phone': phone,
                    'phone_verified': True
                }, merge=True)
            except Exception as fb_err:
                logger.error(f"Firestore update error: {fb_err}")

        logger.info(f"✅ Phone verified: {user_id}")

        return web.json_response({"success": True, "phone": phone})

    except Exception as e:
        logger.error(f"Verify phone error: {e}")
        return web.json_response({"error": str(e)}, status=500)

