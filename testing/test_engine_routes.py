"""Verify the installed engine set end to end through the job queue."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.files.converters import jobs, queue as queue_mod, settings


async def run_case(q, name, src_name, payload, target):
    source_ext = src_name.rsplit(".", 1)[-1]
    job = jobs.STORE.create("test-user", source_ext, target, tier="B")
    await jobs.enqueue_and_run(job, src_name, payload, target, {}, q=q)

    worker = asyncio.create_task(jobs.worker_loop(name, q, jobs.STORE))
    for _ in range(600):
        await asyncio.sleep(0.1)
        if job.state in jobs.TERMINAL_STATES:
            break
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    out_dir = settings.CONVERTER_WORK_DIR / job.job_id / "out"
    files = [p.name for p in out_dir.iterdir()] if out_dir.exists() else []
    print(src_name, "->", target, "state:", job.state,
          "engine:", job.engine, "files:", files)
    if job.state != jobs.DONE:
        print("  error:", job.error_code, job.error_message)
    jobs.wipe_workspace(job.job_id)
    return job.state == jobs.DONE, files


async def main():
    settings.ensure_work_dir()
    queue_mod.reset_queue()
    q = queue_mod.get_queue(backend="memory")

    docx_bytes = (ROOT / "test_conversions" / "test_document.docx").read_bytes()

    ok_pdf, pdf_files = await run_case(q, "w-docx", "report.docx", docx_bytes, "pdf")
    ok_docx, docx_out = await run_case(
        q, "w-md", "notes.md", b"# Hi\n\n- a\n- b\n", "docx")

    assert ok_pdf, "docx -> pdf failed"
    assert any(f.endswith(".pdf") for f in pdf_files), pdf_files
    assert not any("lo-profile" in f for f in pdf_files), pdf_files
    assert ok_docx, "md -> docx failed"
    assert any(f.endswith(".docx") for f in docx_out), docx_out

    print("ALL ENGINE ROUTES OK")


asyncio.run(main())
