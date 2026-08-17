import sys
from pathlib import Path

WEBAPP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEBAPP_ROOT))

import fitz
import pytest


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """A tiny, real, valid one-page PDF with some drawing-like text, built
    on the fly so tests never depend on a real Davco drawing or network
    access."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((72, 72), "3.50 [89.0] MAX", fontsize=12)
    page.insert_text((72, 100), "PART NO: TEST-001", fontsize=12)
    page.insert_text((72, 128), "REVISION: A", fontsize=12)
    page.insert_text((72, 156), "RELEASED: 01/01/24", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def empty_pdf_bytes() -> bytes:
    return b""


@pytest.fixture
def not_a_pdf_bytes() -> bytes:
    return b"this is definitely not a pdf file"
