"""DecentralChatServer: thin orchestrator delegating to modular handlers."""
import logging
import asyncio
from aiohttp import web
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import os, aiohttp_cors

from app.globals import g
from app.core.config import SECRET_KEY, PORT, UPLOAD_DIR
from app.core.rate_limiter import RateLimiter
from app.core.redis_client import init_redis
from app.core.firebase_client import init_firebase
from app.core.middleware import csrf_middleware, security_headers_middleware

from app.auth.handlers import (handle_register, handle_login, handle_logout, refresh_token)
from app.auth.google import handle_google_auth
from app.auth.phone_verification import send_verification_code, verify_phone_code
from app.users.handlers import (get_current_user, update_profile, get_user_public_key,
    upload_avatar, update_email, update_phone, search_users, search_all_users,
    update_user_profile, get_user_by_id, get_user_settings, update_user_settings)
from app.contacts.handlers import (get_contacts, add_contact, remove_contact,
    block_user, unblock_user, check_blocked_status, get_blocked_users)
from app.chats.handlers import (get_chats, create_chat, get_chat, delete_chat,
    add_chat_member, remove_chat_member, update_group_chat)
from app.messages.handlers import (get_messages, search_messages_in_chat,
    send_message_http, delete_message, edit_message, delete_message_for_all,
    delete_message_for_me, forward_message)
from app.files.handlers import (upload_file, upload_voice, get_file, get_thumbnail,
    serve_upload, generate_thumbnail, get_file_type, _check_upload_rate_limit,
    migrate_existing_files)
from app.files.converters.service import (convert_uploaded_file,
    get_conversion_formats, get_conversion_progress)
from app.calls.handlers import (initiate_call, handle_call_signal, get_call_signals,
    end_call, get_call_history)
from app.calls.group.handlers import (initiate_group_call, join_group_call,
    leave_group_call, get_group_call_participants)
from app.static.frontend_routes import (serve_frontend, serve_favicon, index, health_check)
from app.admin.debug_routes import debug_check_user, debug_redis_state, debug_user_chats
from app.sync.firestore_sync import (preload_critical_data_from_firestore,
    sync_redis_to_firestore_periodically)
from app.ws.handler import websocket_handler

logger = logging.getLogger(__name__)


class DecentralChatServer:
    def __init__(self):
        self.app = web.Application(client_max_size=100 * 1024 * 1024)
        self.firebase_app = None
        self.storage_bucket = None
        self.db = None
        self.rate_limiter = RateLimiter(max_attempts=5, window_seconds=60)

    async def initialize(self):
        """Initialize all services."""
        await init_redis(self)
        init_firebase(self)
        await migrate_existing_files(self)
        await preload_critical_data_from_firestore(self)

        self.app.middlewares.append(csrf_middleware)
        self.app.middlewares.append(security_headers_middleware)

        self.setup_routes()
        self.setup_cors()
        self.setup_session()

        if self.db is not None:
            asyncio.create_task(sync_redis_to_firestore_periodically(self))
            logger.info("✅ Started periodic Firestore sync")

        logger.info("✅ Server initialized successfully")

    def setup_session(self):
        secret_key = SECRET_KEY.encode()[:32].ljust(32, b'0')
        setup_session(self.app, EncryptedCookieStorage(secret_key))

    def setup_cors(self):
        allowed_origin = os.getenv('ALLOWED_ORIGIN', '*')
        cors = aiohttp_cors.setup(self.app, defaults={
            allowed_origin: aiohttp_cors.ResourceOptions(
                allow_credentials=True, expose_headers="*",
                allow_headers="*", allow_methods="*")})
        for route in list(self.app.router.routes()):
            cors.add(route)

    def setup_routes(self):
        """Setup all API routes (delegated to modular handlers)."""
        self.app.router.add_get('/api/uploads/{filename:.*}', serve_upload)
        self.app.router.add_static('/api/uploads/', path=str(UPLOAD_DIR), name='uploads')
        self.app.router.add_get('/', serve_frontend)
        self.app.router.add_get('/index.html', serve_frontend)
        self.app.router.add_get('/favicon.ico', serve_favicon)
        self.app.router.add_get('/api', index)
        self.app.router.add_get('/health', health_check)

        # Authentication
        self.app.router.add_post('/api/auth/register', handle_register)
        self.app.router.add_post('/api/auth/login', handle_login)
        self.app.router.add_post('/api/auth/google', handle_google_auth)
        self.app.router.add_post('/api/auth/logout', handle_logout)
        self.app.router.add_post('/api/auth/refresh', refresh_token)

        # User management
        self.app.router.add_get('/api/users/me', get_current_user)
        self.app.router.add_put('/api/users/me', update_profile)
        self.app.router.add_post('/api/users/avatar', upload_avatar)
        self.app.router.add_get('/api/users/search', search_users)
        self.app.router.add_get('/api/users/{user_id}/public_key', get_user_public_key)

        # Contacts
        self.app.router.add_get('/api/contacts', get_contacts)
        self.app.router.add_post('/api/contacts', add_contact)
        self.app.router.add_delete('/api/contacts/{contact_id}', remove_contact)

        # Chats
        self.app.router.add_get('/api/chats', get_chats)
        self.app.router.add_post('/api/chats', create_chat)
        self.app.router.add_get('/api/chats/{chat_id}', get_chat)
        self.app.router.add_delete('/api/chats/{chat_id}', delete_chat)
        self.app.router.add_post('/api/chats/{chat_id}/members', add_chat_member)
        self.app.router.add_delete('/api/chats/{chat_id}/members/{user_id}', remove_chat_member)

        # Messages
        self.app.router.add_get('/api/chats/{chat_id}/messages', get_messages)
        self.app.router.add_post('/api/chats/{chat_id}/messages', send_message_http)
        self.app.router.add_delete('/api/messages/{message_id}', delete_message)
        self.app.router.add_put('/api/messages/{message_id}', edit_message)
        self.app.router.add_get('/api/chats/{chat_id}/messages/search', search_messages_in_chat)

        # Files
        self.app.router.add_post('/api/upload', upload_file)
        self.app.router.add_post('/api/upload/file', upload_file)
        self.app.router.add_post('/api/upload/voice', upload_voice)
        self.app.router.add_get('/api/files/{file_id}', get_file)
        self.app.router.add_get('/api/files/{file_id}/thumbnail', get_thumbnail)
        self.app.router.add_post('/api/files/convert', convert_uploaded_file)
        self.app.router.add_get('/api/files/conversion-formats', get_conversion_formats)
        self.app.router.add_get('/api/files/conversion-progress/{conversion_id}', get_conversion_progress)

        # Calls
        self.app.router.add_post('/api/calls/initiate', initiate_call)
        self.app.router.add_post('/api/calls/{call_id}/signal', handle_call_signal)
        self.app.router.add_post('/api/calls/{call_id}/end', end_call)
        self.app.router.add_get('/api/calls/history', get_call_history)
        self.app.router.add_get('/api/calls/{call_id}/signals', get_call_signals)

        # Group Calls
        self.app.router.add_post('/api/calls/group/initiate', initiate_group_call)
        self.app.router.add_post('/api/calls/group/{call_id}/join', join_group_call)
        self.app.router.add_post('/api/calls/group/{call_id}/leave', leave_group_call)
        self.app.router.add_get('/api/calls/group/{call_id}/participants', get_group_call_participants)

        # WebSocket
        self.app.router.add_get('/api/ws', websocket_handler)

        # Settings routes
        self.app.router.add_get('/api/users/settings', get_user_settings)
        self.app.router.add_put('/api/users/settings', update_user_settings)
        self.app.router.add_put('/api/users/profile', update_user_profile)

        # Phone verification routes
        self.app.router.add_post('/api/auth/send-verification-code', send_verification_code)
        self.app.router.add_post('/api/auth/verify-phone', verify_phone_code)

        # Enhanced message actions
        self.app.router.add_delete('/api/messages/{message_id}/for-all', delete_message_for_all)
        self.app.router.add_delete('/api/messages/{message_id}/for-me', delete_message_for_me)
        self.app.router.add_post('/api/messages/forward', forward_message)

        # Debug routes
        self.app.router.add_get('/api/debug/check-user/{username}', debug_check_user)
        self.app.router.add_get('/api/debug/redis/{username}', debug_redis_state)
        self.app.router.add_get('/api/debug/my-chats', debug_user_chats)
        self.app.router.add_get('/api/users/{user_id}/blocked-status', check_blocked_status)

        # Updates in profile
        self.app.router.add_put('/api/chats/{chat_id}/info', update_group_chat)
        self.app.router.add_put('/api/users/email', update_email)
        self.app.router.add_put('/api/users/phone', update_phone)
        self.app.router.add_get('/api/users/search-all', search_all_users)
        self.app.router.add_get('/api/users/{user_id}', get_user_by_id)

        # Blocking routes
        self.app.router.add_post('/api/users/block', block_user)
        self.app.router.add_post('/api/users/unblock', unblock_user)
        self.app.router.add_get('/api/users/blocked', get_blocked_users)

        logger.info("=" * 70)
        logger.info("📋 Registered API Routes:")
        for route in self.app.router.routes():
            logger.info(f"  {route.method:6s} {route.resource.canonical}")
        logger.info("=" * 70)
