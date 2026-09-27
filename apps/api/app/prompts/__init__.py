"""Versioned prompt templates.

Every prompt lives in ``app/prompts/<name>.md`` behind a YAML front-matter block that
names its ``version`` and ``purpose``; the version is what ``extraction_runs`` and
``llm_calls`` record, so a prompt change is visible in the ledger. :func:`validate_prompts`
checks the whole directory (unique versions, known purposes, non-empty bodies) and runs in
the test suite so a malformed prompt never reaches a deploy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources

import yaml

PURPOSES = ("extraction", "escalation", "embedding", "agent")
VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9]*-v\d+$")
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.S)


class InvalidPrompt(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    purpose: str
    body: str


def parse_prompt(name: str, text: str) -> Prompt:
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise InvalidPrompt(f"Prompt {name} has no front-matter block")
    try:
        header = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise InvalidPrompt(f"Prompt {name} has invalid front-matter: {exc}") from exc
    if not isinstance(header, dict):
        raise InvalidPrompt(f"Prompt {name} front-matter must be a mapping")
    version, purpose = header.get("version"), header.get("purpose")
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise InvalidPrompt(f"Prompt {name} needs a version such as extraction-v3")
    if purpose not in PURPOSES:
        raise InvalidPrompt(f"Prompt {name} purpose must be one of {', '.join(PURPOSES)}")
    body = match.group(2).strip()
    if not body:
        raise InvalidPrompt(f"Prompt {name} has an empty body")
    return Prompt(name=name, version=version, purpose=str(purpose), body=body)


def load_prompt(name: str) -> Prompt:
    """Read and validate ``app/prompts/<name>.md`` so prompt text is reviewed like code."""
    text = resources.files(__name__).joinpath(f"{name}.md").read_text(encoding="utf-8")
    return parse_prompt(name, text)


def validate_prompts() -> list[Prompt]:
    """Load every prompt file and reject duplicate versions; returns them sorted by name."""
    prompts = []
    for entry in resources.files(__name__).iterdir():
        if entry.name.endswith(".md"):
            prompts.append(parse_prompt(entry.name[:-3], entry.read_text(encoding="utf-8")))
    versions = [prompt.version for prompt in prompts]
    duplicates = sorted({version for version in versions if versions.count(version) > 1})
    if duplicates:
        raise InvalidPrompt(f"Duplicate prompt versions: {', '.join(duplicates)}")
    return sorted(prompts, key=lambda prompt: prompt.name)
