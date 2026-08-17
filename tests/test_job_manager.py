import time

import pytest

from app.models.schemas import LayoutType, Stage
from app.services import job_manager


def _fake_process_layout(pdf_path, layout_type, job_dir, on_stage=None):
    """A fast, deterministic stand-in for the real pipeline (which calls
    Claude) -- job_manager doesn't know or care what process_layout does,
    so this exercises exactly the same orchestration code the real
    pipeline runs through."""
    if on_stage:
        on_stage(Stage.analyzing)
        on_stage(Stage.identifying)
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_out = output_dir / "TEST-001_Ballooned.pdf"
    pdf_out.write_bytes(b"%PDF-fake")
    excel_out = output_dir / "TEST-001_Supplier_Layout.xlsx"
    excel_out.write_bytes(b"fake-excel")
    return {
        "ballooned_pdf_path": pdf_out,
        "ballooned_png_path": None,
        "excel_path": excel_out,
        "review_log_path": None,
        "part_number": "TEST-001",
        "revision": "A",
        "customer": None,
        "customer_part_number": None,
        "characteristics_count": 3,
        "total_balloons": 3,
        "warnings": [],
    }


@pytest.fixture(autouse=True)
def isolated_jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(job_manager, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(job_manager, "process_layout", _fake_process_layout)
    yield tmp_path


def _wait_for(job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rec = job_manager.get_job(job_id)
        if rec["state"] in ("complete", "failed"):
            return rec
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish in time")


def test_create_job_produces_isolated_directory(isolated_jobs_dir):
    job_id = job_manager.create_job("my drawing.pdf", b"%PDF-1.4 fake", LayoutType.supplier)
    job_dir = job_manager.job_dir(job_id)
    assert job_dir.is_dir()
    assert (job_dir / "input" / "drawing.pdf").is_file()
    assert (job_dir / "output").is_dir()
    assert (job_dir / "logs").is_dir()
    _wait_for(job_id)


def test_two_jobs_get_different_directories(isolated_jobs_dir):
    id1 = job_manager.create_job("a.pdf", b"%PDF-1", LayoutType.supplier)
    id2 = job_manager.create_job("a.pdf", b"%PDF-1", LayoutType.customer)  # same filename on purpose
    assert id1 != id2
    assert job_manager.job_dir(id1) != job_manager.job_dir(id2)
    _wait_for(id1)
    _wait_for(id2)


def test_uploaded_filename_is_sanitized_on_disk(isolated_jobs_dir):
    job_id = job_manager.create_job("../../evil<>.pdf", b"%PDF-1", LayoutType.supplier)
    rec = _wait_for(job_id)
    assert rec["original_filename"] == "evil__.pdf"
    assert ".." not in rec["original_filename"]


def test_job_completes_and_exposes_result(isolated_jobs_dir):
    job_id = job_manager.create_job("drawing.pdf", b"%PDF-1", LayoutType.supplier)
    rec = _wait_for(job_id)
    assert rec["state"] == "complete"
    assert rec["result"]["part_number"] == "TEST-001"
    assert rec["result"]["files"]["ballooned_pdf"] == "TEST-001_Ballooned.pdf"


def test_failed_pipeline_marks_job_failed(isolated_jobs_dir, monkeypatch):
    def boom(pdf_path, layout_type, job_dir, on_stage=None):
        from app.services.pipeline import PipelineError
        raise PipelineError("synthetic failure for test")

    monkeypatch.setattr(job_manager, "process_layout", boom)
    job_id = job_manager.create_job("drawing.pdf", b"%PDF-1", LayoutType.supplier)
    rec = _wait_for(job_id)
    assert rec["state"] == "failed"
    assert "synthetic failure" in rec["error"]


def test_cleanup_removes_old_jobs_but_not_running_ones(isolated_jobs_dir, monkeypatch):
    old_job = job_manager.create_job("old.pdf", b"%PDF-1", LayoutType.supplier)
    _wait_for(old_job)
    job_dir = job_manager.job_dir(old_job)
    old_time = time.time() - 999999
    import os
    os.utime(job_dir, (old_time, old_time))

    removed = job_manager.cleanup_expired_jobs(retention_hours=24)
    assert removed >= 1
    assert not job_dir.is_dir()
    assert job_manager.get_job(old_job) is None


def test_cleanup_never_deletes_a_running_job(isolated_jobs_dir, monkeypatch):
    import threading
    release = threading.Event()

    def slow_process(pdf_path, layout_type, job_dir, on_stage=None):
        release.wait(timeout=5)
        return _fake_process_layout(pdf_path, layout_type, job_dir, on_stage)

    monkeypatch.setattr(job_manager, "process_layout", slow_process)
    job_id = job_manager.create_job("slow.pdf", b"%PDF-1", LayoutType.supplier)
    try:
        job_dir = job_manager.job_dir(job_id)
        import os
        old_time = time.time() - 999999
        os.utime(job_dir, (old_time, old_time))

        removed = job_manager.cleanup_expired_jobs(retention_hours=24)
        assert job_dir.is_dir()  # must still exist -- job was still running
    finally:
        release.set()
        _wait_for(job_id)
