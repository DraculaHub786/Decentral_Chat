"""Verify the claims in PENDING_TASKS.md against the actual repo state."""
import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def which_all():
    print("=== C2: system binaries ===")
    for name in ("soffice", "libreoffice", "pandoc", "pdftotext", "pdftoppm", "ffmpeg"):
        found = shutil.which(name)
        print(f"  {name:12} PATH={found or 'NOT ON PATH'}")
    try:
        from app.files.converters import settings
        print("\n  registry detection:")
        for name in ("libreoffice", "pandoc", "poppler", "ffmpeg",
                     "raster", "img2pdf", "pdf2docx", "archive"):
            try:
                path = settings.which(name)
                print(f"    {name:12} -> {path or 'NOT FOUND'}")
            except Exception as exc:
                print(f"    {name:12} -> error: {exc}")
    except Exception as exc:
        print("  settings import failed:", exc)


def check_frontend_bugs():
    print("\n=== H2/H3: frontend bug markers ===")
    js = io.open(ROOT / "frontend" / "app.js", encoding="utf-8").read()
    html = io.open(ROOT / "frontend" / "index.html", encoding="utf-8").read()

    # H2: delete-for-me should also clear the chat list preview
    has_delete_for_me = "deleteForMe" in js or "for-me" in js
    print(f"  delete-for-me handler present: {has_delete_for_me}")
    for m in re.finditer(r"function\s+(deleteMessage\w*|deleteForMe\w*)\s*\(", js):
        print("    handler:", m.group(1))

    # H3: does the chat list render an avatar image?
    render_fn = re.search(r"function\s+renderChatList.*?\n\s{8}\}", js, re.S)
    seg = render_fn.group(0) if render_fn else ""
    print(f"  renderChatList found: {bool(render_fn)}")
    print(f"  chat list uses avatar_url: {'avatar_url' in seg}")
    print(f"  chat list uses <img>: {'<img' in seg or 'innerHTML' in seg}")

    # Check what the chat list item actually builds
    for key in ("chat-avatar", "contact-avatar", "chatAvatar"):
        print(f"  '{key}' in app.js: {key in js}")
        print(f"  '{key}' in index.html: {key in html}")


def check_e2e():
    print("\n=== C1: E2E encryption in browser ===")
    js = io.open(ROOT / "frontend" / "app.js", encoding="utf-8").read()

    checks = [
        ("CryptoEngine.init defined", "async init()" in js),
        ("setupChatKey defined", "async setupChatKey(" in js),
        ("setupGroupChatKey defined", "async setupGroupChatKey(" in js),
        ("encryptBuffer defined", "async encryptBuffer(" in js),
        ("encryptText defined", "async encryptText(" in js),
        ("uploadPublicKey defined", "async uploadPublicKey(" in js),
        ("hasKey guard used", "CryptoEngine.hasKey(" in js),
        ("encrypt before upload", "CryptoEngine.encryptBuffer(" in js),
    ]
    for label, ok in checks:
        print(f"  {'OK  ' if ok else 'MISS'} {label}")

    # Is init() ever called?
    print("\n  init call sites:")
    for m in re.finditer(r"CryptoEngine\.init\s*\(", js):
        line = js[:m.start()].count("\n") + 1
        print(f"    line {line}")

    # Is setupChatKey called when a chat opens?
    print("\n  setupChatKey call sites:")
    for m in re.finditer(r"setupChatKey\s*\(", js):
        line = js[:m.start()].count("\n") + 1
        print(f"    line {line}: {js[m.start()-40:m.start()+30].strip()[:70]}")

    # Backend: does the public key endpoint exist and return the key?
    try:
        from app.users import handlers as uh
        print("\n  backend public_key handler:", hasattr(uh, "get_user_public_key"))
    except Exception as exc:
        print("  backend import failed:", exc)


def check_converter():
    print("\n=== H4: converter progress granularity ===")
    jobs = io.open(ROOT / "backend/app/files/converters/jobs.py", encoding="utf-8").read()
    print(f"  jobs.py sets percent: {'percent' in jobs}")
    for m in re.finditer(r"percent\W{0,3}(\d+|None)", jobs):
        line = jobs[:m.start()].count("\n") + 1
        print(f"    line {line}: {jobs[m.start()-30:m.start()+20].strip()[:60]}")


def check_health():
    print("\n=== L3: converter health endpoint ===")
    routes = io.open(ROOT / "backend/app/files/converters/routes.py", encoding="utf-8").read()
    print(f"  converter health route exists: {'health' in routes}")


which_all()
check_e2e()
check_frontend_bugs()
check_converter()
check_health()
