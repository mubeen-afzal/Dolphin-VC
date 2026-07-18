import argparse
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a running VC Brain API")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", default="demo@vcbrain.dev")
    parser.add_argument("--password", default="Demo-password-42!")
    args = parser.parse_args()

    started = time.perf_counter()
    with httpx.Client(base_url=args.base_url, timeout=10) as client:
        health = client.get("/healthz")
        health.raise_for_status()
        login = client.post(
            "/api/v1/auth/login",
            json={"email": args.email, "password": args.password},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        opportunities = client.get("/api/v1/opportunities?limit=1", headers=headers)
        opportunities.raise_for_status()
        schema = client.get("/api/v1/openapi.json")
        schema.raise_for_status()
    elapsed = round((time.perf_counter() - started) * 1000)
    print(
        f"ok: health, auth, opportunities, and OpenAPI ({elapsed} ms; "
        f"{len(opportunities.json()['items'])} opportunity sample)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
