"""
interpret.py -- the one step in the pipeline that requires Claude's
judgment rather than deterministic code: reading the extracted drawing
text and deciding what's a balloon-worthy characteristic, how to group
multi-line callouts, and where each one belongs in the Excel report.

This mirrors exactly the rules in
`.claude/skills/dimensional-layout/SKILL.md` Steps 5-6 (grouping, title
block scope, destinations, customer detection). It does not change those
rules -- it restates them for a single tool-free structured-output call so
the web backend can drive the same reasoning without an interactive
session. If SKILL.md's rules change, update the RULES text below to match.

The call goes through the `claude` CLI as a subprocess (not the raw
Anthropic API) so it reuses whatever authentication is already configured
for Claude Code on this machine -- no API key needs to be issued or
embedded anywhere, unless ANTHROPIC_API_KEY is explicitly set in the
server's environment, in which case it's passed through to the
subprocess only (never to the browser).
"""
import json
import logging
import re
import shutil
import subprocess

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_TIMEOUT_SECONDS

logger = logging.getLogger("dimlayout.interpret")

RULES = """You are a Quality Engineer building a numbered balloon list for a Davco \
engineering drawing, for a dimensional layout / PPAP inspection report. You are given \
the drawing's text already extracted from the PDF, as lines with bounding boxes in PDF \
point coordinates (origin top-left, y increases downward). Follow these rules exactly.

GROUPING (most important rule): one logical drawing callout = one balloon = one \
characteristic. Do not default to one balloon per line of text. If several nearby \
lines describe ONE physical feature (a common leader/arrow, one component, an \
obviously single note block by alignment/indentation/spacing), combine them into ONE \
item, with the lines joined by "; " in its text. Example: "APTIV CONNECTOR P/N \
12015792" / "APTIV TERMINAL P/N 12124580" / "12V-150W NOMINAL" / "NON-POLARIZED \
CONNECTOR" printed as 4 lines is ONE callout about one connector -> ONE balloon, text \
"APTIV CONNECTOR P/N 12015792; APTIV TERMINAL P/N 12124580; 12V-150W NOMINAL; \
NON-POLARIZED CONNECTOR". Likewise a port callout like "FUEL IN" / "1/2\"-14 NPTF" / \
"PACKAGING CAP NOT SHOWN" is ONE callout about one port (a note like "PACKAGING CAP \
NOT SHOWN" that sits directly under a thread spec is a modifier of THAT SAME port, not \
its own characteristic) -> ONE balloon, text "FUEL IN: 1/2\"-14 NPTF (PACKAGING CAP \
NOT SHOWN)". Do not over-merge: genuinely separate dimensions that \
happen to sit near each other stay separate even if close together. Within one \
grouped callout, an inch value / bracketed mm value directly below it / a trailing \
qualifier (MAX, MIN, THRU, 2 HOLES, ON CENTER, FROM HORIZONTAL) is one value, not \
several fragments.

WHAT TO BALLOON: linear dimensions, diameters, radii, angles, depths/heights/widths/\
lengths, MAX/MIN/reference dimensions, tolerances, hole/thread specs, feature \
quantities, GD&T frames, surface finish, material/plating specs, filter/flow ratings, \
manufacturing/inspection notes, dimensional unit notes (e.g. "DIMENSIONS IN [ ] ARE \
MILLIMETERS"), connector/component part numbers (grouped per the rule above), and a \
customer part-number callout if present (see DESTINATIONS below).

TITLE BLOCK RULE (permanent): the bordered title-block box (company info, drawn-by/\
checked-by/engineer/approved-by names+dates, the general tolerance block, third-angle \
projection symbol, sheet/scale/drawing-size, original production release number) is \
NOT ballooned AT ALL except for exactly three fields: the drawing's own Part No., its \
Revision letter, and its Released date. Do not balloon the title, sheet number, scale, \
drawing size, tolerance block, projection symbol, names/dates, company logo/address/\
phone/fax, or release number. A customer part-number callout often sits OUTSIDE the \
title-block box, in the drawing's general notes area -- find and balloon it wherever \
it actually is.

DO NOT balloon a List of Materials / BOM table's own "ITEM NO." reference numbers \
(bare integers scattered around an assembly view, or a ITEM NO./QTY./PART NUMBER/\
DESCRIPTION table) -- those identify assembly components, not inspection dimensions.

AVOID DUPLICATES: the same dimension often appears in more than one view. If it's \
the same characteristic shown again, don't add it twice; if it's a genuinely separate \
feature that happens to share a value, keep both.

DESTINATIONS: every balloon has exactly one destination -- "table" (the normal case), \
or a header/metadata field: "davco_part_number" (the title block's Part No.), \
"revision" (the title block's Revision letter), "released_date" (the title block's \
Released date), or "customer_part_number" (a customer's own P/N callout, labeled \
things like "INTERNATIONAL P/N:", "DTNA P/N:", "VOLVO P/N:", "NAVISTAR P/N:", \
"CUSTOMER P/N:", or similar -- extract the customer's name from that label into a \
"customer_name" field on that same item, e.g. "INTERNATIONAL P/N: 3698221C94" -> \
customer_name "INTERNATIONAL", value "3698221C94"). For header-destined items, set \
"value" to the bare value with no label prefix (e.g. "382932NAV-25", not "PART NO: \
382932NAV-25"). Header-destined items still get numbered in the same single sequence \
as everything else -- numbering never restarts and is never skipped/renumbered.

TOLERANCES: if a dimension shows a genuinely separable nominal + a plain +/- \
tolerance (e.g. "6.63 [168.3] +/-0.12 [3.0]"), you may put the nominal in "text" and \
the tolerance in a "limits" field. Do NOT do this for MAX/MIN/REF/THRU-style \
qualifiers -- those stay combined in "text" as one value.

FORMATTING: preserve symbols exactly as printed: the diameter symbol, +/- (write as \
±), degree symbol (write as °), R for radius, thread callouts like 1/2"-14 NPTF, \
MAX/MIN/REF/TYP, place counts. Keep inch and bracketed millimeter values together, \
e.g. "20.31 [515.9] MAX".

NUMBERING AND PLACEMENT: assign sequential integers starting at 1 in roughly \
top-to-bottom, left-to-right reading order across the whole drawing (all pages, all \
destinations, one sequence). For each item, choose an "x"/"y" (the balloon circle's \
center, in the same PDF point coordinates as the input lines) just outside the text/\
geometry it labels -- never centered on top of the numbers, arrows, or extension \
lines themselves. If the nearest open space is some distance away, also set \
"leader_to": [x, y] pointing at the actual characteristic; otherwise omit leader_to.

REVIEW WARNINGS: if you excluded a BOM item-number table, skipped/merged something \
uncertain, couldn't confidently read a value, weren't sure whether two nearby \
dimensions were duplicates, or made any other judgment call a human quality engineer \
should double-check, add a short plain-language note about it to a top-level \
"warnings" array. Leave it empty if there was nothing meaningfully uncertain --  \
don't invent filler warnings.

OUTPUT: respond with ONLY a single JSON object (no prose, no markdown code fences, no \
trailing commentary) with exactly two top-level keys, "callouts" (array, one object \
per balloon) and "warnings" (array of strings, may be empty), using DOUBLE-QUOTED \
JSON keys and strings exactly like this shape:
{"callouts": [{"item": 1, "page": 0, "x": 496.7, "y": 108.0, "leader_to": [510.0, \
135.0], "destination": "table", "text": "3.22 [81.8]"}, {"item": 23, "page": 0, \
"x": 2259.0, "y": 1565.0, "leader_to": [2259.0, 1552.0], "destination": \
"davco_part_number", "value": "382932NAV-25", "text": "PART NO: 382932NAV-25"}], \
"warnings": ["Excluded the assembly's List of Materials item-number call-outs (BOM \
table) from ballooning -- they identify parts, not dimensions."]}
"""


def _find_claude_exe() -> str:
    exe = shutil.which("claude")
    if exe:
        return exe
    # Common install location on Windows when not on PATH for this process.
    import os
    candidate = os.path.expanduser(r"~\.local\bin\claude.exe")
    if os.path.isfile(candidate):
        return candidate
    raise RuntimeError(
        "claude CLI not found. Install Claude Code and make sure it's "
        "authenticated (`claude` should work from a terminal) before "
        "running the web app's interpretation step."
    )


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    # Strip markdown fences if the model added them despite instructions.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the widest {...} span in case of stray prose around it.
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Claude's response did not contain a JSON object: {text[:500]!r}")
    snippet = text[start:end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        # Last resort: tolerate single-quoted / unquoted-key JS-object-literal
        # style output by quoting bare keys, then retry.
        repaired = re.sub(r"(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", r'"\1":', snippet)
        return json.loads(repaired)


def interpret_pages(pages: list[dict]) -> list[dict]:
    """
    pages: the `pages` list from extract_drawing's extracted.json (only the
    fields we need: page_index, width_pt, height_pt, raw_text,
    lines_reading_order, has_native_text, image_path).

    Returns {"callouts": [...], "warnings": [...]} -- callouts match
    callouts.json's schema, ready to hand to create_balloons() / fill_excel().
    """
    claude_exe = _find_claude_exe()

    page_payload = []
    for p in pages:
        page_payload.append({
            "page": p["page_index"],
            "width_pt": p["width_pt"],
            "height_pt": p["height_pt"],
            "has_native_text": p["has_native_text"],
            "lines": [
                {"text": ln["text"], "bbox": ln["bbox"]}
                for ln in p.get("lines_reading_order", [])
            ],
        })

    if not any(p["has_native_text"] for p in pages):
        raise RuntimeError(
            "This drawing has no embedded/native PDF text on any page (likely a "
            "scanned image) -- the current interpretation step reasons over "
            "extracted text and coordinates, not raw images. Vision-based "
            "fallback isn't wired up in this version; see review log."
        )

    prompt = (
        RULES
        + "\n\nDRAWING PAGES (JSON):\n"
        + json.dumps(page_payload)
    )

    args = [
        claude_exe, "-p", prompt,
        "--output-format", "json",
        "--model", CLAUDE_MODEL,
        "--disallowedTools", "Bash Edit Write Read Glob Grep WebSearch WebFetch NotebookEdit",
        # This call is single-shot and tool-free by design (the whole prompt
        # is self-contained). bypassPermissions only matters for whatever
        # tools are NOT in the disallow list above (e.g. TodoWrite) -- it
        # exists so a stray tool-permission prompt can never block waiting
        # on stdin input that will never arrive from a background job.
        "--permission-mode", "bypassPermissions",
        # This is a bounded structured-extraction task, not open-ended
        # problem solving -- cap reasoning effort so it stays fast.
        "--effort", "high",
    ]

    env = None
    if ANTHROPIC_API_KEY:
        import os
        env = dict(os.environ)
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY

    logger.info("Calling claude CLI for interpretation (%d page(s))", len(pages))
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SECONDS, env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Interpretation call timed out after {CLAUDE_TIMEOUT_SECONDS}s") from e

    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed (exit {proc.returncode}): {proc.stderr[:2000]}")

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude CLI did not return valid JSON envelope: {proc.stdout[:1000]!r}") from e

    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI reported an error: {envelope.get('result')!r}")

    result_text = envelope.get("result", "")
    parsed = _extract_json_object(result_text)

    callouts = parsed.get("callouts")
    warnings = parsed.get("warnings", [])
    if not isinstance(callouts, list):
        raise RuntimeError("Interpretation result was valid JSON but had no 'callouts' list.")
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    for c in callouts:
        if "item" not in c or "destination" not in c:
            raise RuntimeError(f"Interpretation returned a malformed callout: {c!r}")
        c.setdefault("page", 0)
        c.setdefault("text", c.get("value", ""))

    logger.info("Interpretation returned %d callout(s), %d warning(s)", len(callouts), len(warnings))
    return {"callouts": callouts, "warnings": warnings}
