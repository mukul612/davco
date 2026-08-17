---
name: dimensional-layout
description: Turn an engineering drawing PDF into a numbered red balloon print plus a filled-in Supplier or Customer dimensional layout / PPAP inspection Excel report, saved into a part-number folder inside "C:\Davco\Layout by AI". Use whenever the user asks to run/create/build a dimensional layout, balloon print, ballooned drawing, or PPAP layout for a part number or drawing name -- phrasings like "Do a supplier layout for 382932NAV-25 - REV D", "Do a customer layout for 382953NAVR01-25", "Run dimensional layout for X", "Use the dimensional-layout skill for X", "balloon this drawing", or "fill out the DIM layout for part X" should all trigger this skill, even if the user doesn't name the skill explicitly.
---

# Dimensional Layout

Turns a Davco engineering drawing PDF into a ballooned print + a completed
Dimensional Inspection Results Excel workbook (Supplier or Customer
version), ready for a supplier or PPAP submission. This is a real
quality-engineering deliverable used to verify physical parts against
print requirements -- accuracy and traceability between the balloon
numbers and the Excel rows matter more than speed.

## Why this skill is structured the way it is

Two things are genuinely mechanical (extracting text/coordinates from a
PDF, drawing circles, writing Excel cells) and two things genuinely require
engineering judgment (deciding *what* on a drawing is one inspectable
characteristic, and *wording* it correctly without splitting a dimension
from its tolerance). This skill therefore splits the work: bundled Python
scripts do the mechanical parts deterministically, and you (Claude) do the
reading and judgment part yourself, the same way a quality engineer would
mark up a print by hand. Don't try to replace your own reading of the
drawing with a regex -- that's exactly the part a heuristic gets wrong.

## Inputs (fixed for this project)

- Drawings + templates live in: `C:\Davco\Layout by AI`
- Supplier template: `C:\Davco\Layout by AI\Blank Supplier DIM.xlsx`
- Customer template: `C:\Davco\Layout by AI\Blank Customer DIM.xlsx`
- Scripts: `C:\Davco\Layout by AI\.claude\skills\dimensional-layout\scripts\`
- Never modify the source PDF or either blank template. Every run reads
  them and writes new files elsewhere.

## Resolving Python

`python` may resolve to the Windows Store "app execution alias" stub (a
0-byte file that errors immediately) instead of a real interpreter. Before
running any script:

```powershell
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py -or (Get-Item $py).Length -eq 0) {
    $py = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Filter python.exe -Recurse | Select-Object -First 1 -ExpandProperty FullName
}
```

Use `$py` (a real path) for every `python ...` invocation below, e.g.
`& $py "scripts\extract_drawing.py" ...`. If a required package
(pymupdf/openpyxl/pillow/pytesseract) is missing, install it with
`& $py -m pip install -r "scripts\requirements.txt"`.

When writing scratch JSON files with `Out-File` in PowerShell, either pass
`-Encoding utf8NoBOM` or don't worry about it -- the scripts open JSON with
`utf-8-sig`, so a BOM won't break them either way.

## Workflow

### Step 1 -- Determine the layout type

Every request is for a **Supplier layout** or a **Customer layout** --
they use different Excel templates and populate metadata differently (see
Step 7). Detect this from the user's phrasing ("supplier layout",
"customer layout"). If the user gives only a part number with no layout
type and it can't be inferred from context (e.g. earlier in the same
conversation), **ask them which one they want** (AskUserQuestion or a
plain question) rather than guessing -- picking the wrong template means
redoing the whole Excel output.

### Step 2 -- Find the drawing

Search `C:\Davco\Layout by AI` (top level only -- do not search inside
previously generated part folders unless the top-level search fails) for a
PDF matching the given part number / drawing name.

1. Try an exact filename match (ignoring case and the `.pdf`/`.PDF`
   extension).
2. If that fails, normalize both the query and each candidate filename by
   stripping spaces/dashes/underscores and lowercasing, then look for a
   substring match either direction. Revision suffixes ("- REV D") and
   trailing/leading whitespace are the most common source of mismatch.
3. If still not found, list the PDFs in the folder and ask the user which
   one they meant rather than guessing.

### Step 3 -- Create the output folder

Create `C:\Davco\Layout by AI\<PartNumber>\` using the exact part
number/drawing name string the user gave you (matching their casing and
formatting, e.g. `382932NAV-25 - REV D`). All outputs for this part go
here. Do not create any separate global "Output" folder.

### Step 4 -- Extract the drawing

```powershell
& $py "scripts\extract_drawing.py" "<path to PDF>" "<a scratch work dir>"
```

Use a scratch directory outside the deliverable folder (e.g. under
`$env:TEMP\dimensional-layout\<PartNumber>\`) -- the raw extraction JSON
and page PNGs are working material, not deliverables.

This produces `extracted.json` containing, per page:
- `raw_text` -- the full embedded PDF text (present when the drawing has
  native vector text, which is the common case for CAD-exported PDFs)
- `lines_stream_order` / `lines_reading_order` -- text grouped into visual
  lines with bounding boxes in PDF point coordinates (origin top-left,
  y increases downward -- same convention `create_balloons.py` expects)
- `has_native_text` -- if false, there was no embedded text layer
- `image_path` -- a high-resolution PNG render of the page
- `ocr_used` / `ocr_text` -- filled in only if a Tesseract binary was found
  on the system and the page had no native text

**Read `raw_text` and the `lines_reading_order` bounding boxes as your
primary source.** Native vector text preserves symbols (Ø, ±, °) exactly
and gives you precise coordinates for balloon placement -- always prefer it
over OCR or vision when it's available. Only fall back to reading the
`image_path` PNG yourself (with the Read tool -- you can view images
directly, no OCR needed) when `has_native_text` is false, or when you need
to visually confirm the geometry/layout around a cluster of text (e.g. to
judge where free space is for a balloon, or whether several nearby lines
belong to the same callout).

### Step 5 -- Read the drawing like a quality engineer would

Go through every page. The raw words come out of the PDF in content-stream
order grouped by (block, line) -- adjacent lines are very often fragments
of one callout, not separate characteristics. Use the bounding box
coordinates (proximity, alignment) plus your own understanding of drawing
convention to decide what belongs together -- this is exactly the kind of
judgment call a script can't reliably make.

**One logical drawing callout = one balloon = one characteristic. This is
the most important grouping rule and it applies before anything else
below.** Do not default to "one balloon per line of text." Determine
whether a group of nearby lines belongs to a single callout using:
- a common leader line or arrow pointing at one feature
- description of one single physical feature/component (even across
  several lines -- e.g. a connector's part number, its terminal's part
  number, its electrical rating, and its polarity are four lines that
  together describe *one* connector)
- adjacent lines that clearly form one note block (indentation, alignment,
  tight consistent line spacing distinct from surrounding text)
- proximity and semantic relationship

  Example: a callout printed as four lines --
  ```
  APTIV CONNECTOR P/N 12015792
  APTIV TERMINAL P/N 12124580
  12V-150W NOMINAL
  NON-POLARIZED CONNECTOR
  ```
  is ONE callout about one connector. It gets ONE balloon and ONE Excel
  row, with the lines joined by `; `:
  `APTIV CONNECTOR P/N 12015792; APTIV TERMINAL P/N 12124580; 12V-150W NOMINAL; NON-POLARIZED CONNECTOR`

  Do NOT balloon each of those four lines separately.

  On the PDF, a grouped callout still gets exactly one circle -- point its
  leader at the block generally (its left edge or vertical center) rather
  than trying to fan several leaders to individual lines.

Don't over-merge, though: separate dimensions that happen to sit near each
other (e.g. two different envelope widths at the top of a view) are
genuinely separate characteristics and must stay as separate balloons even
if they're only ~30pt apart. The test is "does this group of lines
describe one feature," not "are these lines physically close."

Within a single grouped callout, the usual line-fragment reading still
applies: an inch value, the bracketed mm value directly below it, and a
trailing qualifier (MAX/MIN/THRU/2 HOLES/ON CENTER/FROM HORIZONTAL) are
one value, not three.

Identify every inspectable characteristic, not just numeric dimensions:
- linear dimensions, diameters, radii, angles, depths/heights/widths/lengths
- MAX/MIN/reference dimensions, unilateral/bilateral tolerances, limit dims
- hole and thread specifications, feature quantities ("2 HOLES")
- GD&T feature-control frames and datum references where legible
- surface finish, material/plating specs, filter/flow ratings
- manufacturing and inspection notes, product performance specs
- dimensional unit notes (e.g. "DIMENSIONS IN [ ] ARE MILLIMETERS")
- connector/component part numbers called out on the print (grouped per
  the rule above), e.g. "APTIV CONNECTOR P/N 12015792; ..."
- a customer part-number callout (see Step 6 -- this one is special: it's
  still ballooned, but routes to a header field, not the table)
- anything else in the drawing's general notes area that a supplier would
  need to verify (general notes are NOT the same as the title block itself
  -- see the title-block rule immediately below)

**Title block / bottom-right corner box: only three fields get ballooned,
permanently.** The bordered title-block box (company info, drawn-by/
checked-by/engineer/approved-by, dates, tolerance block, projection
symbol, sheet/scale/drawing-size, and the Part No./Revision/Released row)
is administrative metadata about the drawing, not an inspectable
characteristic -- except for three fields every layout genuinely needs:
- **DAVCO Part No.** (the print's own part number, e.g. "382932NAV-25")
- **Revision** (the revision letter, e.g. "D")
- **Released** (the release date, e.g. "07/19/13")

Balloon only those three, each as its own item. Do **not** balloon
anything else inside that box, including but not limited to: the title,
sheet number, scale, drawing size, the general/default tolerance block
(2 PLC/3 PLC/ANGLES ± values and the "TOLERANCES PER ANSI..." note), the
third-angle-projection symbol, drawn-by/checked-by/engineer/approved-by
names and dates, the company logo/address/phone/fax, and the original
production release number. This restriction applies only to that specific
bordered box -- general notes and specs that live elsewhere on the sheet
(filter ratings, unit notes, customer part numbers called out near the
drawing views, etc.) are unaffected and still get ballooned per the list
above. A customer part-number callout in particular frequently sits
*outside* the title block (e.g. as its own note near the drawing views) --
find and balloon it wherever it actually is; don't skip it just because
it's not in the title-block box.

**Do not balloon the drawing's own item-number call-outs from a List of
Materials / BOM table.** Many Davco prints are assemblies with a parts list
where each component already has a circled reference number tied to the
BOM's "ITEM NO." column (e.g. bare numbers scattered around an assembly
view, or a `ITEM NO. / QTY. / PART NUMBER / DESCRIPTION` table). Those
numbers identify *parts*, not inspectable *dimensions*, and re-ballooning
them would create a second, conflicting numbering system on the same
drawing. Recognize this table (header cells like "ITEM NO.", "QTY.", "PART
NUMBER", "DESCRIPTION" and a bare integer appearing alone with no other
qualifying dimension text nearby) and exclude it, but note in the review
log that it was found and excluded so the user can double check.

**Avoid duplicates.** The same dimension is often shown in more than one
view. Before adding a new item, check whether it's the same characteristic
already captured (same nominal value + tolerance + feature) shown again --
skip it -- versus a genuinely separate feature that happens to share a
value. If you can't tell, include it and flag it in the review log rather
than silently dropping or silently duplicating it.

**Formatting each characteristic** (goes verbatim into the Excel
Specification column):
- Keep a dimension and its tolerance/qualifier together in one line, e.g.
  `3.68 [93.4] MAX`, `Ø.43 [11.0] THRU 2 HOLES`, `2.500 ±0.010` -- UNLESS
  the selected template has a separate Limits column (see Step 7's
  tolerance-splitting note), in which case the nominal and the tolerance
  can be split across the two columns.
- Preserve symbols exactly as printed: Ø, ±, °, R for radius, thread call-
  outs like `1/2"-14 NPTF`, MAX/MIN/REF/TYP, place counts.
- One *logical callout* per row, per the grouping rule above -- multi-line
  callouts about one feature get joined with `; `, but don't merge two
  genuinely unrelated specs into one line.
- Where inch and millimeter values are both shown (common on these prints,
  with mm in brackets per the drawing's own unit note), keep both, e.g.
  `20.31 [515.9] MAX`.

### Step 6 -- Number the balloons and decide each one's destination

Assign sequential integers starting at 1, in a logical reading order where
practical (e.g. roughly top-to-bottom, left-to-right, or by drawing zone)
-- consistency and traceability matter far more than a particular visual
order. Balloon numbering is the same regardless of layout type: number
every callout you identified in Step 5 once, in one pass, whether it will
end up in the dimensional table or a header field.

**Every balloon has exactly one destination in the Excel report: either a
row in the dimensional table, or a header/metadata field. Never both, and
never neither.** This replaces any notion of "every balloon = one table
row" -- that's no longer the rule. The header-bound destinations are:

| destination            | what it is                                  |
|-------------------------|---------------------------------------------|
| `table`                 | a normal Specification/Dimension/Characteristic row (the default) |
| `davco_part_number`     | the title block's DAVCO Part No.             |
| `revision`              | the title block's Revision letter            |
| `released_date`         | the title block's Released date              |
| `customer_part_number`  | the customer's own P/N callout (see Step 5)  |
| `customer_name`         | inferred from the customer P/N callout's label -- do NOT balloon this separately (see Step 7) |

Because header-bound balloons are removed from the table, **the Item #
column in the dimensional table will usually contain gaps** -- e.g. if
balloons 20/22/23/24 are header-bound, the table simply skips straight from
19 to 21. This is correct and intentional. **Never renumber the drawing to
close a gap.** The number printed on the PDF is the source of truth and
the Excel table must match it exactly wherever a number does appear.

Build one single ordered list of callouts up front and generate both the
PDF and the Excel from it -- this is what guarantees the numbers can never
disagree. Write it to a scratch JSON file, e.g. `callouts.json`:

```json
[
  {"item": 7, "page": 0, "x": 1097.7, "y": 191.0, "leader_to": [1097.7, 230], "destination": "table", "text": "6.58 [167.2] MAX"},
  {"item": 10, "page": 0, "x": 1040, "y": 1140, "leader_to": [1128, 1134], "destination": "table", "text": "APTIV CONNECTOR P/N 12015792; APTIV TERMINAL P/N 12124580; 12V-150W NOMINAL; NON-POLARIZED CONNECTOR"},
  {"item": 20, "page": 0, "x": 1700, "y": 1325, "leader_to": [1582, 1356], "destination": "customer_part_number", "value": "3594343C95", "customer_name": "NAVISTAR", "text": "NAVISTAR P/N: 3594343C95"},
  {"item": 23, "page": 0, "x": 2259, "y": 1565, "leader_to": [2259, 1552], "destination": "davco_part_number", "value": "382932NAV-25"},
  {"item": 24, "page": 0, "x": 2402, "y": 1565, "leader_to": [2402, 1552], "destination": "revision", "value": "D"},
  {"item": 22, "page": 0, "x": 2075, "y": 1548, "leader_to": [2095, 1522], "destination": "released_date", "value": "07/19/13"}
]
```

Notes on the fields:
- `x`/`y` are the PDF-point coordinates (from the bounding boxes in
  `extracted.json`) of where the balloon **circle center** should be
  drawn. Pick a point just outside the dimension text/geometry it's
  labeling -- never centered directly on top of numbers, arrows, extension
  lines, or other important text. If the only clear open space is some
  distance away, add `"leader_to": [x, y]` pointing at the actual
  characteristic and the balloon script will draw a thin leader line to
  it. When in doubt about placement, look at the rendered page PNG to
  confirm there's genuinely clear space at your chosen coordinates.
- `destination` defaults to `table` if omitted.
- `text` is the full callout text -- always include it, even for
  header-bound items (it's the fallback if a template turns out not to
  have a field for that destination; see Step 7).
- `value` is the clean bare value for header-bound items (no label
  prefix) -- e.g. `"382932NAV-25"`, not `"PART NO: 382932NAV-25"`.
- `customer_name` only appears on the `customer_part_number` item, when
  you can tell who the customer is from the callout's own label (e.g.
  "NAVISTAR P/N:", "INTERNATIONAL P/N:", "DTNA P/N:", "VOLVO P/N:").
- **This same file is reused for both the PDF (Step 8) and the Excel
  (Step 9), and is layout-type-independent.** The set of balloons and
  their numbering does not change between a Supplier run and a Customer
  run of the same drawing -- only which Excel fields each one lands in
  changes (see Step 9). Reuse one ballooned PDF for both layout types
  instead of generating it twice.

### Step 7 -- Draw the balloon print

```powershell
& $py "scripts\create_balloons.py" "<source pdf>" "<callouts.json>" "<PartNumber>\<PartNumber>_Ballooned.pdf" --png "<PartNumber>\<PartNumber>_Ballooned.png"
```

This draws red circular outlines with red numbers (generated as vector
graphics, not Unicode circled-digit characters) plus any leader lines, onto
a fresh copy of the PDF, and also renders a PNG snapshot. It never touches
the source PDF. It ignores `destination`/`value`/etc. -- it only cares
about `item`/`page`/`x`/`y`/`leader_to`/`text`.

**After running it, view the resulting PNG** (Read tool) to sanity-check
that balloons landed in reasonable places and aren't covering dimension
values, arrows, or text. If several are obviously misplaced, adjust the
coordinates in `callouts.json` and rerun this step -- it's cheap to redo.

### Step 8 -- Fill the Excel layout

Pick the template based on the layout type decided in Step 1:
- Supplier -> `Blank Supplier DIM.xlsx`
- Customer -> `Blank Customer DIM.xlsx`

Build a `header.json` with non-ballooned metadata (currently just the
drawing's description/title, read from the title block but never
ballooned itself):

```json
{"description": "FP382 ASM, FLUID HEAT W/ 12V PRE-HEAT"}
```

```powershell
& $py "scripts\fill_excel.py" "Blank Supplier DIM.xlsx" "<callouts.json>" "<PartNumber>\<PartNumber>_Supplier_Layout.xlsx" --layout-type Supplier --header "<header.json>"
& $py "scripts\fill_excel.py" "Blank Customer DIM.xlsx" "<callouts.json>" "<PartNumber>\<PartNumber>_Customer_Layout.xlsx" --layout-type Customer --header "<header.json>"
```

(Run only the one the user asked for -- both are shown here because the
same `callouts.json` drives either output.)

What the script does with `callouts.json`:
- **Table-destined callouts** get written into the Specification /
  Dimension / Characteristic column, in the Item # column using their OWN
  balloon number -- not a re-flowed 1,2,3 sequence. Rows for skipped
  (header-bound) numbers are simply not created. Extends the table with
  correctly styled new rows if there are more table entries than the
  template pre-built.
- **Header-destined callouts** get written into the matching field for
  the selected template, prefixed `[Balloon N]` so it's traceable back to
  the drawing (e.g. `[Balloon 23] 382932NAV-25`). `customer_name` is the
  one exception -- it's plain text with no balloon prefix, since it isn't
  ballooned itself.
- **If a template has no field for a given destination** (the Supplier
  template has no Customer fields at all), that callout is automatically
  written into the table instead, and the script prints a note about it --
  copy that note into the review log. This is why Step 6 says the balloon
  set doesn't change between layout types: a customer-part-number balloon
  always exists once ballooning is done, it just lands in the table for a
  Supplier layout and in the header for a Customer layout.
- **Released Date** has no dedicated field in either current template. The
  script falls back to the otherwise-unused "Lay-out No." box, written as
  `[Balloon N] Released: <date>`. Always mention this fallback in the
  review log -- it's a reasonable stand-in, not a real field, and the user
  may prefer a different spot.
- **Tolerance/Limits column**: the Customer template has a separate
  "Specification / Limits" column; the Supplier template doesn't. Pass a
  `"limits"` value on a callout (e.g. `"limits": "±.010 [.25]"` alongside
  `"text": "6.63 [168.3]"`) only when the drawing shows a genuinely
  separable nominal + tolerance -- MAX/MIN/REF/THRU-style qualifiers stay
  combined in one cell as before, they aren't tolerances to split out. The
  script silently ignores `"limits"` if the selected template has no such
  column (Supplier), so it's safe to include on both runs.
- Never touches the Sample #1-5, OK, or Not OK columns -- leave those
  blank unless the user specifically asks you to fill them.

### Step 9 -- Write the review log (only if anything is uncertain)

If you skipped/merged/excluded/regrouped anything, hit unreadable text, a
callout got redirected to the table because its layout's template had no
header field for it, the Released Date fallback location was used, or you
made any other judgment call a human should double check, write
`<PartNumber>\<PartNumber>_Review.txt` in plain language. Skip this file
entirely if there was no meaningful uncertainty -- don't manufacture
filler content.

### Step 10 -- Validate before reporting done

- Open/confirm the ballooned PDF and PNG look right (balloons visible, one
  circle per logical callout, not covering geometry, red circles+numbers).
- Confirm the Excel opens, formatting/merges/borders are intact, table
  Item # values exactly match their balloon numbers (gaps included), and
  header fields hold the right values with their `[Balloon N]` tags.
- Confirm the original PDF and both blank templates are byte-for-byte
  unchanged (you never opened them for writing).
- Report back: drawing used, layout type, balloon count, how many landed
  in the table vs. headers, exact output paths, and whether a review log
  was created.

## Files in this folder

```
scripts/
  extract_drawing.py   -- PDF text/coordinate/image extraction (Step 4)
  create_balloons.py   -- draws red numbered balloons + leaders (Step 7)
  fill_excel.py         -- copies the right template, routes each callout
                           to a table row or a header field (Step 8)
  requirements.txt      -- pymupdf, openpyxl, pillow, pytesseract
```

There is also `C:\Davco\Layout by AI\Run-DimensionalLayout.ps1`, a thin
PowerShell wrapper that resolves Python, locates the drawing, creates the
output folder, and (for a fully standalone/non-Claude-Code run) invokes
`claude -p` to execute this same skill headlessly, given a `-LayoutType
Supplier`/`Customer` argument. When you're already running inside Claude
Code and the user just names a part number and layout type, follow the
steps above directly -- there's no need to shell out to the wrapper.
