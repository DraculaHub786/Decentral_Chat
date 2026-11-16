"""Phase 5b: batch conversion over real HTTP.

Two PNGs in, one ZIP out, with the failure path and ownership checks covered.
The point is to drive the actual aiohttp handlers, not the helpers they call.
"""
import asyncio
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from app.files.converters import batch as conv_batch
from app.files.converters import jobs, queue as queue_mod, routes as conv_routes

CURRENT_USER = {"id": "batch-user"}


async def fake_current_user(request):
    return CURRENT_USER["id"]


conv_routes._current_user = fake_current_user
conv_batch.routes._current_user = fake_current_user


def make_png(color):
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(buf, format="PNG")
    return buf.getvalue()


def build_app():
    app = web.Application()
    app.router.add_post("/api/files/batch", conv_batch.batch_convert_handler)
    app.router.add_get("/api/files/batch/{batch_id}", conv_batch.batch_status_handler)
    app.router.add_get("/api/files/batch/{batch_id}/result",
                       conv_batch.batch_result_handler)
    return app


def check(label, condition):
    print(("PASS  " if condition else "FAIL  ") + label)
    if not condition:
        raise AssertionError(label)


async def post_batch(client, files, target):
    form = FormData()
    form.add_field("target", target)
    for name, payload in files:
        form.add_field("file", payload, filename=name,
                       content_type="application/octet-stream")
    return await client.post("/api/files/batch", data=form)


async def wait_batch(client, batch_id, timeout=30.0):
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get("/api/files/batch/" + batch_id)
        last = await resp.json()
        if last.get("state") in (jobs.DONE, jobs.FAILED):
            return last
        await asyncio.sleep(0.15)
    raise AssertionError("batch never finished; last=" + repr(last))


async def main():
    queue_mod.reset_queue()
    q = queue_mod.get_queue(backend="memory")
    workers = jobs.start_inline_workers(q)

    try:
        async with TestClient(TestServer(build_app())) as client:
            # 1. Two files, one target -> one batch, two jobs
            resp = await post_batch(
                client,
                [("red.png", make_png((255, 0, 0))),
                 ("blue.png", make_png((0, 0, 255)))],
                "jpg",
            )
            body = await resp.json()
            check("batch accepted 202", resp.status == 202)
            check("two job ids returned", len(body["job_ids"]) == 2)
            batch_id = body["batch_id"]

            status = await wait_batch(client, batch_id)
            check("batch rolled up to done", status["state"] == jobs.DONE)
            check("total is 2", status["total"] == 2)
            check("both done", status["done"] == 2)

            # One shared token for the whole batch: the ZIP is one deliverable,
            # so per-file tokens (which differ) cannot all match.
            token = status["result_token"]
            check("shared batch token present", bool(token))
            check("per-file tokens are not the batch token",
                  all(f["result_token"] != token for f in status["files"]))

            # 2. Wrong token -> 403
            denied = await client.get(
                "/api/files/batch/" + batch_id + "/result?token=nope")
            check("bad token rejected 403", denied.status == 403)

            # 3. Correct token -> one ZIP with both results plus a manifest
            ok = await client.get(
                "/api/files/batch/" + batch_id + "/result?token=" + token)
            blob = await ok.read()
            check("result 200", ok.status == 200)
            check("result is a zip", blob[:2] == b"PK")

            with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
                names = bundle.namelist()
            print("      zip entries:", names)
            check("manifest included", "manifest.json" in names)
            jpgs = [n for n in names if n.lower().endswith(".jpg")]
            check("two converted files", len(jpgs) == 2)

            # 4. Second collection is refused (single use)
            again = await client.get(
                "/api/files/batch/" + batch_id + "/result?token=" + token)
            check("batch result is single-use", again.status in (403, 404, 409, 410))

            # 5. Mixed batch: one good file, one unsupported -> whole batch rejected
            bad = await post_batch(
                client,
                [("ok.png", make_png((1, 2, 3))), ("weird.xyz", b"junk")],
                "jpg",
            )
            bad_body = await bad.json()
            check("mixed batch rejected", bad.status == 400)
            check("rejection is E_UNSUPPORTED",
                  bad_body.get("code") == "E_UNSUPPORTED")
            check("nothing half-queued", bad_body.get("job_ids") is None)

            # 6. Another user cannot read the batch
            CURRENT_USER["id"] = "intruder"
            steal = await client.get("/api/files/batch/" + batch_id)
            check("cross-user status is 404", steal.status == 404)
            CURRENT_USER["id"] = "batch-user"

    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    print("\nPHASE 5b BATCH API OK")


asyncio.run(main())
