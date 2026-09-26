#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
lock_file="$repo_dir/infra/api-requirements.lock"
temp_file=$(mktemp "$repo_dir/infra/.api-requirements.lock.XXXXXX")
trap 'rm -f "$temp_file"' EXIT HUP INT TERM

docker run --rm -i \
  -v "$repo_dir/apps/api/pyproject.toml:/pyproject.toml:ro" \
  public.ecr.aws/docker/library/python:3.12-slim python - > "$temp_file" <<'PY'
import subprocess
import sys
import tomllib

with open("/pyproject.toml", "rb") as project_file:
    dependencies = tomllib.load(project_file)["project"]["dependencies"]

subprocess.check_call(
    [sys.executable, "-m", "pip", "install", "--no-cache-dir", "setuptools>=75", "wheel", *dependencies],
    stdout=sys.stderr,
)
subprocess.check_call([sys.executable, "-m", "pip", "check"], stdout=sys.stderr)
subprocess.check_call([sys.executable, "-m", "pip", "freeze", "--exclude-editable"])
PY

chmod 644 "$temp_file"
mv "$temp_file" "$lock_file"
