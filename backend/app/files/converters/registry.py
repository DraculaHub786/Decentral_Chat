"""Engine registry: the single source of truth for every supported route.

The registry replaces the hand-maintained extension lists that caused D-01
(the HTTP handler re-declared shorter lists than the advertised map, so the UI
offered conversions that returned HTTP 500) and D-02 (archives were advertised
but never implemented).

Both the API and the UI read their capability table from here.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import settings
from .fidelity import TIER_A, TIER_B, TIER_C

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineSpec:
    """What one engine can read, write and how it is invoked."""

    name: str
    reads: frozenset
    writes: frozenset
    binaries: Sequence[str] = ()
    modules: Sequence[str] = ()
    timeout: int = settings.CONVERTER_TIMEOUT_SECONDS

    def can_read(self, ext: str) -> bool:
        return ext in self.reads

    def can_write(self, ext: str) -> bool:
        return ext in self.writes

    @property
    def binary(self) -> Optional[str]:
        return settings.which(*self.binaries) if self.binaries else None

    def _module_present(self, module: str) -> bool:
        import importlib.util
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    @property
    def available(self) -> bool:
        """Feature-detected, never assumed. A missing engine disables its routes.

        Binaries are probed on PATH (plus the well-known install dirs). Engines
        implemented as Python libraries probe the import instead - an earlier
        version returned True for any engine without a binary, so `img2pdf`
        and AVIF support were advertised while the package was not installed
        and every one of those routes failed at request time.
        """
        if self.binaries:
            return self.binary is not None
        if self.modules:
            return all(self._module_present(m) for m in self.modules)
        return True


@dataclass(frozen=True)
class Route:
    src: str
    dst: str
    engines: Sequence[str]
    tier: str = TIER_B
    options: Dict[str, str] = field(default_factory=dict)
    warnings_possible: Sequence[str] = ()

    @property
    def key(self) -> str:
        return f"{self.src}->{self.dst}"

    def available_engine(self) -> Optional[str]:
        """First engine in the chain that is actually installed."""
        for name in self.engines:
            spec = ENGINES.get(name)
            if spec and spec.available:
                return name
        return None

    @property
    def available(self) -> bool:
        return self.available_engine() is not None

    def as_capability(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "tier": self.tier,
            "engines": list(self.engines),
            "available": self.available,
            "active_engine": self.available_engine(),
            "options": dict(self.options),
            "limits": {
                "max_bytes": settings.CONVERTER_LIMITS_MAX_BYTES,
                "max_pages": settings.CONVERTER_LIMITS_MAX_PAGES,
                "max_duration_seconds": settings.CONVERTER_LIMITS_MAX_DURATION_SECONDS,
                "max_megapixels": settings.CONVERTER_LIMITS_MAX_MEGAPIXELS,
            },
            "warnings_possible": list(self.warnings_possible),
        }


OFFICE_EXTS = frozenset(
    {"docx", "doc", "odt", "rtf", "pptx", "ppt", "odp", "xlsx", "xls", "ods"}
)
MARKUP_EXTS = frozenset(
    {"docx", "doc", "odt", "rtf", "html", "htm", "md", "txt", "epub"}
)
IMAGE_RASTER_EXTS = (
    "png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif", "avif", "ico",
)
AUDIO_EXTS = ("mp3", "wav", "ogg", "aac", "m4a", "flac", "wma", "opus")
VIDEO_EXTS = ("mp4", "webm", "mkv", "mov", "avi", "flv", "wmv")
ARCHIVE_EXTS = frozenset({"zip", "tar"})
OFFICE_TO_PDF = ("docx", "doc", "odt", "rtf", "pptx", "ppt", "odp", "xlsx", "xls", "ods")

ENGINES: Dict[str, EngineSpec] = {
    "libreoffice": EngineSpec(
        name="libreoffice",
        reads=OFFICE_EXTS | MARKUP_EXTS | {"csv"},
        writes=frozenset(
            {"pdf", "docx", "odt", "rtf", "pptx", "xlsx", "ods", "csv", "txt", "html"}
        ),
        binaries=("soffice", "libreoffice"),
        timeout=max(settings.CONVERTER_TIMEOUT_SECONDS, 240),
    ),
    "pandoc": EngineSpec(
        name="pandoc",
        reads=MARKUP_EXTS,
        writes=frozenset({"html", "md", "txt", "docx", "odt", "rtf", "epub"}),
        binaries=("pandoc",),
    ),
    "poppler": EngineSpec(
        name="poppler",
        reads=frozenset({"pdf"}),
        writes=frozenset({"txt", "html", "png", "jpg"}),
        binaries=("pdftotext",),
    ),
    "ffmpeg": EngineSpec(
        name="ffmpeg",
        reads=frozenset(
            set(AUDIO_EXTS) | set(VIDEO_EXTS)
        ),
        writes=frozenset(
            set(AUDIO_EXTS) | set(VIDEO_EXTS) | {"gif"}
        ),
        binaries=("ffmpeg",),
    ),
    "raster": EngineSpec(
        name="raster",
        reads=frozenset(IMAGE_RASTER_EXTS),
        writes=frozenset(IMAGE_RASTER_EXTS),
        binaries=(),  # Pillow is a Python dependency, always importable
        modules=("PIL",),
    ),
    "img2pdf": EngineSpec(
        name="img2pdf",
        reads=frozenset({"png", "jpg", "jpeg", "webp", "tiff", "tif", "bmp", "gif"}),
        writes=frozenset({"pdf"}),
        binaries=(),
        modules=("img2pdf",),
    ),
    "archive": EngineSpec(
        name="archive",
        reads=frozenset({"zip", "tar"}) | frozenset(OFFICE_EXTS) | frozenset(IMAGE_RASTER_EXTS)
              | frozenset({"pdf", "txt", "md", "html", "csv", "mp3", "mp4"}),
        writes=frozenset({"zip", "tar"}),
        binaries=(),  # stdlib only
        modules=("zipfile", "tarfile"),
    ),
    "pdf2docx": EngineSpec(
        name="pdf2docx",
        reads=frozenset({"pdf"}),
        writes=frozenset({"docx"}),
        binaries=(),
        modules=("pdf2docx",),
    ),
}
