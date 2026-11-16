"""Batch conversion: many uploads in, one ZIP out (plan Phase 5b).

Kept separate from ``routes.py`` so the single-job handler stays readable. The
batch endpoint reuses the same registry, limits, staging and worker pool; it
only fans one request out into several jobs and collects the results.
"""
import io
import json
import logging
import secrets
import time
import uuid
import zipfile

from aiohttp import web

from . import jobs, queue as queue_mod, routes, routes_table, settings
from . import workspace as workspace_mod

logger = logging.getLogger(__name__)

MAX_BATCH_FILES = 20


def _error(code, detail=""):
    return routes.error_response(code, detail)


def _split_ext(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def batch_convert_handler(request):
    """Accept several files, convert each to the same target, return one ZIP.

    Every route is validated before anything is queued, so a batch either
    starts cleanly or is rejected outright - never half-queued.
    """
    if not settings.CONVERTER_V2_ENABLED:
        return _error("E_ENGINE_UNAVAILABLE", "The converter is disabled on this server.")

    user_id = await routes._current_user(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)

    target_ext = ""
    options = {}
    uploads = []

    try:
        reader = await request.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "target":
                target_ext = (await part.text()).strip().lower().lstrip(".")
            elif part.name == "options":
                raw = (await part.text()).strip()
                if raw:
                    try:
                        options = json.loads(raw)
                    except json.JSONDecodeError:
                        options = {}
            elif part.filename:
                uploads.append(
                    (workspace_mod.sanitize_filename(part.filename), await part.read())
                )
    except Exception as err:
        logger.warning("Batch multipart parse failed: %s", err)
        return _error("E_CORRUPT", "The upload could not be read.")

    if not uploads:
        return web.json_response({"error": "No files provided"}, status=400)
    if not target_ext:
        return web.json_response({"error": "target is required"}, status=400)
    if jobs.STORE.over_hourly_cap(user_id):
        return _error(
            "E_LIMIT",
            "You've reached the hourly conversion limit. Try again later.",
        )
    if len(uploads) > MAX_BATCH_FILES:
        return _error("E_LIMIT", "Send at most %d files per batch." % MAX_BATCH_FILES)
    if sum(len(payload) for _, payload in uploads) > settings.CONVERTER_LIMITS_MAX_BYTES:
        return _error("E_TOO_LARGE")

    for filename, payload in uploads:
        source_ext = _split_ext(filename)
        if routes_table.lookup(source_ext, target_ext) is None:
            declared = routes_table.lookup_unavailable(source_ext, target_ext)
            if declared is not None:
                return _error(
                    "E_ENGINE_UNAVAILABLE",
                    "%s is not installed, so %s to %s is unavailable."
                    % (declared.engines[0], source_ext.upper(), target_ext.upper()),
                )
            return _error(
                "E_UNSUPPORTED",
                "%s to %s is not supported." % (source_ext.upper(), target_ext.upper()),
            )
        if len(payload) > settings.CONVERTER_LIMITS_MAX_BYTES:
            return _error("E_TOO_LARGE", "%s is larger than the limit." % filename)

    # Resolve the queue the same way the server does at boot. An earlier
    # version called routes._redis_client(), which does not exist, so every
    # batch request failed with a 500. get_queue falls back to memory when
    # Redis is absent, which is the right behaviour here.
    from ...globals import g
    q = queue_mod.get_queue(getattr(g, "redis_client", None))
    batch_id = uuid.uuid4().hex
    batch_token = secrets.token_urlsafe(32)
    job_ids = []

    for filename, payload in uploads:
        source_ext = _split_ext(filename)
        route = routes_table.lookup(source_ext, target_ext)
        job = jobs.STORE.create(user_id, source_ext, target_ext, tier=route.tier)
        job.batch_id = batch_id
        job.source_name = filename
        job.batch_token = batch_token
        job.result_token_expires_at = 0.0
        try:
            jobs.stage_upload(job, filename, payload, target_ext, options)
            jobs.STORE.record_submission(user_id)
            await q.put(job.job_id)
        except Exception:
            logger.exception("Batch member %s could not be queued", job.job_id)
            jobs.wipe_workspace(job.job_id)
            jobs.STORE.purge(job.job_id)
            return _error("E_ENGINE_UNAVAILABLE", "The converter queue is unavailable.")
        job_ids.append(job.job_id)

    logger.info("Batch %s queued: %d file(s) -> %s", batch_id, len(job_ids), target_ext)
    return web.json_response(
        {"batch_id": batch_id, "job_ids": job_ids, "state": jobs.QUEUED},
        status=202,
    )


def _batch_members(user_id, batch_id):
    return [
        job for job in jobs.STORE.iter_user_jobs(user_id)
        if getattr(job, "batch_id", "") == batch_id
    ]


async def batch_status_handler(request):
    """Aggregate status for a batch: per-file state plus an overall rollup."""
    user_id = await routes._current_user(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)

    batch_id = request.match_info["batch_id"]
    members = _batch_members(user_id, batch_id)
    if not members:
        return web.json_response({"error": "Batch not found"}, status=404)

    states = [job.state for job in members]
    failed = sum(1 for s in states if s == jobs.FAILED)
    done = sum(1 for s in states if s == jobs.DONE)

    if all(s in jobs.TERMINAL_STATES for s in states):
        overall = jobs.FAILED if failed == len(states) else jobs.DONE
    elif any(s == jobs.RUNNING for s in states):
        overall = jobs.RUNNING
    else:
        overall = jobs.QUEUED

    return web.json_response(
        {
            "batch_id": batch_id,
            "state": overall,
            "result_token": members[0].batch_token if overall == jobs.DONE else "",
            "total": len(members),
            "done": done,
            "failed": failed,
            "files": [
                {
                    "job_id": job.job_id,
                    "name": getattr(job, "source_name", ""),
                    "state": job.state,
                    "code": job.error_code,
                    "result_token": job.result_token if job.state == jobs.DONE else "",
                }
                for job in members
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


async def batch_result_handler(request):
    """Stream one ZIP containing every finished result in the batch.

    Failed members are recorded in a manifest inside the archive rather than
    aborting the download: someone who converted 20 files and lost 1 should
    still receive the other 19.
    """
    user_id = await routes._current_user(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)

    batch_id = request.match_info["batch_id"]
    members = _batch_members(user_id, batch_id)
    if not members:
        return web.json_response({"error": "Batch not found"}, status=404)
    if any(job.state not in jobs.TERMINAL_STATES for job in members):
        return web.json_response({"error": "Batch not ready"}, status=409)

    finished = [job for job in members if job.state == jobs.DONE]
    if finished:
        token = request.query.get("token", "")
        # Every member shares one batch token. Requiring the caller's token to
        # match each member's own token was impossible - those differ.
        expected = members[0].batch_token
        if not token or not expected or not secrets.compare_digest(token, expected):
            return web.json_response(
                {"error": "Invalid or expired result token"}, status=403
            )
        if members[0].result_token_expires_at and (
            time.time() > members[0].result_token_expires_at
        ):
            return web.json_response(
                {"error": "Invalid or expired result token"}, status=403
            )

    buffer = io.BytesIO()
    manifest = {"batch_id": batch_id, "files": []}

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for job in members:
            entry = {
                "job_id": job.job_id,
                "name": getattr(job, "source_name", ""),
                "state": job.state,
            }
            if job.state != jobs.DONE:
                entry["code"] = job.error_code
                entry["error"] = job.error_message
                manifest["files"].append(entry)
                continue

            ws = workspace_mod.Workspace(
                job.job_id, settings.CONVERTER_WORK_DIR / job.job_id
            )
            outputs = ws.list_outputs()
            for produced in outputs:
                try:
                    bundle.write(produced, arcname=produced.name)
                except OSError:
                    logger.warning("Batch %s: could not add %s", batch_id, produced.name)
            entry["result_files"] = [p.name for p in outputs]
            manifest["files"].append(entry)

            job.result_token = ""
            job.state = jobs.EXPIRED
            job.result_files = []
            job.touch()
            ws.cleanup()
            jobs.STORE.purge(job.job_id)

        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))

    return web.Response(
        body=buffer.getvalue(),
        content_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="batch.zip"',
            "Cache-Control": "no-store",
        },
    )
