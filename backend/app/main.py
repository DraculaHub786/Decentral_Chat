"""Application entrypoint: create app, run server."""
import asyncio
import logging
import os
import sys
from pathlib import Path

# OAUTHLIB_INSECURE_TRANSPORT must NOT be enabled in production/staging.
# It globally disables HTTPS enforcement for OAuth token exchange, which is
# a local-dev convenience only. Set it here (dev default) so the app still
# boots for local testing, but never in deployed environments.
_env = os.getenv("ENVIRONMENT", "development").lower()
if _env in ("production", "prod", "staging"):
    os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)
else:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from app.core.config import UPLOAD_DIR
from app.server import DecentralChatServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def create_app():
    """Build and initialize the aiohttp application."""
    server = DecentralChatServer()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.initialize())
    return server.app


async def run_server():
    """Async entrypoint: initialize and serve the app (host/port from config)."""
    server = DecentralChatServer()
    await server.initialize()
    from app.core.config import PORT
    runner = AppRunner(server.app)
    await runner.setup()
    site = TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🚀 Server running on http://0.0.0.0:{PORT}")
    return runner


def main():
    """Initialize and run server (matches original main())."""
    # Create upload directories
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for category in ['images', 'videos', 'audio', 'documents',
                         'archives', 'voices', 'avatars', 'thumbnails']:
            subdir = UPLOAD_DIR / category
            subdir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Upload directory ready: {subdir.absolute()}")
            test_file = subdir / '.test'
            try:
                test_file.write_text('test')
                test_file.unlink()
            except Exception as perm_error:
                logger.error(f"❌ No write permission: {subdir} - {perm_error}")
    except Exception as e:
        logger.error(f"❌ Failed to create upload directories: {e}")
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    server = DecentralChatServer()
    try:
        loop.run_until_complete(server.initialize())
        from app.core.config import PORT
        web_run_app(server.app, port=PORT, host='0.0.0.0')
    except KeyboardInterrupt:
        logger.info("🛑 Server shutting down...")
    finally:
        loop.close()


# aiohttp run helpers (lazy import to avoid import cost at module load)
from aiohttp import web as _web
from aiohttp.web import AppRunner as _AppRunner, TCPSite as _TCPSite


def web_run_app(app, port, host='0.0.0.0'):
    """Start the app and block serving (mirrors aiohttp.web.run_app)."""
    runner = _AppRunner(app)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(runner.setup())
    site = _TCPSite(runner, host, port)
    loop.run_until_complete(site.start())
    logger.info(f"🚀 Server running on http://{host}:{port}")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("🛑 Server shutting down...")
    finally:
        loop.run_until_complete(runner.cleanup())
    return runner


if __name__ == '__main__':
    main()
