"""Route table construction + lookup API (half 2 of registry.py).

Kept in its own module so the registry stays readable: ENGINE declarations live
in ``registry.py``, the route matrix lives here, and ``registry`` re-exports the
lookup helpers below.
"""
import logging
import os
from typing import Dict, List, Optional, Sequence

from . import settings
from .fidelity import TIER_A, TIER_B, TIER_C
from .registry import (
    AUDIO_EXTS,
    ENGINES,
    IMAGE_RASTER_EXTS,
    OFFICE_TO_PDF,
    VIDEO_EXTS,
    Route,
)

logger = logging.getLogger(__name__)

PACKABLE_EXTS = (
    "docx", "doc", "odt", "rtf", "xlsx", "xls", "ods", "pptx", "ppt",
    "odp", "pdf", "txt", "md", "html", "csv",
    "png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif",
    "mp3", "wav", "ogg", "aac", "m4a", "flac",
    "mp4", "webm", "mkv", "mov", "avi",
)

IMAGE_TO_PDF = ("png", "jpg", "jpeg", "webp", "tiff", "tif", "bmp", "gif")


def _build_routes() -> List[Route]:
    routes: List[Route] = []
    seen = set()

    def add(src, dst, engines, tier=TIER_B, options=None, warnings=()):
        if src == dst:
            return
        route = Route(
            src=src,
            dst=dst,
            engines=tuple(engines),
            tier=tier,
            options=dict(options or {}),
            warnings_possible=tuple(warnings),
        )
        if route.key in seen:
            return
        seen.add(route.key)
        routes.append(route)

    page_opt = {"page_range": "string", "engine": "enum"}

    # Office -> PDF (Tier B, LibreOffice; fail loudly when missing)
    for ext in OFFICE_TO_PDF:
        add(ext, "pdf", ["libreoffice"], TIER_B, page_opt, ["font_substitution"])

    # Office -> office
    for ext in ("docx", "doc", "odt", "rtf"):
        for dst in ("docx", "odt", "rtf"):
            add(ext, dst, ["libreoffice"], TIER_B, {"engine": "enum"}, ["font_substitution"])
    for ext in ("xlsx", "xls", "ods"):
        for dst in ("xlsx", "ods", "csv"):
            add(ext, dst, ["libreoffice"], TIER_B, {"engine": "enum"})
    for ext in ("pptx", "ppt", "odp"):
        for dst in ("pptx", "odp", "pdf"):
            add(ext, dst, ["libreoffice"], TIER_B, {"engine": "enum"}, ["font_substitution"])

    # Document -> light markup (Pandoc primary, LibreOffice fallback)
    for ext in ("docx", "doc", "odt", "rtf"):
        for dst in ("html", "md", "txt"):
            add(ext, dst, ["pandoc", "libreoffice"], TIER_B, {"engine": "enum"})

    # Markup -> document
    for ext in ("md", "html", "htm"):
        for dst in ("docx", "odt"):
            add(ext, dst, ["pandoc"], TIER_B, {"engine": "enum"})

    # Markup/text -> PDF
    for ext in ("md", "html", "htm", "txt"):
        add(ext, "pdf", ["libreoffice", "pandoc"], TIER_B, page_opt, ["font_substitution"])

    # PDF -> editable (Tier C: reconstructive, user is warned)
    add("pdf", "docx", ["pdf2docx", "libreoffice"], TIER_C,
        {"page_range": "string"}, ["reconstructed_layout"])
    for dst in ("txt", "html"):
        add("pdf", dst, ["poppler"], TIER_C, {"page_range": "string"}, ["reconstructed_layout"])
    for dst in ("png", "jpg"):
        add("pdf", dst, ["poppler"], TIER_A, page_opt)

    # Images -> PDF (lossless embedding: JPEG bytes are never re-encoded)
    for ext in IMAGE_TO_PDF:
        add(ext, "pdf", ["img2pdf", "raster"], TIER_A)

    # Raster -> raster
    for src in IMAGE_RASTER_EXTS:
        for dst in IMAGE_RASTER_EXTS:
            if src == dst:
                continue
            tier = TIER_A if dst in ("png", "tiff", "bmp") else TIER_B
            add(src, dst, ["raster"], tier, {"quality": "int"},
                ["alpha_flattened", "frames_dropped"])

    # Audio
    for src in AUDIO_EXTS:
        for dst in AUDIO_EXTS:
            if src == dst:
                continue
            lossless_pair = src in ("wav", "flac") and dst in ("wav", "flac")
            add(src, dst, ["ffmpeg"], TIER_A if lossless_pair else TIER_B,
                {"bitrate": "string", "engine": "enum"}, ["metadata_stripped"])

    # Video
    for src in VIDEO_EXTS:
        for dst in VIDEO_EXTS:
            if src == dst:
                continue
            add(src, dst, ["ffmpeg"], TIER_B, {"quality": "string"},
                ["resolution_changed", "recompressed"])
    for src in VIDEO_EXTS:
        for dst in ("mp3", "wav", "aac", "ogg", "flac", "m4a"):
            add(src, dst, ["ffmpeg"], TIER_B, {"bitrate": "string"})
        add(src, "gif", ["ffmpeg"], TIER_B, {"fps": "int", "width": "int"})

    # Spreadsheet data
    add("csv", "xlsx", ["libreoffice"], TIER_B, {"delimiter": "string", "charset": "string"})
    add("xlsx", "csv", ["libreoffice"], TIER_B, {"delimiter": "string", "charset": "string"})

    # Archives (plan Phase 6). D-02 removed the advertised-but-missing
    # zip/tar/gz/7z options; they return here, but only zip and tar, and only
    # because the engine now actually exists and validates hostile input.
    for ext in PACKABLE_EXTS:
        add(ext, "zip", ["archive"], TIER_A, {}, ["archive_not_encrypted"])
        add(ext, "tar", ["archive"], TIER_A, {}, ["archive_not_encrypted"])
    add("zip", "tar", ["archive"], TIER_A, {}, ["archive_not_encrypted"])
    add("tar", "zip", ["archive"], TIER_A, {}, ["archive_not_encrypted"])

    return routes


_ROUTES: List[Route] = _build_routes()
_BY_KEY: Dict[str, Route] = {route.key: route for route in _ROUTES}


def normalize_ext(ext: str) -> str:
    """Lowercase, strip dots/whitespace. 'JPEG' and '.jpg' both normalise."""
    return (ext or "").strip().lower().lstrip(".")


def lookup(source_ext: str, target_ext: str) -> Optional[Route]:
    """Return the route for this pair, or ``None`` if unsupported/unavailable."""
    route = _BY_KEY.get(f"{normalize_ext(source_ext)}->{normalize_ext(target_ext)}")
    if route is None:
        return None
    if not route.available:
        logger.warning("Route %s has no installed engine (chain=%s)", route.key, route.engines)
        return None
    return route


def lookup_unavailable(source_ext: str, target_ext: str) -> Optional[Route]:
    """Return the route even when its engines are missing (for good errors)."""
    return _BY_KEY.get(f"{normalize_ext(source_ext)}->{normalize_ext(target_ext)}")


def supported_targets(source_ext: str) -> List[str]:
    src = normalize_ext(source_ext)
    return sorted({r.dst for r in _ROUTES if r.src == src and r.available})


def supported_sources() -> List[str]:
    return sorted({r.src for r in _ROUTES if r.available})


def all_routes() -> Sequence[Route]:
    return tuple(_ROUTES)


def capabilities() -> dict:
    """Machine-readable table for ``GET /api/convert/capabilities``."""
    return {
        "version": settings.CAPABILITIES_VERSION,
        "engines": {
            name: {
                "available": spec.available,
                "binary": spec.binary,
                "reads": sorted(spec.reads),
                "writes": sorted(spec.writes),
            }
            for name, spec in ENGINES.items()
        },
        "routes": [route.as_capability() for route in _ROUTES],
    }


def engine_concurrency_cap(engine_name: str) -> int:
    """Per-engine parallelism cap (defaults to 1 when not configured)."""
    return settings.CONVERTER_ENGINE_CAPS.get(engine_name, 1)


def ffmpeg_extra_args() -> List[str]:
    """Env-driven extra FFmpeg arguments, e.g. hardware acceleration."""
    raw = os.getenv("CONVERTER_FFMPEG_EXTRA_ARGS", "")
    return [token for token in raw.split() if token]
