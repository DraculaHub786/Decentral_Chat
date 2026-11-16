"""Engine factory: maps registry engine names to adapter instances."""
from .archive import ArchiveEngine
from .base import BaseEngine, EngineFailed, EngineOutput, EngineUnavailable
from .ffmpeg import FFmpegEngine
from .img2pdf_engine import Img2PdfEngine
from .libreoffice import LibreOfficeEngine
from .pandoc import PandocEngine
from .pdf2docx import Pdf2DocxEngine
from .poppler import PopplerEngine
from .raster import RasterEngine

_REGISTRY = {
    "libreoffice": LibreOfficeEngine,
    "pandoc": PandocEngine,
    "poppler": PopplerEngine,
    "ffmpeg": FFmpegEngine,
    "raster": RasterEngine,
    "img2pdf": Img2PdfEngine,
    "pdf2docx": Pdf2DocxEngine,
    "archive": ArchiveEngine,
}

_instances = {}


def get_engine(name: str):
    """Return the singleton adapter for ``name`` or raise EngineUnavailable."""
    key = (name or "").lower()
    if key not in _REGISTRY:
        raise EngineUnavailable(f"Unknown engine '{name}'")
    if key not in _instances:
        _instances[key] = _REGISTRY[key]()
    return _instances[key]


def engine_available(name: str) -> bool:
    try:
        return get_engine(name).available
    except EngineUnavailable:
        return False


__all__ = [
    "BaseEngine", "EngineOutput", "EngineFailed", "EngineUnavailable",
    "get_engine", "engine_available",
]
