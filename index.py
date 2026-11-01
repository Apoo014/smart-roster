"""Vercel entrypoint: Vercel looks for an ASGI object named `app` in index.py."""
from backend.app.main import app  # noqa: F401
