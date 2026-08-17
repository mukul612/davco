"""Pydantic models shared between the pipeline, job manager, and API routes."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class LayoutType(str, Enum):
    supplier = "supplier"
    customer = "customer"


class JobState(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


class Stage(str, Enum):
    queued = "Queued"
    analyzing = "Analyzing drawing..."
    identifying = "Identifying characteristics..."
    generating_balloons = "Generating balloons..."
    creating_supplier_layout = "Creating Supplier layout..."
    creating_customer_layout = "Creating Customer layout..."
    validating = "Validating files..."
    complete = "Complete"
    failed = "Failed"


class ResultMetadata(BaseModel):
    part_number: Optional[str] = None
    revision: Optional[str] = None
    layout_type: Optional[LayoutType] = None
    customer: Optional[str] = None
    customer_part_number: Optional[str] = None
    characteristics_count: int = 0
    warnings: list[str] = []
    has_review_log: bool = False


class JobStatusResponse(BaseModel):
    job_id: str
    state: JobState
    stage: Stage
    error: Optional[str] = None
    original_filename: Optional[str] = None
    layout_type: Optional[LayoutType] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    result: Optional[ResultMetadata] = None
