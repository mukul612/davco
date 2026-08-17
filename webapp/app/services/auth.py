"""
Optional shared-password gate, controlled entirely by the APP_PASSWORD
environment variable. If it's unset/blank, the app requires no
authentication (acceptable for v1 on a trusted internal LAN). If set,
every request must carry it as a Bearer token or an `app_auth` cookie
(set by the login form) equal to APP_PASSWORD.

This is intentionally minimal -- one shared password, no accounts, no
roles -- per the brief ("structure so auth can be added easily... do not
build a complex account/role-management system yet").
"""
import hmac

from fastapi import Cookie, Header, HTTPException, status

from app.config import APP_PASSWORD

COOKIE_NAME = "dimlayout_auth"


def auth_enabled() -> bool:
    return bool(APP_PASSWORD)


def check_password(candidate: str) -> bool:
    return hmac.compare_digest(candidate or "", APP_PASSWORD)


async def require_auth(
    dimlayout_auth: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    if not auth_enabled():
        return
    token = dimlayout_auth
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not token or not check_password(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
