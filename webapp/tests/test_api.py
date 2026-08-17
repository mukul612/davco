import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import Stage
from app.services import job_manager


def _fake_process_layout(pdf_path, layout_type, job_dir, on_stage=None):
    if on_stage:
        on_stage(Stage.analyzing)
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_out = output_dir / "TEST-001_Ballooned.pdf"
    pdf_out.write_bytes(b"%PDF-fake-content")
    excel_out = output_dir / f"TEST-001_{layout_type.value.capitalize()}_Layout.xlsx"
    excel_out.write_bytes(b"fake-excel-content")
    review = output_dir / "TEST-001_Review.txt"
    review.write_text("- something to double check", encoding="utf-8")
    return {
        "ballooned_pdf_path": pdf_out,
        "ballooned_png_path": None,
        "excel_path": excel_out,
        "review_log_path": review,
        "part_number": "TEST-001",
        "revision": "A",
        "customer": "NAVISTAR" if layout_type.value == "customer" else None,
        "customer_part_number": "999" if layout_type.value == "customer" else None,
        "characteristics_count": 2,
        "total_balloons": 3,
        "warnings": ["something to double check"],
    }


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_manager, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(job_manager, "process_layout", _fake_process_layout)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _wait_complete(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        data = r.json()
        if data["state"] in ("complete", "failed"):
            return data
        time.sleep(0.05)
    raise TimeoutError("job did not complete in time")


def test_index_page_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Dimensional Layout Generator" in r.text


def test_reject_non_pdf_upload(client, not_a_pdf_bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("notes.txt", not_a_pdf_bytes, "text/plain")},
        data={"layout_type": "supplier"},
    )
    assert r.status_code == 400
    assert "pdf" in r.json()["detail"].lower()


def test_reject_empty_pdf(client, empty_pdf_bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("empty.pdf", empty_pdf_bytes, "application/pdf")},
        data={"layout_type": "supplier"},
    )
    assert r.status_code == 400


def test_supplier_job_end_to_end(client, sample_pdf_bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("drawing.pdf", sample_pdf_bytes, "application/pdf")},
        data={"layout_type": "supplier"},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    data = _wait_complete(client, job_id)
    assert data["state"] == "complete"
    assert data["layout_type"] == "supplier"
    assert data["result"]["part_number"] == "TEST-001"
    assert data["result"]["has_review_log"] is True

    pdf_resp = client.get(f"/api/jobs/{job_id}/ballooned-pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")

    excel_resp = client.get(f"/api/jobs/{job_id}/excel")
    assert excel_resp.status_code == 200

    review_resp = client.get(f"/api/jobs/{job_id}/review-log")
    assert review_resp.status_code == 200

    zip_resp = client.get(f"/api/jobs/{job_id}/download-all")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"] == "application/zip"


def test_customer_job_end_to_end(client, sample_pdf_bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("drawing.pdf", sample_pdf_bytes, "application/pdf")},
        data={"layout_type": "customer"},
    )
    job_id = r.json()["job_id"]
    data = _wait_complete(client, job_id)
    assert data["layout_type"] == "customer"
    assert data["result"]["customer"] == "NAVISTAR"
    assert data["result"]["customer_part_number"] == "999"


def test_unknown_job_returns_404(client):
    r = client.get("/api/jobs/deadbeefdeadbeefdeadbeefdeadbeef")
    assert r.status_code == 404


def test_malformed_job_id_returns_404_not_500(client):
    r = client.get("/api/jobs/../../etc/passwd")
    assert r.status_code in (404, 307)  # starlette may redirect-normalize; never a 500


def test_download_before_complete_returns_409(client, sample_pdf_bytes, monkeypatch):
    import threading
    release = threading.Event()

    def slow(pdf_path, layout_type, job_dir, on_stage=None):
        release.wait(timeout=5)
        return _fake_process_layout(pdf_path, layout_type, job_dir, on_stage)

    monkeypatch.setattr(job_manager, "process_layout", slow)
    r = client.post(
        "/api/jobs",
        files={"file": ("drawing.pdf", sample_pdf_bytes, "application/pdf")},
        data={"layout_type": "supplier"},
    )
    job_id = r.json()["job_id"]
    try:
        resp = client.get(f"/api/jobs/{job_id}/ballooned-pdf")
        assert resp.status_code == 409
    finally:
        release.set()
        _wait_complete(client, job_id)


def test_missing_layout_type_is_rejected(client, sample_pdf_bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("drawing.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 422  # FastAPI validation error, not a crash
