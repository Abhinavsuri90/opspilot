"""Create a small, repeatable local workspace story through the real HTTP API.

The account seed runs first. This script uploads fictional PDFs, waits for the worker,
sets categories and verified amounts, adds team comments and approves one invoice per
organization. Existing records and manual edits are retained on later runs.
"""

import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

EXAMPLES = Path("/workspace/examples/demo")


@dataclass(frozen=True)
class Example:
    filename: str
    category: str
    amount: str
    approve: bool
    comment: str


DEMO: dict[str, tuple[str, str, str, tuple[Example, ...]]] = {
    "northwind": (
        "northwind@example.com",
        "northwind.reviewer@example.com",
        "northwind.member@example.com",
        (
            Example(
                "northwind-harbor-supply.pdf",
                "Office supplies",
                "187.40",
                True,
                "Purchase order checked; Harbor Supply can be approved.",
            ),
            Example(
                "northwind-maple-office.pdf",
                "Facilities",
                "942.15",
                False,
                "Please check the equipment line before approving.",
            ),
        ),
    ),
    "contoso": (
        "contoso.admin@example.com",
        "contoso@example.com",
        "contoso.member@example.com",
        (
            Example(
                "contoso-cedar-freight.pdf",
                "Freight",
                "356.80",
                True,
                "Freight charge checked against the delivery note.",
            ),
            Example(
                "contoso-blue-ridge-parts.pdf",
                "Parts",
                "1284.32",
                False,
                "Awaiting confirmation from the receiving team.",
            ),
        ),
    ),
}

CATEGORY_DESCRIPTIONS = {
    "Office supplies": "Stationery and consumable workplace supplies",
    "Facilities": "Furniture and workplace equipment",
    "Freight": "Transport and delivery services",
    "Parts": "Purchased parts and materials",
}


def checked(response: httpx.Response) -> Any:
    if response.is_error:
        location = f"{response.request.method} {response.request.url.path}"
        raise RuntimeError(
            f"{location} returned HTTP {response.status_code}: {response.text[:250]}"
        )
    return response.json()


def login(base_url: str, slug: str, email: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=25)
    try:
        checked(
            client.post(
                "/v1/auth/login", json={"org_slug": slug, "email": email, "password": password}
            )
        )
    except Exception:
        client.close()
        raise
    return client


def ensure_categories(admin: httpx.Client, examples: tuple[Example, ...]) -> dict[str, str]:
    current = {item["name"]: item["id"] for item in checked(admin.get("/v1/categories"))}
    for item in examples:
        if item.category not in current:
            created = checked(
                admin.post(
                    "/v1/categories",
                    json={
                        "name": item.category,
                        "description": CATEGORY_DESCRIPTIONS[item.category],
                    },
                )
            )
            current[item.category] = created["id"]
    return current


def wait_for_review(admin: httpx.Client, document_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        document = checked(admin.get(f"/v1/documents/{document_id}"))
        if document["status"] in {"needs_review", "approved", "rejected"}:
            return cast(dict[str, Any], document)
        if document["status"] == "failed":
            raise RuntimeError(
                f"Demo document {document_id} failed extraction: {document.get('failure_reason')}"
            )
        time.sleep(2)
    raise RuntimeError(f"Demo document {document_id} did not reach review within 90 seconds")


def seed_org(
    base_url: str, slug: str, password: str, team: tuple[str, str, str, tuple[Example, ...]]
) -> None:
    admin_email, reviewer_email, member_email, examples = team
    with (
        login(base_url, slug, admin_email, password) as admin,
        login(base_url, slug, reviewer_email, password) as reviewer,
        login(base_url, slug, member_email, password) as member,
    ):
        categories = ensure_categories(admin, examples)
        collaborators = checked(admin.get("/v1/organization/collaborators"))
        reviewer_id = next(
            row["user_id"] for row in collaborators if row["email"] == reviewer_email
        )
        for example in examples:
            pdf = EXAMPLES.joinpath(example.filename).read_bytes()
            uploaded = checked(
                admin.post(
                    "/v1/documents", files={"file": (example.filename, pdf, "application/pdf")}
                )
            )
            document_id = uploaded["id"]
            document = wait_for_review(admin, document_id)
            if document["status"] == "needs_review":
                workspace = checked(admin.get(f"/v1/documents/{document_id}/workspace"))
                update: dict[str, Any] = {"version": workspace["version"]}
                if workspace["category_id"] is None:
                    update["category_id"] = categories[example.category]
                if workspace["assigned_reviewer_id"] is None:
                    update["assigned_reviewer_id"] = reviewer_id
                if workspace["verified_amount"] is None:
                    update["verified_amount"] = example.amount
                    update["currency"] = "USD"
                if len(update) > 1:
                    workspace = checked(
                        admin.post(f"/v1/documents/{document_id}/metadata", json=update)
                    )
            else:
                workspace = checked(admin.get(f"/v1/documents/{document_id}/workspace"))
            if not any(comment["body"] == example.comment for comment in workspace["comments"]):
                workspace = checked(
                    member.post(
                        f"/v1/documents/{document_id}/comments", json={"body": example.comment}
                    )
                )
            if example.approve and document["status"] == "needs_review":
                checked(
                    reviewer.post(
                        f"/v1/documents/{document_id}/review",
                        json={
                            "version": workspace["version"],
                            "decision": "approve",
                            "comment": "Verified against the source PDF and team note.",
                        },
                    )
                )
            status = "approved" if example.approve else "awaiting review"
            print(f"{slug}: {example.filename} ({status})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Internal API URL, for example http://api:8000")
    args = parser.parse_args()
    if os.environ.get("ENVIRONMENT", "development") != "development":
        raise RuntimeError("Fictional demo activity may only be seeded in development")
    password = os.environ["DEMO_PASSWORD"]
    for slug, team in DEMO.items():
        seed_org(args.base_url, slug, password, team)
    print("Demo activity ready. Sign in as northwind@example.com or contoso.admin@example.com.")


if __name__ == "__main__":
    main()
