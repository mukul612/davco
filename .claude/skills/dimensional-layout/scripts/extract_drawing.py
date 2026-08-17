"""
extract_drawing.py

Extracts everything needed to analyze an engineering drawing PDF:
  - native embedded vector text (preferred, exact symbols preserved: Ø ± ° etc.)
  - word-level and line-level bounding boxes (for balloon placement later)
  - a high-resolution PNG render of every page (for visual/vision analysis
    and as a fallback when a page has no embedded text)
  - best-effort OCR text for any page that has no embedded text, IF a
    Tesseract binary can be found on the system. If not found, no error is
    raised -- the rendered PNG is still produced so a vision-capable reader
    (e.g. Claude reading the PNG directly) can analyze the page.

Never modifies the source PDF.

Usage:
    python extract_drawing.py <input_pdf> <output_dir> [--zoom 2.0]

Writes:
    <output_dir>/extracted.json   -- structured extraction result
    <output_dir>/page_XX.png      -- rendered page images
"""
import argparse
import json
import os
import shutil
import sys

import fitz  # PyMuPDF


def find_tesseract():
    candidates = [
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def group_words_into_lines(words):
    """Group raw fitz words ((x0,y0,x1,y1,text,block,line,word_no)) into
    reading lines keyed by (block, line), preserving left-to-right order.
    Returns a list of dicts: {text, bbox:[x0,y0,x1,y1], block, line, words:[...]}
    in the same order the PDF content stream produced them (fitz block order),
    which is usually -- but not guaranteed to be -- visual reading order.
    A y0-then-x0 sorted copy is also provided by the caller if needed.
    """
    lines = {}
    order = []
    for (x0, y0, x1, y1, text, block, line, word_no) in words:
        key = (block, line)
        if key not in lines:
            lines[key] = {
                "block": block,
                "line": line,
                "words": [],
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            }
            order.append(key)
        e = lines[key]
        e["words"].append(text)
        e["x0"] = min(e["x0"], x0)
        e["y0"] = min(e["y0"], y0)
        e["x1"] = max(e["x1"], x1)
        e["y1"] = max(e["y1"], y1)

    result = []
    for key in order:
        e = lines[key]
        result.append({
            "text": " ".join(e["words"]),
            "bbox": [round(e["x0"], 1), round(e["y0"], 1), round(e["x1"], 1), round(e["y1"], 1)],
            "block": e["block"],
            "line": e["line"],
        })
    return result


def extract(pdf_path, out_dir, zoom):
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)

    tesseract_path = find_tesseract()
    ocr_available = tesseract_path is not None
    if ocr_available:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

    pages_out = []
    for i, page in enumerate(doc):
        text = page.get_text()
        has_native_text = len(text.strip()) > 20

        words = page.get_text("words")
        lines = group_words_into_lines(words)
        lines_reading_order = sorted(lines, key=lambda l: (round(l["bbox"][1] / 10), l["bbox"][0]))

        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img_name = f"page_{i:02d}.png"
        img_path = os.path.join(out_dir, img_name)
        pix.save(img_path)

        ocr_text = None
        ocr_used = False
        if not has_native_text and ocr_available:
            from PIL import Image
            import pytesseract
            ocr_text = pytesseract.image_to_string(Image.open(img_path))
            ocr_used = True

        pages_out.append({
            "page_index": i,
            "width_pt": round(page.rect.width, 1),
            "height_pt": round(page.rect.height, 1),
            "render_zoom": zoom,
            "image_path": img_path,
            "has_native_text": has_native_text,
            "ocr_available": ocr_available,
            "ocr_used": ocr_used,
            "raw_text": text,
            "ocr_text": ocr_text,
            "word_count": len(words),
            "lines_stream_order": lines,
            "lines_reading_order": lines_reading_order,
        })

    result = {
        "source_pdf": os.path.abspath(pdf_path),
        "page_count": len(doc),
        "tesseract_path": tesseract_path,
        "pages": pages_out,
    }

    out_json = os.path.join(out_dir, "extracted.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Extracted {len(doc)} page(s) from: {pdf_path}")
    for p in pages_out:
        mode = "native text" if p["has_native_text"] else ("OCR" if p["ocr_used"] else "IMAGE ONLY (no OCR engine found -- read the PNG directly)")
        print(f"  page {p['page_index']}: {mode}, {p['word_count']} words, image: {p['image_path']}")
    print(f"JSON written to: {out_json}")
    return out_json


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_pdf")
    ap.add_argument("output_dir")
    ap.add_argument("--zoom", type=float, default=2.0)
    args = ap.parse_args()

    if not os.path.isfile(args.input_pdf):
        print(f"ERROR: input PDF not found: {args.input_pdf}", file=sys.stderr)
        sys.exit(1)

    extract(args.input_pdf, args.output_dir, args.zoom)
