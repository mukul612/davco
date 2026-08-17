"""
JSON/file API routes. The browser only ever talks to these -- it never
calls Claude or touches the filesystem directly.
"""
import logging
import zipfile
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.models.schemas import JobStatusResponse, LayoutType, ResultMetadata
from app.services import job_manager, security
from app.services.auth import require_auth
from app.services.validation import validate_upload, ValidationError

logger = logging.getLogger("dimlayout.api")

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@router.post("/jobs")
async def create_job(
    file: UploadFile = File(...),
    layout_type: LayoutType = Form(...),
):
    content = await file.read()
    try:
        validate_upload(file.filename or "", content)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id = job_manager.create_job(file.filename or "drawing.pdf", content, layout_type)
    return {"job_id": job_id}


def _job_or_404(job_id: str) -> dict:
    if not security.is_valid_job_id(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    rec = job_manager.get_job(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Job not found.")
    return rec


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    rec = _job_or_404(job_id)
    result = None
    if rec.get("result"):
        r = rec["result"]
        result = ResultMetadata(
            part_number=r.get("part_number"),
            revision=r.get("revision"),
            layout_type=r.get("layout_type"),
            customer=r.get("customer"),
            customer_part_number=r.get("customer_part_number"),
            characteristics_count=r.get("characteristics_count", 0),
            warnings=r.get("warnings", []),
            has_review_log=r.get("has_review_log", False),
        )
    return JobStatusResponse(
        job_id=rec["job_id"],
        state=rec["state"],
        stage=rec["stage"],
        error=rec["error"],
        original_filename=rec["original_filename"],
        layout_type=rec["layout_type"],
        created_at=rec["created_at"],
        updated_at=rec["updated_at"],
        result=result,
    )


def _output_file_or_404(job_id: str, filename_key: str) -> tuple[dict, str]:
    rec = _job_or_404(job_id)
    if rec["state"] != "complete" or not rec.get("result"):
        raise HTTPException(status_code=409, detail="Job is not complete yet.")
    filename = rec["result"]["files"].get(filename_key)
    if not filename:
        raise HTTPException(status_code=404, detail="Requested file was not generated for this job.")
    return rec, filename


@router.get("/jobs/{job_id}/ballooned-pdf")
async def download_ballooned_pdf(job_id: str):
    rec, filename = _output_file_or_404(job_id, "ballooned_pdf")
    path = security.safe_download_path(job_manager.job_dir(job_id) / "output", filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File no longer available (it may have expired).")
    return FileResponse(path, filename=filename, media_type="application/pdf")


@router.get("/jobs/{job_id}/excel")
async def download_excel(job_id: str):
    rec, filename = _output_file_or_404(job_id, "excel")
    path = security.safe_download_path(job_manager.job_dir(job_id) / "output", filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File no longer available (it may have expired).")
    return FileResponse(
        path, filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/jobs/{job_id}/review-log")
async def download_review_log(job_id: str):
    rec, filename = _output_file_or_404(job_id, "review_log")
    path = security.safe_download_path(job_manager.job_dir(job_id) / "output", filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File no longer available (it may have expired).")
    return FileResponse(path, filename=filename, media_type="text/plain")


@router.get("/jobs/{job_id}/download-all")
async def download_all(job_id: str):
    rec = _job_or_404(job_id)
    if rec["state"] != "complete" or not rec.get("result"):
        raise HTTPException(status_code=409, detail="Job is not complete yet.")

    output_dir = job_manager.job_dir(job_id) / "output"
    files = rec["result"]["files"]
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key in ("ballooned_pdf", "excel", "review_log"):
            name = files.get(key)
            if not name:
                continue
            path = security.safe_download_path(output_dir, name)
            if path.is_file():
                zf.write(path, arcname=name)
    buf.seek(0)

    base = (rec["result"].get("part_number") or "dimensional_layout").replace(" ", "_")
    zip_name = f"{base}_layout.zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
