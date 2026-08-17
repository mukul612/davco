import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Allow `import app.xxx` whether this is launched as `python -m app.main`
# from the webapp/ directory or via uvicorn's app.main:app string target.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import DEBUG, LOGS_DIR, CLEANUP_INTERVAL_MINUTES, JOB_RETENTION_HOURS
from app.routes import jobs, pages
from app.services.job_manager import start_cleanup_thread

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("dimlayout")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info(
        "Dimensional Layout Generator starting up (retention=%sh, cleanup every %smin)",
        JOB_RETENTION_HOURS, CLEANUP_INTERVAL_MINUTES,
    )
    start_cleanup_thread(CLEANUP_INTERVAL_MINUTES)
    yield


app = FastAPI(title="Dimensional Layout Generator", debug=DEBUG, lifespan=lifespan)

app.include_router(pages.router)
app.include_router(jobs.router)

_static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
