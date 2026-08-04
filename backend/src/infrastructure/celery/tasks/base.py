"""Shared task decorator applying context, retry policy and dead lettering."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind

from infrastructure.celery.app import TenantTask, app
from infrastructure.celery.context import bound_context, headers_from_request
from infrastructure.celery.queues import BY_NAME, DEFAULT_QUEUE, queue_for
from infrastructure.celery.reliability import (
    DEFAULT_MAX_ATTEMPTS,
    DeadLetterRecord,
    classify_exception,
    is_retryable,
    record_retry,
    retry_delay,
    write_dead_letter,
)
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import start_span

logger = get_logger("celery.tasks")


def airev_task(
    name: str,
    *,
    tenant_scoped: bool = True,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    queue: str | None = None,
) -> Callable[[Callable[..., Any]], Any]:
    """Register an async function as a Celery task with the platform's guarantees.

    The wrapped function is a coroutine. It receives the bound `TaskContext` as its
    first argument, so a task can never accidentally run without knowing which
    tenant it belongs to.
    """

    resolved_queue = queue or queue_for(name)
    spec = BY_NAME.get(resolved_queue, BY_NAME[DEFAULT_QUEUE])

    def decorator(fn: Callable[..., Any]) -> Any:
        @app.task(
            name=name,
            base=TenantTask,
            bind=True,
            queue=resolved_queue,
            time_limit=spec.timeout_seconds,
            soft_time_limit=spec.soft_timeout_seconds,
            max_retries=max_attempts - 1,
        )
        @functools.wraps(fn)
        def wrapper(self: TenantTask, *args: Any, **kwargs: Any) -> Any:
            context = headers_from_request(self.request)
            attempt = int(getattr(self.request, "retries", 0)) + 1

            raw_headers = getattr(self.request, "headers", None)
            carrier = (
                {k: v for k, v in raw_headers.items() if isinstance(v, str)}
                if isinstance(raw_headers, dict)
                else {}
            )

            with (
                bound_context(context),
                start_span(
                    f"task {name}",
                    kind=SpanKind.CONSUMER,
                    context=extract(carrier),
                    attributes={
                        "task.name": name,
                        "task.attempt": attempt,
                        "messaging.operation": "process",
                        "messaging.destination.name": resolved_queue,
                        "tenant.id": str(context.tenant_id) if context.tenant_id else None,
                        "correlation.id": context.correlation_id,
                    },
                ),
            ):
                if tenant_scoped:
                    # Fails closed: no tenant header means no RLS predicate.
                    context.require_tenant()
                try:
                    return self.run_async(fn(context, *args, **kwargs))
                except Exception as exc:
                    retry_class = classify_exception(exc)
                    record_retry(name, resolved_queue, retry_class)

                    if is_retryable(exc, attempt, max_attempts):
                        delay = retry_delay(exc, attempt)
                        logger.warning(
                            "task_will_retry",
                            task=name,
                            attempt=attempt,
                            retry_class=retry_class.value,
                            delay_seconds=round(delay, 2),
                        )
                        raise self.retry(exc=exc, countdown=delay) from exc

                    self.run_async(
                        write_dead_letter(
                            DeadLetterRecord(
                                queue=resolved_queue,
                                task_name=name,
                                payload={
                                    "args": list(args),
                                    "kwargs": dict(kwargs),
                                    "correlation_id": context.correlation_id,
                                    "retry_class": retry_class.value,
                                },
                                error=f"{type(exc).__name__}: {exc}",
                                attempts=attempt,
                                tenant_id=context.tenant_id,
                            )
                        )
                    )
                    raise

        wrapper.tenant_scoped = tenant_scoped
        return wrapper

    return decorator
