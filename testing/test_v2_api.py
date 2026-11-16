"""End-to-end test of the converter v2 HTTP API over a real aiohttp app."""
import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from app.files.converters import jobs, queue as conv_queue
from app.files.converters import routes as conv_routes

CURRENT_USER = {"id": "user-a"}


async def fake_current_user(request):
    return CURRENT_USER["id"]


conv_routes._current_user = fake_current_user


def make_png_bytes(size=(40, 30), color=(200, 30, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/files/capabilities", conv_routes.capabilities_handler)
    app.router.add_get("/api/files/formats", conv_routes.formats_handler)
    app.router.add_post("/api/files/jobs", conv_routes.create_job_handler)
    app.router.add_get("/api/files/jobs/{job_id}", conv_routes.job_status_handler)
    app.router.add_get("/api/files/jobs/{job_id}/result", conv_routes.job_result_handler)
    app.router.add_delete("/api/files/jobs/{job_id}", conv_routes.cancel_job_handler)
    return app


async def post_job(client, filename, data, target, options=None):
    form = FormData()
    form.add_field("target", target)
    if options:
        form.add_field("options", json.dumps(options))
    form.add_field("file", data, filename=filename,
                   content_type="application/octet-stream")
    return await client.post("/api/files/jobs", data=form)


async def wait_for_state(client, job_id, wanted, timeout=25.0):
    """Poll the status endpoint until the job reaches a terminal state."""
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get(f"/api/files/jobs/{job_id}")
        last = await resp.json()
        if last.get("state") in wanted:
            return last
        await asyncio.sleep(0.15)
    raise AssertionError(f"job {job_id} never reached {wanted}; last={last}")


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        raise AssertionError(label)


async def main():
    # Since Phase 4 the upload handler only *enqueues*; a worker pool drains the
    # queue. This test must start that pool, exactly as the server does at boot,
    # or every job sits in `queued` forever.
    conv_queue.reset_queue()
    work_queue = conv_queue.get_queue(backend="memory")
    workers = jobs.start_inline_workers(work_queue)

    app = build_app()
    async with TestClient(TestServer(app)) as client:
        # 1. Capabilities + ETag revalidation
        caps = await client.get("/api/files/capabilities")
        payload = await caps.json()
        check("capabilities 200", caps.status == 200)
        print(f"      {len(payload['routes'])} routes, version {payload['version']}")
        again = await client.get("/api/files/capabilities",
                                 headers={"If-None-Match": caps.headers["ETag"]})
        check("ETag revalidation returns 304", again.status == 304)

        # 2. Formats
        fmt = await client.get("/api/files/formats?ext=png")
        fmt_payload = await fmt.json()
        check("formats lists png targets", "webp" in fmt_payload["formats"])

        # 3. Async job: PNG -> WEBP
        resp = await post_job(client, "sample.png", make_png_bytes(), "webp")
        body = await resp.json()
        check("create job returns 202", resp.status == 202)
        check("job starts queued/running", body["state"] in ("queued", "running"))
        job_id = body["job_id"]

        status = await wait_for_state(client, job_id, ("done", "failed"))
        check("job finished done", status["state"] == "done")
        check("engine recorded", status["engine"] == "raster")
        check("tier reported", status["tier"] in ("A", "B", "C"))

        token = status["result_token"]

        # 4. Result access control
        bad = await client.get(f"/api/files/jobs/{job_id}/result?token=nope")
        check("bad token rejected 403", bad.status == 403)

        ok = await client.get(f"/api/files/jobs/{job_id}/result?token={token}")
        blob = await ok.read()
        check("result 200", ok.status == 200)
        check("result is real WEBP", blob[:4] == b"RIFF" and blob[8:12] == b"WEBP")
        print(f"      {len(blob)} bytes, tier header={ok.headers.get('X-Converted-Tier')}")

        # 5. Single-use token
        again_resp = await client.get(
            f"/api/files/jobs/{job_id}/result?token={token}")
        check("token is single-use", again_resp.status in (403, 404, 410))

        # 6. Unsupported pair -> friendly error, never a 500.
        # gz is still not implemented (only zip and tar are), so it remains a
        # clean 400. zip->tar became a real route in Phase 6 and is no longer
        # a valid negative case.
        bad_resp = await post_job(client, "sample.png", make_png_bytes(), "gz")
        bad_body = await bad_resp.json()
        check("png->gz is 400 E_UNSUPPORTED",
              bad_resp.status == 400 and bad_body["code"] == "E_UNSUPPORTED")

        # zip -> tar must now actually work (Phase 6 archive engine)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("inside.txt", b"hello")
        arc_resp = await post_job(client, "bundle.zip", archive.getvalue(), "tar")
        arc_body = await arc_resp.json()
        check("zip->tar accepted", arc_resp.status == 202)
        arc_status = await wait_for_state(client, arc_body["job_id"], ("done", "failed"))
        check("zip->tar done via archive engine",
              arc_status["state"] == "done" and arc_status["engine"] == "archive")
        arc_get = await client.get(
            "/api/files/jobs/%s/result?token=%s"
            % (arc_body["job_id"], arc_status["result_token"]))
        tar_blob = await arc_get.read()
        check("zip->tar result is a real tar", tar_blob[257:262] == b"ustar")

        # 7. D-05: another user cannot read the job or its result
        resp2 = await post_job(client, "second.png", make_png_bytes(color=(10, 120, 200)), "jpg")
        draft2 = await resp2.json()
        check("second job accepted", resp2.status == 202)
        status2 = await wait_for_state(client, draft2["job_id"], ("done", "failed"))
        check("second job done", status2["state"] == "done")

        CURRENT_USER["id"] = "user-b"
        steal = await client.get(f"/api/files/jobs/{draft2['job_id']}")
        check("cross-user status is 404", steal.status == 404)
        steal2 = await client.get(
            f"/api/files/jobs/{draft2['job_id']}/result?token={status2['result_token']}")
        check("cross-user result is 404", steal2.status == 404)
        CURRENT_USER["id"] = "user-a"

        # 8. Cancel removes the job
        resp3 = await post_job(client, "third.png", make_png_bytes(color=(1, 2, 3)), "bmp")
        draft3 = await resp3.json()
        cancelled = await client.delete(f"/api/files/jobs/{draft3['job_id']}")
        check("cancel accepted", cancelled.status == 200)
        gone = await client.get(f"/api/files/jobs/{draft3['job_id']}")
        check("cancelled job is gone", gone.status == 404)

    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)

    print("\nALL V2 API CHECKS PASSED")


asyncio.run(main())
