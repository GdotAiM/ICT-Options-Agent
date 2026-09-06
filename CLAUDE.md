# ICT-Options-Agent — Deploy Configuration

## Deploy Configuration (configured by /setup-deploy)
- Platform: Docker + GitHub Actions (GHCR)
- Production URL: https://<your-domain-or-render-url>
- Deploy workflow: .github/workflows/deploy.yml (push to main triggers build + push to GHCR)
- Deploy status command: `curl -sf https://<host>/health`
- Merge method: squash
- Project type: Python FastAPI + Streamlit (paper trading agent)
- Post-deploy health check: GET /health → `{"status":"ok"}`

### Custom deploy hooks
- Pre-merge: none
- Deploy trigger: automatic on push to main
- Deploy status: poll `https://<host>/health` every 30s until 200
- Health check: http://localhost:8000/health (container exit code 0)
- Registry: ghcr.io/gdotaim/ict-options-agent
- Base image: python:3.14-slim
- Exposed ports: 8000 (FastAPI/auth), 8501 (Streamlit dashboard)
- Required env vars at deploy time: ALPACA_API_KEY, ALPACA_SECRET_KEY, LLM_API_KEY, OPENAI_API_KEY
