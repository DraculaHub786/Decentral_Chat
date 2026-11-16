"""Output validators: prove a result is real before reporting success (D-11).

Previously a silent engine failure or a truncated write was reported as a
successful conversion. These validators re-open the artifact every time.
"""
import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_BYTES = 16

MAGIC = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "bmp": (b"BM",),
    "ico": (b"\x00\x00\x01\x00",),
    "tiff": (b"II*\x00", b"MM\x00*"),
    "tif": (b"II*\x00", b"MM\x00*"),
    "mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "flac": (b"fLaC",),
    "ogg": (b"OggS",),
    "opus": (b"OggS",),
    "webm": (b"\x1a\x45\xdf\xa3",),
    "mkv": (b"\x1a\x45\xdf\xa3",),
}

RIFF_FORMATS = {"webp", "wav", "avi"}
FTYP_FORMATS = {"mp4", "m4a", "mov"}
ZIP_FORMATS = {"docx", "xlsx", "pptx", "odt", "ods", "odp", "epub"}
TEXT_FORMATS = {"txt", "md", "html", "htm", "csv", "rtf", "svg"}


class VerifyError(Exception):
    """Raised when output fails validation. The result must be discarded."""


def _read_header(path: Path, size: int = 64) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(size)


def _verify_zip(path: Path, ext: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as err:
        raise VerifyError(f"{ext.upper()} output is not a valid archive: {err}") from err
    if not names:
        raise VerifyError(f"{ext.upper()} output archive is empty")


def _verify_text(path: Path) -> None:
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        decoded = raw.decode("utf-8", errors="replace")
        replacement_ratio = decoded.count("\ufffd") / max(len(decoded), 1)
        if replacement_ratio > 0.1:
            raise VerifyError("Text output is not valid UTF-8")


def _verify_magic(path: Path, ext: str) -> None:
    header = _read_header(path)
    if ext in RIFF_FORMATS:
        if not header.startswith(b"RIFF"):
            raise VerifyError(f"{ext.upper()} output is missing the RIFF header")
        if ext == "webp" and header[8:12] != b"WEBP":
            raise VerifyError("WEBP output is missing the WEBP fourcc")
        return
    if ext in FTYP_FORMATS:
        if header[4:8] != b"ftyp":
            raise VerifyError(f"{ext.upper()} output is missing the ftyp box")
        return
    expected = MAGIC.get(ext)
    if expected and not any(header.startswith(sig) for sig in expected):
        raise VerifyError(f"{ext.upper()} output has an invalid file signature")


def pdf_page_count(path: Path):
    """Count pages without a heavy dependency; ``None`` when unknown."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            PdfReader = None  # type: ignore
    if PdfReader is not None:
        try:
            return len(PdfReader(str(path)).pages)
        except Exception as err:
            logger.warning("Could not read PDF page count: %s", err)
            return None
    try:
        blob = path.read_bytes()
        return blob.count(b"/Type /Page") - blob.count(b"/Type /Pages")
    except Exception:
        return None


def verify_output(path: Path, ext: str) -> dict:
    """Confirm the artifact is a usable file of the expected type."""
    ext = (ext or "").lower().lstrip(".")
    path = Path(path)

    if not path.exists():
        raise VerifyError("Output file was not created")
    size = path.stat().st_size
    if size < MIN_BYTES:
        raise VerifyError(f"Output file is suspiciously small ({size} bytes)")

    if ext in ZIP_FORMATS:
        _verify_zip(path, ext)
    elif ext in TEXT_FORMATS:
        _verify_text(path)
    else:
        _verify_magic(path, ext)

    metrics = {"bytes": size}
    if ext == "pdf":
        pages = pdf_page_count(path)
        if pages is not None:
            if pages <= 0:
                raise VerifyError("PDF output contains no pages")
            metrics["pages"] = pages
    return metrics
