#!/usr/bin/env python3
"""Run the OverADP paid-search conversion funnel through the GA4 Data API.

The GA4 Funnel Reporting endpoint is currently v1alpha. This script deliberately
uses the REST endpoint and Python's standard library so the repository does not
need another runtime dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_PROPERTY_ID = "533452511"
DEFAULT_START_DATE = "2026-08-21"
DEFAULT_SOURCE_MEDIUM = "google / cpc"
DEFAULT_SERVICE_ACCOUNT = "ga4-reader@ggc-ads-api.iam.gserviceaccount.com"
DEFAULT_QUOTA_PROJECT = "ggc-ads-api"
ENDPOINT = (
    "https://analyticsdata.googleapis.com/v1alpha/"
    "properties/{property_id}:runFunnelReport"
)

FUNNEL_STEPS = (
    ("Recommendation viewed", "recommendation_viewed"),
    ("Draft pick recorded", "draft_pick_recorded"),
    ("One-pick proof completed", "proof_demo_completed"),
    ("Offer shown", "offer_shown"),
    ("Checkout intent before auth", "checkout_intent_preauth"),
    ("Checkout started", "checkout_started"),
    ("Purchase", "purchase"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OverADP's GA4 paid-search activation and purchase funnel."
    )
    parser.add_argument(
        "--property-id",
        default=os.environ.get("GA4_PROPERTY_ID", DEFAULT_PROPERTY_ID),
        help="Numeric GA4 property ID (default: %(default)s).",
    )
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help="GA4 start date in YYYY-MM-DD or relative form (default: %(default)s).",
    )
    parser.add_argument(
        "--end-date",
        default="today",
        help="GA4 end date in YYYY-MM-DD or relative form (default: %(default)s).",
    )
    parser.add_argument(
        "--source-medium",
        default=DEFAULT_SOURCE_MEDIUM,
        help="Exact session source / medium to include (default: %(default)s).",
    )
    parser.add_argument(
        "--all-traffic",
        action="store_true",
        help="Do not restrict the funnel to a session source / medium.",
    )
    parser.add_argument(
        "--access-token",
        help=(
            "OAuth access token. Prefer GOOGLE_ANALYTICS_ACCESS_TOKEN or gcloud "
            "authentication so the token does not enter shell history."
        ),
    )
    parser.add_argument(
        "--service-account",
        default=os.environ.get("GA4_SERVICE_ACCOUNT", DEFAULT_SERVICE_ACCOUNT),
        help="Reader service account to impersonate (default: %(default)s).",
    )
    parser.add_argument(
        "--quota-project",
        default=os.environ.get("GA4_QUOTA_PROJECT", DEFAULT_QUOTA_PROJECT),
        help="Google Cloud quota project for impersonation (default: %(default)s).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete API response instead of the compact table.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request without contacting Google Analytics.",
    )
    return parser.parse_args()


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    request: dict[str, Any] = {
        "dateRanges": [
            {"startDate": args.start_date, "endDate": args.end_date},
        ],
        "funnel": {
            "isOpenFunnel": False,
            "steps": [
                {
                    "name": label,
                    "filterExpression": {
                        "funnelEventFilter": {"eventName": event_name}
                    },
                }
                for label, event_name in FUNNEL_STEPS
            ],
        },
        "returnPropertyQuota": True,
    }

    if not args.all_traffic:
        request["dimensionFilter"] = {
            "filter": {
                "fieldName": "sessionSourceMedium",
                "stringFilter": {
                    "matchType": "EXACT",
                    "value": args.source_medium,
                    "caseSensitive": False,
                },
            }
        }

    return request


def gcloud_token(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    token = completed.stdout.strip()
    return token or None


def generate_impersonated_token(
    base_token: str, service_account: str, quota_project: str
) -> str:
    endpoint = (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{service_account}:generateAccessToken"
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(
            {
                "scope": ["https://www.googleapis.com/auth/analytics.readonly"],
                "lifetime": "3600s",
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {base_token}",
            "Content-Type": "application/json",
            "x-goog-user-project": quota_project,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {}).get("message", body)
        except json.JSONDecodeError:
            detail = body
        raise RuntimeError(
            f"Reader impersonation returned HTTP {error.code}: {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not reach the IAM Credentials API: {error.reason}"
        ) from error

    token = payload.get("accessToken")
    if not token:
        raise RuntimeError("Reader impersonation returned no access token.")
    return token


def resolve_access_token(
    cli_token: str | None, service_account: str, quota_project: str
) -> str:
    if cli_token:
        return cli_token

    env_token = os.environ.get("GOOGLE_ANALYTICS_ACCESS_TOKEN")
    if env_token:
        return env_token

    if service_account:
        base_token = gcloud_token(["gcloud", "auth", "print-access-token"])
        if base_token:
            return generate_impersonated_token(
                base_token, service_account, quota_project
            )

    token = gcloud_token(["gcloud", "auth", "application-default", "print-access-token"])
    if token:
        return token

    token = gcloud_token(["gcloud", "auth", "print-access-token"])
    if token:
        return token

    raise RuntimeError(
        "No Google OAuth token is available. Run `gcloud auth application-default "
        "login --scopes=https://www.googleapis.com/auth/analytics.readonly,"
        "https://www.googleapis.com/auth/cloud-platform` or set "
        "GOOGLE_ANALYTICS_ACCESS_TOKEN."
    )


def run_report(property_id: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        ENDPOINT.format(property_id=property_id),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {}).get("message", body)
        except json.JSONDecodeError:
            detail = body
        raise RuntimeError(f"GA4 API returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach the GA4 Data API: {error.reason}") from error


def value_at(values: list[dict[str, str]], index: int, default: str = "0") -> str:
    if index >= len(values):
        return default
    return values[index].get("value", default)


def print_compact_report(response: dict[str, Any], args: argparse.Namespace) -> None:
    table = response.get("funnelTable", {})
    rows = table.get("rows", [])

    traffic = "all traffic" if args.all_traffic else args.source_medium
    print(f"OverADP funnel | {args.start_date} to {args.end_date} | {traffic}")
    print("-" * 91)
    print(f"{'Step':38} {'Users':>8} {'Next step':>12} {'Abandoned':>12} {'Abandon %':>12}")
    print("-" * 91)

    for row in rows:
        dimensions = row.get("dimensionValues", [])
        metrics = row.get("metricValues", [])
        step = value_at(dimensions, 0, "Unknown")
        users = value_at(metrics, 0)
        completion = float(value_at(metrics, 1, "0"))
        abandonments = value_at(metrics, 2)
        abandonment_rate = float(value_at(metrics, 3, "0"))
        print(
            f"{step[:38]:38} {users:>8} {completion:>11.1%} "
            f"{abandonments:>12} {abandonment_rate:>11.1%}"
        )

    if not rows:
        print("No matching funnel rows were returned yet.")

    sampling = table.get("metadata", {}).get("samplingMetadatas", [])
    if sampling:
        print("\nWarning: GA4 sampled this report.")


def main() -> int:
    args = parse_args()
    payload = build_request(args)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    try:
        token = resolve_access_token(
            args.access_token, args.service_account, args.quota_project
        )
        response = run_report(args.property_id, payload, token)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(response, indent=2))
    else:
        print_compact_report(response, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
