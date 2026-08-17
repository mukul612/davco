"""
Lightweight in-process job manager -- a ThreadPoolExecutor plus an
in-memory status dict. This is intentionally simple: the app serves ~4
concurrent Quality Engineering users, so there's no need for Redis/Celery/
a message broker. Each job is fully isolated in its own
`jobs/<uuid4-hex>/` directory (input/work/output), so concurrent jobs
never share a working file.

If this ever needs to scale beyond one process (e.g. multiple server
instances behind a load balancer), replace `_STATE` with a shared store
(e.g. a small SQLite table or Redis) and swap the ThreadPoolExecutor for a
real queue -- `process_layout()` itself doesn't know or care how it's
invoked, so that swap wouldn't touch the pipeline/engine code at all.
"""
import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import JOBS_DIR, JOB_RETENTION_HOURS
from app.models.schemas import JobState, LayoutType, Stage
from app.services import security
from app.services.pipeline import process_layout, PipelineError
from app.services.validation import ValidationError

logger = logging.getLogger("dimlayout.jobs")

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dimlayout-job")
_LOCK = threading.Lock()
_STATE: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    job_id: str
    state: JobState
    stage: Stage
    original_filename: str
    layout_type: LayoutType
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    error: Optional[str] = None
    result: Optional[dict] = None


def _persist(job_id: str) -> None:
    """Best-effort durability: write current status to disk so it can be
    inspected (or, later, reloaded) outside the in-memory dict."""
    rec = _STATE.get(job_id)
    if not rec:
        return
    status_path = JOBS_DIR / job_id / "logs" / "status.json"
    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(_public_view(rec), f, default=str, indent=2)
    except OSError:
        logger.exception("Failed to persist status for job %s", job_id)


def _update(job_id: str, **kwargs) -> None:
    with _LOCK:
        rec = _STATE[job_id]
        for k, v in kwargs.items():
            setattr(rec, k, v)
        rec.updated_at = _now()
    _persist(job_id)


def _public_view(rec: JobRecord) -> dict:
    return {
        "job_id": rec.job_id,
        "state": rec.state.value,
        "stage": rec.stage.value,
        "error": rec.error,
        "original_filename": rec.original_filename,
        "layout_type": rec.layout_type.value,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
        "result": rec.result,
    }


def get_job(job_id: str) -> Optional[dict]:
    with _LOCK:
        rec = _STATE.get(job_id)
        return _public_view(rec) if rec else None


def job_dir(job_id: str) -> Path:
    return security.safe_job_path(JOBS_DIR, job_id)


def _run_job(job_id: str) -> None:
    rec_dir = job_dir(job_id)
    pdf_path = rec_dir / "input" / "drawing.pdf"

    with _LOCK:
        layout_type = _STATE[job_id].layout_type

    logger.info(
        "job %s: starting (layout=%s, file=%s)",
        job_id, layout_type.value, _STATE[job_id].original_filename,
    )
    started = time.monotonic()
    try:
        _update(job_id, state=JobState.running, stage=Stage.analyzing)

        def on_stage(s: Stage):
            _update(job_id, stage=s)

        result = process_layout(pdf_path, layout_type, rec_dir, on_stage=on_stage)

        result_public = {
            "part_number": result["part_number"],
            "revision": result["revision"],
            "layout_type": layout_type.value,
            "customer": result["customer"],
            "customer_part_number": result["customer_part_number"],
            "characteristics_count": result["characteristics_count"],
            "warnings": result["warnings"],
            "has_review_log": result["review_log_path"] is not None,
            "files": {
                "ballooned_pdf": result["ballooned_pdf_path"].name,
                "excel": result["excel_path"].name,
                "review_log": result["review_log_path"].name if result["review_log_path"] else None,
            },
        }
        _update(job_id, state=JobState.complete, stage=Stage.complete, result=result_public)
        elapsed = time.monotonic() - started
        logger.info(
            "job %s: complete in %.1fs (%d characteristics, %d warning(s))",
            job_id, elapsed, result["characteristics_count"], len(result["warnings"]),
        )
    except (PipelineError, ValidationError) as e:
        logger.warning("job %s: failed - %s", job_id, e)
        _update(job_id, state=JobState.failed, stage=Stage.failed, error=str(e))
    except Exception:
        logger.exception("job %s: unexpected error", job_id)
        _update(job_id, state=JobState.failed, stage=Stage.failed,
                 error="An unexpected error occurred while processing this drawing. See server logs.")


def create_job(original_filename: str, content: bytes, layout_type: LayoutType) -> str:
    job_id = security.new_job_id()
    rec_dir = job_dir(job_id)
    (rec_dir / "input").mkdir(parents=True, exist_ok=True)
    (rec_dir / "output").mkdir(parents=True, exist_ok=True)
    (rec_dir / "logs").mkdir(parents=True, exist_ok=True)

    safe_name = security.sanitize_filename(original_filename, fallback="drawing.pdf")
    (rec_dir / "input" / "drawing.pdf").write_bytes(content)
    (rec_dir / "logs" / "original_filename.txt").write_text(safe_name, encoding="utf-8")

    with _LOCK:
        _STATE[job_id] = JobRecord(
            job_id=job_id,
            state=JobState.pending,
            stage=Stage.queued,
            original_filename=safe_name,
            layout_type=layout_type,
        )
    _persist(job_id)

    logger.info("job %s: created (file=%s, layout=%s)", job_id, safe_name, layout_type.value)
    _EXECUTOR.submit(_run_job, job_id)
    return job_id


def cleanup_expired_jobs(retention_hours: float = JOB_RETENTION_HOURS) -> int:
    """Delete job directories (and their in-memory records) older than the
    retention window. Safe to call repeatedly / concurrently. Returns the
    number of jobs removed."""
    cutoff = time.time() - retention_hours * 3600
    removed = 0
    if not JOBS_DIR.is_dir():
        return 0
    for entry in JOBS_DIR.iterdir():
        if not entry.is_dir() or not security.is_valid_job_id(entry.name):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue
        with _LOCK:
            in_progress = _STATE.get(entry.name)
            if in_progress and in_progress.state in (JobState.pending, JobState.running):
                continue  # never delete a job that's still working
        try:
            shutil.rmtree(entry, ignore_errors=True)
            with _LOCK:
                _STATE.pop(entry.name, None)
            removed += 1
            logger.info("cleanup: removed expired job %s", entry.name)
        except OSError:
            logger.exception("cleanup: failed to remove job %s", entry.name)
    return removed


def start_cleanup_thread(interval_minutes: float) -> None:
    def loop():
        while True:
            time.sleep(interval_minutes * 60)
            try:
                cleanup_expired_jobs()
            except Exception:
                logger.exception("cleanup thread: unexpected error")

    t = threading.Thread(target=loop, name="dimlayout-cleanup", daemon=True)
    t.start()
