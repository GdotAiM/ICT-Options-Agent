"""
Featherless OAuth 2.0 Authentication Proxy

Provides login/logout endpoints for Streamlit dashboard access control.
Tokens stored in signed cookies (server-side only).

Endpoints:
  GET  /login          → Redirect to Featherless auth
  GET  /callback       → Exchange code for tokens
  POST /api/*          → Proxy authenticated requests to Featherless API
  GET  /logout         → Clear session cookies
"""
from __future__ import annotations
import os
import httpx
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Response, HTTPException, Cookie
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger

# ── Configuration (read from environment) ──────────────────────────────────────
FEATHERLESS_CLIENT_ID = os.getenv("FEATHERLESS_CLIENT_ID", "YOUR_CLIENT_ID")
FEATHERLESS_CLIENT_SECRET = os.getenv("FEATHERLESS_CLIENT_SECRET", "")
FEATHERLESS_REDIRECT_URI = os.getenv(
    "FEATHERLESS_REDIRECT_URI",
    "http://localhost:8000/callback",
)
FEATHERLESS_SCOPES = os.getenv("FEATHERLESS_SCOPES", "read write")
FEATHERLESS_API_BASE = "https://api.featherless.ai"

TOKEN_COOKIE_NAME = "ft_access_token"
SECRET_COOKIE_NAME = "ft_csrf_secret"
EXPIRY_COOKIE_NAME = "ft_token_expiry"

# Security: cookie lifetime
SESSION_MAX_AGE = 3600 * 24  # 24 hours
CSRF_SECRET_LENGTH = 32

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(title="ICT Options Agent — Auth Proxy")


def _make_state() -> str:
    """Generate CSRF protection state parameter."""
    return secrets.token_urlsafe(CSRF_SECRET_LENGTH)


def _set_token_cookies(
    response: Response,
    access_token: str,
    expires_in: int,
    csrf_secret: str,
) -> None:
    """Set secure cookies for token storage."""
    expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    response.set_cookie(
        key=TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=expires_in,
    )
    response.set_cookie(
        key=SECRET_COOKIE_NAME,
        value=csrf_secret,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )
    response.set_cookie(
        key=EXPIRY_COOKIE_NAME,
        value=expiry.isoformat(),
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )


def _clear_session(response: Response) -> None:
    """Remove all session cookies."""
    for name in [TOKEN_COOKIE_NAME, SECRET_COOKIE_NAME, EXPIRY_COOKIE_NAME]:
        response.delete_cookie(name)


def _is_authenticated(request: Request) -> bool:
    """Check if request has valid auth cookies."""
    token = request.cookies.get(TOKEN_COOKIE_NAME)
    expiry_str = request.cookies.get(EXPIRY_COOKIE_NAME)
    if not token or not expiry_str:
        return False
    try:
        expiry = datetime.fromisoformat(expiry_str)
        return expiry > datetime.utcnow()
    except (ValueError, TypeError):
        return False


def _get_token(request: Request) -> Optional[str]:
    """Extract access token from cookies."""
    return request.cookies.get(TOKEN_COOKIE_NAME)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/login")
async def login(request: Request):
    """Redirect user to Featherless authorization endpoint."""
    state = _make_state()
    params = urlencode({
        "client_id": FEATHERLESS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": FEATHERLESS_REDIRECT_URI,
        "scope": FEATHERLESS_SCOPES,
        "state": state,
    })
    auth_url = f"https://featherless.ai/oauth/authorize?{params}"

    resp = RedirectResponse(url=auth_url)
    # Store CSRF state in signed cookie
    resp.set_cookie(
        key="ft_auth_state",
        value=state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=300,  # 5 minutes
    )
    return resp


@app.get("/callback")
async def callback(request: Request):
    """Exchange authorization code for tokens."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        desc = request.query_params.get("error_description", error)
        raise HTTPException(status_code=400, detail=f"Auth denied: {desc}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Verify CSRF state
    stored_state = request.cookies.get("ft_auth_state")
    if not stored_state or state != stored_state:
        raise HTTPException(status_code=403, detail="Invalid or expired CSRF state")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "https://api.featherless.ai/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": FEATHERLESS_CLIENT_ID,
                    "client_secret": FEATHERLESS_CLIENT_SECRET,
                    "redirect_uri": FEATHERLESS_REDIRECT_URI,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            token_data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Token exchange failed: {e.response.text}")
            raise HTTPException(status_code=500, detail="Failed to authenticate")
        except Exception as e:
            logger.error(f"Token exchange error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        raise HTTPException(status_code=500, detail="No access token received")

    # Build redirect back to Streamlit with auth cookies
    csrf_secret = secrets.token_urlsafe(CSRF_SECRET_LENGTH)
    target = request.query_params.get("redirect", "/")

    resp = RedirectResponse(url=target)
    _set_token_cookies(resp, access_token, expires_in, csrf_secret)
    return resp


@app.post("/api/{path:path}")
async def api_proxy(path: str, request: Request):
    """Proxy authenticated requests to Featherless API."""
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = _get_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="No access token")

    # Forward the request to Featherless API
    api_url = f"{FEATHERLESS_API_BASE}/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    # Copy relevant headers
    for header in ["accept", "authorization", "content-type"]:
        if request.headers.get(header):
            headers[header] = request.headers[header]

    method = request.method.upper()
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.request(
                method=method,
                url=api_url,
                headers=headers,
                content=body,
                timeout=30.0,
            )
            return JSONResponse(
                content=resp.json() if resp.headers.get("content-type") == "application/json" else {"raw": resp.text},
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"API proxy error: {e.response.status_code} {e.response.text[:200]}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=e.response.text[:500],
            )


@app.post("/logout")
async def logout(request: Request, response: Response):
    """Clear session cookies and redirect to login."""
    _clear_session(response)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/status")
async def status(request: Request):
    """Check authentication status."""
    authenticated = _is_authenticated(request)
    return {
        "authenticated": authenticated,
        "client_id": FEATHERLESS_CLIENT_ID,
        "redirect_uri": FEATHERLESS_REDIRECT_URI,
    }
