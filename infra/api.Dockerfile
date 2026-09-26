FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /workspace
COPY apps/api/pyproject.toml /workspace/apps/api/pyproject.toml
RUN python -c "import pathlib, subprocess, tomllib; p = tomllib.loads(pathlib.Path('/workspace/apps/api/pyproject.toml').read_text()); subprocess.check_call(['pip', 'install', '--no-cache-dir', 'setuptools>=75', 'wheel', *p['project']['dependencies'], *p['project']['optional-dependencies']['dev']])"
COPY apps/api/app /workspace/apps/api/app
RUN pip install --no-deps --no-build-isolation -e /workspace/apps/api
COPY apps/api/alembic /workspace/apps/api/alembic
COPY apps/api/alembic.ini /workspace/apps/api/alembic.ini
COPY apps/api/tests /workspace/apps/api/tests
COPY scripts /workspace/scripts
COPY examples /workspace/examples
COPY evals /workspace/evals
WORKDIR /workspace/apps/api
ENV PYTHONPATH=/workspace:/workspace/apps/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
