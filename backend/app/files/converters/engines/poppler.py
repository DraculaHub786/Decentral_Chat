"""Poppler engine: pdftotext / pdftohtml / pdftoppm (replaces PyPDF2-only paths)."""
import logging
from pathlib import Path

from .. import runner, settings
from ..verify import verify_output
from .base import BaseEngine, EngineFailed, EngineOutput, unique_path

logger = logging.getLogger(__name__)

DEFAULT_DPI = 200


def _page_args(options) -> list:
    """Turn options['page_range'] ('1-5' or '3') into Poppler flags."""
    page_range = str(options.get("page_range") or "").strip()
    if not page_range:
        return []
    if "-" in page_range:
        first, _, last = page_range.partition("-")
        if first.strip().isdigit() and last.strip().isdigit():
            return ["-f", first.strip(), "-l", last.strip()]
    elif page_range.isdigit():
        return ["-f", page_range, "-l", page_range]
    raise EngineFailed(f"Invalid page_range '{page_range}' (use '3' or '1-5')")


class PopplerEngine(BaseEngine):
    """PDF -> TXT/HTML (Tier C) and PDF -> PNG/JPG (Tier A raster)."""

    name = "poppler"
    binaries = ("pdftotext",)

    async def run(self, source: Path, target_ext: str, dest: Path, options):
        target_ext = target_ext.lower().lstrip(".")
        pages = _page_args(options)
        work_dir = dest.parent

        if target_ext == "txt":
            command = [self.require(), "-layout", "-enc", "UTF-8", *pages,
                       str(source), str(dest)]
            await runner.run_checked(command, timeout=self.timeout(), cwd=work_dir)
            if not dest.exists():
                raise EngineFailed("pdftotext wrote no output")
            return EngineOutput(files=[dest], engine=self.name,
                                metrics=verify_output(dest, "txt"))

        if target_ext in ("html", "htm"):
            command = [self._named("pdftohtml"), "-s", "-noframes", "-enc", "UTF-8",
                       *pages, str(source), str(dest)]
            await runner.run_checked(command, timeout=self.timeout(), cwd=work_dir)
            if not dest.exists():
                raise EngineFailed("pdftohtml wrote no output")
            return EngineOutput(files=[dest], engine=self.name,
                                metrics=verify_output(dest, "html"))

        if target_ext in ("png", "jpg", "jpeg"):
            fmt = "-png" if target_ext == "png" else "-jpeg"
            dpi = int(options.get("dpi") or DEFAULT_DPI)
            prefix = unique_path(work_dir, f"{dest.stem}-page", target_ext).with_suffix("")
            command = [self._named("pdftoppm"), fmt, "-r", str(dpi), *pages,
                       str(source), str(prefix)]
            await runner.run_checked(command, timeout=self.timeout(), cwd=work_dir)

            produced = sorted(
                p for p in work_dir.iterdir()
                if p.is_file() and p.name.startswith(prefix.name)
                and p.suffix.lower().lstrip(".") in ("png", "jpg", "jpeg")
            )
            if not produced:
                raise EngineFailed("pdftoppm rendered no pages")
            return EngineOutput(files=produced, engine=self.name,
                                metrics={"pages": len(produced)})

        raise EngineFailed(f"Poppler cannot write .{target_ext}")

    def _named(self, binary_name: str) -> str:
        found = settings.which(binary_name)
        if not found:
            raise EngineFailed(f"{binary_name} is not installed")
        return found
