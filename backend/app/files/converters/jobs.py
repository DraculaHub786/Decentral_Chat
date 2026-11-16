"""Job model, state machine and scheduling (plan §3.5, §3.6).

A job record holds identity, state and progress only — no file paths, no
plaintext. The bytes live in the workspace, which the janitor reaps.
"""
import asyncio
import datetime
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import settings

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
EXPIRED = "expired"

TERMINAL_STATES = {DONE, FAILED, CANCELLED, EXPIRED}

STAGE_PROBING = "probing"
STAGE_CONVERTING = "converting"
STAGE_VERIFYING = "verifying"


@dataclass
class Job:
    """Everything the status endpoint is allowed to reveal."""

    job_id: str
    user_id: str
    source_ext: str
    target_ext: str
    state: str = QUEUED
    stage: str = STAGE_PROBING
    percent: Optional[int] = None
    engine: str = ""
    tier: str = ""
    warnings: List[str] = field(default_factory=list)
    error_code: str = ""
    error_message: str = ""
    result_name: str = ""
    result_token: str = ""
    result_files: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    # Wall-clock deadline; the janitor and every read honour it.
    expires_at: float = 0.0
    # Result tokens expire sooner than the job record (CONVERTER_RESULT_TOKEN_TTL_SECONDS).
    result_token_expires_at: float = 0.0
    task: Optional[asyncio.Task] = field(default=None, repr=False)
    cancelled: bool = False
    # Batch membership, set only by the batch endpoint. Empty for single jobs.
    batch_id: str = ""
    source_name: str = ""
    # One download token for the whole batch: the ZIP is a single deliverable,
    # so per-job tokens cannot all be required (they differ per member).
    batch_token: str = ""

    def touch(self) -> None:
        self.updated_at = datetime.datetime.now(datetime.UTC).isoformat()

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    @property
    def result_token_valid(self) -> bool:
        """The download token is only good for a short window.

        Without this, the token stayed live for the whole job TTL (15 min by
        default) even though it is meant to be redeemed seconds after the job
        finishes. A leaked status payload gave a 15-minute download window.
        """
        if not self.result_token:
            return False
        if self.result_token_expires_at <= 0:
            return True
        return time.time() <= self.result_token_expires_at

    def as_status(self) -> dict:
        payload = {
            "job_id": self.job_id,
            "state": self.state,
            "stage": self.stage,
            "percent": self.percent,
            "engine": self.engine,
            "tier": self.tier,
            "warnings": list(self.warnings),
            "queue_position": 0,
        }
        if self.state == DONE:
            payload["result_token"] = self.result_token
            payload["result_name"] = self.result_name
            payload["result_files"] = list(self.result_files)
            payload["multi_file"] = len(self.result_files) > 1
        if self.state == FAILED:
            payload["error"] = self.error_message
            payload["code"] = self.error_code
        return payload


class JobStore:
    """In-process job registry keyed by job id, scoped per user."""

    MAX_PER_USER = 200

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._user_jobs: Dict[str, List[str]] = {}
        # Submission timestamps per user, pruned to a rolling hour.
        self._user_submissions: Dict[str, List[float]] = {}

    def create(self, user_id: str, source_ext: str, target_ext: str,
               tier: str = "") -> Job:
        job = Job(
            job_id=uuid.uuid4().hex,
            user_id=user_id,
            source_ext=source_ext,
            target_ext=target_ext,
            tier=tier,
            result_token=secrets.token_urlsafe(32),
            expires_at=time.time() + settings.CONVERTER_JOB_TTL_SECONDS,
        )
        job.touch()
        job.created_at = job.updated_at
        self._jobs[job.job_id] = job
        self._user_jobs.setdefault(user_id, []).append(job.job_id)
        self._trim(user_id)
        return job

    def _trim(self, user_id: str) -> None:
        """Bound memory: drop the oldest finished jobs past the per-user cap."""
        ids = self._user_jobs.get(user_id, [])
        excess = len(ids) - self.MAX_PER_USER
        if excess <= 0:
            return
        # Oldest first; only finished jobs are droppable, and only as many as
        # are needed. Dropping more would erase results the client is polling.
        surviving = []
        for job_id in ids:
            job = self._jobs.get(job_id)
            if excess > 0 and job is not None and job.state in TERMINAL_STATES:
                self._jobs.pop(job_id, None)
                excess -= 1
                continue
            surviving.append(job_id)
        self._user_jobs[user_id] = surviving

    def get(self, job_id: str) -> Optional[Job]:
        job = self._jobs.get(job_id)
        if job is not None and job.is_expired and job.state not in TERMINAL_STATES:
            job.state = EXPIRED
            job.touch()
        return job

    def get_owned(self, job_id: str, user_id: str) -> Optional[Job]:
        """Ownership is enforced here, never in a handler (fixes D-05)."""
        job = self.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    def _recent_submissions(self, user_id: str) -> List[float]:
        """Submission times inside the last hour, oldest first."""
        cutoff = time.time() - 3600
        recent = [t for t in self._user_submissions.get(user_id, []) if t > cutoff]
        if recent:
            self._user_submissions[user_id] = recent
        else:
            self._user_submissions.pop(user_id, None)
        return recent

    def hourly_count(self, user_id: str) -> int:
        """Conversions this user started in the last rolling hour."""
        return len(self._recent_submissions(user_id))

    def over_hourly_cap(self, user_id: str) -> bool:
        """True when the user has spent their hourly allowance.

        CONVERTER_USER_HOURLY_CAP was declared but never enforced, so a single
        account could occupy the worker pool indefinitely. The cap is checked
        here rather than in the handlers so batch jobs count as well.
        """
        cap = settings.CONVERTER_USER_HOURLY_CAP
        if cap <= 0:
            return False
        return self.hourly_count(user_id) >= cap

    def record_submission(self, user_id: str) -> None:
        self._recent_submissions(user_id)
        self._user_submissions.setdefault(user_id, []).append(time.time())

    def running_count(self, user_id: str) -> int:
        return sum(
            1 for job_id in self._user_jobs.get(user_id, [])
            if (job := self._jobs.get(job_id)) is not None
            and job.state in (QUEUED, RUNNING)
        )

    def iter_user_jobs(self, user_id: str) -> List[Job]:
        """Live job records for one user, newest last."""
        out = []
        for job_id in self._user_jobs.get(user_id, []):
            job = self._jobs.get(job_id)
            if job is not None:
                out.append(job)
        return out

    def purge(self, job_id: str) -> None:
        job = self._jobs.pop(job_id, None)
        if job is None:
            return
        # Previously only _jobs was cleaned, so _user_jobs grew forever with
        # ids that no longer resolved - a slow leak on a long-lived process.
        owned = self._user_jobs.get(job.user_id)
        if owned and job_id in owned:
            owned.remove(job_id)
            if not owned:
                self._user_jobs.pop(job.user_id, None)
        if job.task is not None and not job.task.done():
            job.task.cancel()

    def sweep(self) -> int:
        """Drop expired finished records. Called by the janitor."""
        expired = [
            job_id for job_id, job in self._jobs.items()
            if job.state in TERMINAL_STATES
            and job.expires_at > 0 and time.time() > job.expires_at
        ]
        for job_id in expired:
            self.purge(job_id)
        return len(expired)


STORE = JobStore()

# Global + per-engine concurrency caps (§3.6).
_global_sem: Optional[asyncio.Semaphore] = None
_engine_sems: Dict[str, asyncio.Semaphore] = {}


def global_semaphore() -> asyncio.Semaphore:
    global _global_sem
    if _global_sem is None:
        _global_sem = asyncio.Semaphore(settings.CONVERTER_MAX_CONCURRENT)
    return _global_sem


def engine_semaphore(engine_name: str) -> asyncio.Semaphore:
    if engine_name not in _engine_sems:
        from .routes_table import engine_concurrency_cap
        _engine_sems[engine_name] = asyncio.Semaphore(engine_concurrency_cap(engine_name))
    return _engine_sems[engine_name]


# ---------------------------------------------------------------------------
# Staging: persist a request beside its job so any runner can pick it up.
# Only the job id crosses the queue; bytes stay on local disk under a
# directory the janitor reaps, so no plaintext ever enters Redis.
# ---------------------------------------------------------------------------

JOB_META = "job.json"


def stage_upload(job: Job, filename: str, payload: bytes,
                 target_ext: str, options: dict) -> None:
    """Write the upload and its metadata into the job workspace."""
    import json

    from . import workspace as workspace_mod

    ws = workspace_mod.create(job.job_id)
    safe_name = workspace_mod.sanitize_filename(filename)
    (ws.input_dir / safe_name).write_bytes(payload)
    (ws.root / JOB_META).write_text(
        json.dumps({
            "job_id": job.job_id,
            "user_id": job.user_id,
            "filename": safe_name,
            "target_ext": target_ext,
            "source_ext": job.source_ext,
            "tier": job.tier,
            "options": options or {},
        }),
        encoding="utf-8",
    )


def load_staged(job_id: str) -> dict:
    """Re-read a staged job. Raises if the workspace was already reaped."""
    import json

    root = settings.CONVERTER_WORK_DIR / job_id
    meta_path = root / JOB_META
    if not meta_path.exists():
        raise FileNotFoundError("staged job " + job_id + " is gone")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    filename = meta["filename"]
    return {
        "filename": filename,
        "payload": (root / "in" / filename).read_bytes(),
        "target_ext": meta["target_ext"],
        "options": meta.get("options") or {},
    }


def wipe_workspace(job_id: str) -> None:
    from . import workspace as workspace_mod

    workspace_mod.Workspace(
        job_id, settings.CONVERTER_WORK_DIR / job_id
    ).cleanup()


async def run_one(job: Job) -> None:
    """Execute one queued job and record the outcome. Never raises."""
    from . import dispatch

    try:
        staged = load_staged(job.job_id)
    except FileNotFoundError as err:
        logger.warning("Job %s: %s", job.job_id, err)
        job.state = FAILED
        job.error_code = "E_TIMEOUT"
        job.error_message = "The upload expired before it could be converted."
        job.touch()
        return
    except Exception:
        logger.exception("Job %s: could not reload the staged upload", job.job_id)
        job.state = FAILED
        job.error_code = "E_CORRUPT"
        job.error_message = "The upload could not be read back."
        job.touch()
        return

    try:
        await dispatch.run_job(
            job, staged["filename"], staged["payload"],
            staged["target_ext"], staged["options"],
        )
    except dispatch.DispatchError as err:
        job.state = FAILED
        job.error_code = err.code
        job.error_message = err.message or "Conversion failed."
        job.touch()
        wipe_workspace(job.job_id)
    except asyncio.CancelledError:
        job.state = CANCELLED
        job.touch()
        wipe_workspace(job.job_id)
        raise
    except Exception:
        logger.exception("Job %s crashed in the runner", job.job_id)
        job.state = FAILED
        job.error_code = "E_VERIFY_FAILED"
        job.error_message = "The conversion failed unexpectedly."
        job.touch()
        wipe_workspace(job.job_id)


async def worker_loop(name: str, q, store: Optional["JobStore"] = None) -> None:
    """Pull ids forever and run them. Cancellation is the shutdown signal."""
    store = store or STORE
    logger.info("Converter worker %s started (queue=%s)", name, q.name)
    while True:
        try:
            job_id = await q.get(timeout=5.0)
            if job_id is None:
                continue
            job = store.get(job_id)
            if job is None:
                logger.warning("Worker %s: job %s is no longer known", name, job_id)
                wipe_workspace(job_id)
                continue
            if job.state not in (QUEUED, RUNNING):
                continue
            job.stage = STAGE_PROBING
            job.touch()
            job.task = asyncio.current_task()
            await run_one(job)
            job.task = None
        except asyncio.CancelledError:
            logger.info("Converter worker %s stopping", name)
            raise
        except Exception:
            logger.exception("Worker %s: loop iteration failed", name)
            await asyncio.sleep(1)


def worker_count() -> int:
    """How many inline workers to start. 0 means an external worker owns it."""
    import os
    raw = os.getenv("CONVERTER_INLINE_WORKERS")
    if raw is None:
        return settings.CONVERTER_MAX_CONCURRENT
    try:
        return max(0, int(raw))
    except ValueError:
        return settings.CONVERTER_MAX_CONCURRENT


async def enqueue_and_run(job: Job, filename: str, payload: bytes,
                          target_ext: str, options: dict, q=None) -> None:
    """Stage the upload and hand the job id to the queue.

    Called as the job's own task by the upload handler. It returns as soon as
    the job is queued — the conversion itself runs inside a worker, which
    re-points ``job.task`` at its own task so cancel still reaches it.
    """
    if q is None:
        from . import queue as queue_mod
        q = queue_mod.get_queue()
    try:
        stage_upload(job, filename, payload, target_ext, options)
        await q.put(job.job_id)
    except Exception:
        logger.exception("Job %s could not be queued", job.job_id)
        wipe_workspace(job.job_id)
        if job.state not in TERMINAL_STATES:
            job.state = FAILED
            job.error_code = "E_ENGINE_UNAVAILABLE"
            job.error_message = "The converter queue is unavailable."
            job.touch()


def start_inline_workers(q, store=None) -> list:
    """Start the inline pool. Returns the tasks so shutdown can cancel them."""
    tasks = []
    for index in range(worker_count()):
        tasks.append(asyncio.create_task(
            worker_loop("inline-" + str(index), q, store),
            name="converter-worker-" + str(index),
        ))
    if tasks:
        logger.info("Started %d inline converter worker(s)", len(tasks))
    else:
        logger.info("Inline workers disabled; expecting an external worker")
    return tasks
