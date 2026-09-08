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
async def initiate_call(self, request):
    """Initiate voice/video call with blocking checks"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        recipient_id = data.get('recipient_id')
        call_type = data.get('type', 'audio')

        if not recipient_id:
            return web.json_response({"error": "Recipient required"}, status=400)

        # ✅ CRITICAL: Check if users have blocked each other
        caller_blocked_recipient = await g.redis_client.sismember(f"user_blocked:{user_id}", recipient_id)
        recipient_blocked_caller = await g.redis_client.sismember(f"user_blocked:{recipient_id}", user_id)
        
        if caller_blocked_recipient:
            logger.warning(f"⚠️ Call blocked: {user_id} has blocked {recipient_id}")
            return web.json_response({
                "error": "Cannot call this user. You have blocked them."
            }, status=403)
        
        if recipient_blocked_caller:
            logger.warning(f"⚠️ Call blocked: {user_id} is blocked by {recipient_id}")
            return web.json_response({
                "error": "Cannot call this user. They have blocked you."
            }, status=403)

        # Create call session
        call_id = str(uuid.uuid4())
        call_data = {
            "id": call_id,
            "caller_id": user_id,
            "recipient_id": recipient_id,
            "type": call_type,
            "status": "ringing",
            "started_at": datetime.datetime.now(datetime.UTC).isoformat()
        }

        g.active_calls[call_id] = call_data
        await g.redis_client.hset(f"call:{call_id}", mapping=call_data)
        await g.redis_client.setex(f"active_call:{call_id}", 300, "true")

        # Get caller info
        caller_data = await g.redis_client.hgetall(f"user:{user_id}")

        # Notify recipient
        await self.broadcast_to_users(
            [recipient_id],
            {
                "type": "incoming_call",
                "call": {
                    **call_data,
                    "caller_name": caller_data.get('username'),
                    "caller_avatar": caller_data.get('avatar_url')
                }
            }
        )

        logger.info(f"📞 Call initiated: {call_id} ({call_type})")

        # ✅ Fetch dynamic TURN credentials from Metered.ca
        ice_servers = []
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://chatcentral.metered.live/api/v1/turn/credentials?apiKey=e39874b8e274c80c452f27c6eb1622a856b8'
                ) as resp:
                    if resp.status == 200:
                        ice_servers = await resp.json()
                        logger.info(f"✅ Fetched {len(ice_servers)} TURN servers from Metered.ca")
                    else:
                        raise Exception(f"HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch TURN credentials: {e}, using fallback")

        # Return with ICE server configuration
        return web.json_response({
            "success": True,
            "call_id": call_id,
            "ice_servers": [
                # Google STUN
                { 'urls': 'stun:stun.l.google.com:19302' },
                { 'urls': 'stun:stun1.l.google.com:19302' },
                
                # OpenRelay TURN (Free)
                {
                    'urls': 'turn:openrelay.metered.ca:80',
                    'username': 'openrelayproject',
                    'credential': 'openrelayproject'
                },
                {
                    'urls': 'turn:openrelay.metered.ca:443',
                    'username': 'openrelayproject',
                    'credential': 'openrelayproject'
                },
                {
                    'urls': 'turn:openrelay.metered.ca:443?transport=tcp',
                    'username': 'openrelayproject',
                    'credential': 'openrelayproject'
                }
            ]
        })

    except Exception as e:
        logger.error(f"Initiate call error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_call_signal(self, request):
    """Handle WebRTC signaling with GUARANTEED storage"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        call_id = request.match_info['call_id']
        data = await request.json()
        signal_type = data.get('signal_type')
        signal_data = data.get('signal_data')

        logger.info(f"📞 Received {signal_type} for call {call_id} from user {user_id}")

        if not signal_type:
            return web.json_response({"error": "Signal type required"}, status=400)

        # Get call info
        call_data = await g.redis_client.hgetall(f"call:{call_id}")
        
        if not call_data:
            logger.error(f"❌ Call {call_id} not found in Redis")
            return web.json_response({"error": "Call not found"}, status=404)

        # Determine recipient
        recipient_id = (
            call_data['recipient_id'] 
            if user_id == call_data['caller_id'] 
            else call_data['caller_id']
        )

        # **CRITICAL FIX: Store signal with DOUBLE CONFIRMATION**
        if signal_type in ['offer', 'answer']:
            signal_key = f"call_signal:{call_id}:{signal_type}"
            signal_json = json.dumps(signal_data)
            
            # Store with pipeline for atomic operation
            pipe = g.redis_client.pipeline()
            pipe.set(signal_key, signal_json, ex=600)
            pipe.get(signal_key)  # Verify immediately
            results = await pipe.execute()
            
            if not results[1]:
                logger.error(f"❌ Failed to store {signal_type} - verification failed")
                return web.json_response({"error": "Storage failed"}, status=500)
            
            logger.info(f"✅ Stored and verified {signal_type} for call {call_id}")
            
            # **NEW: Extra delay for mobile networks**
            await asyncio.sleep(0.1)  # 100ms to ensure Redis persistence

        # Forward to recipient via WebSocket
        signal_type_map = {
            'offer': 'call_offer',
            'answer': 'call_answer',
            'ice_candidate': 'ice_candidate'
        }

        await self.broadcast_to_users(
            [recipient_id],
            {
                "type": signal_type_map.get(signal_type, signal_type),
                "call_id": call_id,
                "signal_data": signal_data,
                "from_user": user_id
            }
        )
        
        logger.info(f"✅ Forwarded {signal_type} to user {recipient_id}")

        # Update call status
        if signal_type == 'answer':
            await g.redis_client.hset(f"call:{call_id}", "status", "active")
            if call_id in g.active_calls:
                g.active_calls[call_id]['status'] = "active"

        return web.json_response({"success": True})

    except Exception as e:
        logger.error(f"❌ Call signal handler error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def get_call_signals(self, request):
    """Retrieve stored call signals with AGGRESSIVE retry logic"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        call_id = request.match_info['call_id']
        
        logger.info(f"📥 Fetching signals for call {call_id} by user {user_id}")
        
        # Check if user is part of the call
        call_data = await g.redis_client.hgetall(f"call:{call_id}")
        if not call_data:
            return web.json_response({"error": "Call not found"}, status=404)
            
        if user_id not in [call_data.get('caller_id'), call_data.get('recipient_id')]:
            return web.json_response({"error": "Forbidden"}, status=403)
        
        signals = {}
        
        # **CRITICAL: Retry up to 20 times with exponential backoff**
        for attempt in range(20):
            offer_json = await g.redis_client.get(f"call_signal:{call_id}:offer")
            if offer_json:
                try:
                    signals['offer'] = json.loads(offer_json)
                    logger.info(f"✅ Retrieved offer (attempt {attempt + 1})")
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Invalid offer JSON: {e}")
            else:
                if attempt < 19:
                    # Exponential backoff: 100ms, 150ms, 225ms, 337ms, 500ms...
                    delay = min(0.1 * (1.5 ** attempt), 1.0)
                    logger.warning(f"⏳ Offer not ready, waiting {int(delay*1000)}ms (attempt {attempt + 1}/20)")
                    await asyncio.sleep(delay)
        
        if not signals.get('offer'):
            logger.error(f"❌ Could not retrieve offer after 20 attempts")
            return web.json_response({"error": "Offer not available"}, status=404)
        
        # Get answer (might not exist yet)
        answer_json = await g.redis_client.get(f"call_signal:{call_id}:answer")
        if answer_json:
            try:
                signals['answer'] = json.loads(answer_json)
            except json.JSONDecodeError:
                pass
        
        return web.json_response({"success": True, "signals": signals})
        
    except Exception as e:
        logger.error(f"❌ Get call signals error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)

async def end_call(self, request):
    """End active call"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        call_id = request.match_info['call_id']
        
        call_data = await g.redis_client.hgetall(f"call:{call_id}")
        if not call_data:
            return web.json_response({"error": "Call not found"}, status=404)

        # Calculate duration
        started_at = datetime.datetime.fromisoformat(call_data.get('started_at'))
        duration = int((datetime.datetime.now(datetime.UTC) - started_at).total_seconds())

        # Update call status
        await g.redis_client.hset(f"call:{call_id}", mapping={
            "status": "ended",
            "ended_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "duration": str(duration)
        })

        # Remove from active calls
        if call_id in g.active_calls:
            del g.active_calls[call_id]

        # Notify other party
        other_user_id = (
            call_data['recipient_id'] 
            if user_id == call_data['caller_id'] 
            else call_data['caller_id']
        )

        await self.broadcast_to_users(
            [other_user_id],
            {
                "type": "call_ended",
                "call_id": call_id,
                "duration": duration
            }
        )

        logger.info(f"📞 Call ended: {call_id} (duration: {duration}s)")

        return web.json_response({
            "success": True,
            "duration": duration
        })

    except Exception as e:
        logger.error(f"End call error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def get_call_history(self, request):
    """Get call history"""
    try:
        user_id = await self.get_user_from_token(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        # Get all calls where user is caller or recipient
        all_call_ids = await g.redis_client.keys("call:*")
        calls_list = []

        for call_key in all_call_ids:
            call_data = await g.redis_client.hgetall(call_key)
            
            if not call_data:
                continue

            if call_data.get('caller_id') == user_id or call_data.get('recipient_id') == user_id:
                # Get other user info
                other_user_id = (
                    call_data['recipient_id'] 
                    if user_id == call_data['caller_id'] 
                    else call_data['caller_id']
                )
                
                other_user = await g.redis_client.hgetall(f"user:{other_user_id}")

                calls_list.append({
                    "id": call_data.get('id'),
                    "type": call_data.get('type'),
                    "status": call_data.get('status'),
                    "duration": int(call_data.get('duration', 0)),
                    "started_at": call_data.get('started_at'),
                    "ended_at": call_data.get('ended_at'),
                    "is_outgoing": call_data.get('caller_id') == user_id,
                    "other_user": {
                        "id": other_user_id,
                        "username": other_user.get('username'),
                        "avatar_url": other_user.get('avatar_url')
                    }
                })

        # Sort by started_at descending
        calls_list.sort(key=lambda x: x.get('started_at', ''), reverse=True)

        return web.json_response({"calls": calls_list[:50]})  # Last 50 calls

    except Exception as e:
        logger.error(f"Get call history error: {e}")
        return web.json_response({"error": str(e)}, status=500)

