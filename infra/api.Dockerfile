FROM public.ecr.aws/docker/library/python:3.12-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace:/workspace/apps/api

WORKDIR /workspace
COPY apps/api/pyproject.toml /workspace/apps/api/pyproject.toml
COPY infra/api-requirements.lock /workspace/infra/api-requirements.lock
RUN pip install --no-cache-dir -r /workspace/infra/api-requirements.lock

FROM deps AS base
COPY apps/api/app /workspace/apps/api/app
RUN pip install --no-deps --no-build-isolation -e /workspace/apps/api && pip check
COPY apps/api/alembic /workspace/apps/api/alembic
COPY apps/api/alembic.ini /workspace/apps/api/alembic.ini
COPY scripts/__init__.py scripts/seed.py /workspace/scripts/

WORKDIR /workspace/apps/api
EXPOSE 8000
# Forwarded client addresses are resolved in app/client_ip.py, which only trusts
# X-Forwarded-For from private-network peers and uses the edge-appended entry.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM deps AS development
# Development tooling is installed before the application code is copied, so an
# application change never re-downloads mypy, pytest and ruff.
RUN python -c "import pathlib, subprocess, tomllib; p = tomllib.loads(pathlib.Path('/workspace/apps/api/pyproject.toml').read_text()); subprocess.check_call(['pip', 'install', '--no-cache-dir', *p['project']['optional-dependencies']['dev']])"
COPY apps/api/app /workspace/apps/api/app
RUN pip install --no-deps --no-build-isolation -e /workspace/apps/api && pip check
COPY apps/api/alembic /workspace/apps/api/alembic
COPY apps/api/alembic.ini /workspace/apps/api/alembic.ini
COPY apps/api/tests /workspace/apps/api/tests
COPY scripts /workspace/scripts
COPY examples /workspace/examples
COPY evals /workspace/evals

WORKDIR /workspace/apps/api
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM base AS runtime
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin opspilot
USER opspilot
