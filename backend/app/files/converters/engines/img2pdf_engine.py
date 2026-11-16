"""Image -> PDF engine using img2pdf (lossless embedding, D-13)."""
import logging

from ..verify import verify_output
from .base import BaseEngine, EngineFailed, EngineOutput

logger = logging.getLogger(__name__)

try:
    import img2pdf as _img2pdf
    HAS_IMG2PDF = True
except ImportError:
    _img2pdf = None
    HAS_IMG2PDF = False

LOSSLESS_SOURCES = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}


class Img2PdfEngine(BaseEngine):
    """Emits one PDF page per image without re-compressing the pixels."""

    name = "img2pdf"
    binaries = ()

    def require(self) -> str:
        if not HAS_IMG2PDF:
            raise EngineFailed("img2pdf is not installed (pip install img2pdf)")
        return "img2pdf"

    async def run(self, source, target_ext, dest, options):
        self.require()
        if target_ext.lower().lstrip(".") != "pdf":
            raise EngineFailed("img2pdf only writes PDF")
        try:
            with open(dest, "wb") as handle:
                handle.write(_img2pdf.convert(str(source)))
        except Exception as err:
            raise EngineFailed(f"img2pdf failed: {err}") from err
        if not dest.exists():
            raise EngineFailed("img2pdf wrote no output")
        metrics = verify_output(dest, "pdf")
        metrics["lossless_embed"] = source.suffix.lower() in LOSSLESS_SOURCES
        return EngineOutput(files=[dest], engine=self.name, metrics=metrics)
