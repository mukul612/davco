"""
Filename sanitization and path-safety helpers. Nothing here trusts a
user-supplied filename or job ID to be safe on its own.
"""
import re
import uuid
from pathlib import Path

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex


def new_job_id() -> str:
    return uuid.uuid4().hex


def is_valid_job_id(job_id: str) -> bool:
    return bool(_JOB_ID_RE.match(job_id or ""))


def sanitize_filename(name: str, fallback: str = "drawing") -> str:
    """Strip directory components and any character that isn't safe in a
    Windows/Unix filename. Never trust an uploaded filename as a path."""
    name = Path(name or "").name  # drop any directory component (../, C:\, etc.)
    name = _UNSAFE_CHARS.sub("_", name).strip(" .")
    if not name:
        name = fallback
    # Keep it reasonably short so downstream Excel/PDF filenames (which
    # append suffixes like "_Customer_Layout.xlsx") don't blow past
    # Windows' ~260 char path limit.
    stem, dot, ext = name.rpartition(".")
    if dot and len(stem) > 100:
        name = stem[:100] + dot + ext
    elif not dot and len(name) > 100:
        name = name[:100]
    return name


def safe_job_path(jobs_dir: Path, job_id: str) -> Path:
    """Resolve a job's directory, refusing anything that isn't a bare,
    well-formed job id (blocks path traversal via a crafted job_id)."""
    if not is_valid_job_id(job_id):
        raise ValueError(f"Invalid job id: {job_id!r}")
    jobs_dir = jobs_dir.resolve()
    candidate = (jobs_dir / job_id).resolve()
    if candidate.parent != jobs_dir:
        # Defense in depth -- should be unreachable given the regex above.
        raise ValueError("Resolved job path escapes the jobs directory.")
    return candidate


def safe_download_path(job_dir: Path, filename: str) -> Path:
    """Resolve a file inside a specific job's output directory, refusing
    anything that would escape it."""
    job_dir = job_dir.resolve()
    candidate = (job_dir / filename).resolve()
    if job_dir not in candidate.parents and candidate != job_dir:
        raise ValueError("Resolved download path escapes the job directory.")
    return candidate
