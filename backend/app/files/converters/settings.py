"""Converter v2 settings — every value is environment-driven (plan §3.6)."""
import os
import shutil
from pathlib import Path

_TRUE = {"1", "true", "yes", "on"}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _engine_caps(raw: str) -> dict:
    """Parse 'libreoffice=2,ffmpeg=2' into {'libreoffice': 2, 'ffmpeg': 2}."""
    caps: dict = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        try:
            caps[name.strip()] = max(1, int(value.strip()))
        except ValueError:
            continue
    return caps


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent

# Feature flag doubles as the kill switch. Defaults to enabled because the v2
# path is now the only path that reports real engines, real progress and real
# fidelity tiers; set CONVERTER_V2=off to reject new jobs immediately.
CONVERTER_V2_ENABLED = _flag("CONVERTER_V2", True)

CONVERTER_WORK_DIR = Path(os.getenv("CONVERTER_WORK_DIR", str(_BACKEND_DIR / "work")))
CONVERTER_JOB_TTL_SECONDS = _int("CONVERTER_JOB_TTL_SECONDS", 900)
CONVERTER_RESULT_TOKEN_TTL_SECONDS = _int("CONVERTER_RESULT_TOKEN_TTL_SECONDS", 600)
CONVERTER_MAX_CONCURRENT = _int("CONVERTER_MAX_CONCURRENT", min(os.cpu_count() or 1, 4))
CONVERTER_ENGINE_CAPS = _engine_caps(os.getenv("CONVERTER_ENGINE_CAPS", "libreoffice=2"))
CONVERTER_USER_MAX_RUNNING = _int("CONVERTER_USER_MAX_RUNNING", 2)
CONVERTER_USER_HOURLY_CAP = _int("CONVERTER_USER_HOURLY_CAP", 30)
CONVERTER_JANITOR_INTERVAL_SECONDS = _int("CONVERTER_JANITOR_INTERVAL_SECONDS", 300)
CONVERTER_QUEUE_BACKEND = os.getenv("CONVERTER_QUEUE_BACKEND", "redis").strip().lower()
CONVERTER_FFMPEG_EXTRA_ARGS = os.getenv("CONVERTER_FFMPEG_EXTRA_ARGS", "").strip()

# Per-family limits (plan §3.6 CONVERTER_LIMITS_*).
CONVERTER_LIMITS_MAX_BYTES = _int("CONVERTER_LIMITS_MAX_BYTES", 50 * 1024 * 1024)
CONVERTER_LIMITS_MAX_PAGES = _int("CONVERTER_LIMITS_MAX_PAGES", 300)
CONVERTER_LIMITS_MAX_DURATION_SECONDS = _int("CONVERTER_LIMITS_MAX_DURATION_SECONDS", 3600)
CONVERTER_LIMITS_MAX_MEGAPIXELS = _int("CONVERTER_LIMITS_MAX_MEGAPIXELS", 80)
CONVERTER_TIMEOUT_SECONDS = _int("CONVERTER_TIMEOUT_SECONDS", 300)

CAPABILITIES_VERSION = "2026-11-15"


def ensure_work_dir() -> Path:
    CONVERTER_WORK_DIR.mkdir(parents=True, exist_ok=True)
    return CONVERTER_WORK_DIR


_WINDOWS_ENGINE_DIRS = [
    "C:/Program Files/Pandoc",
    "C:/Program Files (x86)/Pandoc",
    "C:/Program Files/LibreOffice/program",
    "C:/Program Files (x86)/LibreOffice/program",
    "C:/Program Files/poppler/Library/bin",
    "C:/Program Files/poppler/bin",
]


def _search_dirs() -> list:
    """Extra places to look when an installer never touched PATH.

    Windows installers - including the winget packages for Pandoc, LibreOffice
    and Poppler - routinely install outside PATH. A binary that works in an
    interactive shell would otherwise be invisible to the server, silently
    disabling every conversion route that depends on it.
    """
    dirs = list(_WINDOWS_ENGINE_DIRS)
    local = os.getenv("LOCALAPPDATA")
    if local:
        dirs.extend([
            os.path.join(local, "Pandoc"),
            os.path.join(local, "Programs", "LibreOffice", "program"),
            os.path.join(local, "Microsoft", "WinGet", "Links"),
        ])
    override = os.getenv("CONVERTER_ENGINE_PATHS", "")
    dirs.extend(part.strip() for part in override.split(os.pathsep) if part.strip())
    return dirs


def which(*names: str):
    """Return the first resolvable executable path among ``names``."""
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    for name in names:
        candidates = [name] if "." in name else [name, name + ".exe"]
        for directory in _search_dirs():
            for candidate in candidates:
                path = Path(directory) / candidate
                if path.is_file():
                    return str(path)
    return None
