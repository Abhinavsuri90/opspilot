"""Smoke-test a running API using the fictional demo account."""

import argparse
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "base_url", help="API base URL, for example http://localhost:8000"
    )
    args = parser.parse_args()
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        print("Set DEMO_PASSWORD before running the smoke test", file=sys.stderr)
        return 2
    with httpx.Client(base_url=args.base_url, timeout=10) as client:
        for path in ("/healthz", "/readyz"):
            response = client.get(path)
            response.raise_for_status()
        login = client.post(
            "/v1/auth/login",
            json={
                "org_slug": "northwind",
                "email": "northwind@example.com",
                "password": password,
            },
        )
        login.raise_for_status()
        me = client.get("/v1/auth/me")
        me.raise_for_status()
        assert me.json()["org_name"] == "Northwind Traders"
    print("Health, readiness, login and current session passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
