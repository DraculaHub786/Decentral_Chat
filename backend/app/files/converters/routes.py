"""Converter API v2: capabilities, jobs, status, result, cancel (plan §3.5)."""
import asyncio
import json
import logging
import mimetypes

from aiohttp import web

from . import dispatch, jobs, queue as queue_mod, routes_table, settings, workspace as workspace_mod
from .jobs import STORE

logger = logging.getLogger(__name__)

# Errors map to the friendly messages in the plan.
ERROR_MESSAGES = {
    "E_UNSUPPORTED": "That conversion isn't available.",
    "E_TYPE_MISMATCH": "The file content doesn't match its extension.",
    "E_TOO_LARGE": "The file is larger than the limit for this type.",
    "E_CORRUPT": "The file looks damaged and can't be read.",
    "E_PASSWORD_REQUIRED": "The file is password-protected; remove the password and retry.",
    "E_TIMEOUT": "The conversion took too long and was stopped.",
    "E_ENGINE_UNAVAILABLE": "This conversion is temporarily unavailable.",
    "E_VERIFY_FAILED": "The result failed a safety check and was discarded.",
    "E_LIMIT": "Too many conversions in progress; try again shortly.",
}

ERROR_STATUS = {
    "E_UNSUPPORTED": 400,
    "E_TYPE_MISMATCH": 400,
    "E_TOO_LARGE": 413,
    "E_CORRUPT": 422,
    "E_PASSWORD_REQUIRED": 422,
    "E_TIMEOUT": 504,
    "E_ENGINE_UNAVAILABLE": 503,
    "E_VERIFY_FAILED": 500,
    "E_LIMIT": 429,
}


def error_response(code: str, detail: str = "") -> web.Response:
    return web.json_response(
        {"code": code, "error": detail or ERROR_MESSAGES.get(code, "Conversion failed.")},
        status=ERROR_STATUS.get(code, 500),
    )


async def _current_user(request):
    """Resolve the caller from the bearer token, or return None."""
    from ...auth.tokens import get_user_from_token
    return await get_user_from_token(request)


async def _run_job_task(job, filename, payload, target_ext, options):
    """Run one job to completion, recording the outcome on the job record."""
    try:
        await dispatch.run_job(job, filename, payload, target_ext, options)
    except dispatch.DispatchError as err:
        job.state = jobs.FAILED
        job.error_code = err.code
        job.error_message = err.message or ERROR_MESSAGES.get(err.code, "Conversion failed.")
        job.touch()
        _wipe(job.job_id)
    except asyncio.CancelledError:
        job.state = jobs.CANCELLED
        job.touch()
        _wipe(job.job_id)
        raise
    except Exception as err:  # never let a crash leave a job running forever
        logger.exception("Job %s crashed", job.job_id)
        job.state = jobs.FAILED
        job.error_code = "E_VERIFY_FAILED"
        job.error_message = "The conversion failed unexpectedly."
        job.touch()
        _wipe(job.job_id)


def _wipe(job_id: str) -> None:
    workspace_mod.Workspace(
        job_id, settings.CONVERTER_WORK_DIR / job_id
    ).cleanup()


async def capabilities_handler(request: web.Request) -> web.Response:
    """Full route table, versioned, with ETag revalidation."""
    payload = routes_table.capabilities()
    etag = f'W/"{payload["version"]}-{len(payload["routes"])}"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag})
    return web.json_response(payload, headers={"ETag": etag, "Cache-Control": "no-cache"})


async def create_job_handler(request: web.Request) -> web.Response:
    """Accept one upload, enqueue the job, and return 202 immediately."""
    if not settings.CONVERTER_V2_ENABLED:
        return error_response("E_ENGINE_UNAVAILABLE", "The converter is disabled on this server.")

    user_id = await _current_user(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)

    if STORE.running_count(user_id) >= settings.CONVERTER_USER_MAX_RUNNING:
        return error_response("E_LIMIT")
    if STORE.over_hourly_cap(user_id):
        return error_response(
            "E_LIMIT",
            "You've reached the hourly conversion limit. Try again later.",
        )

    target_ext = ""
    options = {}
    received = None
    filename = "upload.bin"

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
            elif part.name == "engine":
                options["engine"] = (await part.text()).strip().lower()
            elif part.filename:
                if received is not None:
                    return error_response("E_UNSUPPORTED", "Send exactly one file per job.")
                filename = workspace_mod.sanitize_filename(part.filename)
                received = await part.read()
    except Exception as err:
        logger.warning("Multipart parse failed: %s", err)
        return error_response("E_CORRUPT", "The upload could not be read.")

    if received is None:
        return web.json_response({"error": "No file provided"}, status=400)
    if not target_ext:
        return web.json_response({"error": "target is required"}, status=400)
    if len(received) > settings.CONVERTER_LIMITS_MAX_BYTES:
        return error_response("E_TOO_LARGE")

    source_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    route = routes_table.lookup(source_ext, target_ext)
    if route is None:
        declared = routes_table.lookup_unavailable(source_ext, target_ext)
        if declared is not None:
            return error_response(
                "E_ENGINE_UNAVAILABLE",
                f"{declared.engines[0]} is not installed on this server.",
            )
        return error_response(
            "E_UNSUPPORTED",
            f"{source_ext.upper()} to {target_ext.upper()} is not supported.",
        )

    job = STORE.create(user_id, source_ext, target_ext, tier=route.tier)
    STORE.record_submission(user_id)
    job.task = asyncio.create_task(
        jobs.enqueue_and_run(job, filename, received, target_ext, options)
    )

    logger.info("Job %s accepted: %s -> %s (%s)",
                job.job_id, source_ext, target_ext, route.tier)
    return web.json_response(job.as_status(), status=202)


async def job_status_handler(request: web.Request) -> web.Response:
    """Owner-only status. Never leaks another user's job."""
    user_id = await _current_user(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)

    job = STORE.get_owned(request.match_info["job_id"], user_id)
    if job is None:
        return web.json_response({"error": "Job not found"}, status=404)
    return web.json_response(job.as_status(), headers={"Cache-Control": "no-store"})


async def job_result_handler(request: web.Request) -> web.Response:
    """Stream the result once, then destroy the plaintext workspace."""
    user_id = await _current_user(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)

    job = STORE.get_owned(request.match_info["job_id"], user_id)
    if job is None:
        return web.json_response({"error": "Job not found"}, status=404)
    if job.state != jobs.DONE:
        return web.json_response({"error": "Result not ready"}, status=409)

    token = request.query.get("token", "")
    if not token or token != job.result_token or not job.result_token_valid:
        return web.json_response({"error": "Invalid or expired result token"}, status=403)

    ws = workspace_mod.Workspace(
        job.job_id, settings.CONVERTER_WORK_DIR / job.job_id
    )
    files = ws.list_outputs()
    if not files:
        return web.json_response({"error": "Result already collected"}, status=410)

    # A multi-file result (one PNG per PDF page) used to return files[0]
    # and silently drop the rest. Package them into one archive instead.
    multi_file = len(files) > 1
    target = workspace_mod.package_outputs(ws) if multi_file else files[0]
    if target is None:
        target = files[0]
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    body = target.read_bytes()
    download_name = "converted.zip" if multi_file else (job.result_name or target.name)

    # Single use: the token is burned and the plaintext is gone before we reply.
    job.result_token = ""
    job.state = jobs.EXPIRED
    job.result_files = []
    job.touch()
    ws.cleanup()
    STORE.purge(job.job_id)

    return web.Response(
        body=body,
        content_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "no-store",
            "X-Converted-Tier": job.tier,
        },
    )


async def cancel_job_handler(request: web.Request) -> web.Response:
    """Cancel a job: signal the engine, drop the record, wipe the directory."""
    user_id = await _current_user(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)

    job = STORE.get_owned(request.match_info["job_id"], user_id)
    if job is None:
        return web.json_response({"error": "Job not found"}, status=404)

    job.cancelled = True
    if job.task is not None and not job.task.done():
        job.task.cancel()
    _wipe(job.job_id)
    if job.state not in jobs.TERMINAL_STATES:
        job.state = jobs.CANCELLED
        job.touch()
    STORE.purge(job.job_id)
    return web.json_response({"success": True, "state": jobs.CANCELLED})


async def formats_handler(request: web.Request) -> web.Response:
    """Registry-backed target list for one extension (replaces the old shim)."""
    ext = (request.query.get("ext") or "").strip().lower().lstrip(".")
    if not ext:
        return web.json_response({
            "sources": routes_table.supported_sources(),
            "formats": {},
        })
    return web.json_response({"ext": ext, "formats": routes_table.supported_targets(ext)})


async def janitor_loop() -> None:
    """Periodically reap expired job records and orphaned directories (§3.6)."""
    interval = max(30, settings.CONVERTER_JANITOR_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(interval)
            removed_jobs = STORE.sweep()
            removed_dirs = workspace_mod.sweep_expired()
            if removed_jobs or removed_dirs:
                logger.info("🧹 Janitor: %d job records, %d directories",
                            removed_jobs, removed_dirs)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Janitor iteration failed")
