# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

FROM base AS deps-runtime
COPY requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements.lock

FROM base AS deps-development
COPY requirements-dev.lock ./
RUN pip install --require-hashes --no-deps -r requirements-dev.lock

FROM deps-development AS development
# `pg_dump` for the local safety snapshot taken before any destructive demo
# maintenance. Development only: the production image has no business carrying a
# tool that can read the whole database to a file.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--app-dir", "src"]

FROM base AS production
# Non-root by construction; the image carries no secret of any kind.
RUN useradd --create-home --uid 10001 appuser
COPY --from=deps-runtime /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps-runtime /usr/local/bin /usr/local/bin
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health/liveness')"
CMD ["gunicorn", "main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", "--bind", "0.0.0.0:8000", \
     "--timeout", "60", "--graceful-timeout", "30", "--max-requests", "2000", \
     "--max-requests-jitter", "200", "--access-logfile", "-", "--chdir", "src"]
