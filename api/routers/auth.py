"""Login and logout routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import ROOT_DIR, get_settings
from services import auth_service

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, error: str = "") -> HTMLResponse:
    """Render the login form."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error, "auth_enabled": auth_service.auth_is_enabled()},
    )


@router.post("/login", include_in_schema=False, response_model=None)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Validate credentials and set the session cookie."""
    settings = get_settings()
    if not auth_service.auth_is_enabled():
        return RedirectResponse(url="/", status_code=302)

    if username == settings.mission_control_username and auth_service.verify_password(
        password, auth_service.get_password_hash()
    ):
        token = await auth_service.create_session(username)
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="session_token",
            value=token,
            max_age=auth_service.session_max_age_seconds(),
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="lax",
        )
        return response

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": "Invalid username or password",
            "auth_enabled": True,
        },
        status_code=401,
    )


@router.get("/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    """Clear the session cookie and redirect to login."""
    await auth_service.delete_session(request.cookies.get("session_token"))
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response
