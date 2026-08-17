"""
layout_engine -- the callable interface onto the EXISTING, already-tuned
dimensional-layout system.

This package does not reimplement extraction, ballooning, or Excel
filling. It imports the three scripts that already live in
`.claude/skills/dimensional-layout/scripts/` (the same scripts the
interactive Claude Code skill uses) directly as Python modules, so there
is exactly one implementation of that logic shared by both the skill and
this web application. If those scripts are improved later (better
placement heuristics, new destinations, etc.), the web app picks the
change up automatically -- nothing here needs to change in lockstep.

Only `interpret.py` is new: it's the one piece of genuine judgment
(grouping callouts, deciding what's a title-block field vs. a dimension,
identifying the customer) that the existing system always relied on
Claude's own reading of the drawing for -- see PHASE 1 notes in
docs/ENGINE_NOTES.md. It calls the already-authenticated `claude` CLI
as a subprocess, scoped to a single tool-free structured-output request.
"""
import importlib.util
import sys
from pathlib import Path

from app.config import SKILL_SCRIPTS_DIR


def _load(module_name: str, filename: str):
    """Import a script from SKILL_SCRIPTS_DIR as a normal module, without
    copying its source. Cached in sys.modules like any other import."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = SKILL_SCRIPTS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Expected existing dimensional-layout script not found: {path}. "
            f"Set DIMENSIONAL_LAYOUT_SCRIPTS_DIR if the skill moved."
        )
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_extract_mod = _load("dimlayout_extract_drawing", "extract_drawing.py")
_balloons_mod = _load("dimlayout_create_balloons", "create_balloons.py")
_excel_mod = _load("dimlayout_fill_excel", "fill_excel.py")

# Re-exported callables -- exactly the functions the skill itself calls.
extract_drawing = _extract_mod.extract
draw_balloons = _balloons_mod.draw_balloons
fill_excel = _excel_mod.fill
