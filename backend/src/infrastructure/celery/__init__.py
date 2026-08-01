"""Celery worker tier.

`docker-compose.yml` and the Makefile invoke `celery -A infrastructure.celery.app`,
so this package is the deployment contract for every asynchronous worker.
"""

from __future__ import annotations

from infrastructure.celery.app import app

__all__ = ["app"]
