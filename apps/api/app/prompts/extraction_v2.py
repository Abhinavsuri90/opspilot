"""Extraction prompt v2: configuration-driven fields with self-reported confidence."""

from app.prompts import load_prompt
from app.workflow_config import DocumentTypeSpec

PROMPT_VERSION = "extraction-v2"
SYSTEM_PROMPT = load_prompt("extraction_v2")


def render_system_prompt(type_spec: DocumentTypeSpec) -> str:
    lines = []
    for field in type_spec.fields:
        note = f"{field.name}: {field.label} ({field.type}"
        if field.required:
            note += ", required"
        if field.enum:
            note += ", one of " + ", ".join(field.enum)
        lines.append(note + ")")
    return SYSTEM_PROMPT.replace("{{document_label}}", type_spec.label.lower()).replace(
        "{{fields}}", "\n".join(f"- {line}" for line in lines)
    )
