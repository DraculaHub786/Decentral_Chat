"""Progress reporting: the bar must reflect real engine output, not a timer.

The original defect (D-04) incremented the percentage in the browser on a
200ms interval. These checks assert the replacement: values come from FFmpeg's
own ``time=`` output, never move backwards, and never reach 100 before the
dispatcher has verified the output.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.files.converters.progress import (
    ProgressReporter,
    parse_ffmpeg_time,
    percent_from_elapsed,
)

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)
        if detail:
            print(f"      {detail}")


def main():
    # --- ffmpeg timestamp parsing -------------------------------------------
    check("parses a plain timestamp",
          parse_ffmpeg_time("frame=  120 time=00:00:05.00 bitrate=...") == 5.0)
    check("parses hours", abs(parse_ffmpeg_time("time=01:02:03.50") - 3723.5) < 0.01)
    check("handles CR-separated progress output",
          parse_ffmpeg_time("size=1kB time=00:00:12.34 bitrate=1k") == 12.34)
    check("ignores lines without a timestamp",
          parse_ffmpeg_time("Stream #0:0: Video: h264") is None)
    check("ignores a malformed timestamp", parse_ffmpeg_time("time=abc") is None)

    # --- percentage mapping --------------------------------------------------
    check("0% at start", percent_from_elapsed(0, 10) == 0)
    check("50% halfway", percent_from_elapsed(5, 10) == 49)
    check("clamps at 99", percent_from_elapsed(10, 10) == 99)
    check("never exceeds 99 on overshoot", percent_from_elapsed(30, 10) == 99)
    check("unknown duration yields 0", percent_from_elapsed(5, 0) == 0)
    check("garbage duration yields 0", percent_from_elapsed(5, "nope") == 0)

    # --- reporter behaviour --------------------------------------------------
    class FakeJob:
        def __init__(self):
            self.percent = None
            self.touches = 0

        def touch(self):
            self.touches += 1

    clock = [1000.0]
    job = FakeJob()
    reporter = ProgressReporter(job, clock=lambda: clock[0])

    reporter.report(10)
    check("first report is stored", job.percent == 10, f"percent={job.percent}")

    # Within the throttle window a small step is dropped...
    clock[0] += 0.1
    reporter.report(12)
    check("throttled update is dropped", job.percent == 10, f"percent={job.percent}")

    # ...but a jump to the ceiling still lands, so the bar cannot stall.
    reporter.report(99)
    check("ceiling update bypasses throttle", job.percent == 99,
          f"percent={job.percent}")

    # Monotonic: an engine retry must not drag the bar backwards.
    reporter.report(40)
    check("never moves backwards", job.percent == 99, f"percent={job.percent}")

    # Clamped hard at 99 so only dispatch can report 100.
    clock[0] += 5
    reporter.report(100)
    check("engine cannot report 100", job.percent == 99, f"percent={job.percent}")
    check("reporter value matches job", reporter.value == 99)

    # Invalid input must not corrupt the record.
    reporter.report("bogus")
    check("non-numeric input ignored", job.percent == 99)

    # A reporter with no job still tracks its own value.
    bare = ProgressReporter()
    bare.report(42)
    check("reporter works without a job", bare.value == 42)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED")
        return 1
    print("PROGRESS REPORTING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
