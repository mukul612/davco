"""HTML page routes: the main app page, and a minimal login page used
only when APP_PASSWORD is configured."""
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.auth import COOKIE_NAME, auth_enabled, check_password

router = APIRouter()

_WEB_DIR = Path(__file__).resolve().parent.parent / "templates_web"


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if auth_enabled() and not check_password(request.cookies.get(COOKIE_NAME, "")):
        return RedirectResponse(url="/login")
    return HTMLResponse((_WEB_DIR / "index.html").read_text(encoding="utf-8"))


@router.get("/login", response_class=HTMLResponse)
async def login_form(error: str | None = None):
    html = (_WEB_DIR / "login.html").read_text(encoding="utf-8")
    if error:
        html = html.replace(
            "<!--ERROR-->",
            '<p class="error">Incorrect password.</p>',
        )
    return HTMLResponse(html)


@router.post("/login")
async def login_submit(password: str = Form(...)):
    if not check_password(password):
        return RedirectResponse(url="/login?error=1", status_code=303)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(COOKIE_NAME, password, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp
