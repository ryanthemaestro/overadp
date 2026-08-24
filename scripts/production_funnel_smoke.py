#!/usr/bin/env python3
"""No-charge smoke test for the deployed signup-to-checkout funnel.

The test creates an already-confirmed disposable account, verifies login and
session restoration, asks Stripe for a hosted checkout session, and then
removes the test account and marketing-list row. It never submits payment.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


@dataclass
class Response:
    status: int
    body: dict[str, Any]


class SmokeFailure(RuntimeError):
    pass


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 25,
) -> Response:
    request_headers = {"Accept": "application/json", **(headers or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as result:
            raw = result.read().decode("utf-8")
            return Response(result.status, json.loads(raw) if raw else {})
    except HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"error": raw[:300]}
        return Response(error.code, body)
    except URLError as error:
        raise SmokeFailure(f"Request failed for {url}: {error.reason}") from error


def get_text(url: str, timeout: float = 25) -> tuple[int, str]:
    try:
        with urlopen(Request(url, headers={"Accept": "text/html"}), timeout=timeout) as result:
            return result.status, result.read().decode("utf-8")
    except (HTTPError, URLError) as error:
        raise SmokeFailure(f"Could not load {url}: {error}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def netlify_environment(name: str) -> str:
    try:
        value = subprocess.check_output(
            [
                "netlify",
                "env:get",
                name,
                "--context",
                "production",
                "--scope",
                "functions",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise SmokeFailure(f"Could not read {name} from the linked Netlify site") from error
    require(bool(value), f"Netlify returned an empty {name}")
    return value


def cleanup_test_records(
    supabase_url: str,
    service_key: str,
    user_id: str,
    email: str,
) -> None:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Prefer": "return=minimal",
    }
    email_filter = quote(f"eq.{email}", safe=".@+-_")
    email_row = request_json(
        f"{supabase_url.rstrip('/')}/rest/v1/email_list?email={email_filter}",
        method="DELETE",
        headers=headers,
    )
    require(email_row.status in {200, 204}, f"Test email cleanup returned {email_row.status}")
    user = request_json(
        f"{supabase_url.rstrip('/')}/auth/v1/admin/users/{quote(user_id)}",
        method="DELETE",
        headers=headers,
    )
    require(user.status == 200, f"Test user cleanup returned {user.status}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://overadp.com")
    parser.add_argument(
        "--email-domain",
        default="overadp.com",
        help="Domain used for the disposable QA account",
    )
    parser.add_argument(
        "--netlify-env",
        action="store_true",
        help="Read cleanup credentials from the linked Netlify production site",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    email = f"qa+funnel-smoke-{stamp}@{args.email_domain}"
    password = f"Smoke-{secrets.token_urlsafe(18)}"

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if args.netlify_env:
        supabase_url = supabase_url or netlify_environment("SUPABASE_URL")
        service_key = service_key or netlify_environment("SUPABASE_SERVICE_KEY")
    require(
        bool(supabase_url and service_key),
        "Cleanup credentials are required. Set SUPABASE_URL and "
        "SUPABASE_SERVICE_KEY or pass --netlify-env.",
    )

    user_id = ""
    try:
        app_status, app_html = get_text(f"{base_url}/app/")
        require(app_status == 200, f"App returned HTTP {app_status}")
        require(
            'id="warRoom"' in app_html and "auth-register" in app_html,
            "App shell is incomplete",
        )
        print("PASS app shell")

        short_password = request_json(
            f"{base_url}/.netlify/functions/auth-register",
            method="POST",
            payload={"email": email, "password": "short"},
        )
        require(short_password.status == 400, "Short-password validation did not return 400")
        print("PASS registration validation")

        registration = request_json(
            f"{base_url}/.netlify/functions/auth-register",
            method="POST",
            payload={"email": email, "password": password},
        )
        require(registration.status == 200, f"Registration failed: {registration.body.get('error')}")
        user_id = str(registration.body.get("user", {}).get("id", ""))
        access_token = str(registration.body.get("session", {}).get("access_token", ""))
        require(bool(user_id and access_token), "Registration omitted the user or session")
        require(registration.body.get("profile", {}).get("plan") == "free", "Wrong initial plan")
        print("PASS account creation")

        session = request_json(
            f"{base_url}/.netlify/functions/auth-session",
            method="POST",
            payload={"access_token": access_token},
        )
        require(session.status == 200, f"Session restoration failed: {session.body.get('error')}")
        require(session.body.get("user", {}).get("id") == user_id, "Session restored the wrong user")
        print("PASS session restoration")

        wrong_login = request_json(
            f"{base_url}/.netlify/functions/auth-login",
            method="POST",
            payload={"email": email, "password": f"{password}-wrong"},
        )
        require(wrong_login.status == 401, "Wrong-password login did not return 401")

        login = request_json(
            f"{base_url}/.netlify/functions/auth-login",
            method="POST",
            payload={"email": email, "password": password},
        )
        require(login.status == 200, f"Login failed: {login.body.get('error')}")
        require(bool(login.body.get("session", {}).get("access_token")), "Login omitted the session")
        print("PASS login and rejection behavior")

        checkout = request_json(
            f"{base_url}/.netlify/functions/stripe-checkout",
            method="POST",
            payload={
                "user_id": user_id,
                "email": email,
                "plan_type": "draft",
                "attribution": {
                    "utm_source": "qa",
                    "utm_medium": "production_smoke_test",
                    "utm_campaign": "auth_funnel",
                },
            },
        )
        checkout_url = str(checkout.body.get("url", ""))
        checkout_host = urlparse(checkout_url).hostname
        require(checkout.status == 200, f"Checkout failed: {checkout.body.get('error')}")
        require(checkout_host == "checkout.stripe.com", "Checkout did not return a Stripe URL")
        print("PASS Stripe checkout handoff (no charge submitted)")
    finally:
        if user_id:
            cleanup_test_records(supabase_url, service_key, user_id, email)
            print("PASS disposable account cleanup")

    print("PASS deployed signup-to-checkout funnel")


if __name__ == "__main__":
    main()
