"""
FastAPI server with Featherless OAuth + static file serving.

Run:  python fastapi_server.py
Env:  FEATHERLESS_CLIENT_ID, FEATHERLESS_CLIENT_SECRET, FEATHERLESS_REDIRECT_URI
"""
import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import httpx

from src.auth_proxy import app as auth_app, _is_authenticated, _get_token


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# ── Main Application ─────────────────────────────────────────────────────────
app = FastAPI(title="ICT Options Agent")

# Include auth proxy routes
app.include_router(auth_app, prefix="")

# Serve static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# CORS for Streamlit if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Show login page."""
    authenticated = _is_authenticated(request)
    html_path = STATIC_DIR / "index.html"
    html = html_path.read_text()
    # Simple template replacement
    html = html.replace("{% if authenticated %}", f'{{% if {authenticated} %}}')
    return html


@app.get("/dashboard")
async def dashboard_redirect(request: Request):
    """Redirect to Streamlit dashboard if authenticated."""
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = _get_token(request)
    # Redirect to Streamlit with token in query (Streamlit will pick it up)
    streamlit_port = os.getenv("STREAMLIT_PORT", "8501")
    return f"http://localhost:{streamlit_port}?token={token}"


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "auth_proxy": "running"}


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("AUTH_HOST", "0.0.0.0")
    port = int(os.getenv("AUTH_PORT", "8000"))
    print(f"Starting ICT Options Agent server on http://{host}:{port}")
    print(f"  Login:      http://{host}:{port}/")
    print(f"  Health:     http://{host}:{port}/health")
    uvicorn.run(app, host=host, port=port, reload=False)
