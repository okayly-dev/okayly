"""Run: .venv/bin/uvicorn app.main:app --port 8000
Env: DRAFTER=fixture|muse (default fixture, no spend), MODEL_API_KEY, DB_PATH, DEMO_CONTROLS=1"""
from .api import create_app

app = create_app()
