"""Engine progress reporting.

Progress is coarse by design: engines report a percentage they can actually
justify, or nothing at all. A fabricated "10% every 200ms" timer (the original
behaviour, defect D-04) is worse than no bar, because it claims certainty the
engine does not have.

Each job gets a :class:`ProgressReporter` bound to its ``Job`` record. Engines
call ``reporter.report(percent)`` from their output parser; the reporter clamps,
never moves backwards, and throttles writes so a chatty engine cannot flood the
status endpoint with updates.
"""
import logging
import time

logger = logging.getLogger(__name__)

# Don't write more than one update per this many seconds per job.
MIN_INTERVAL_SECONDS = 1.0


class ProgressReporter:
    """Binds a job to a monotonic 0-99 progress counter.

    Capped at 99: only the dispatcher may report 100, and only once the output
    has passed verification. Otherwise the bar reaches 100 while the safety
    check is still running, and a failed verification would pull it back down.
    """

    MAX_ENGINE_PERCENT = 99

    def __init__(self, job=None, clock=time.monotonic):
        self._job = job
        self._clock = clock
        self._last_value = -1
        self._last_write = 0.0

    def report(self, percent) -> int:
        """Record a new percentage. Returns the value actually stored."""
        try:
            value = int(percent)
        except (TypeError, ValueError):
            return self._last_value

        value = max(0, min(self.MAX_ENGINE_PERCENT, value))
        if value <= self._last_value:
            return self._last_value

        now = self._clock()
        throttled = (self._last_value >= 0
                     and now - self._last_write < MIN_INTERVAL_SECONDS
                     and value < self.MAX_ENGINE_PERCENT)
        if throttled:
            return self._last_value

        self._last_value = value
        self._last_write = now
        if self._job is not None:
            self._job.percent = value
            self._job.touch()
        return value

    @property
    def value(self) -> int:
        return self._last_value


def parse_ffmpeg_time(line: str):
    """Extract elapsed seconds from an FFmpeg ``time=HH:MM:SS.ss`` line.

    Returns None when the line carries no timestamp, so callers can ignore
    banners, stream maps and codec notices without special-casing them.
    """
    marker = "time="
    index = line.find(marker)
    if index < 0:
        return None
    remainder = line[index + len(marker):].split()
    if not remainder:
        return None
    parts = remainder[0].split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (float(part) for part in parts)
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def percent_from_elapsed(elapsed, total) -> int:
    """Map elapsed/total seconds onto 0-99, guarding against bad durations."""
    try:
        total = float(total)
        elapsed = float(elapsed)
    except (TypeError, ValueError):
        return 0
    if total <= 0:
        return 0
    ratio = max(0.0, min(1.0, elapsed / total))
    return int(ratio * ProgressReporter.MAX_ENGINE_PERCENT)
