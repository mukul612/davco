"""
Central configuration, read from environment variables (and an optional
.env file loaded by start-server.ps1 / python-dotenv if present). Nothing
here is a secret by default -- if APP_PASSWORD or ANTHROPIC_API_KEY are
set, they come from the environment, never from source.
"""
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent  # .../webapp

# Where the original, unmodified dimensional-layout skill and its scripts
# live. We import its functions directly rather than copying the code, so
# there is exactly one implementation of the ballooning/Excel logic.
SKILL_SCRIPTS_DIR = Path(
    os.environ.get(
        "DIMENSIONAL_LAYOUT_SCRIPTS_DIR",
        APP_ROOT.parent / ".claude" / "skills" / "dimensional-layout" / "scripts",
    )
)

TEMPLATES_LAYOUT_DIR = APP_ROOT / "templates_layout"
SUPPLIER_TEMPLATE = TEMPLATES_LAYOUT_DIR / "Blank Supplier DIM.xlsx"
CUSTOMER_TEMPLATE = TEMPLATES_LAYOUT_DIR / "Blank Customer DIM.xlsx"

JOBS_DIR = Path(os.environ.get("JOBS_DIR", APP_ROOT / "jobs"))
LOGS_DIR = Path(os.environ.get("LOGS_DIR", APP_ROOT / "logs"))

APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "8000"))

JOB_RETENTION_HOURS = float(os.environ.get("JOB_RETENTION_HOURS", "24"))
CLEANUP_INTERVAL_MINUTES = float(os.environ.get("CLEANUP_INTERVAL_MINUTES", "30"))

MAX_UPLOAD_MB = float(os.environ.get("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)

# Optional shared-password gate for the whole app (see app/services/auth.py).
# Blank/unset = no authentication (fine for a trusted internal LAN in v1).
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()

# If set, this is exported into the claude CLI subprocess's environment so
# it authenticates with a plain API key instead of its normal interactive
# login/session. Leave unset to use whatever auth the `claude` CLI already
# has configured on this machine (the common case for an internal tool run
# from a developer/service workstation that's already `claude`-authenticated).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
# The interpretation call runs at --effort high for completeness (a missed
# dimension matters far more than an extra minute of wait for this tool).
# Observed ~110-210s for a single-page drawing with ~230 text lines --
# 300s leaves comfortable headroom without letting a truly stuck call hang
# the job forever.
CLAUDE_TIMEOUT_SECONDS = float(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "300"))

DEBUG = os.environ.get("DEBUG", "false").strip().lower() in ("1", "true", "yes")

for _d in (JOBS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
