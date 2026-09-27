"""Versioned prompt templates. Each prompt module exposes PROMPT_VERSION and its text."""

from importlib import resources


def load_prompt(name: str) -> str:
    """Read ``app/prompts/<name>.md`` so prompt text is reviewed like code."""
    return resources.files(__name__).joinpath(f"{name}.md").read_text(encoding="utf-8").strip()
