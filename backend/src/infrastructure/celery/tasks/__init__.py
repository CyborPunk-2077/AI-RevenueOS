"""Task modules. Importing this package registers every task on the app."""

from __future__ import annotations

from infrastructure.celery.tasks import files, maintenance, scheduled, webhook, workflow

__all__ = ["files", "maintenance", "scheduled", "webhook", "workflow"]
