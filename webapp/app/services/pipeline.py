"""
Orchestrates one job through the existing dimensional-layout engine:
extract -> interpret (Claude) -> balloon -> fill Excel -> validate.

Every mechanical step calls the SAME unmodified functions the interactive
skill uses (see app/layout_engine). This module only sequences them, reports
stage progress, and assembles the result metadata the web UI displays. It
does not re-implement any ballooning/grouping/destination-routing rule.
"""
import json
import logging
import re
from pathlib import Path
from typing import Callable, Optional

from app.config import SUPPLIER_TEMPLATE, CUSTOMER_TEMPLATE
from app.layout_engine import extract_drawing, draw_balloons, fill_excel
from app.layout_engine.interpret import interpret_pages
from app.models.schemas import LayoutType, Stage
from app.services.validation import validate_outputs, file_hash, ValidationError
from app.services.security import sanitize_filename

logger = logging.getLogger("dimlayout.pipeline")

# A bare decimal number (e.g. "16.13", "409.7", ".43") is almost always a
# dimension value on these drawings. Bare integers ("1", "2", "12") are
# deliberately NOT matched -- those are exactly the BOM item numbers /
# revision-history row numbers the skill's rules say to exclude, so
# matching them here would flood this safety net with expected exclusions
# instead of real misses.
_DIMENSION_LIKE = re.compile(r"^-?\.?\d+\.\d+$|^-?\.\d+$")


def _find_orphaned_dimensions(pages: list[dict], callouts: list[dict]) -> list[str]:
    """Deterministic safety net, independent of the LLM's own self-reported
    warnings: flag any dimension-shaped value from the extraction that
    doesn't appear in ANY balloon's text. Interpretation is inherently
    imperfect (an LLM can silently drop a line the way a human proofreader
    can) -- this catches that failure mode instead of hiding it, per the
    rule that uncertain/possibly-missed content must surface for review,
    not be silently dropped."""
    all_text = " ␟ ".join(c.get("text", "") for c in callouts)
    missed = []
    for page in pages:
        for ln in page.get("lines_reading_order", []):
            text = ln["text"].strip()
            if not _DIMENSION_LIKE.match(text):
                continue
            if text in all_text:
                continue
            missed.append(f"{text} (near x={ln['bbox'][0]:.0f}, y={ln['bbox'][1]:.0f})")
    return missed


class PipelineError(Exception):
    pass


def process_layout(
    pdf_path: Path,
    layout_type: LayoutType,
    job_dir: Path,
    on_stage: Optional[Callable[[Stage], None]] = None,
) -> dict:
    """Run the full pipeline for one job. Returns a result dict (see
    bottom of this function). Raises PipelineError / ValidationError on
    any failure -- callers are expected to mark the job failed and keep
    whatever partial logs exist rather than show a raw traceback."""

    def stage(s: Stage):
        logger.info("job stage: %s", s.value)
        if on_stage:
            on_stage(s)

    work_dir = job_dir / "work"
    output_dir = job_dir / "output"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: extraction (deterministic, unmodified script) ---
    stage(Stage.analyzing)
    extracted_json_path = extract_drawing(str(pdf_path), str(work_dir), 2.0)
    with open(extracted_json_path, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    if not extracted.get("pages"):
        raise PipelineError("The PDF appears to have no pages.")

    # --- Step 2: interpretation (the one Claude call) ---
    stage(Stage.identifying)
    try:
        interp = interpret_pages(extracted["pages"])
    except Exception as e:
        raise PipelineError(f"Drawing interpretation failed: {e}") from e

    callouts = interp["callouts"]
    warnings: list[str] = list(interp["warnings"])

    orphaned = _find_orphaned_dimensions(extracted["pages"], callouts)
    if orphaned:
        warnings.append(
            "Possibly missed dimension(s) not referenced by any balloon -- "
            "verify against the source drawing: " + "; ".join(orphaned)
        )
        logger.warning("orphaned dimension-like values not covered by any callout: %s", orphaned)

    if not callouts:
        raise PipelineError("No inspectable characteristics were identified on this drawing.")

    detected_part_number = next(
        (c.get("value") for c in callouts if c.get("destination") == "davco_part_number"),
        None,
    )
    base_name = sanitize_filename(detected_part_number, fallback=pdf_path.stem) if detected_part_number else pdf_path.stem

    # --- Step 3: balloons (deterministic, unmodified script) ---
    stage(Stage.generating_balloons)
    ballooned_pdf = output_dir / f"{base_name}_Ballooned.pdf"
    ballooned_png = output_dir / f"{base_name}_Ballooned.png"
    draw_balloons(str(pdf_path), callouts, str(ballooned_pdf), 15.0, str(ballooned_png), 2.0)

    # --- Step 4: Excel (deterministic, unmodified script) ---
    is_supplier = layout_type == LayoutType.supplier
    layout_label = "Supplier" if is_supplier else "Customer"
    stage(Stage.creating_supplier_layout if is_supplier else Stage.creating_customer_layout)

    template_path = SUPPLIER_TEMPLATE if is_supplier else CUSTOMER_TEMPLATE
    if not template_path.is_file():
        raise PipelineError(f"Missing master template: {template_path}")
    template_hash_before = file_hash(template_path)

    excel_path = output_dir / f"{base_name}_{layout_label}_Layout.xlsx"
    _excel_out, excel_notes, table_rows_used, _header_used = fill_excel(
        str(template_path), callouts, str(excel_path), layout_label, None
    )
    warnings.extend(excel_notes)

    # --- Step 5: validate ---
    stage(Stage.validating)
    try:
        val_warnings = validate_outputs(
            ballooned_pdf, excel_path, template_path, template_hash_before,
            expected_min_rows=1,
        )
    except ValidationError:
        raise
    warnings.extend(val_warnings)

    # --- Result metadata (read straight from the callouts Claude produced --
    # not re-derived, so it can never disagree with what's actually on the
    # drawing/Excel) ---
    def find(destination: str) -> Optional[str]:
        for c in callouts:
            if c.get("destination") == destination:
                return c.get("value") or c.get("text")
        return None

    customer_name = None
    for c in callouts:
        if c.get("destination") == "customer_part_number":
            customer_name = c.get("customer_name")
            break

    review_log_path = None
    if warnings:
        review_log_path = output_dir / f"{base_name}_Review.txt"
        body = f"Review notes for {base_name} ({layout_label} layout)\n\n" + "\n".join(
            f"- {w}" for w in warnings
        )
        review_log_path.write_text(body, encoding="utf-8")

    stage(Stage.complete)

    return {
        "ballooned_pdf_path": ballooned_pdf,
        "ballooned_png_path": ballooned_png if ballooned_png.is_file() else None,
        "excel_path": excel_path,
        "review_log_path": review_log_path,
        "part_number": find("davco_part_number"),
        "revision": find("revision"),
        "customer": customer_name,
        "customer_part_number": find("customer_part_number"),
        "characteristics_count": table_rows_used,
        "total_balloons": len(callouts),
        "warnings": warnings,
    }
