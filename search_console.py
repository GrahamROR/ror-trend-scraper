"""
Rock On Ruby - Google Search Console fetcher

First local run:
  python3 search_console.py

That opens a Google login/approval flow and stores gsc_token.json locally.
Do not commit gsc_oauth_client.json or gsc_token.json.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

OUTPUT_DIR = Path(__file__).parent
CLIENT_FILE = OUTPUT_DIR / "gsc_oauth_client.json"
TOKEN_FILE = OUTPUT_DIR / "gsc_token.json"
CACHE_FILE = OUTPUT_DIR / "search_console_cache.json"

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
DEFAULT_SITE_URL = "sc-domain:rockonruby.co.uk"


def load_env_credentials() -> Credentials | None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    if not client_id or not client_secret or not refresh_token:
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def load_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        creds = load_env_credentials()

    if not creds or not creds.valid:
        if not CLIENT_FILE.exists():
            raise FileNotFoundError(
                "gsc_oauth_client.json not found. Download the OAuth Desktop JSON from Google Cloud and place it in this folder."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def query_search_console(service, site_url: str, start_date: str, end_date: str, dimensions: list[str]) -> list[dict]:
    rows: list[dict] = []
    start_row = 0
    row_limit = 25000
    while True:
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "startRow": start_row,
        }
        response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        batch = response.get("rows", [])
        rows.extend(batch)
        if len(batch) < row_limit:
            break
        start_row += row_limit
    return rows


def normalise_row(row: dict, dimensions: list[str]) -> dict:
    keys = row.get("keys", [])
    out = {dim: keys[i] if i < len(keys) else "" for i, dim in enumerate(dimensions)}
    out.update(
        {
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
            "ctr": round(float(row.get("ctr", 0)) * 100, 2),
            "position": round(float(row.get("position", 0)), 2),
        }
    )
    return out


def summarize_opportunities(query_page_rows: list[dict]) -> dict:
    high_impressions_low_ctr = []
    striking_distance = []
    weak_pages = defaultdict(lambda: {"clicks": 0, "impressions": 0, "queries": set(), "positions": []})

    for row in query_page_rows:
        impressions = row["impressions"]
        ctr = row["ctr"]
        position = row["position"]
        if impressions >= 100 and ctr < 2.0:
            high_impressions_low_ctr.append(row)
        if 8 <= position <= 20 and impressions >= 50:
            striking_distance.append(row)

        page = row.get("page", "")
        if page:
            weak_pages[page]["clicks"] += row["clicks"]
            weak_pages[page]["impressions"] += impressions
            weak_pages[page]["queries"].add(row.get("query", ""))
            weak_pages[page]["positions"].append(position)

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0

    page_summary = []
    for page, data in weak_pages.items():
        impressions = data["impressions"]
        clicks = data["clicks"]
        ctr = round((clicks / impressions) * 100, 2) if impressions else 0
        if impressions >= 100:
            page_summary.append(
                {
                    "page": page,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": ctr,
                    "avg_position": avg(data["positions"]),
                    "query_count": len(data["queries"]),
                }
            )

    return {
        "high_impressions_low_ctr": sorted(
            high_impressions_low_ctr, key=lambda r: (-r["impressions"], r["ctr"])
        )[:25],
        "striking_distance": sorted(
            striking_distance, key=lambda r: (r["position"], -r["impressions"])
        )[:25],
        "pages": sorted(page_summary, key=lambda r: (-r["impressions"], r["ctr"]))[:25],
    }


def fetch_search_console(site_url: str = DEFAULT_SITE_URL, days: int = 28) -> dict:
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days - 1)
    start_date = start.isoformat()
    end_date = end.isoformat()

    creds = load_credentials()
    service = build("searchconsole", "v1", credentials=creds)

    query_rows = [
        normalise_row(row, ["query"])
        for row in query_search_console(service, site_url, start_date, end_date, ["query"])
    ]
    page_rows = [
        normalise_row(row, ["page"])
        for row in query_search_console(service, site_url, start_date, end_date, ["page"])
    ]
    query_page_rows = [
        normalise_row(row, ["query", "page"])
        for row in query_search_console(service, site_url, start_date, end_date, ["query", "page"])
    ]

    cache = {
        "site_url": site_url,
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "queries": sorted(query_rows, key=lambda r: (-r["impressions"], -r["clicks"]))[:500],
        "pages": sorted(page_rows, key=lambda r: (-r["impressions"], -r["clicks"]))[:500],
        "query_pages": sorted(query_page_rows, key=lambda r: (-r["impressions"], -r["clicks"]))[:1000],
        "opportunities": summarize_opportunities(query_page_rows),
    }
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return cache


def print_summary(cache: dict) -> None:
    print("\n-- Google Search Console --")
    print(f"Site: {cache['site_url']}")
    print(f"Window: {cache['start_date']} to {cache['end_date']} ({cache['days']} days)")
    print(f"Queries captured: {len(cache['queries'])}")
    print(f"Pages captured: {len(cache['pages'])}")
    print(f"Query/page pairs captured: {len(cache['query_pages'])}")

    print("\nTop striking-distance opportunities (position 8-20):")
    for row in cache["opportunities"]["striking_distance"][:10]:
        print(
            f"  pos {row['position']:>5} | {row['impressions']:>5} imp | {row['clicks']:>3} clicks | {row['ctr']:>5}% | {row['query']} -> {row['page']}"
        )

    print(f"\nSaved: {CACHE_FILE}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Google Search Console performance data.")
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL, help="Search Console site URL, e.g. sc-domain:rockonruby.co.uk")
    parser.add_argument("--days", type=int, default=28, help="Lookback window. Defaults to 28 days.")
    args = parser.parse_args()

    cache = fetch_search_console(args.site_url, args.days)
    print_summary(cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
