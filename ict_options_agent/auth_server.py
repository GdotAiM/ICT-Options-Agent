"""
FastAPI application entry point for ICT Options Agent.

Starts the Featherless OAuth auth proxy alongside optional Streamlit serving.
"""
import os
import uvicorn
from src.auth_proxy import app as auth_app


def main():
    host = os.getenv("AUTH_HOST", "0.0.0.0")
    port = int(os.getenv("AUTH_PORT", "8000"))
    reload = os.getenv("AUTH_RELOAD", "false").lower() == "true"

    print(f"Starting auth proxy on http://{host}:{port}")
    print(f"Featherless Client ID: {os.getenv('FEATHERLESS_CLIENT_ID', 'NOT SET')[:10]}...")
    print(f"Redirect URI: {os.getenv('FEATHERLESS_REDIRECT_URI', 'NOT SET')}")
    print("\nEndpoints:")
    print("  GET  /login      - Start OAuth flow")
    print("  GET  /callback   - Handle OAuth callback")
    print("  POST /api/*      - Proxy to Featherless API")
    print("  GET  /status     - Check auth status")
    print("  POST /logout     - Clear session")

    uvicorn.run(
        auth_app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
