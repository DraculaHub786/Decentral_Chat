"""Job execution: pick the engine chain, run it, verify, report fidelity."""
import logging
import time
from pathlib import Path
from typing import Dict, Optional

from . import jobs, routes_table, settings
from . import workspace as workspace_mod
from .engines import EngineFailed, EngineUnavailable, get_engine
from .fidelity import TIER_C, build_warnings
from .progress import ProgressReporter

logger = logging.getLogger(__name__)


class DispatchError(Exception):
    """A job could not be completed. Carries the API error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _split_ext(filename: str) -> str:
    name = workspace_mod.sanitize_filename(filename or "upload.bin")
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


async def run_job(
    job: jobs.Job,
    filename: str,
    payload: bytes,
    target_ext: str,
    options: Optional[Dict[str, object]] = None,
) -> workspace_mod.Workspace:
    """Convert ``payload`` and return the populated workspace.

    The workspace is created here and only here: ``workspace.create`` wipes an
    existing directory for the same job id, so pre-staging the upload under that
    id and then creating the workspace again would delete the upload.

    The caller owns the returned workspace and must clean it up once the result
    has been handed to the browser.
    """
    options = dict(options or {})
    target_ext = target_ext.lower().lstrip(".")
    source_name = workspace_mod.sanitize_filename(filename or "upload.bin")
    source_ext = _split_ext(source_name)

    route = routes_table.lookup(source_ext, target_ext)
    if route is None:
        declared = routes_table.lookup_unavailable(source_ext, target_ext)
        if declared is not None:
            raise DispatchError(
                "E_ENGINE_UNAVAILABLE",
                f"{declared.engines[0]} is not installed on this server, so "
                f"{source_ext.upper()} to {target_ext.upper()} is unavailable.",
            )
        raise DispatchError(
            "E_UNSUPPORTED",
            f"{source_ext.upper()} to {target_ext.upper()} is not a supported conversion.",
        )

    if len(payload) > settings.CONVERTER_LIMITS_MAX_BYTES:
        raise DispatchError("E_TOO_LARGE", "")

    requested = str(options.get("engine") or "").strip().lower()
    chain = list(route.engines)
    if requested and requested in chain:
        chain = [requested] + [name for name in chain if name != requested]

    ws = workspace_mod.create(job.job_id)
    source_path = ws.input_dir / source_name
    source_path.write_bytes(payload)

    stem = source_name.rsplit(".", 1)[0] or "converted"
    dest = ws.output_path(f"{stem}.{target_ext}")

    job.state = jobs.RUNNING
    job.stage = jobs.STAGE_PROBING
    job.tier = route.tier
    job.percent = None
    job.touch()

    last_error = None
    for engine_name in chain:
        try:
            engine = get_engine(engine_name)
        except EngineUnavailable as err:
            last_error = err
            continue
        if not engine.available:
            last_error = EngineUnavailable(f"{engine_name} is not installed")
            continue

        job.engine = engine_name
        job.stage = jobs.STAGE_CONVERTING
        job.touch()
        logger.info("Job %s: %s -> %s via %s",
                    job.job_id, source_ext, target_ext, engine_name)

        # The reporter is injected here rather than by the HTTP handler: the
        # handler's options are serialised into the staged job.json and re-read
        # by the worker, and a bound method is not JSON-serialisable.
        engine_options = dict(options)
        engine_options["_progress"] = ProgressReporter(job)

        try:
            async with jobs.global_semaphore():
                async with jobs.engine_semaphore(engine_name):
                    output = await engine.convert(
                        source_path, target_ext, dest, engine_options)
        except (EngineFailed, EngineUnavailable) as err:
            logger.warning("Job %s: engine %s failed: %s",
                           job.job_id, engine_name, err)
            last_error = err
            continue
        except Exception as err:  # defensive: never leak a 500 to the client
            logger.exception("Job %s: unexpected engine error", job.job_id)
            last_error = err
            continue

        job.stage = jobs.STAGE_VERIFYING
        job.touch()

        report = build_warnings(
            source_ext=source_ext,
            target_ext=target_ext,
            tier=route.tier,
        )
        for message in output.warnings:
            report.add(message)

        job.warnings = report.warnings
        job.result_files = [p.name for p in output.files]
        job.result_name = dest.name
        job.percent = 100
        job.state = jobs.DONE
        # The download window starts now and is shorter than the job TTL.
        job.result_token_expires_at = (
            time.time() + settings.CONVERTER_RESULT_TOKEN_TTL_SECONDS
        )
        job.touch()

        _prune_scratch(ws)
        return ws

    job.state = jobs.FAILED
    job.error_code = "E_VERIFY_FAILED" if route.tier == TIER_C else "E_CORRUPT"
    job.error_message = str(last_error or "No engine could perform this conversion")
    job.touch()
    ws.cleanup()
    raise DispatchError(job.error_code, job.error_message)


def _prune_scratch(ws: workspace_mod.Workspace) -> None:
    """Delete everything in the job tree that is not a result file."""
    import shutil

    output_dir = ws.output_dir
    for entry in list(ws.root.iterdir()):
        if entry == output_dir:
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            try:
                entry.unlink()
            except OSError:
                pass
