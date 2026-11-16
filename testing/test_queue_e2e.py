"""End-to-end check of the Phase 4 queue: stage -> enqueue -> worker -> result."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.files.converters import jobs, queue as queue_mod, settings


async def main() -> None:
    settings.ensure_work_dir()
    queue_mod.reset_queue()

    q = queue_mod.get_queue(backend="memory")
    print("queue backend:", q.name)

    job = jobs.STORE.create("test-user", "md", "docx", tier="B")
    payload = b"# Heading\n\nSome **bold** text.\n\n- one\n- two\n"
    await jobs.enqueue_and_run(job, "sample.md", payload, "docx", {}, q=q)
    print("queued:", job.job_id, "state:", job.state)

    worker = asyncio.create_task(jobs.worker_loop("test-worker", q, jobs.STORE))

    for _ in range(200):
        await asyncio.sleep(0.1)
        if job.state in jobs.TERMINAL_STATES:
            break

    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    print("final:", job.state, "engine:", job.engine, "tier:", job.tier)

    if job.state != jobs.DONE:
        print("error:", job.error_code, job.error_message)
        jobs.wipe_workspace(job.job_id)
        raise SystemExit("job did not finish successfully")

    out_dir = settings.CONVERTER_WORK_DIR / job.job_id / "out"
    files = [p for p in out_dir.iterdir()] if out_dir.exists() else []
    print("result files:", [p.name for p in files])
    assert files, "no output produced"
    assert files[0].suffix == ".docx", files
    assert files[0].stat().st_size > 0, "empty output"
    print("QUEUE E2E OK")

    jobs.wipe_workspace(job.job_id)


asyncio.run(main())
