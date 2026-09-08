"""Environment configuration, constants, and crypto setup."""
import os
import logging
import shutil
import subprocess
from cryptography.fernet import Fernet
from pathlib import Path

logger = logging.getLogger(__name__)

# ---- environment-driven config ----
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-change-me')
FIREBASE_CRED = os.getenv('FIREBASE_CRED', 'firebase-config.json')
PORT = int(os.getenv('PORT', '8080'))
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

# Base dirs
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
UPLOAD_DIR = BASE_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'],
    'video': ['.mp4', '.webm', '.mov', '.avi', '.mkv'],
    'audio': ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac'],
    'document': ['.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt',
                 '.ppt', '.pptx', '.xls', '.xlsx', '.csv', '.md'],
}

# ---- crypto ----
def _ensure_secret_key():
    return SECRET_KEY

def _ensure_fernet_key():
    return os.getenv('FERNET_KEY', SECRET_KEY)

ENCRYPTION_KEY = _ensure_fernet_key()
try:
    _fk = ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY
    cipher_suite = Fernet(_fk)
except Exception:
    cipher_suite = Fernet.generate_key()

# Expose cipher_suite on the shared globals namespace.
from app.globals import g as _g
_g.cipher_suite = cipher_suite

# ---- conversion capability flags ----
try:
    from pdf2docx import Converter as PDFConverter
    HAS_PDF2DOCX = True
except ImportError:
    HAS_PDF2DOCX = False
    PDFConverter = None

HAS_LIBREOFFICE = shutil.which('soffice') or shutil.which('libreoffice')
HAS_UNOCONV = shutil.which('unoconv')

FFMPEG_PATH = None
_ffmpeg_checked = shutil.which('ffmpeg')
if _ffmpeg_checked:
    FFMPEG_PATH = _ffmpeg_checked
else:
    _common_ffmpeg_paths = [
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\ProgramData\chocolatey\bin\ffmpeg.exe',
        os.path.expanduser(r'~\scoop\apps\ffmpeg\current\bin\ffmpeg.exe'),
        os.path.expanduser(r'~\AppData\Local\Microsoft\WinGet\Packages\ffmpeg\ffmpeg.exe'),
    ]
    _search_dirs = [
        r'C:\Program Files',
        r'C:\Program Files (x86)',
        os.path.expanduser(r'~\Documents'),
        os.path.expanduser(r'~\Downloads'),
    ]
    for _d in _search_dirs:
        if os.path.isdir(_d):
            try:
                for _root, _dirs, _files in os.walk(_d):
                    if 'ffmpeg.exe' in _files:
                        FFMPEG_PATH = os.path.join(_root, 'ffmpeg.exe')
                        break
                    if _root.count(os.sep) > 6:
                        _dirs[:] = []
            except Exception:
                pass
    if not FFMPEG_PATH:
        try:
            _r = subprocess.run(['where.exe', 'ffmpeg'], capture_output=True, text=True, timeout=5)
            if _r.returncode == 0:
                _line = _r.stdout.strip().split('\n')[0].strip()
                if _line:
                    FFMPEG_PATH = _line
        except Exception:
            pass

if FFMPEG_PATH:
    _ffmpeg_dir = str(Path(FFMPEG_PATH).parent)
    if _ffmpeg_dir not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')

# Late-bound optional imports used by converters
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger.warning("⚠️ beautifulsoup4 not installed. HTML conversions will be basic.")

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False
    logger.warning("⚠️ markdown not installed. Markdown conversions will be basic.")


def print_conversion_capabilities():
    """Print available conversion tools and capabilities"""
    logger.info("=" * 70)
    logger.info("🔄 FILE CONVERSION CAPABILITIES")
    logger.info("=" * 70)
    if HAS_PDF2DOCX:
        logger.info("✅ pdf2docx: INSTALLED - High-quality PDF→DOCX with images")
    else:
        logger.warning("⚠️ pdf2docx: NOT INSTALLED - PDF conversions will be text-only")
        logger.info("   Install with: pip install pdf2docx")
    if HAS_LIBREOFFICE:
        logger.info(f"✅ LibreOffice: FOUND at {shutil.which('soffice') or shutil.which('libreoffice')}")
        logger.info("   Supports: PDF↔DOCX, PPT→PDF, with images & formatting")
    else:
        logger.warning("⚠️ LibreOffice: NOT FOUND - Advanced document conversions unavailable")
        logger.info("   Install: https://www.libreoffice.org/download/")
    if HAS_BS4:
        logger.info("✅ BeautifulSoup4: INSTALLED - Enhanced HTML parsing")
    else:
        logger.warning("⚠️ beautifulsoup4: NOT INSTALLED - Basic HTML parsing only")
    if HAS_MARKDOWN:
        logger.info("✅ Markdown: INSTALLED - Markdown conversions available")
    if shutil.which('ffmpeg') or FFMPEG_PATH:
        _ffmpeg_loc = FFMPEG_PATH or shutil.which('ffmpeg')
        logger.info(f"✅ FFmpeg: FOUND at {_ffmpeg_loc} - Audio/video conversions available")
    else:
        logger.warning("⚠️ FFmpeg: NOT FOUND - Media conversions unavailable")
    logger.info("=" * 70)
    if not HAS_PDF2DOCX or not HAS_LIBREOFFICE:
        logger.warning("⚠️ RECOMMENDATION: Install LibreOffice and pdf2docx for best conversion quality")
        logger.info("   With these tools, conversions will preserve:")
        logger.info("   • Images and graphics")
        logger.info("   • Text formatting (fonts, colors, sizes)")
        logger.info("   • Page layouts and structure")
        logger.info("   • Tables and charts")
    else:
        logger.info("✅ All conversion tools installed - Full capability available!")
    logger.info("=" * 70)
