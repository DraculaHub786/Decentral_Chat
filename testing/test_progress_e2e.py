"""End-to-end: a real FFmpeg conversion must report intermediate percentages.

Unit tests prove the parser and the reporter. This proves the wiring: dispatch
injects the reporter, ffmpeg reads its own stderr, and the job record moves off
``percent is None`` before the conversion finishes.

A 12-second synthetic clip is generated with FFmpeg itself, so the test needs no
fixture file and no network. It is skipped (not failed) when FFmpeg is missing.
"""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.files.converters import dispatch, jobs, settings, workspace

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)
        if detail:
            print(f"      {detail}")


def make_sample(directory: Path):
    """A 12s test pattern; long enough that FFmpeg emits several time= lines."""
    ffmpeg = settings.which("ffmpeg")
    if not ffmpeg:
        return None
    target = directory / "sample.mp4"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=12",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
         "-shortest", str(target)],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0 or not target.exists():
        print("      ffmpeg sample generation failed:", result.stderr[-300:])
        return None
    return target


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        sample = make_sample(Path(tmp))
        if sample is None:
            print("SKIP  FFmpeg unavailable; end-to-end progress not exercised")
            print("\nPROGRESS E2E SKIPPED")
            return 0

        payload = sample.read_bytes()
        job = jobs.STORE.create("progress-test-user", "mp4", "mp3")
        check("job starts with no percentage", job.percent is None,
              f"percent={job.percent}")

        seen = []
        stop = asyncio.Event()

        async def poll():
            # Sample the record while the conversion runs: the reporter writes
            # to the job directly, so this is exactly what the API would serve.
            while not stop.is_set():
                if job.percent is not None:
                    seen.append(job.percent)
                await asyncio.sleep(0.05)

        poller = asyncio.create_task(poll())
        try:
            ws = await dispatch.run_job(job, "sample.mp4", payload, "mp3", {})
        finally:
            stop.set()
            await poller

        check("conversion finished done", job.state == jobs.DONE,
              f"state={job.state} error={job.error_message}")
        check("final percentage is 100", job.percent == 100, f"percent={job.percent}")
        check("intermediate progress was observed", bool(seen),
              f"sampled values={seen[:10]}")

        # The point of the whole change: at least one value strictly between the
        # start and the end, which the old timer-free code could never produce.
        intermediate = [p for p in seen if 0 < p < 100]
        check("progress advanced past 0 before finishing",
              bool(intermediate), f"sampled values={seen[:10]}")
        check("progress never decreased",
              all(b >= a for a, b in zip(seen, seen[1:])),
              f"sampled values={seen[:10]}")

        workspace.Workspace(job.job_id,
                            settings.CONVERTER_WORK_DIR / job.job_id).cleanup()
        jobs.STORE.purge(job.job_id)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED")
        return 1
    print("PROGRESS E2E CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
