#!/usr/bin/env python3
"""Backend server entrypoint — compatibility shim.

The application logic has been refactored into the modular ``app`` package
(see ``app/server.py`` and ``app/main.py``). This module re-exports
:class:`DecentralChatServer` and the ``main`` entrypoint so that legacy
invocations (``python server.py``) and imports
(``from server import DecentralChatServer``) keep working unchanged.

For new code, prefer::

    from app.server import DecentralChatServer
    # or simply:  python run.py   /   python -m app.main
"""
import sys
from pathlib import Path

# Ensure the backend directory is importable (so ``from app...`` resolves).
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load .env before importing config (mirrors the old monolith behaviour).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from app.server import DecentralChatServer  # noqa: E402,F401
from app.main import main, create_app, run_server  # noqa: E402,F401

__all__ = ["DecentralChatServer", "main", "create_app", "run_server"]


if __name__ == "__main__":
    sys.exit(main())
