"""
create_balloons.py

Draws numbered red balloon circles (and optional leader lines) onto a COPY
of the source drawing PDF. The source PDF is opened read-only and is never
written back to -- output is always a new file.

Input is a JSON file describing the balloons, produced by the analysis step
(normally authored by Claude after reading extracted.json / the page PNGs).

balloons.json shape:
[
  {
    "item": 1,
    "page": 0,
    "x": 496.7, "y": 126.7,        // anchor point balloon center is placed at
    "leader_to": [520.0, 140.0],   // OPTIONAL: point the leader line should touch
                                   // (e.g. the actual dimension text) if the
                                   // balloon had to be offset into open space
    "text": "3.22 [81.8]"          // informational only, not drawn on the PDF
  },
  ...
]

Usage:
    python create_balloons.py <input_pdf> <balloons_json> <output_pdf> [--png <output_png>] [--radius 15] [--zoom 2.0]
"""
import argparse
import json
import os
import sys

import fitz  # PyMuPDF

RED = (1, 0, 0)


def draw_balloons(pdf_path, balloons, out_pdf, radius, out_png=None, png_zoom=2.0):
    doc = fitz.open(pdf_path)

    for b in balloons:
        page_index = b.get("page", 0)
        if page_index < 0 or page_index >= len(doc):
            raise ValueError(f"balloon item {b.get('item')} references invalid page {page_index}")
        page = doc[page_index]

        cx, cy = float(b["x"]), float(b["y"])
        item_no = b["item"]

        leader_to = b.get("leader_to")
        if leader_to:
            lx, ly = float(leader_to[0]), float(leader_to[1])
            dx, dy = lx - cx, ly - cy
            dist = max((dx ** 2 + dy ** 2) ** 0.5, 0.0001)
            ux, uy = dx / dist, dy / dist
            edge_x, edge_y = cx + ux * radius, cy + uy * radius
            page.draw_line(fitz.Point(edge_x, edge_y), fitz.Point(lx, ly),
                            color=RED, width=1.2)

        page.draw_circle(fitz.Point(cx, cy), radius, color=RED, width=1.6, fill=None)

        label = str(item_no)
        fontsize = radius * 1.05 if len(label) == 1 else radius * 0.85
        text_width = fitz.get_text_length(label, fontname="helv", fontsize=fontsize)
        tx = cx - text_width / 2
        ty = cy + fontsize * 0.36
        page.insert_text(fitz.Point(tx, ty), label, fontname="helv",
                          fontsize=fontsize, color=RED)

    os.makedirs(os.path.dirname(os.path.abspath(out_pdf)), exist_ok=True)
    doc.save(out_pdf)

    png_paths = []
    if out_png:
        base, ext = os.path.splitext(out_png)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(png_zoom, png_zoom))
            path = out_png if len(doc) == 1 else f"{base}_p{i}{ext}"
            pix.save(path)
            png_paths.append(path)

    doc.close()
    return out_pdf, png_paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_pdf")
    ap.add_argument("balloons_json")
    ap.add_argument("output_pdf")
    ap.add_argument("--png", default=None, help="also render a PNG snapshot of the ballooned pages")
    ap.add_argument("--radius", type=float, default=15.0)
    ap.add_argument("--zoom", type=float, default=2.0)
    args = ap.parse_args()

    if not os.path.isfile(args.input_pdf):
        print(f"ERROR: input PDF not found: {args.input_pdf}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.balloons_json):
        print(f"ERROR: balloons JSON not found: {args.balloons_json}", file=sys.stderr)
        sys.exit(1)

    with open(args.balloons_json, "r", encoding="utf-8-sig") as f:
        balloons = json.load(f)

    out_pdf, png_paths = draw_balloons(args.input_pdf, balloons, args.output_pdf,
                                        args.radius, args.png, args.zoom)
    print(f"Ballooned PDF written to: {out_pdf}  ({len(balloons)} balloons)")
    for p in png_paths:
        print(f"PNG snapshot written to: {p}")
