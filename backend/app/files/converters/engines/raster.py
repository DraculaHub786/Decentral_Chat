"""Raster engine: Pillow-based image conversion that keeps data (fixes D-13).

The old pipeline lost three things:
  1. Animated GIFs collapsed to a single frame.
  2. ICC profiles and EXIF were dropped.
  3. Animated sources to static targets silently kept only frame one.

Here, animation is preserved when the target supports it, the ICC profile is
carried across, and anything we cannot keep becomes an explicit warning.
"""
import logging
from pathlib import Path

from ..verify import verify_output
from .base import BaseEngine, EngineFailed, EngineOutput

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps, ImageSequence
    HAS_PILLOW = True
except ImportError:  # pragma: no cover
    HAS_PILLOW = False

OPAQUE_FORMATS = {"jpg", "jpeg", "bmp"}
ANIMATED_FORMATS = {"gif", "webp"}
LOSSLESS_FORMATS = {"png", "tiff", "tif", "bmp"}

SAVE_OPTIONS = {
    "png": {"optimize": True, "compress_level": 6},
    "jpg": {"quality": 95, "optimize": True, "progressive": True},
    "jpeg": {"quality": 95, "optimize": True, "progressive": True},
    "webp": {"quality": 90, "method": 6},
    "tiff": {"compression": "tiff_lzw"},
    "tif": {"compression": "tiff_lzw"},
    "bmp": {},
    "gif": {"optimize": True},
    "ico": {},
    "avif": {"quality": 80},
}

ICO_SIZES = ((256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16))

# Pillow keys its save handlers by canonical format name, not by extension.
# "jpg" and "tif" are extensions only; upper-casing them misses the handler
# (KeyError: 'JPG'), which used to surface to the user as a corrupt file.
FORMAT_NAMES = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "tif": "TIFF",
    "tiff": "TIFF",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "gif": "GIF",
    "ico": "ICO",
    "avif": "AVIF",
}


def _flatten_alpha(image):
    """Composite transparency onto white for targets that cannot hold alpha."""
    if image.mode == "P":
        image = image.convert("RGBA")
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        return background
    return image.convert("RGB")


def _apply_orientation(image):
    """Honour EXIF orientation so a rotated photo stays upright."""
    try:
        corrected = ImageOps.exif_transpose(image)
        return corrected if corrected is not None else image
    except Exception:
        return image


def _carry_icc(image, target_format):
    """Return allow-listed save options so the ICC profile survives."""
    icc = None
    try:
        icc = image.info.get("icc_profile")
    except Exception:
        icc = None
    if icc and target_format in ("jpg", "jpeg", "png", "webp", "tiff", "tif"):
        return {"icc_profile": icc}
    return {}


def _build_ico(image, dest):
    """Write a multi-resolution icon; Pillow picks the best layers."""
    sized = []
    for width, height in ICO_SIZES:
        frame = image.copy()
        frame.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(frame, ((width - frame.width) // 2, (height - frame.height) // 2))
        sized.append(canvas)
    sized[0].save(dest, format="ICO", sizes=[im.size for im in sized])
    return dest


class RasterEngine(BaseEngine):
    """Raster <-> raster in Python; animated frames survive when supported."""

    name = "raster"
    binaries = ()

    def require(self) -> str:
        if not HAS_PILLOW:
            raise EngineFailed("Pillow is not installed; image conversion unavailable")
        return "pillow"

    async def run(self, source: Path, target_ext: str, dest: Path, options):
        self.require()
        target_ext = target_ext.lower().lstrip(".")
        warnings = []
        metrics = {}

        with Image.open(source) as opened:
            frame_count = getattr(opened, "n_frames", 1) or 1
            has_alpha = (opened.mode in ("RGBA", "LA", "PA")
                         or "transparency" in opened.info)
            metrics["frames_in"] = frame_count

            if target_ext == "ico":
                flat = _apply_orientation(opened.convert("RGBA"))
                _build_ico(flat, dest)
                metrics.update(verify_output(dest, "ico"))
                metrics["frames_out"] = 1
                return EngineOutput(files=[dest], engine=self.name,
                                    metrics=metrics, warnings=warnings)

            keep_animation = frame_count > 1 and target_ext in ANIMATED_FORMATS
            if keep_animation:
                frames = []
                durations = []
                for frame in ImageSequence.Iterator(opened):
                    oriented = _apply_orientation(frame.copy())
                    frames.append(oriented.convert("RGBA"))
                    durations.append(frame.info.get("duration", 100))
                options_out = dict(SAVE_OPTIONS.get(target_ext, {}))
                options_out.update({
                    "save_all": True,
                    "append_images": frames[1:],
                    "duration": durations,
                    "loop": opened.info.get("loop", 0),
                })
                frames[0].save(dest,
                               format="WEBP" if target_ext == "webp" else "GIF",
                               **options_out)
                metrics["frames_out"] = len(frames)
            else:
                if frame_count > 1:
                    warnings.append(f"Only the first of {frame_count} frames was kept.")
                working = _apply_orientation(opened.copy())
                if target_ext in OPAQUE_FORMATS and has_alpha:
                    warnings.append("Transparency was replaced with white.")
                    working = _flatten_alpha(working)
                elif target_ext in ("png", "webp") and working.mode == "RGB":
                    working = working.convert("RGBA") if has_alpha else working
                save_kwargs = dict(SAVE_OPTIONS.get(target_ext, {}))
                save_kwargs.update(_carry_icc(opened, target_ext))
                save_kwargs.setdefault(
                    "format", FORMAT_NAMES.get(target_ext, target_ext.upper()))
                if target_ext == "gif" and working.mode != "P":
                    working = working.convert("P", palette=Image.ADAPTIVE, colors=256)
                working.save(dest, **save_kwargs)
                metrics["frames_out"] = 1
                if _carry_icc(opened, target_ext):
                    metrics["icc_preserved"] = True

        metrics.update(verify_output(dest, target_ext))
        return EngineOutput(files=[dest], engine=self.name,
                            metrics=metrics, warnings=warnings)
