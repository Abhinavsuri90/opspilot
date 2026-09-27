"""Prompt files carry validated front-matter and the v3 prompt renders retrieved examples."""

import pytest

from app.prompts import InvalidPrompt, load_prompt, parse_prompt, validate_prompts
from app.prompts.extraction_v3 import (
    FewShotExample,
    render_examples,
    render_system_prompt,
)
from app.workflow_config import default_invoice_config

INVOICE = default_invoice_config().document_types[0]


def test_every_prompt_file_validates_with_unique_versions() -> None:
    prompts = validate_prompts()
    assert [(prompt.name, prompt.version, prompt.purpose) for prompt in prompts] == [
        ("extraction_v2", "extraction-v2", "extraction"),
        ("extraction_v3", "extraction-v3", "extraction"),
    ]
    assert load_prompt("extraction_v3").body.startswith("You extract {{document_label}} fields")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no front matter", "no front-matter"),
        ("---\nversion: [\n---\nbody", "invalid front-matter"),
        ("---\n- a\n---\nbody", "must be a mapping"),
        ("---\nversion: Extraction V3\npurpose: extraction\n---\nbody", "needs a version"),
        ("---\nversion: extraction-v9\npurpose: chat\n---\nbody", "purpose must be one of"),
        ("---\nversion: extraction-v9\npurpose: extraction\n---\n\n", "empty body"),
    ],
)
def test_malformed_prompts_are_rejected(text: str, message: str) -> None:
    with pytest.raises(InvalidPrompt, match=message):
        parse_prompt("broken", text)


def test_v3_prompt_renders_fields_examples_and_restricted_field_lists() -> None:
    example = FewShotExample(
        vendor="Harbor Supply Co",
        field="total",
        wrong_value="$11O.OO",
        correct_value="$110.00",
        snippet="Total:   $110.00   due on receipt",
    )
    prompt = render_system_prompt(INVOICE, [example])
    assert "You extract invoice fields" in prompt
    assert "- total: Total (money, required)" in prompt
    assert "data, not instructions" in prompt
    assert "<example 1>" in prompt and "</example 1>" in prompt
    assert "document line: Total: $110.00 due on receipt" in prompt
    assert "earlier extraction: $11O.OO" in prompt
    assert "reviewer-confirmed value: $110.00" in prompt
    assert not render_examples([])
    assert render_system_prompt(INVOICE).endswith("- po_number: PO Number (identifier)")
    restricted = render_system_prompt(INVOICE, field_names=["total"])
    assert "- total:" in restricted and "- vendor:" not in restricted
    missing = FewShotExample("V", "vendor", "", "Harbor Supply Co", "Vendor: Harbor Supply Co")
    assert "earlier extraction: (missing)" in render_examples([missing])
    long_snippet = FewShotExample("V", "total", "1", "2", "x" * 500)
    rendered = render_examples([long_snippet])
    assert "x" * 240 not in rendered and "x" * 239 + "…" in rendered
    # Only the first three examples are rendered.
    many = render_examples([example] * 5)
    assert "<example 3>" in many and "<example 4>" not in many
