"""Thin ASGI entrypoint: `uvicorn app.api:app`. All wiring lives in bootstrap."""

from app.bootstrap import create_app

app = create_app()
