"""ASGI entrypoint: `uvicorn main:app`."""

from __future__ import annotations

from api.app.factory import create_app

app = create_app()
