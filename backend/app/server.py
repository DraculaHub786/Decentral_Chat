"""DecentralChatServer: thin orchestrator delegating to modular handlers."""
import logging
import asyncio
import functools
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
from app.auth.tokens import generate_token, _generate_refresh_token, get_user_from_token

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
from app.calls.ws_signal import handle_ws_call_signal
from app.calls.group.ws_signal import (handle_group_call_start,
    handle_group_call_signal, handle_group_call_ice, handle_group_call_leave_ws)
from app.ws.connection_manager import (broadcast_user_status, broadcast_to_users,
    broadcast_typing)
from app.messages.service import create_message, broadcast_message
from app.static.frontend_routes import (serve_frontend, serve_favicon,
    serve_static_asset, index, health_check)
from app.admin.debug_routes import debug_check_user, debug_redis_state, debug_user_chats
from app.sync.firestore_sync import (preload_critical_data_from_firestore,
    sync_redis_to_firestore_periodically)
from app.ws.handler import websocket_handler, handle_ws_message, handle_read_receipt

logger = logging.getLogger(__name__)


class DecentralChatServer:
    def __init__(self):
        self.app = web.Application(client_max_size=100 * 1024 * 1024)
        self.firebase_app = None
        self.storage_bucket = None
        self.db = None
        self.rate_limiter = RateLimiter(max_attempts=5, window_seconds=60)

    # Token helpers used by auth handlers via `self.generate_token(...)` /
    # `self._generate_refresh_token(...)`. Bound as methods so the wired
    # handlers (which take `(self, request)`) can reach them through `self`.
    generate_token = generate_token
    _generate_refresh_token = _generate_refresh_token
    get_user_from_token = get_user_from_token

    # WebSocket handler helpers used via `self.<name>(...)` inside
    # websocket_handler. Bound as methods so the wired handler (which takes
    # `(self, request)`) can reach them through `self`, mirroring the
    # token helpers above. All of these are defined with `self` as their
    # first parameter in their respective modules.
    websocket_handler = websocket_handler
    handle_ws_message = handle_ws_message
    handle_read_receipt = handle_read_receipt
    broadcast_user_status = broadcast_user_status
    broadcast_to_users = broadcast_to_users
    broadcast_typing = broadcast_typing
    handle_ws_call_signal = handle_ws_call_signal
    handle_group_call_start = handle_group_call_start
    handle_group_call_signal = handle_group_call_signal
    handle_group_call_ice = handle_group_call_ice
    handle_group_call_leave_ws = handle_group_call_leave_ws
    create_message = create_message
    broadcast_message = broadcast_message

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

        # Catch-all for frontend static assets (styles.css, app.js, images,
        # etc.) referenced by index.html via relative paths. Registered after
        # the explicit API routes so it never shadows them.
        self.app.router.add_get('/{filename:.*}', serve_static_asset)

        # Authentication (handlers take (self, request) -> bind self)
        self.app.router.add_post('/api/auth/register', functools.partial(handle_register, self))
        self.app.router.add_post('/api/auth/login', functools.partial(handle_login, self))
        self.app.router.add_post('/api/auth/google', functools.partial(handle_google_auth, self))
        self.app.router.add_post('/api/auth/logout', functools.partial(handle_logout, self))
        self.app.router.add_post('/api/auth/refresh', functools.partial(refresh_token, self))

        # User management
        self.app.router.add_get('/api/users/me', functools.partial(get_current_user, self))
        self.app.router.add_put('/api/users/me', functools.partial(update_profile, self))
        self.app.router.add_post('/api/users/avatar', functools.partial(upload_avatar, self))
        self.app.router.add_get('/api/users/search', functools.partial(search_users, self))
        self.app.router.add_get('/api/users/{user_id}/public_key', functools.partial(get_user_public_key, self))

        # Contacts
        self.app.router.add_get('/api/contacts', functools.partial(get_contacts, self))
        self.app.router.add_post('/api/contacts', functools.partial(add_contact, self))
        self.app.router.add_delete('/api/contacts/{contact_id}', functools.partial(remove_contact, self))

        # Chats
        self.app.router.add_get('/api/chats', functools.partial(get_chats, self))
        self.app.router.add_post('/api/chats', functools.partial(create_chat, self))
        self.app.router.add_get('/api/chats/{chat_id}', functools.partial(get_chat, self))
        self.app.router.add_delete('/api/chats/{chat_id}', functools.partial(delete_chat, self))
        self.app.router.add_post('/api/chats/{chat_id}/members', functools.partial(add_chat_member, self))
        self.app.router.add_delete('/api/chats/{chat_id}/members/{user_id}', functools.partial(remove_chat_member, self))

        # Messages
        self.app.router.add_get('/api/chats/{chat_id}/messages', functools.partial(get_messages, self))
        self.app.router.add_post('/api/chats/{chat_id}/messages', functools.partial(send_message_http, self))
        self.app.router.add_delete('/api/messages/{message_id}', functools.partial(delete_message, self))
        self.app.router.add_put('/api/messages/{message_id}', functools.partial(edit_message, self))
        self.app.router.add_get('/api/chats/{chat_id}/messages/search', functools.partial(search_messages_in_chat, self))

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
        self.app.router.add_post('/api/calls/initiate', functools.partial(initiate_call, self))
        self.app.router.add_post('/api/calls/{call_id}/signal', functools.partial(handle_call_signal, self))
        self.app.router.add_post('/api/calls/{call_id}/end', functools.partial(end_call, self))
        self.app.router.add_get('/api/calls/history', functools.partial(get_call_history, self))
        self.app.router.add_get('/api/calls/{call_id}/signals', functools.partial(get_call_signals, self))

        # Group Calls
        self.app.router.add_post('/api/calls/group/initiate', functools.partial(initiate_group_call, self))
        self.app.router.add_post('/api/calls/group/{call_id}/join', functools.partial(join_group_call, self))
        self.app.router.add_post('/api/calls/group/{call_id}/leave', functools.partial(leave_group_call, self))
        self.app.router.add_get('/api/calls/group/{call_id}/participants', functools.partial(get_group_call_participants, self))

        # WebSocket
        self.app.router.add_get('/api/ws', functools.partial(websocket_handler, self))

        # Settings routes
        self.app.router.add_get('/api/users/settings', functools.partial(get_user_settings, self))
        self.app.router.add_put('/api/users/settings', functools.partial(update_user_settings, self))
        self.app.router.add_put('/api/users/profile', functools.partial(update_user_profile, self))

        # Phone verification routes
        self.app.router.add_post('/api/auth/send-verification-code', functools.partial(send_verification_code, self))
        self.app.router.add_post('/api/auth/verify-phone', functools.partial(verify_phone_code, self))

        # Enhanced message actions
        self.app.router.add_delete('/api/messages/{message_id}/for-all', functools.partial(delete_message_for_all, self))
        self.app.router.add_delete('/api/messages/{message_id}/for-me', functools.partial(delete_message_for_me, self))
        self.app.router.add_post('/api/messages/forward', functools.partial(forward_message, self))

        # Debug routes
        self.app.router.add_get('/api/debug/check-user/{username}', functools.partial(debug_check_user, self))
        self.app.router.add_get('/api/debug/redis/{username}', functools.partial(debug_redis_state, self))
        self.app.router.add_get('/api/debug/my-chats', functools.partial(debug_user_chats, self))
        self.app.router.add_get('/api/users/{user_id}/blocked-status', functools.partial(check_blocked_status, self))

        # Updates in profile
        self.app.router.add_put('/api/chats/{chat_id}/info', functools.partial(update_group_chat, self))
        self.app.router.add_put('/api/users/email', functools.partial(update_email, self))
        self.app.router.add_put('/api/users/phone', functools.partial(update_phone, self))
        self.app.router.add_get('/api/users/search-all', functools.partial(search_all_users, self))
        self.app.router.add_get('/api/users/{user_id}', functools.partial(get_user_by_id, self))

        # Blocking routes
        self.app.router.add_post('/api/users/block', functools.partial(block_user, self))
        self.app.router.add_post('/api/users/unblock', functools.partial(unblock_user, self))
        self.app.router.add_get('/api/users/blocked', functools.partial(get_blocked_users, self))

        logger.info("=" * 70)
        logger.info("📋 Registered API Routes:")
        for route in self.app.router.routes():
            logger.info(f"  {route.method:6s} {route.resource.canonical}")
        logger.info("=" * 70)
