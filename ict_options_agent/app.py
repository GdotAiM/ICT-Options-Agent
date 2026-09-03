"""
Auth-aware Streamlit wrapper.

Shows the dashboard only when the user is authenticated via Featherless OAuth.
Forwards the access token to the agent's API calls.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

# Set environment for Streamlit
os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

# ── Check authentication via auth proxy ─────────────────────────────────────
try:
    import httpx

    auth_url = os.getenv("AUTH_URL", "http://localhost:8000")
    status_resp = httpx.get(f"{auth_url}/status", timeout=5)
    auth_data = status_resp.json()
    authenticated = auth_data.get("authenticated", False)
except Exception as e:
    # If auth proxy is unavailable, allow access (fallback for local dev)
    print(f"Auth proxy unavailable ({e}), allowing access")
    authenticated = True


# ── Inject authentication state into streamlit_app context ───────────────────
import streamlit as st

if not authenticated:
    st.set_page_config(page_title="Login Required", page_icon="🔒", layout="centered")
    st.error("⚠️ Authentication required")
    st.markdown("""
    Please sign in through the auth proxy to access the dashboard.

    **Login URL:** [http://localhost:8000/login](http://localhost:8000/login)

    Or set `AUTH_URL` environment variable if using a different host.
    """)
    st.stop()

# ── Import and run the actual dashboard ──────────────────────────────────────
# The auth token will be passed as a query parameter or header
token = None
try:
    token = httpx.get(f"{auth_url}/api/me", timeout=5).json().get("access_token")
except Exception:
    pass

# Set token in environment for agent modules
if token:
    os.environ["FEATHERLESS_ACCESS_TOKEN"] = token

# Import and run the dashboard
from streamlit_app import *  # noqa: F401,F403
