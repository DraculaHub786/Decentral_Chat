"""Per-job temp workspace with secure cleanup (plan §3.1, fixes D-12).

Plaintext exists only inside these directories and is destroyed when the job
ends. Nothing here is ever written to Redis, Firestore, or a permanent path.
"""
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import settings

logger = logging.getLogger(__name__)


@dataclass
class Workspace:
    """A single job's scratch directory: ``<work>/<job>/in`` and ``/out``."""

    job_id: str
    root: Path

    @property
    def input_dir(self) -> Path:
        return self.root / "in"

    @property
    def output_dir(self) -> Path:
        return self.root / "out"

    @property
    def temp_dir(self) -> Path:
        return self.root / "tmp"

    def input_path(self, filename: str) -> Path:
        return self.input_dir / sanitize_filename(filename)

    def output_path(self, filename: str) -> Path:
        return self.output_dir / sanitize_filename(filename)

    def list_outputs(self) -> list:
        if not self.output_dir.exists():
            return []
        return sorted(p for p in self.output_dir.iterdir() if p.is_file())

    def cleanup(self) -> None:
        """Destroy the whole job tree. Safe to call more than once."""
        shutil.rmtree(self.root, ignore_errors=True)


def sanitize_filename(name: str, fallback: str = "file") -> str:
    """Strip directory components and control characters from a filename."""
    if not name:
        return fallback
    base = os.path.basename(str(name).replace("\\", "/"))
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '/\\:*?"<>|')
    cleaned = cleaned.strip().strip(".")
    return cleaned or fallback


def package_outputs(ws: Workspace, archive_name: str = "converted.zip"):
    """Zip every result file into one archive. Returns the archive, or None.

    Used for the multi-file case (PDF -> one PNG per page), where the plan
    says the pages come back as a single ZIP rather than as the first page
    with the rest silently dropped.
    """
    import zipfile

    files = ws.list_outputs()
    if not files:
        return None

    archive = ws.output_dir / archive_name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for produced in files:
            if produced == archive:
                continue
            bundle.write(produced, arcname=produced.name)
    return archive


def create(job_id: Optional[str] = None) -> Workspace:
    """Create an isolated workspace tree for one job."""
    settings.ensure_work_dir()
    job_id = job_id or uuid.uuid4().hex
    root = settings.CONVERTER_WORK_DIR / job_id

    # A reused id must never inherit someone else's leftovers.
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    workspace = Workspace(job_id=job_id, root=root)
    for directory in (workspace.input_dir, workspace.output_dir, workspace.temp_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return workspace


def sweep_expired(max_age_seconds: Optional[int] = None) -> int:
    """Janitor: remove job directories older than the configured TTL."""
    import time

    work_dir = settings.CONVERTER_WORK_DIR
    if not work_dir.exists():
        return 0

    ttl = max_age_seconds or settings.CONVERTER_JOB_TTL_SECONDS
    now = time.time()
    removed = 0
    for entry in work_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            continue
        if age > ttl:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    if removed:
        logger.info("🧹 Janitor removed %d expired job directories", removed)
    return removed
