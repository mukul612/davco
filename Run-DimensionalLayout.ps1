<#
.SYNOPSIS
    Runs the dimensional-layout workflow for a part number / drawing name.

.DESCRIPTION
    Finds the matching engineering drawing PDF inside "C:\Davco\Layout by AI",
    creates a folder named after the part number, and drives Claude Code
    (headless, via `claude -p`) to run the "dimensional-layout" skill, which
    reads the drawing, creates a numbered red balloon print, fills the
    correct DIM template (Supplier or Customer), and saves both into the new
    folder along with a review log for anything uncertain.

    This is the same workflow you get by simply telling Claude Code, inside
    this project:  "Do a supplier layout for <PartNumber>" or
    "Do a customer layout for <PartNumber>"

.PARAMETER PartNumber
    The part number / drawing name, e.g. "382932NAV-25 - REV D". Matched
    against PDF filenames in the root folder (exact match first, then a
    fuzzy match).

.PARAMETER LayoutType
    "Supplier" or "Customer" -- selects which blank template gets filled
    (Blank Supplier DIM.xlsx or Blank Customer DIM.xlsx) and how header
    metadata (DAVCO Part Number, Revision, Released Date, and for Customer
    layouts, Customer/Customer Part Number) gets populated. Required --
    this script runs non-interactively, so unlike an interactive Claude
    Code session it cannot ask you which one you meant if you omit it.

.PARAMETER BypassPermissions
    Run the headless Claude session with ALL permission checks bypassed
    (--dangerously-skip-permissions) instead of the default, narrower
    --permission-mode acceptEdits + explicit tool allow-list. Only use this
    if you understand the risk -- it lets the session run any tool call
    without confirmation.

.PARAMETER ExtractOnly
    Only run the deterministic PDF extraction step (no Claude, no balloons,
    no Excel). Useful for debugging what text/coordinates were pulled from
    a drawing before trusting the full automated run. Does not require
    -LayoutType.

.EXAMPLE
    .\Run-DimensionalLayout.ps1 -PartNumber "382932NAV-25 - REV D" -LayoutType Supplier

.EXAMPLE
    .\Run-DimensionalLayout.ps1 -PartNumber "382953NAVR01-25" -LayoutType Customer
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$PartNumber,

    [Parameter(Mandatory = $false)]
    [ValidateSet("Supplier", "Customer")]
    [string]$LayoutType,

    [switch]$BypassPermissions,

    [switch]$ExtractOnly
)

$ErrorActionPreference = "Stop"

$RootDir  = "C:\Davco\Layout by AI"
$SkillDir = Join-Path $RootDir ".claude\skills\dimensional-layout"

function Resolve-WorkingPython {
    $candidates = New-Object System.Collections.Generic.List[string]

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path $cmd.Source)) {
        $item = Get-Item $cmd.Source
        # The Windows Store "app execution alias" stub is a 0-byte file that
        # errors out instead of running Python -- skip it.
        if ($item.Length -gt 0) { $candidates.Add($cmd.Source) }
    }

    Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object { $candidates.Add($_.FullName) }

    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    throw "No working Python interpreter found. Install Python 3.10+ and ensure 'python' resolves to a real interpreter (not the Windows Store alias)."
}

function Find-DrawingPdf {
    param([string]$Query)

    $all = Get-ChildItem -Path $RootDir -Filter "*.pdf" -File

    $exact = $all | Where-Object { $_.BaseName -eq $Query }
    if ($exact) { return $exact | Select-Object -First 1 }

    $exactCI = $all | Where-Object { $_.BaseName.ToLower() -eq $Query.ToLower() }
    if ($exactCI) { return $exactCI | Select-Object -First 1 }

    $norm = ($Query -replace '[\s\-_]', '').ToLower()
    $fuzzy = $all | Where-Object {
        $baseNorm = ($_.BaseName -replace '[\s\-_]', '').ToLower()
        $baseNorm -like "*$norm*" -or $norm -like "*$baseNorm*"
    } | Select-Object -First 1
    if ($fuzzy) { return $fuzzy }

    return $null
}

if (-not $ExtractOnly -and -not $LayoutType) {
    throw "Pass -LayoutType Supplier or -LayoutType Customer. This script runs non-interactively so it can't ask you which one you meant (an interactive Claude Code session would ask instead of guessing)."
}

Write-Host "Dimensional Layout - Part: $PartNumber"
if ($LayoutType) { Write-Host "Layout type:     $LayoutType" }

$pdf = Find-DrawingPdf -Query $PartNumber
if (-not $pdf) {
    throw "No matching drawing PDF found for '$PartNumber' in '$RootDir'."
}
Write-Host "Matched drawing: $($pdf.Name)"

$OutFolder = Join-Path $RootDir $PartNumber
New-Item -ItemType Directory -Force -Path $OutFolder | Out-Null
Write-Host "Output folder:   $OutFolder"

$PythonExe = Resolve-WorkingPython
Write-Host "Python:          $PythonExe"

if ($ExtractOnly) {
    $work = Join-Path $env:TEMP "dimensional-layout\$PartNumber"
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    & $PythonExe (Join-Path $SkillDir "scripts\extract_drawing.py") $pdf.FullName $work
    Write-Host ""
    Write-Host "Extraction-only complete. See: $work\extracted.json"
    return
}

$TemplateFile = if ($LayoutType -eq "Customer") { "Blank Customer DIM.xlsx" } else { "Blank Supplier DIM.xlsx" }
$TemplatePath = Join-Path $RootDir $TemplateFile
if (-not (Test-Path $TemplatePath)) {
    throw "Expected template not found: $TemplatePath"
}

$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    throw "claude CLI not found on PATH. Install/enable Claude Code, or run with -ExtractOnly and finish the workflow manually inside Claude Code."
}

$permMode = if ($BypassPermissions) { "bypassPermissions" } else { "acceptEdits" }

$prompt = @"
Use the dimensional-layout skill for "$PartNumber", $LayoutType layout.
Drawing PDF: $($pdf.FullName)
Excel template: $TemplatePath
Output folder (already created): $OutFolder
Follow the skill's workflow exactly, including: group multi-line callouts describing one physical feature into a single balloon; balloon only DAVCO Part No./Revision/Released inside the title-block box (plus the customer part-number callout wherever it actually appears, for later routing); route DAVCO Part Number/Revision/Released Date/Customer Part Number/Customer Name balloons to the correct $LayoutType template header fields instead of the dimensional table (gaps in the table's Item # column are expected and must not be closed by renumbering); save the ballooned PDF and completed "${PartNumber}_${LayoutType}_Layout.xlsx" into the output folder, plus a review log if anything is uncertain. Do not modify the original PDF or either blank Excel template.
"@

Push-Location $RootDir
try {
    if ($BypassPermissions) {
        & $claudeCmd.Source -p $prompt --permission-mode $permMode --add-dir $RootDir
    } else {
        & $claudeCmd.Source -p $prompt --permission-mode $permMode `
            --allowedTools "Bash Edit Write Read Glob Grep Skill TaskCreate TaskUpdate" `
            --add-dir $RootDir
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Check: $OutFolder"
