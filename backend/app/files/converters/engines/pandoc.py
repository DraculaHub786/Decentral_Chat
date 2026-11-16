"""Pandoc engine: structure-preserving document -> markup conversion (D-08).

The old code rebuilt documents from ``paragraph.text``, which dropped bold,
tables, lists and images. Pandoc converts natively in both directions, and
``--sandbox`` stops a malicious document from reaching the filesystem.
"""
import logging
from pathlib import Path

from .. import runner
from ..verify import verify_output
from .base import BaseEngine, EngineFailed, EngineOutput

logger = logging.getLogger(__name__)

WRITER_BY_EXT = {
    "md": "gfm",
    "html": "html5",
    "htm": "html5",
    "txt": "plain",
    "docx": "docx",
    "odt": "odt",
    "rtf": "rtf",
    "epub": "epub",
}


class PandocEngine(BaseEngine):
    """DOCX/ODT/RTF -> HTML/MD/TXT and MD/HTML -> DOCX/ODT."""

    name = "pandoc"
    binaries = ("pandoc",)

    async def run(self, source: Path, target_ext: str, dest: Path, options):
        binary = self.require()
        target_ext = target_ext.lower().lstrip(".")
        writer = WRITER_BY_EXT.get(target_ext)
        if not writer:
            raise EngineFailed(f"Pandoc cannot write .{target_ext}")

        media_dir = dest.parent / "media"
        command = [
            binary,
            "--sandbox",
            str(source),
            "--output",
            str(dest),
            "--to",
            writer,
        ]
        if target_ext in ("html", "htm"):
            command.extend(["--standalone", "--embed-resources", "--extract-media", str(media_dir)])
        elif target_ext == "md":
            command.extend(["--extract-media", str(media_dir)])
        elif target_ext == "docx":
            reference = options.get("reference_doc")
            if reference and Path(str(reference)).exists():
                command.extend(["--reference-doc", str(reference)])

        await runner.run_checked(command, timeout=self.timeout(), cwd=dest.parent)

        if not dest.exists():
            raise EngineFailed(f"Pandoc wrote no .{target_ext} output")

        metrics = verify_output(dest, target_ext)
        output = EngineOutput(files=[dest], engine=self.name, metrics=metrics)
        if media_dir.exists() and any(media_dir.iterdir()):
            output.metrics["extracted_media"] = True
        return output
