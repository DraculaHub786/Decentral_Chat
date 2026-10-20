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

from aiohttp.web import AppRunner, TCPSite
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
    """Async entrypoint: initialize and serve the app (host/port from config).

    Binds on BOTH IPv4 (0.0.0.0) and IPv6 (::1) so that clients resolving
    ``localhost`` to ``::1`` (the default on Windows/macOS) still reach the
    server. Binding only to 0.0.0.0 made the browser fail with a
    "network error" because it connected to the unreachable IPv6 address.
    """
    server = DecentralChatServer()
    await server.initialize()
    from app.core.config import PORT
    runner = AppRunner(server.app)
    await runner.setup()
    await _bind_all(runner, PORT)
    return runner


async def _bind_all(runner, port):
    """Start a TCPSite on every viable listen address; ignore ones that fail.

    Tries IPv4 (0.0.0.0) and IPv6 (::1). If the HOST env var is set, only that
    single address is used. Raises if no address could be bound.
    """
    override = os.getenv('HOST', '').strip()
    hosts = [override] if override else ['0.0.0.0', '::1']
    bound = []
    for host in hosts:
        try:
            site = TCPSite(runner, host, port)
            await site.start()
            bound.append(host)
            logger.info(f"🚀 Listening on http://{host}:{port}")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"⚠️ Could not bind to {host}:{port} ({e})")
    if not bound:
        raise RuntimeError("Failed to bind any listen address")


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
        _run_app_dual_stack(server.app, PORT)
    except KeyboardInterrupt:
        logger.info("🛑 Server shutting down...")
    finally:
        loop.close()


# aiohttp run helpers (lazy import to avoid import cost at module load)
from aiohttp import web as _web
from aiohttp.web import AppRunner as _AppRunner, TCPSite as _TCPSite


def _run_app_dual_stack(app, port, host=None):
    """Start the app and block serving, listening on both IPv4 and IPv6.

    ``host`` (single address) may be passed via the HOST env var to force a
    specific bind (e.g. '0.0.0.0' or '::1'). Otherwise both '0.0.0.0' and
    '::1' are bound so that ``localhost`` (which resolves to ::1 on Windows/
    macOS) and ``127.0.0.1`` both reach the server.
    """
    if host is None:
        host = os.getenv('HOST', '').strip()

    runner = _AppRunner(app)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(runner.setup())

    hosts = [host] if host else ['0.0.0.0', '::1']
    bound = []
    for h in hosts:
        try:
            site = _TCPSite(runner, h, port)
            loop.run_until_complete(site.start())
            bound.append(h)
            logger.info(f"🚀 Listening on http://{h}:{port}")
        except Exception as e:
            logger.warning(f"⚠️ Could not bind to {h}:{port} ({e})")

    if not bound:
        raise RuntimeError("Failed to bind any listen address")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("🛑 Server shutting down...")
    finally:
        loop.run_until_complete(runner.cleanup())
    return runner


if __name__ == '__main__':
    main()
