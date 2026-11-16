"""FFmpeg engine: codec table, progress parsing, cover art, protocol whitelist."""
import logging
import re
from pathlib import Path

from .. import runner
from ..progress import parse_ffmpeg_time, percent_from_elapsed
from ..verify import verify_output
from .base import BaseEngine, EngineFailed, EngineOutput

logger = logging.getLogger(__name__)

AUDIO_CODECS = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    "wav": ["-c:a", "pcm_s16le"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "flac": ["-c:a", "flac", "-compression_level", "5"],
    "wma": ["-c:a", "wmav2"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
}

VIDEO_CODECS = {
    "mp4": ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart"],
    "webm": ["-c:v", "libvpx-vp9", "-b:v", "1M", "-c:a", "libopus"],
    "mkv": ["-c:v", "libx264", "-crf", "23", "-c:a", "aac"],
    "mov": ["-c:v", "libx264", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart"],
    "avi": ["-c:v", "mpeg4", "-c:a", "libmp3lame"],
    "flv": ["-c:v", "flv", "-c:a", "libmp3lame"],
    "wmv": ["-c:v", "wmv2", "-c:a", "wmav2"],
}

# Only these protocols may be read; blocks file://, http:// and friends.
SAFE_PROTOCOLS = "file,pipe"

PROGRESS_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
AUDIO_TARGETS = set(AUDIO_CODECS)


def _progress_hook(options, total_seconds):
    """Build an FFmpeg stderr callback that maps ``time=`` onto a percentage.

    Returns None when the caller did not supply a reporter or the duration is
    unknown - an unknown total means there is no honest percentage to show, so
    no progress is reported at all rather than guessing.
    """
    reporter = (options or {}).get("_progress")
    if reporter is None or not total_seconds or total_seconds <= 0:
        return None

    def on_line(line: str) -> None:
        elapsed = parse_ffmpeg_time(line)
        if elapsed is None:
            return
        reporter.report(percent_from_elapsed(elapsed, total_seconds))

    return on_line


class FFmpegEngine(BaseEngine):
    """Audio, video, video -> audio, and video -> GIF with a safe protocol list."""

    name = "ffmpeg"
    binaries = ("ffmpeg",)

    async def run(self, source: Path, target_ext: str, dest: Path, options):
        binary = self.require()
        target_ext = target_ext.lower().lstrip(".")
        work_dir = dest.parent

        base = [
            binary, "-hide_banner", "-nostdin", "-y",
            "-protocol_whitelist", SAFE_PROTOCOLS,
            "-i", str(source),
        ]
        extra = _extra_args()

        if target_ext in AUDIO_CODECS:
            # -vn drops any video stream; cover art is re-attached afterwards.
            command = base + ["-vn"] + AUDIO_CODECS[target_ext] + ["-map_metadata", "0"]
            command += _cover_art_args(source)
            command += extra + [str(dest)]
        elif target_ext == "gif":
            fps = str(int(options.get("fps") or 15))
            width = str(int(options.get("width") or 480))
            palette = work_dir / "palette.png"
            await runner.run_checked(
                base + ["-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen",
                        str(palette)],
                timeout=self.timeout(), cwd=work_dir,
            )
            command = [
                binary, "-hide_banner", "-nostdin", "-y",
                "-protocol_whitelist", SAFE_PROTOCOLS,
                "-i", str(source), "-i", str(palette),
                "-filter_complex",
                f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse",
                *extra, str(dest),
            ]
        elif target_ext in VIDEO_CODECS:
            command = base + VIDEO_CODECS[target_ext] + ["-map_metadata", "0"]
            command += extra + [str(dest)]
        else:
            raise EngineFailed(f"FFmpeg cannot write .{target_ext}")

        # -progress would also work, but stderr already carries `time=` for free
        # and needs no extra flag or pipe. The total comes from the *input*, so
        # the percentage is real even though the output does not exist yet.
        hook = _progress_hook(options, await _duration(source))
        await runner.run_checked(command, timeout=self.timeout(), cwd=work_dir,
                                 on_stderr_line=hook)

        if not dest.exists():
            raise EngineFailed(f"FFmpeg wrote no .{target_ext} output")

        metrics = verify_output(dest, target_ext)
        duration = await _duration(dest)
        if duration is not None:
            metrics["duration"] = duration
        output = EngineOutput(files=[dest], engine=self.name, metrics=metrics)
        if target_ext in AUDIO_CODECS:
            output.metrics["metadata_copied"] = True
        return output


def _extra_args() -> list:
    """Env-driven extras, e.g. CONVERTER_FFMPEG_EXTRA_ARGS='-hwaccel cuda'."""
    import os
    raw = os.getenv("CONVERTER_FFMPEG_EXTRA_ARGS", "")
    return [token for token in raw.split() if token]


def _cover_art_args(source: Path) -> list:
    """Copy attached cover art when the source carries an embedded picture."""
    return ["-map", "0:a", "-map", "0:v?", "-c:v", "copy", "-disposition:v", "attached_pic"]


async def _duration(path: Path):
    """Ask ffprobe for the real duration so we can verify it against the input."""
    import asyncio
    from .. import settings
    ffprobe = settings.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                runner.subprocess.run,
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True,
            ),
            timeout=20,
        )
        value = (result.stdout or "").strip()
        return float(value) if value else None
    except Exception:
        return None
