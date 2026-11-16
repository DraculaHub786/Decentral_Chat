"""PDF to DOCX engine (Tier C, reconstructive)."""
import asyncio
import logging

from ..verify import verify_output
from .base import BaseEngine, EngineFailed, EngineOutput

logger = logging.getLogger(__name__)

try:
    from pdf2docx import Converter as _Converter
    HAS_PDF2DOCX = True
except ImportError:
    _Converter = None
    HAS_PDF2DOCX = False


class Pdf2DocxEngine(BaseEngine):
    """Rebuilds an editable document from a PDF. Structure is inferred."""

    name = "pdf2docx"
    binaries = ()

    def require(self) -> str:
        if not HAS_PDF2DOCX:
            raise EngineFailed("pdf2docx is not installed (pip install pdf2docx)")
        return "pdf2docx"

    async def run(self, source, target_ext, dest, options):
        self.require()
        if target_ext.lower().lstrip(".") != "docx":
            raise EngineFailed("pdf2docx only writes DOCX")

        page_range = str(options.get("page_range") or "").strip()

        def _convert():
            converter = _Converter(str(source))
            try:
                if page_range and "-" in page_range:
                    first, _, last = page_range.partition("-")
                    converter.convert(str(dest), start=int(first), end=int(last))
                elif page_range.isdigit():
                    page = int(page_range)
                    converter.convert(str(dest), start=page, end=page)
                else:
                    converter.convert(str(dest))
            finally:
                converter.close()

        try:
            await asyncio.to_thread(_convert)
        except Exception as err:
            raise EngineFailed(f"pdf2docx failed: {err}") from err

        if not dest.exists():
            raise EngineFailed("pdf2docx wrote no output")

        output = EngineOutput(files=[dest], engine=self.name,
                              metrics=verify_output(dest, "docx"))
        output.warnings.append(
            "This conversion rebuilds the layout from a PDF and may differ from the original."
        )
        return output
