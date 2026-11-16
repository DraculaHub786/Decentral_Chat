"""Phase 5: a multi-file result must come back as one ZIP, not page 1 only."""
import asyncio
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.files.converters import jobs, queue as queue_mod, settings
from app.files.converters import workspace as workspace_mod


class FakeRequest:
    """Minimal stand-in so we can drive the real handler without aiohttp."""

    def __init__(self, user_id, job_id, token):
        self.user_id = user_id
        self.match_info = {"job_id": job_id}
        self.query = {"token": token}


async def run_job(q, src_name, payload, target):
    job = jobs.STORE.create("phase5-user", src_name.rsplit(".", 1)[-1], target, tier="A")
    await jobs.enqueue_and_run(job, src_name, payload, target, {}, q=q)

    worker = asyncio.create_task(jobs.worker_loop("p5", q, jobs.STORE))
    for _ in range(600):
        await asyncio.sleep(0.1)
        if job.state in jobs.TERMINAL_STATES:
            break
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass
    return job


def make_two_page_pdf() -> bytes:
    """Two PNG pages through img2pdf, so the PDF really has 2 pages."""
    from PIL import Image
    import img2pdf

    blobs = []
    for colour in ((255, 0, 0), (0, 0, 255)):
        buf = io.BytesIO()
        Image.new("RGB", (60, 60), colour).save(buf, format="PNG")
        blobs.append(buf.getvalue())
    return img2pdf.convert(blobs)


async def main() -> None:
    settings.ensure_work_dir()
    queue_mod.reset_queue()
    q = queue_mod.get_queue(backend="memory")

    pdf = make_two_page_pdf()
    job = await run_job(q, "twopage.pdf", pdf, "png")
    assert job.state == jobs.DONE, (job.state, job.error_message)

    ws = workspace_mod.Workspace(job.job_id, settings.CONVERTER_WORK_DIR / job.job_id)
    pages = ws.list_outputs()
    print("pages produced:", [p.name for p in pages])
    assert len(pages) >= 2, f"expected several pages, got {len(pages)}"

    archive = workspace_mod.package_outputs(ws)
    assert archive is not None and archive.exists(), "no archive produced"
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    print("zip entries:", names)
    assert len(names) >= 2, names
    assert all(n.lower().endswith(".png") for n in names), names

    jobs.wipe_workspace(job.job_id)
    print("PHASE 5a OK")


asyncio.run(main())
