"""Task modules. Importing this package registers every task on the app."""

from __future__ import annotations

from infrastructure.celery.tasks import maintenance, scheduled, webhook, workflow

__all__ = ["maintenance", "scheduled", "webhook", "workflow"]
